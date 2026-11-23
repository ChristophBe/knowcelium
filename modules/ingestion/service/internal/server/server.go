// Package server implements knowcel.ingestion.v1.IngestionService.
package server

import (
	"context"
	"errors"
	"fmt"
	"log/slog"
	"slices"
	"strings"
	"time"

	"github.com/google/uuid"
	"google.golang.org/genproto/googleapis/rpc/errdetails"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/status"
	"google.golang.org/protobuf/types/known/timestamppb"

	ingestionv1 "github.com/ChristophBe/knowcelium/modules/ingestion/api/go/ingestionv1"
	"github.com/ChristophBe/knowcelium/modules/ingestion/service/internal/app"
	"github.com/ChristophBe/knowcelium/modules/ingestion/service/internal/connectors"
	commonv1 "github.com/ChristophBe/knowcelium/platform/api/go/commonv1"
	"github.com/ChristophBe/knowcelium/platform/go/grpcserver"
	"github.com/ChristophBe/knowcelium/platform/go/postgres"
)

const (
	defaultPageSize = 50
	maxPageSize     = 200
	// domain is the ErrorInfo domain of this module's errors.
	domain = "knowcel.ingestion.v1"
)

// Server implements IngestionService. Jobs belong to the user who created the
// upload: every RPC acts on the calling user's jobs only and reports another
// user's as not found.
type Server struct {
	ingestionv1.UnimplementedIngestionServiceServer
	app        *app.Service
	connectors *connectors.Service
	// callers tells who is a platform admin; only the connector RPCs ask, so
	// the other calls do not depend on iam.
	callers *grpcserver.Resolver
	log     *slog.Logger
	// PollInterval controls how often WatchJob checks for changes.
	PollInterval time.Duration
	// connectorSearch reaches the connector runtime for live search.
	connectorSearch ConnectorSearcher
}

// ConnectorSearcher asks the connector runtime to search its connectors live.
type ConnectorSearcher interface {
	Search(ctx context.Context, req *ingestionv1.ConnectorSearchRequest) (*ingestionv1.ConnectorSearchReply, error)
}

func New(service *app.Service, log *slog.Logger) *Server {
	return &Server{app: service, log: log, PollInterval: 500 * time.Millisecond}
}

// WithConnectors serves the connectors' status from c to the platform admins
// callers knows. Without it ListConnectors and GetConnector are unimplemented.
func (s *Server) WithConnectors(c *connectors.Service, callers *grpcserver.Resolver) *Server {
	s.connectors, s.callers = c, callers
	return s
}

// WithConnectorSearch sets how SearchConnectors reaches the connectors; without
// one it finds nothing and reports UNAVAILABLE.
func (s *Server) WithConnectorSearch(c ConnectorSearcher) *Server {
	s.connectorSearch = c
	return s
}

func (s *Server) CreateUpload(ctx context.Context, req *ingestionv1.CreateUploadRequest) (*ingestionv1.CreateUploadResponse, error) {
	owner, err := caller(ctx)
	if err != nil {
		return nil, err
	}
	var violations []*errdetails.BadRequest_FieldViolation
	if req.GetFilename() == "" {
		violations = append(violations, grpcserver.Violation("filename", "A filename is required"))
	}
	if req.GetSizeBytes() <= 0 {
		// Nothing could be extracted from an empty file; it would only fail later.
		violations = append(violations, grpcserver.Violation("size_bytes", "The file is empty"))
	}
	teamIDs, teamViolations := parseTeamIDs(req.GetTeamIds())
	violations = append(violations, teamViolations...)
	if len(violations) > 0 {
		return nil, grpcserver.InvalidArgument(violations...)
	}
	job, uploadURL, err := s.app.CreateUpload(ctx, owner, app.NewUpload{
		Title:       req.GetTitle(),
		Filename:    req.GetFilename(),
		ContentType: req.GetContentType(),
		SizeBytes:   req.GetSizeBytes(),
		SHA256:      req.GetSha256(),
		Access:      req.GetAccess(),
		TeamIDs:     teamIDs,
	})
	if err != nil {
		return nil, s.toStatus("create upload", err)
	}
	return &ingestionv1.CreateUploadResponse{Job: toProto(job), UploadUrl: uploadURL}, nil
}

// parseTeamIDs parses the team ids of a request, without duplicates, and
// returns a violation per invalid one.
func parseTeamIDs(raw []string) ([]uuid.UUID, []*errdetails.BadRequest_FieldViolation) {
	var violations []*errdetails.BadRequest_FieldViolation
	ids := make([]uuid.UUID, 0, len(raw))
	for i, r := range raw {
		id, err := uuid.Parse(r)
		if err != nil {
			violations = append(violations, grpcserver.Violation(fmt.Sprintf("team_ids[%d]", i), fmt.Sprintf("Invalid team id %q", r)))
			continue
		}
		if !slices.Contains(ids, id) {
			ids = append(ids, id)
		}
	}
	return ids, violations
}

// ReplaceUpload starts a new version of the calling user's document.
func (s *Server) ReplaceUpload(ctx context.Context, req *ingestionv1.ReplaceUploadRequest) (*ingestionv1.ReplaceUploadResponse, error) {
	owner, err := caller(ctx)
	if err != nil {
		return nil, err
	}
	var violations []*errdetails.BadRequest_FieldViolation
	documentID, err := uuid.Parse(req.GetDocumentId())
	if err != nil {
		violations = append(violations, grpcserver.Violation("document_id", fmt.Sprintf("Invalid document id %q", req.GetDocumentId())))
	}
	if req.GetFilename() == "" {
		violations = append(violations, grpcserver.Violation("filename", "A filename is required"))
	}
	if req.GetSizeBytes() <= 0 {
		violations = append(violations, grpcserver.Violation("size_bytes", "The file is empty"))
	}
	if len(violations) > 0 {
		return nil, grpcserver.InvalidArgument(violations...)
	}
	job, uploadURL, err := s.app.ReplaceUpload(ctx, owner, documentID, app.NewUpload{
		Filename:    req.GetFilename(),
		ContentType: req.GetContentType(),
		SizeBytes:   req.GetSizeBytes(),
		SHA256:      req.GetSha256(),
	})
	if err != nil {
		return nil, s.toStatus("replace upload", err)
	}
	return &ingestionv1.ReplaceUploadResponse{Job: toProto(job), UploadUrl: uploadURL}, nil
}

func (s *Server) CompleteUpload(ctx context.Context, req *ingestionv1.CompleteUploadRequest) (*ingestionv1.CompleteUploadResponse, error) {
	owner, err := caller(ctx)
	if err != nil {
		return nil, err
	}
	id, err := parseID("job_id", req.GetJobId())
	if err != nil {
		return nil, err
	}
	job, err := s.app.CompleteUpload(ctx, owner, id)
	if err != nil {
		return nil, s.toStatus("complete upload", err)
	}
	return &ingestionv1.CompleteUploadResponse{Job: toProto(job)}, nil
}

func (s *Server) GetJob(ctx context.Context, req *ingestionv1.GetJobRequest) (*ingestionv1.GetJobResponse, error) {
	job, err := s.getJob(ctx, req.GetId())
	if err != nil {
		return nil, err
	}
	return &ingestionv1.GetJobResponse{Job: toProto(job)}, nil
}

func (s *Server) ListJobs(ctx context.Context, req *ingestionv1.ListJobsRequest) (*ingestionv1.ListJobsResponse, error) {
	owner, err := caller(ctx)
	if err != nil {
		return nil, err
	}
	limit := req.GetPage().GetPageSize()
	if limit <= 0 {
		limit = defaultPageSize
	}
	limit = min(limit, maxPageSize)
	var after *app.JobCursor
	if tok := req.GetPage().GetPageToken(); tok != "" {
		c, err := postgres.DecodeCursor(tok)
		if err != nil {
			return nil, grpcserver.InvalidArgument(grpcserver.Violation("page.page_token", "The page token is invalid"))
		}
		after = &app.JobCursor{CreatedAt: c.Time, ID: c.ID}
	}
	jobs, err := s.app.ListJobs(ctx, owner, after, limit+1)
	if err != nil {
		return nil, s.toStatus("list jobs", err)
	}
	resp := &ingestionv1.ListJobsResponse{Page: &commonv1.PageResponse{}}
	if len(jobs) > int(limit) {
		jobs = jobs[:limit]
		last := jobs[len(jobs)-1]
		resp.Page.NextPageToken = postgres.Cursor{Time: last.CreatedAt, ID: last.ID}.Encode()
	}
	for _, j := range jobs {
		resp.Jobs = append(resp.Jobs, toProto(j))
	}
	return resp, nil
}

func (s *Server) WatchJob(req *ingestionv1.WatchJobRequest, stream ingestionv1.IngestionService_WatchJobServer) error {
	ctx := stream.Context()
	ticker := time.NewTicker(s.PollInterval)
	defer ticker.Stop()
	var last time.Time
	for {
		job, err := s.getJob(ctx, req.GetId())
		if err != nil {
			return err
		}
		if !job.UpdatedAt.Equal(last) {
			last = job.UpdatedAt
			if err := stream.Send(&ingestionv1.WatchJobResponse{Job: toProto(job)}); err != nil {
				return err
			}
		}
		if job.Terminal() {
			return nil
		}
		select {
		case <-ctx.Done():
			return nil
		case <-ticker.C:
		}
	}
}

func (s *Server) ReprocessJob(ctx context.Context, req *ingestionv1.ReprocessJobRequest) (*ingestionv1.ReprocessJobResponse, error) {
	owner, err := caller(ctx)
	if err != nil {
		return nil, err
	}
	id, err := parseID("id", req.GetId())
	if err != nil {
		return nil, err
	}
	job, err := s.app.ReprocessJob(ctx, owner, id)
	if err != nil {
		return nil, s.toStatus("reprocess job", err)
	}
	return &ingestionv1.ReprocessJobResponse{Job: toProto(job)}, nil
}

const (
	defaultSearchLimit = 5
	maxSearchLimit     = 20
	maxQueryLength     = 2000
)

// SearchConnectors searches the connectors the calling user may read. What the
// user may read is decided here, from their teams in iam, never from the
// request: the worker only gets the teams this service resolved.
func (s *Server) SearchConnectors(ctx context.Context, req *ingestionv1.SearchConnectorsRequest) (*ingestionv1.SearchConnectorsResponse, error) {
	user, err := caller(ctx)
	if err != nil {
		return nil, err
	}
	var violations []*errdetails.BadRequest_FieldViolation
	query := strings.TrimSpace(req.GetQuery())
	if query == "" {
		violations = append(violations, grpcserver.Violation("query", "A query is required"))
	}
	if len(query) > maxQueryLength {
		violations = append(violations, grpcserver.Violation("query", fmt.Sprintf("A query can be at most %d bytes", maxQueryLength)))
	}
	if req.GetLimit() < 0 || req.GetLimit() > maxSearchLimit {
		violations = append(violations, grpcserver.Violation("limit", fmt.Sprintf("The limit must be between 0 and %d", maxSearchLimit)))
	}
	if len(violations) > 0 {
		return nil, grpcserver.InvalidArgument(violations...)
	}
	if s.connectorSearch == nil {
		return nil, status.Error(codes.Unavailable, "connector search is not available")
	}
	// Without teams (iam is down, or the server has no resolver) only public
	// connectors are searched. Only this and the connector status RPCs ask iam,
	// so the other calls do not depend on it.
	var principal grpcserver.Principal
	if s.callers != nil {
		principal = s.callers.Resolve(ctx, user)
	}
	member := principal.TeamIDs()
	scope := slices.DeleteFunc(slices.Clone(req.GetTeamIds()), func(id string) bool { return !slices.Contains(member, id) })
	if len(req.GetTeamIds()) > 0 && len(scope) == 0 {
		return &ingestionv1.SearchConnectorsResponse{}, nil
	}
	limit := req.GetLimit()
	if limit == 0 {
		limit = defaultSearchLimit
	}
	reply, err := s.connectorSearch.Search(ctx, &ingestionv1.ConnectorSearchRequest{
		Query:         query,
		ConnectorIds:  req.GetConnectorIds(),
		Limit:         limit,
		MemberTeamIds: member,
		ScopeTeamIds:  scope,
	})
	switch {
	case errors.Is(err, connectors.ErrUnavailable), errors.Is(err, connectors.ErrTimeout):
		s.log.WarnContext(ctx, "search connectors", "error", err)
		return nil, status.Error(codes.Unavailable, err.Error())
	case errors.Is(err, context.Canceled):
		return nil, status.FromContextError(err).Err()
	case err != nil:
		s.log.ErrorContext(ctx, "search connectors", "error", err)
		return nil, status.Error(codes.Internal, "search connectors failed")
	}
	return &ingestionv1.SearchConnectorsResponse{
		Snippets:              reply.GetSnippets(),
		UnavailableConnectors: reply.GetUnavailableConnectors(),
	}, nil
}

// getJob returns the calling user's job with the id in the request.
func (s *Server) getJob(ctx context.Context, raw string) (app.Job, error) {
	owner, err := caller(ctx)
	if err != nil {
		return app.Job{}, err
	}
	id, err := parseID("id", raw)
	if err != nil {
		return app.Job{}, err
	}
	job, err := s.app.GetJob(ctx, owner, id)
	if err != nil {
		return app.Job{}, s.toStatus("get job", err)
	}
	return job, nil
}

// caller returns the user the call is made for. Calls through the gateway
// always carry one.
func caller(ctx context.Context) (string, error) {
	user, ok := grpcserver.UserFromContext(ctx)
	if !ok {
		return "", status.Error(codes.Unauthenticated, "the call has no user")
	}
	return user, nil
}

// parseID parses the job id in the request field named field.
func parseID(field, raw string) (uuid.UUID, error) {
	id, err := uuid.Parse(raw)
	if err != nil {
		return uuid.Nil, grpcserver.InvalidArgument(grpcserver.Violation(field, fmt.Sprintf("Invalid job id %q", raw)))
	}
	return id, nil
}

func (s *Server) toStatus(op string, err error) error {
	var invalid *app.InvalidUploadError
	if errors.As(err, &invalid) {
		violations := make([]*errdetails.BadRequest_FieldViolation, 0, len(invalid.Violations))
		for _, v := range invalid.Violations {
			violations = append(violations, grpcserver.Violation(v.Field, v.Description))
		}
		return grpcserver.InvalidArgument(violations...)
	}
	switch {
	case errors.Is(err, app.ErrNotFound):
		return status.Error(codes.NotFound, err.Error())
	case errors.Is(err, app.ErrAlreadyCompleted):
		return failedPrecondition("UPLOAD_ALREADY_COMPLETED", app.ErrAlreadyCompleted)
	case errors.Is(err, app.ErrUploadMissing):
		return failedPrecondition("UPLOAD_MISSING", app.ErrUploadMissing)
	case errors.Is(err, app.ErrNotReprocessable):
		return failedPrecondition("JOB_NOT_REPROCESSABLE", app.ErrNotReprocessable)
	case errors.Is(err, app.ErrTeamNotFound):
		return grpcserver.WithDetails(codes.NotFound, app.ErrTeamNotFound.Error(), grpcserver.ErrorInfo(domain, "TEAM_NOT_FOUND", nil))
	case errors.Is(err, app.ErrDocumentNotFound):
		return status.Error(codes.NotFound, app.ErrDocumentNotFound.Error())
	case errors.Is(err, app.ErrNotOwner):
		return status.Error(codes.PermissionDenied, app.ErrNotOwner.Error())
	case errors.Is(err, app.ErrDocumentBusy):
		return failedPrecondition("DOCUMENT_BUSY", app.ErrDocumentBusy)
	case errors.Is(err, app.ErrDocumentsUnavailable):
		s.log.Warn(op, "error", err)
		return status.Error(codes.Unavailable, app.ErrDocumentsUnavailable.Error())
	}
	s.log.Error(op, "error", err)
	return status.Errorf(codes.Internal, "%s failed", op)
}

// failedPrecondition reports a request in the wrong state, with a reason
// clients can branch on.
func failedPrecondition(reason string, err error) error {
	return grpcserver.WithDetails(codes.FailedPrecondition, err.Error(), grpcserver.ErrorInfo(domain, reason, nil))
}

func toProto(j app.Job) *ingestionv1.Job {
	return &ingestionv1.Job{
		Id:          j.ID.String(),
		DocumentId:  j.DocumentID.String(),
		Filename:    j.Filename,
		ContentType: j.ContentType,
		Status:      j.Status,
		Error:       j.Error,
		ChunkCount:  j.ChunkCount,
		Progress:    j.Progress,
		Stage:       j.Stage,
		CreateTime:  timestamppb.New(j.CreatedAt),
		UpdateTime:  timestamppb.New(j.UpdatedAt),
		OwnerId:     j.OwnerID,
	}
}

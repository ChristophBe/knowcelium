package server

import (
	"context"
	"errors"

	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/status"
	"google.golang.org/protobuf/types/known/timestamppb"

	ingestionv1 "github.com/ChristophBe/knowcelium/modules/ingestion/api/go/ingestionv1"
	"github.com/ChristophBe/knowcelium/modules/ingestion/service/internal/connectors"
)

// ListConnectors returns every configured connector. Platform admins only.
func (s *Server) ListConnectors(ctx context.Context, _ *ingestionv1.ListConnectorsRequest) (*ingestionv1.ListConnectorsResponse, error) {
	if err := s.requirePlatformAdmin(ctx); err != nil {
		return nil, err
	}
	list, err := s.connectors.List(ctx)
	if err != nil {
		return nil, s.toStatus("list connectors", err)
	}
	resp := &ingestionv1.ListConnectorsResponse{}
	for _, c := range list {
		resp.Connectors = append(resp.Connectors, connectorToProto(c))
	}
	return resp, nil
}

// GetConnector returns one connector. Platform admins only.
func (s *Server) GetConnector(ctx context.Context, req *ingestionv1.GetConnectorRequest) (*ingestionv1.GetConnectorResponse, error) {
	if err := s.requirePlatformAdmin(ctx); err != nil {
		return nil, err
	}
	c, err := s.connectors.Get(ctx, req.GetId())
	if errors.Is(err, connectors.ErrNotFound) {
		return nil, status.Error(codes.NotFound, err.Error())
	}
	if err != nil {
		return nil, s.toStatus("get connector", err)
	}
	return &ingestionv1.GetConnectorResponse{Connector: connectorToProto(c)}, nil
}

// requirePlatformAdmin fails with PERMISSION_DENIED unless the caller is a
// platform admin, and with UNAVAILABLE while iam, which knows, is down. It
// is UNIMPLEMENTED without connectors to serve.
func (s *Server) requirePlatformAdmin(ctx context.Context) error {
	if s.connectors == nil || s.callers == nil {
		return status.Error(codes.Unimplemented, "connector status is not served")
	}
	user, err := caller(ctx)
	if err != nil {
		return err
	}
	switch p := s.callers.Resolve(ctx, user); {
	case p.PlatformAdmin:
		return nil
	case p.Unavailable:
		return status.Error(codes.Unavailable, "cannot tell whether you are a platform admin: the iam service is unavailable")
	}
	return status.Error(codes.PermissionDenied, "Only platform admins can see connectors")
}

func connectorToProto(c connectors.Connector) *ingestionv1.Connector {
	out := &ingestionv1.Connector{
		Id:              c.Name,
		Name:            c.Name,
		Kind:            c.Kind,
		Enabled:         c.Enabled,
		Health:          c.Health,
		IntervalSeconds: int32(c.Interval.Seconds()),
		DocumentsSynced: c.Documents,
		LastError:       c.LastError,
	}
	if !c.LastStart.IsZero() {
		out.LastSyncStartTime = timestamppb.New(c.LastStart)
	}
	if !c.LastEnd.IsZero() {
		out.LastSyncEndTime = timestamppb.New(c.LastEnd)
	}
	if !c.LastSuccess.IsZero() {
		out.LastSuccessTime = timestamppb.New(c.LastSuccess)
	}
	return out
}

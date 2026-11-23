package server

import (
	"context"
	"log/slog"
	"testing"
	"time"

	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/status"

	ingestionv1 "github.com/ChristophBe/knowcelium/modules/ingestion/api/go/ingestionv1"
	"github.com/ChristophBe/knowcelium/modules/ingestion/service/internal/connectors"
	"github.com/ChristophBe/knowcelium/platform/go/grpcserver"
)

type fakeConnectorRepo struct {
	connectors.Repository
	statuses []connectors.Status
	err      error
}

func (f *fakeConnectorRepo) List(context.Context) ([]connectors.Status, error) {
	return f.statuses, f.err
}

func (f *fakeConnectorRepo) Get(_ context.Context, name string) (connectors.Status, error) {
	if f.err != nil {
		return connectors.Status{}, f.err
	}
	for _, s := range f.statuses {
		if s.Name == name {
			return s, nil
		}
	}
	return connectors.Status{}, connectors.ErrNotFound
}

func connectorServer(repo *fakeConnectorRepo) *Server {
	return New(nil, slog.New(slog.DiscardHandler)).WithConnectors(connectors.New(repo))
}

func callerCtx(t *testing.T, p grpcserver.Principal) context.Context {
	return grpcserver.WithPrincipal(t.Context(), p)
}

func TestConnectorsAreForPlatformAdminsOnly(t *testing.T) {
	srv := connectorServer(&fakeConnectorRepo{statuses: []connectors.Status{{Name: "docs"}}})
	tests := []struct {
		name string
		ctx  context.Context
		want codes.Code
	}{
		{"a member", callerCtx(t, grpcserver.Principal{UserID: alice}), codes.PermissionDenied},
		{"a team admin", callerCtx(t, grpcserver.Principal{UserID: alice, Teams: []grpcserver.Team{{ID: "t", Admin: true}}}), codes.PermissionDenied},
		{"no principal", as(t, alice), codes.PermissionDenied},
		{"iam down", callerCtx(t, grpcserver.Principal{UserID: alice, Unavailable: true}), codes.Unavailable},
		{"a platform admin", callerCtx(t, grpcserver.Principal{UserID: alice, PlatformAdmin: true}), codes.OK},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			_, listErr := srv.ListConnectors(tt.ctx, &ingestionv1.ListConnectorsRequest{})
			_, getErr := srv.GetConnector(tt.ctx, &ingestionv1.GetConnectorRequest{Id: "docs"})
			for op, err := range map[string]error{"ListConnectors": listErr, "GetConnector": getErr} {
				if got := status.Code(err); got != tt.want {
					t.Errorf("%s code = %v, want %v (%v)", op, got, tt.want, err)
				}
			}
		})
	}
}

func TestListConnectorsReportsHealthTimesAndError(t *testing.T) {
	start := time.Date(2026, 11, 23, 10, 0, 0, 0, time.UTC)
	repo := &fakeConnectorRepo{statuses: []connectors.Status{
		{Name: "docs", Kind: "folder", Enabled: true, Interval: 5 * time.Minute,
			Outcome: ingestionv1.SyncOutcome_SYNC_OUTCOME_FAILED, LastStart: start, LastEnd: start.Add(time.Second),
			LastSuccess: start.Add(-time.Hour), Documents: 7, LastError: "boom"},
		{Name: "new", Kind: "folder", Enabled: true, Interval: time.Minute},
	}}
	resp, err := connectorServer(repo).ListConnectors(callerCtx(t, grpcserver.Principal{PlatformAdmin: true}), &ingestionv1.ListConnectorsRequest{})
	if err != nil {
		t.Fatal(err)
	}
	if len(resp.GetConnectors()) != 2 {
		t.Fatalf("connectors = %v", resp.GetConnectors())
	}
	c := resp.GetConnectors()[0]
	if c.GetId() != "docs" || c.GetName() != "docs" || c.GetKind() != "folder" || !c.GetEnabled() ||
		c.GetHealth() != ingestionv1.ConnectorHealth_CONNECTOR_HEALTH_FAILING || c.GetIntervalSeconds() != 300 ||
		c.GetDocumentsSynced() != 7 || c.GetLastError() != "boom" ||
		!c.GetLastSyncStartTime().AsTime().Equal(start) || !c.GetLastSyncEndTime().AsTime().Equal(start.Add(time.Second)) ||
		!c.GetLastSuccessTime().AsTime().Equal(start.Add(-time.Hour)) {
		t.Errorf("connector = %v", c)
	}
	n := resp.GetConnectors()[1]
	if n.GetHealth() != ingestionv1.ConnectorHealth_CONNECTOR_HEALTH_UNKNOWN || n.GetLastSyncStartTime() != nil || n.GetLastSuccessTime() != nil {
		t.Errorf("never synced connector = %v", n)
	}
}

func TestGetConnectorNotFoundAndFailures(t *testing.T) {
	admin := callerCtx(t, grpcserver.Principal{PlatformAdmin: true})
	srv := connectorServer(&fakeConnectorRepo{})
	if _, err := srv.GetConnector(admin, &ingestionv1.GetConnectorRequest{Id: "nope"}); status.Code(err) != codes.NotFound {
		t.Errorf("get unknown: %v", err)
	}
	srv = connectorServer(&fakeConnectorRepo{err: context.DeadlineExceeded})
	if _, err := srv.ListConnectors(admin, &ingestionv1.ListConnectorsRequest{}); status.Code(err) != codes.Internal {
		t.Errorf("list: %v", err)
	}
	if _, err := srv.GetConnector(admin, &ingestionv1.GetConnectorRequest{Id: "x"}); status.Code(err) != codes.Internal {
		t.Errorf("get: %v", err)
	}
}

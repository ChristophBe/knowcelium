package server

import (
	"context"
	"errors"
	"log/slog"
	"testing"
	"time"

	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/status"
	"google.golang.org/protobuf/proto"

	ingestionv1 "github.com/ChristophBe/knowcelium/modules/ingestion/api/go/ingestionv1"
	"github.com/ChristophBe/knowcelium/modules/ingestion/service/internal/connectors"
	"github.com/ChristophBe/knowcelium/platform/go/grpcserver"
)

type fakeSearcher struct {
	reply *ingestionv1.ConnectorSearchReply
	err   error
	got   *ingestionv1.ConnectorSearchRequest
}

func (f *fakeSearcher) Search(_ context.Context, req *ingestionv1.ConnectorSearchRequest) (*ingestionv1.ConnectorSearchReply, error) {
	f.got = req
	return f.reply, f.err
}

// searchServer is a server whose iam says the caller belongs to the teams.
func searchServer(f *fakeSearcher, teams ...string) *Server {
	callers := grpcserver.NewResolver(func(_ context.Context, user string) (grpcserver.Principal, error) {
		p := grpcserver.Principal{UserID: user}
		for _, id := range teams {
			p.Teams = append(p.Teams, grpcserver.Team{ID: id})
		}
		return p, nil
	}, time.Minute, slog.New(slog.DiscardHandler))
	return New(nil, slog.Default()).WithConnectors(nil, callers).WithConnectorSearch(f)
}

// searchServerIAMDown is a server whose iam cannot be reached.
func searchServerIAMDown(f *fakeSearcher) *Server {
	callers := grpcserver.NewResolver(func(context.Context, string) (grpcserver.Principal, error) {
		return grpcserver.Principal{}, errors.New("iam is down")
	}, time.Minute, slog.New(slog.DiscardHandler))
	return New(nil, slog.Default()).WithConnectors(nil, callers).WithConnectorSearch(f)
}

func TestSearchConnectorsAsksWithTheCallersTeamsFromIAM(t *testing.T) {
	f := &fakeSearcher{reply: &ingestionv1.ConnectorSearchReply{
		Snippets:              []*ingestionv1.ConnectorSnippet{{Connector: "stock", Text: "40 boxes", SourceUrl: "https://wms/1"}},
		UnavailableConnectors: []string{"slow"},
	}}
	resp, err := searchServer(f, "t1", "t2").SearchConnectors(as(t, alice), &ingestionv1.SearchConnectorsRequest{
		Query:        "  boxes ",
		ConnectorIds: []string{"stock"},
		// t3 is not the caller's team and is dropped, whatever the request says.
		TeamIds: []string{"t2", "t3"},
	})
	if err != nil {
		t.Fatal(err)
	}
	want := &ingestionv1.ConnectorSearchRequest{
		Query: "boxes", ConnectorIds: []string{"stock"}, Limit: defaultSearchLimit,
		MemberTeamIds: []string{"t1", "t2"}, ScopeTeamIds: []string{"t2"},
	}
	if !proto.Equal(f.got, want) {
		t.Errorf("asked %v, want %v", f.got, want)
	}
	if len(resp.GetSnippets()) != 1 || resp.GetUnavailableConnectors()[0] != "slow" {
		t.Errorf("response = %v", resp)
	}
}

func TestSearchConnectorsNeverTrustsTeamsOutsideTheScope(t *testing.T) {
	f := &fakeSearcher{reply: &ingestionv1.ConnectorSearchReply{}}
	// While iam is down the caller has no teams: only public connectors.
	if _, err := searchServerIAMDown(f).SearchConnectors(as(t, alice), &ingestionv1.SearchConnectorsRequest{Query: "q"}); err != nil {
		t.Fatal(err)
	}
	if len(f.got.GetMemberTeamIds()) != 0 {
		t.Errorf("member teams = %v, want none", f.got.GetMemberTeamIds())
	}
	// A scope of teams the caller is not in searches nothing at all, instead of everything.
	f.got = nil
	resp, err := searchServer(f).SearchConnectors(as(t, alice), &ingestionv1.SearchConnectorsRequest{Query: "q", TeamIds: []string{"t1"}})
	if err != nil {
		t.Fatal(err)
	}
	if f.got != nil || len(resp.GetSnippets()) != 0 {
		t.Errorf("asked %v and got %v, want nothing searched", f.got, resp)
	}
}

func TestSearchConnectorsValidates(t *testing.T) {
	for name, req := range map[string]*ingestionv1.SearchConnectorsRequest{
		"no query":      {},
		"blank query":   {Query: "  "},
		"long query":    {Query: string(make([]byte, maxQueryLength+1))},
		"negative":      {Query: "q", Limit: -1},
		"too many rows": {Query: "q", Limit: maxSearchLimit + 1},
	} {
		t.Run(name, func(t *testing.T) {
			_, err := searchServer(&fakeSearcher{}).SearchConnectors(as(t, alice), req)
			if status.Code(err) != codes.InvalidArgument {
				t.Errorf("code = %v, want InvalidArgument", status.Code(err))
			}
		})
	}
	if _, err := searchServer(&fakeSearcher{}).SearchConnectors(t.Context(), &ingestionv1.SearchConnectorsRequest{Query: "q"}); status.Code(err) != codes.Unauthenticated {
		t.Errorf("code = %v, want Unauthenticated", status.Code(err))
	}
}

func TestSearchConnectorsReportsAMissingRuntimeAsUnavailable(t *testing.T) {
	for _, err := range []error{connectors.ErrUnavailable, connectors.ErrTimeout} {
		_, got := searchServer(&fakeSearcher{err: err}).SearchConnectors(as(t, alice), &ingestionv1.SearchConnectorsRequest{Query: "q"})
		if status.Code(got) != codes.Unavailable {
			t.Errorf("%v: code = %v, want Unavailable", err, status.Code(got))
		}
	}
	_, got := searchServer(&fakeSearcher{err: context.Canceled}).SearchConnectors(as(t, alice), &ingestionv1.SearchConnectorsRequest{Query: "q"})
	if status.Code(got) != codes.Internal {
		t.Errorf("code = %v, want Internal", status.Code(got))
	}
	_, got = New(nil, slog.Default()).SearchConnectors(as(t, alice), &ingestionv1.SearchConnectorsRequest{Query: "q"})
	if status.Code(got) != codes.Unavailable {
		t.Errorf("without a searcher: code = %v, want Unavailable", status.Code(got))
	}
}

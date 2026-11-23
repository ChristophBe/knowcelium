package connectors

import (
	"context"
	"errors"
	"testing"
	"time"

	"github.com/nats-io/nats.go"
	"google.golang.org/protobuf/proto"

	ingestionv1 "github.com/ChristophBe/knowcelium/modules/ingestion/api/go/ingestionv1"
)

type fakeNATS struct {
	reply []byte
	err   error
	sent  *ingestionv1.ConnectorSearchRequest
	wait  bool
}

func (f *fakeNATS) RequestWithContext(ctx context.Context, subj string, data []byte) (*nats.Msg, error) {
	f.sent = &ingestionv1.ConnectorSearchRequest{}
	if err := proto.Unmarshal(data, f.sent); err != nil {
		return nil, err
	}
	if subj != Subject {
		return nil, errors.New("wrong subject " + subj)
	}
	if f.wait {
		<-ctx.Done()
		return nil, ctx.Err()
	}
	return &nats.Msg{Data: f.reply}, f.err
}

func TestSearchDecodesTheReplyAndLimitsTheConnectors(t *testing.T) {
	want := &ingestionv1.ConnectorSearchReply{
		Snippets:              []*ingestionv1.ConnectorSnippet{{Connector: "stock", Text: "40 boxes", SourceUrl: "https://wms/1"}},
		UnavailableConnectors: []string{"slow"},
	}
	raw, _ := proto.Marshal(want)
	nc := &fakeNATS{reply: raw}
	got, err := NewSearcher(nc, 5*time.Second).Search(t.Context(), &ingestionv1.ConnectorSearchRequest{Query: "boxes", Limit: 3})
	if err != nil {
		t.Fatal(err)
	}
	if !proto.Equal(got, want) {
		t.Errorf("reply = %v, want %v", got, want)
	}
	if nc.sent.GetQuery() != "boxes" || nc.sent.GetTimeoutSeconds() != 4 {
		t.Errorf("sent %v, want the query and a connector timeout of 4s", nc.sent)
	}
}

func TestSearchMapsFailures(t *testing.T) {
	tests := []struct {
		name string
		nc   *fakeNATS
		want error
	}{
		{"no worker", &fakeNATS{err: nats.ErrNoResponders}, ErrUnavailable},
		{"nats timeout", &fakeNATS{err: nats.ErrTimeout}, ErrTimeout},
		{"no reply in time", &fakeNATS{wait: true}, ErrTimeout},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			_, err := NewSearcher(tt.nc, 20*time.Millisecond).Search(t.Context(), &ingestionv1.ConnectorSearchRequest{Query: "q"})
			if !errors.Is(err, tt.want) {
				t.Errorf("error = %v, want %v", err, tt.want)
			}
		})
	}
	if _, err := NewSearcher(&fakeNATS{err: errors.New("boom")}, time.Second).Search(t.Context(), &ingestionv1.ConnectorSearchRequest{}); err == nil || errors.Is(err, ErrUnavailable) {
		t.Errorf("other errors are passed on, got %v", err)
	}
	if _, err := NewSearcher(&fakeNATS{reply: []byte{0xff}}, time.Second).Search(t.Context(), &ingestionv1.ConnectorSearchRequest{}); err == nil {
		t.Error("a reply that is not a ConnectorSearchReply is an error")
	}
}

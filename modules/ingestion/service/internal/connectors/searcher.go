// Package connectors asks the ingestion worker's connector runtime to search
// its connectors live. The worker is a separate process, so the service
// reaches it with a NATS request (docs/adr/0015-live-retrieval-through-connectors.md).
package connectors

import (
	"context"
	"errors"
	"fmt"
	"time"

	"github.com/nats-io/nats.go"
	"google.golang.org/protobuf/proto"

	ingestionv1 "github.com/ChristophBe/knowcelium/modules/ingestion/api/go/ingestionv1"
)

// Subject is the core NATS subject the worker answers searches on. It lies
// outside the INGESTION stream (knowcel.ingestion.>), which would acknowledge
// the request instead of the worker.
const Subject = "knowcel.connectors.search"

var (
	// ErrUnavailable means no worker is running to answer.
	ErrUnavailable = errors.New("the connector runtime is not running")
	// ErrTimeout means the worker did not answer in time.
	ErrTimeout = errors.New("the connector runtime did not answer in time")
)

// Requester sends a request and waits for its reply; *nats.Conn does.
type Requester interface {
	RequestWithContext(ctx context.Context, subj string, data []byte) (*nats.Msg, error)
}

// Searcher searches connectors through the worker.
type Searcher struct {
	nc Requester
	// Timeout bounds the whole search. A connector gets a bit less of it, so
	// that a slow one is reported by name instead of failing the search.
	timeout time.Duration
}

func NewSearcher(nc Requester, timeout time.Duration) *Searcher {
	return &Searcher{nc: nc, timeout: timeout}
}

// Search sends the request to a worker and returns its reply. It sets the time
// each connector gets, shorter than this search's own timeout.
func (s *Searcher) Search(ctx context.Context, req *ingestionv1.ConnectorSearchRequest) (*ingestionv1.ConnectorSearchReply, error) {
	req = proto.Clone(req).(*ingestionv1.ConnectorSearchRequest)
	req.TimeoutSeconds = float32((s.timeout * 4 / 5).Seconds())
	data, err := proto.Marshal(req)
	if err != nil {
		return nil, err
	}
	ctx, cancel := context.WithTimeout(ctx, s.timeout)
	defer cancel()
	msg, err := s.nc.RequestWithContext(ctx, Subject, data)
	switch {
	case errors.Is(err, nats.ErrNoResponders):
		return nil, ErrUnavailable
	case errors.Is(err, context.DeadlineExceeded), errors.Is(err, nats.ErrTimeout):
		return nil, ErrTimeout
	case err != nil:
		return nil, fmt.Errorf("request connector search: %w", err)
	}
	reply := &ingestionv1.ConnectorSearchReply{}
	if err := proto.Unmarshal(msg.Data, reply); err != nil {
		return nil, fmt.Errorf("decode connector search reply: %w", err)
	}
	return reply, nil
}

// Package connectors keeps what the worker reports about its connectors and
// derives their health for ListConnectors and GetConnector.
package connectors

import (
	"context"
	"errors"
	"sort"
	"time"

	ingestionv1 "github.com/ChristophBe/knowcelium/modules/ingestion/api/go/ingestionv1"
)

// ErrNotFound means no connector is configured under the name.
var ErrNotFound = errors.New("connector not found")

// StaleFactor is how many intervals may pass without a successful sync before
// a connector is STALE.
const StaleFactor = 2

// Status is what the worker last reported about a connector.
type Status struct {
	Name     string
	Kind     string
	Enabled  bool
	Interval time.Duration
	// Outcome of the last run; unspecified while the connector has not run.
	Outcome     ingestionv1.SyncOutcome
	LastStart   time.Time
	LastEnd     time.Time
	LastSuccess time.Time
	Documents   int32
	LastError   string
}

// Connector is a Status with its health at a point in time.
type Connector struct {
	Status
	Health ingestionv1.ConnectorHealth
}

// Config is one entry of the worker's connectors file.
type Config struct {
	Name     string
	Kind     string
	Enabled  bool
	Interval time.Duration
	// Error says what is wrong with an invalid entry.
	Error string
}

// Sync is the outcome of one sync run.
type Sync struct {
	Name      string
	Outcome   ingestionv1.SyncOutcome
	Start     time.Time // zero when the run failed before it started
	End       time.Time
	Documents int32
	Error     string
}

// Repository persists connector statuses. Record keeps the newest report per
// connector: one that ended before the stored one changes nothing. Configure
// leaves what the last run reported alone, except for an invalid entry, whose
// last run is its error. Forget removes the connectors not named in keep.
type Repository interface {
	List(ctx context.Context) ([]Status, error)
	Get(ctx context.Context, name string) (Status, error)
	Configure(ctx context.Context, c Config, at time.Time) error
	Forget(ctx context.Context, keep []string) error
	Record(ctx context.Context, s Sync) error
}

// Service reads and updates connector statuses.
type Service struct {
	repo Repository
	now  func() time.Time
}

func New(repo Repository) *Service { return &Service{repo: repo, now: time.Now} }

// List returns every known connector, by name.
func (s *Service) List(ctx context.Context) ([]Connector, error) {
	statuses, err := s.repo.List(ctx)
	if err != nil {
		return nil, err
	}
	now := s.now()
	out := make([]Connector, 0, len(statuses))
	for _, st := range statuses {
		out = append(out, Connector{Status: st, Health: Health(st, now)})
	}
	sort.Slice(out, func(i, j int) bool { return out[i].Name < out[j].Name })
	return out, nil
}

// Get returns the connector with the name, or ErrNotFound.
func (s *Service) Get(ctx context.Context, name string) (Connector, error) {
	st, err := s.repo.Get(ctx, name)
	if err != nil {
		return Connector{}, err
	}
	return Connector{Status: st, Health: Health(st, s.now())}, nil
}

// ApplyConfigured records the connectors the worker was started with and
// forgets the others.
func (s *Service) ApplyConfigured(ctx context.Context, configs []Config, at time.Time) error {
	names := make([]string, 0, len(configs))
	for _, c := range configs {
		if err := s.repo.Configure(ctx, c, at); err != nil {
			return err
		}
		names = append(names, c.Name)
	}
	return s.repo.Forget(ctx, names)
}

// ApplySynced records the outcome of a sync run.
func (s *Service) ApplySynced(ctx context.Context, sync Sync) error {
	return s.repo.Record(ctx, sync)
}

// Health derives the health of a connector at now.
//
// A failed last run is FAILING and a partly failed one DEGRADED, whatever
// their age: the error says what to fix. A run that succeeded is HEALTHY
// unless the success is older than StaleFactor intervals, which means syncs
// stopped. A disabled connector is not expected to sync and so never STALE,
// nor is one whose interval is unknown (an invalid entry). One that never
// reported a run is UNKNOWN.
func Health(st Status, now time.Time) ingestionv1.ConnectorHealth {
	switch st.Outcome {
	case ingestionv1.SyncOutcome_SYNC_OUTCOME_FAILED:
		return ingestionv1.ConnectorHealth_CONNECTOR_HEALTH_FAILING
	case ingestionv1.SyncOutcome_SYNC_OUTCOME_PARTIAL:
		return ingestionv1.ConnectorHealth_CONNECTOR_HEALTH_DEGRADED
	case ingestionv1.SyncOutcome_SYNC_OUTCOME_SUCCEEDED:
		if st.Enabled && st.Interval > 0 && !st.LastSuccess.IsZero() &&
			now.Sub(st.LastSuccess) > StaleFactor*st.Interval {
			return ingestionv1.ConnectorHealth_CONNECTOR_HEALTH_STALE
		}
		return ingestionv1.ConnectorHealth_CONNECTOR_HEALTH_HEALTHY
	default:
		return ingestionv1.ConnectorHealth_CONNECTOR_HEALTH_UNKNOWN
	}
}

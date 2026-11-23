package connectors

import (
	"context"
	"errors"
	"testing"
	"time"

	ingestionv1 "github.com/ChristophBe/knowcelium/modules/ingestion/api/go/ingestionv1"
)

const (
	succeeded = ingestionv1.SyncOutcome_SYNC_OUTCOME_SUCCEEDED
	partial   = ingestionv1.SyncOutcome_SYNC_OUTCOME_PARTIAL
	failed    = ingestionv1.SyncOutcome_SYNC_OUTCOME_FAILED

	healthy  = ingestionv1.ConnectorHealth_CONNECTOR_HEALTH_HEALTHY
	degraded = ingestionv1.ConnectorHealth_CONNECTOR_HEALTH_DEGRADED
	failing  = ingestionv1.ConnectorHealth_CONNECTOR_HEALTH_FAILING
	stale    = ingestionv1.ConnectorHealth_CONNECTOR_HEALTH_STALE
	unknown  = ingestionv1.ConnectorHealth_CONNECTOR_HEALTH_UNKNOWN
)

var now = time.Date(2026, 11, 23, 12, 0, 0, 0, time.UTC)

func TestHealth(t *testing.T) {
	interval := 5 * time.Minute
	tests := []struct {
		name string
		st   Status
		want ingestionv1.ConnectorHealth
	}{
		{"a connector that never ran is unknown", Status{Enabled: true, Interval: interval}, unknown},
		{"a success within the interval is healthy", Status{Enabled: true, Interval: interval, Outcome: succeeded, LastSuccess: now.Add(-time.Minute)}, healthy},
		{"a success just inside twice the interval is healthy", Status{Enabled: true, Interval: interval, Outcome: succeeded, LastSuccess: now.Add(-2 * interval)}, healthy},
		{"a success older than twice the interval is stale", Status{Enabled: true, Interval: interval, Outcome: succeeded, LastSuccess: now.Add(-2*interval - time.Second)}, stale},
		{"partial failures degrade", Status{Enabled: true, Interval: interval, Outcome: partial, LastSuccess: now.Add(-time.Hour)}, degraded},
		{"a failed run fails", Status{Enabled: true, Interval: interval, Outcome: failed, LastError: "boom"}, failing},
		{"a failed run fails however old the last success", Status{Enabled: true, Interval: interval, Outcome: failed, LastSuccess: now.Add(-24 * time.Hour)}, failing},
		{"a disabled connector is never stale", Status{Enabled: false, Interval: interval, Outcome: succeeded, LastSuccess: now.Add(-24 * time.Hour)}, healthy},
		{"an unknown interval is never stale", Status{Enabled: true, Outcome: succeeded, LastSuccess: now.Add(-24 * time.Hour)}, healthy},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			if got := Health(tt.st, now); got != tt.want {
				t.Errorf("Health = %v, want %v", got, tt.want)
			}
		})
	}
}

type fakeRepo struct {
	statuses []Status
	err      error
	configs  []Config
	kept     []string
	synced   []Sync
}

func (f *fakeRepo) List(context.Context) ([]Status, error) { return f.statuses, f.err }

func (f *fakeRepo) Get(_ context.Context, name string) (Status, error) {
	for _, s := range f.statuses {
		if s.Name == name {
			return s, nil
		}
	}
	return Status{}, ErrNotFound
}

func (f *fakeRepo) Configure(_ context.Context, c Config, _ time.Time) error {
	f.configs = append(f.configs, c)
	return f.err
}

func (f *fakeRepo) Forget(_ context.Context, keep []string) error { f.kept = keep; return f.err }

func (f *fakeRepo) Record(_ context.Context, s Sync) error {
	f.synced = append(f.synced, s)
	return f.err
}

func newService(repo *fakeRepo) *Service {
	s := New(repo)
	s.now = func() time.Time { return now }
	return s
}

func TestListDerivesHealthAndSortsByName(t *testing.T) {
	repo := &fakeRepo{statuses: []Status{
		{Name: "b", Enabled: true, Interval: time.Minute, Outcome: succeeded, LastSuccess: now.Add(-time.Hour)},
		{Name: "a", Enabled: true, Interval: time.Minute},
	}}
	list, err := newService(repo).List(t.Context())
	if err != nil {
		t.Fatal(err)
	}
	if len(list) != 2 || list[0].Name != "a" || list[0].Health != unknown || list[1].Name != "b" || list[1].Health != stale {
		t.Errorf("list = %+v", list)
	}
}

func TestGetDerivesHealth(t *testing.T) {
	repo := &fakeRepo{statuses: []Status{{Name: "a", Enabled: true, Interval: time.Minute, Outcome: failed}}}
	c, err := newService(repo).Get(t.Context(), "a")
	if err != nil || c.Health != failing {
		t.Fatalf("Get = %+v, %v", c, err)
	}
	if _, err := newService(repo).Get(t.Context(), "zzz"); !errors.Is(err, ErrNotFound) {
		t.Errorf("err = %v, want ErrNotFound", err)
	}
}

func TestApplyConfiguredKeepsOnlyTheListedConnectors(t *testing.T) {
	repo := &fakeRepo{}
	err := newService(repo).ApplyConfigured(t.Context(), []Config{{Name: "a"}, {Name: "#2", Error: "bad"}}, now)
	if err != nil {
		t.Fatal(err)
	}
	if len(repo.configs) != 2 || len(repo.kept) != 2 || repo.kept[0] != "a" || repo.kept[1] != "#2" {
		t.Errorf("configs = %+v, kept = %v", repo.configs, repo.kept)
	}
}

func TestErrorsPassThrough(t *testing.T) {
	boom := errors.New("db down")
	repo := &fakeRepo{err: boom}
	s := newService(repo)
	if _, err := s.List(t.Context()); !errors.Is(err, boom) {
		t.Errorf("List err = %v", err)
	}
	if err := s.ApplyConfigured(t.Context(), []Config{{Name: "a"}}, now); !errors.Is(err, boom) {
		t.Errorf("ApplyConfigured err = %v", err)
	}
	if err := s.ApplySynced(t.Context(), Sync{Name: "a"}); !errors.Is(err, boom) {
		t.Errorf("ApplySynced err = %v", err)
	}
}

func TestApplySyncedRecords(t *testing.T) {
	repo := &fakeRepo{}
	if err := newService(repo).ApplySynced(t.Context(), Sync{Name: "a", Outcome: succeeded, End: now}); err != nil {
		t.Fatal(err)
	}
	if len(repo.synced) != 1 || repo.synced[0].Name != "a" {
		t.Errorf("synced = %+v", repo.synced)
	}
}

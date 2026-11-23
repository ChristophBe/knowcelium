//go:build integration

package store

import (
	"errors"
	"slices"
	"testing"
	"time"

	ingestionv1 "github.com/ChristophBe/knowcelium/modules/ingestion/api/go/ingestionv1"
	"github.com/ChristophBe/knowcelium/modules/ingestion/migrations"
	"github.com/ChristophBe/knowcelium/modules/ingestion/service/internal/connectors"
	"github.com/ChristophBe/knowcelium/platform/go/postgres/pgtest"
)

const (
	succeeded = ingestionv1.SyncOutcome_SYNC_OUTCOME_SUCCEEDED
	partial   = ingestionv1.SyncOutcome_SYNC_OUTCOME_PARTIAL
	failedRun = ingestionv1.SyncOutcome_SYNC_OUTCOME_FAILED
)

var t0 = time.Date(2026, 11, 23, 8, 0, 0, 0, time.UTC)

func TestConnectorStatus(t *testing.T) {
	repo := NewConnectors(New(pgtest.Start(t, "ingestion", migrations.FS)))
	ctx := t.Context()
	cfg := connectors.Config{Name: "docs", Kind: "folder", Enabled: true, Interval: 5 * time.Minute}

	t.Run("a configured connector that never ran has no outcome", func(t *testing.T) {
		if err := repo.Configure(ctx, cfg, t0); err != nil {
			t.Fatal(err)
		}
		got, err := repo.Get(ctx, "docs")
		if err != nil {
			t.Fatal(err)
		}
		if got.Kind != "folder" || !got.Enabled || got.Interval != 5*time.Minute ||
			got.Outcome != ingestionv1.SyncOutcome_SYNC_OUTCOME_UNSPECIFIED || !got.LastEnd.IsZero() || !got.LastSuccess.IsZero() {
			t.Errorf("status = %+v", got)
		}
	})

	t.Run("a success sets the last success", func(t *testing.T) {
		err := repo.Record(ctx, connectors.Sync{Name: "docs", Outcome: succeeded, Start: t0, End: t0.Add(time.Second), Documents: 3})
		if err != nil {
			t.Fatal(err)
		}
		got, _ := repo.Get(ctx, "docs")
		if got.Outcome != succeeded || got.Documents != 3 || !got.LastStart.Equal(t0) || !got.LastEnd.Equal(t0.Add(time.Second)) || !got.LastSuccess.Equal(t0.Add(time.Second)) {
			t.Errorf("status = %+v", got)
		}
	})

	t.Run("a failure keeps the last success and records the error", func(t *testing.T) {
		err := repo.Record(ctx, connectors.Sync{Name: "docs", Outcome: failedRun, Start: t0.Add(time.Minute), End: t0.Add(time.Minute + time.Second), Documents: 3, Error: "boom"})
		if err != nil {
			t.Fatal(err)
		}
		got, _ := repo.Get(ctx, "docs")
		if got.Outcome != failedRun || got.LastError != "boom" || !got.LastSuccess.Equal(t0.Add(time.Second)) {
			t.Errorf("status = %+v", got)
		}
	})

	t.Run("a partial failure does not count as a success", func(t *testing.T) {
		err := repo.Record(ctx, connectors.Sync{Name: "docs", Outcome: partial, Start: t0.Add(2 * time.Minute), End: t0.Add(2*time.Minute + time.Second), Error: "1 items failed"})
		if err != nil {
			t.Fatal(err)
		}
		got, _ := repo.Get(ctx, "docs")
		if got.Outcome != partial || !got.LastSuccess.Equal(t0.Add(time.Second)) {
			t.Errorf("status = %+v", got)
		}
	})

	t.Run("an older report changes nothing", func(t *testing.T) {
		err := repo.Record(ctx, connectors.Sync{Name: "docs", Outcome: succeeded, Start: t0, End: t0.Add(time.Second), Documents: 99})
		if err != nil {
			t.Fatal(err)
		}
		got, _ := repo.Get(ctx, "docs")
		if got.Outcome != partial || got.Documents == 99 {
			t.Errorf("a stale report was applied: %+v", got)
		}
	})

	t.Run("configuring again keeps the last run", func(t *testing.T) {
		cfg.Interval = time.Minute
		if err := repo.Configure(ctx, cfg, t0.Add(time.Hour)); err != nil {
			t.Fatal(err)
		}
		got, _ := repo.Get(ctx, "docs")
		if got.Interval != time.Minute || got.Outcome != partial || !got.LastSuccess.Equal(t0.Add(time.Second)) {
			t.Errorf("status = %+v", got)
		}
	})

	t.Run("an invalid entry fails with its error", func(t *testing.T) {
		bad := connectors.Config{Name: "#2", Enabled: true, Error: "unknown kind"}
		if err := repo.Configure(ctx, bad, t0); err != nil {
			t.Fatal(err)
		}
		got, _ := repo.Get(ctx, "#2")
		if got.Outcome != failedRun || got.LastError != "unknown kind" || got.LastEnd.IsZero() {
			t.Errorf("status = %+v", got)
		}
	})

	t.Run("a report for an unknown connector adds it", func(t *testing.T) {
		if err := repo.Record(ctx, connectors.Sync{Name: "early", Outcome: succeeded, End: t0}); err != nil {
			t.Fatal(err)
		}
		got, err := repo.Get(ctx, "early")
		if err != nil || got.Outcome != succeeded || !got.LastStart.IsZero() {
			t.Errorf("status = %+v, err %v", got, err)
		}
	})

	t.Run("lists by name and forgets the unlisted", func(t *testing.T) {
		all, err := repo.List(ctx)
		if err != nil {
			t.Fatal(err)
		}
		names := func(s []connectors.Status) []string {
			var out []string
			for _, c := range s {
				out = append(out, c.Name)
			}
			return out
		}
		if got := names(all); !slices.Equal(got, []string{"#2", "docs", "early"}) {
			t.Errorf("names = %v", got)
		}
		if err := repo.Forget(ctx, []string{"docs"}); err != nil {
			t.Fatal(err)
		}
		all, _ = repo.List(ctx)
		if got := names(all); !slices.Equal(got, []string{"docs"}) {
			t.Errorf("after Forget: %v", got)
		}
		if err := repo.Forget(ctx, nil); err != nil {
			t.Fatal(err)
		}
		if all, _ = repo.List(ctx); len(all) != 0 {
			t.Errorf("Forget(nil) kept %v", names(all))
		}
		if _, err := repo.Get(ctx, "docs"); !errors.Is(err, connectors.ErrNotFound) {
			t.Errorf("Get err = %v, want ErrNotFound", err)
		}
	})
}

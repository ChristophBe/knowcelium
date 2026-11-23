package store

import (
	"context"
	"errors"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgtype"

	ingestionv1 "github.com/ChristophBe/knowcelium/modules/ingestion/api/go/ingestionv1"
	"github.com/ChristophBe/knowcelium/modules/ingestion/service/internal/connectors"
)

// Connectors implements connectors.Repository on top of the generated queries.
type Connectors struct {
	q Querier
}

func NewConnectors(q Querier) *Connectors { return &Connectors{q: q} }

func (c *Connectors) List(ctx context.Context) ([]connectors.Status, error) {
	rows, err := c.q.ListConnectorStatuses(ctx)
	if err != nil {
		return nil, err
	}
	out := make([]connectors.Status, 0, len(rows))
	for _, r := range rows {
		out = append(out, toStatus(r))
	}
	return out, nil
}

func (c *Connectors) Get(ctx context.Context, name string) (connectors.Status, error) {
	row, err := c.q.GetConnectorStatus(ctx, name)
	if errors.Is(err, pgx.ErrNoRows) {
		return connectors.Status{}, connectors.ErrNotFound
	}
	if err != nil {
		return connectors.Status{}, err
	}
	return toStatus(row), nil
}

func (c *Connectors) Configure(ctx context.Context, cfg connectors.Config, at time.Time) error {
	return c.q.ConfigureConnector(ctx, ConfigureConnectorParams{
		Name:            cfg.Name,
		Kind:            cfg.Kind,
		Enabled:         cfg.Enabled,
		IntervalSeconds: int32(cfg.Interval / time.Second),
		Error:           cfg.Error,
		Time:            timestamptz(at),
	})
}

func (c *Connectors) Forget(ctx context.Context, keep []string) error {
	if keep == nil {
		keep = []string{} // an empty array, not NULL: `<> ALL(NULL)` matches nothing
	}
	return c.q.DeleteConnectorsExcept(ctx, keep)
}

func (c *Connectors) Record(ctx context.Context, s connectors.Sync) error {
	return c.q.RecordConnectorSync(ctx, RecordConnectorSyncParams{
		Name:      s.Name,
		Outcome:   int16(s.Outcome),
		StartTime: timestamptz(s.Start),
		EndTime:   timestamptz(s.End),
		Documents: s.Documents,
		Error:     s.Error,
	})
}

// timestamptz is NULL for the zero time.
func timestamptz(t time.Time) pgtype.Timestamptz {
	return pgtype.Timestamptz{Time: t, Valid: !t.IsZero()}
}

func toStatus(r IngestionConnectorStatus) connectors.Status {
	return connectors.Status{
		Name:        r.Name,
		Kind:        r.Kind,
		Enabled:     r.Enabled,
		Interval:    time.Duration(r.IntervalSeconds) * time.Second,
		Outcome:     ingestionv1.SyncOutcome(r.LastOutcome),
		LastStart:   r.LastStart.Time,
		LastEnd:     r.LastEnd.Time,
		LastSuccess: r.LastSuccess.Time,
		Documents:   r.Documents,
		LastError:   r.LastError,
	}
}

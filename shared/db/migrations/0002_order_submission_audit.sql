CREATE TABLE order_submission_attempt (
    attempt_id TEXT PRIMARY KEY,
    draft_id TEXT NOT NULL UNIQUE,
    plan_id TEXT NOT NULL UNIQUE,
    approval_id TEXT NOT NULL,
    account_id TEXT NOT NULL,
    mode TEXT NOT NULL CHECK (mode = 'SIMULATED'),
    order_payload JSON NOT NULL,
    status TEXT NOT NULL,
    broker_order_id TEXT,
    event_number INTEGER NOT NULL CHECK (event_number >= 1),
    started_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    UNIQUE (account_id, broker_order_id)
);

CREATE TABLE order_submission_event (
    attempt_id TEXT NOT NULL,
    event_number INTEGER NOT NULL,
    status TEXT NOT NULL,
    recorded_at TIMESTAMPTZ NOT NULL,
    broker_response JSON,
    PRIMARY KEY (attempt_id, event_number)
);

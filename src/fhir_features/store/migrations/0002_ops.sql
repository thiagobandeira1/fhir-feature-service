-- Operational tables: raw bundle retention (reparse) and the append-only ingest audit log.

CREATE TABLE raw_bundles (
    bundle_hash     VARCHAR NOT NULL PRIMARY KEY,
    source          VARCHAR NOT NULL,
    patient_id      VARCHAR NOT NULL,
    resource_count  INTEGER NOT NULL,
    payload         JSON NOT NULL,
    ingested_at     TIMESTAMP NOT NULL
);

CREATE TABLE ingest_log (
    ingest_id        VARCHAR NOT NULL PRIMARY KEY,
    source           VARCHAR NOT NULL,
    patient_id       VARCHAR,
    bundle_hash      VARCHAR,
    action           VARCHAR NOT NULL,
    resource_counts  JSON,
    warnings         JSON,
    started_at       TIMESTAMP NOT NULL,
    completed_at     TIMESTAMP,
    service_version  VARCHAR NOT NULL
);

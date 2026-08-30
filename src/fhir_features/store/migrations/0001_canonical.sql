-- Canonical clinical-event tables. Grain: one row per (source, <native id>).
-- (source, patient_id) is the cross-adapter namespacing rule.

CREATE TABLE patients (
    source        VARCHAR NOT NULL,
    patient_id    VARCHAR NOT NULL,
    birth_date    DATE,
    death_date    DATE,
    sex           VARCHAR NOT NULL,
    race          VARCHAR,
    ethnicity     VARCHAR,
    city          VARCHAR,
    state         VARCHAR,
    postal_code   VARCHAR,
    ingested_at   TIMESTAMP NOT NULL,
    PRIMARY KEY (source, patient_id)
);

CREATE TABLE encounters (
    source           VARCHAR NOT NULL,
    encounter_id     VARCHAR NOT NULL,
    patient_id       VARCHAR NOT NULL,
    encounter_class  VARCHAR NOT NULL,
    type_code        VARCHAR,
    type_system      VARCHAR,
    type_display     VARCHAR,
    start_ts         TIMESTAMP,
    end_ts           TIMESTAMP,
    start_date       DATE NOT NULL,
    date_precision   VARCHAR NOT NULL,
    ingested_at      TIMESTAMP NOT NULL,
    PRIMARY KEY (source, encounter_id)
);

CREATE TABLE conditions (
    source              VARCHAR NOT NULL,
    condition_id        VARCHAR NOT NULL,
    patient_id          VARCHAR NOT NULL,
    encounter_id        VARCHAR,
    code                VARCHAR NOT NULL,
    code_system         VARCHAR NOT NULL,
    code_display        VARCHAR,
    clinical_status     VARCHAR,
    verification_status VARCHAR,
    onset_date          DATE NOT NULL,
    abatement_date      DATE,
    recorded_date       DATE,
    date_precision      VARCHAR NOT NULL,
    ingested_at         TIMESTAMP NOT NULL,
    PRIMARY KEY (source, condition_id)
);

CREATE TABLE observations (
    source                 VARCHAR NOT NULL,
    observation_id         VARCHAR NOT NULL,
    parent_observation_id  VARCHAR,
    patient_id             VARCHAR NOT NULL,
    encounter_id           VARCHAR,
    code                   VARCHAR NOT NULL,
    code_system            VARCHAR NOT NULL,
    code_display           VARCHAR,
    category               VARCHAR,
    effective_ts           TIMESTAMP,
    effective_date         DATE NOT NULL,
    date_precision         VARCHAR NOT NULL,
    value_num              DECIMAL(18, 6),
    value_unit             VARCHAR,
    value_code             VARCHAR,
    value_code_system      VARCHAR,
    value_text             VARCHAR,
    status                 VARCHAR NOT NULL,
    ingested_at            TIMESTAMP NOT NULL,
    PRIMARY KEY (source, observation_id)
);

CREATE TABLE procedures (
    source              VARCHAR NOT NULL,
    procedure_id        VARCHAR NOT NULL,
    patient_id          VARCHAR NOT NULL,
    encounter_id        VARCHAR,
    code                VARCHAR NOT NULL,
    code_system         VARCHAR NOT NULL,
    code_display        VARCHAR,
    performed_date      DATE NOT NULL,
    performed_end_date  DATE,
    date_precision      VARCHAR NOT NULL,
    status              VARCHAR NOT NULL,
    ingested_at         TIMESTAMP NOT NULL,
    PRIMARY KEY (source, procedure_id)
);

CREATE TABLE medication_requests (
    source                 VARCHAR NOT NULL,
    medication_request_id  VARCHAR NOT NULL,
    patient_id             VARCHAR NOT NULL,
    encounter_id           VARCHAR,
    code                   VARCHAR NOT NULL,
    code_system            VARCHAR NOT NULL,
    code_display           VARCHAR,
    authored_date          DATE NOT NULL,
    date_precision         VARCHAR NOT NULL,
    status                 VARCHAR,
    intent                 VARCHAR,
    ingested_at            TIMESTAMP NOT NULL,
    PRIMARY KEY (source, medication_request_id)
);

CREATE TABLE immunizations (
    source           VARCHAR NOT NULL,
    immunization_id  VARCHAR NOT NULL,
    patient_id       VARCHAR NOT NULL,
    code             VARCHAR NOT NULL,
    code_system      VARCHAR NOT NULL,
    code_display     VARCHAR,
    occurrence_date  DATE NOT NULL,
    ingested_at      TIMESTAMP NOT NULL,
    PRIMARY KEY (source, immunization_id)
);

CREATE TABLE claim_diagnoses (
    source                 VARCHAR NOT NULL,
    claim_id               VARCHAR NOT NULL,
    diagnosis_sequence     SMALLINT NOT NULL,
    patient_id             VARCHAR NOT NULL,
    claim_type             VARCHAR,
    billable_period_start  DATE,
    billable_period_end    DATE,
    diagnosis_code         VARCHAR NOT NULL,
    diagnosis_code_system  VARCHAR NOT NULL,
    diagnosis_display      VARCHAR,
    resolved_condition_id  VARCHAR NOT NULL,
    ingested_at            TIMESTAMP NOT NULL,
    PRIMARY KEY (source, claim_id, diagnosis_sequence)
);

-- Every coding of Condition/Procedure resources; raw URI always preserved.
CREATE TABLE resource_codings (
    source           VARCHAR NOT NULL,
    resource_type    VARCHAR NOT NULL,
    resource_id      VARCHAR NOT NULL,
    coding_seq       SMALLINT NOT NULL,
    code             VARCHAR NOT NULL,
    code_system_uri  VARCHAR,
    code_system      VARCHAR NOT NULL,
    display          VARCHAR,
    PRIMARY KEY (source, resource_type, resource_id, coding_seq)
);

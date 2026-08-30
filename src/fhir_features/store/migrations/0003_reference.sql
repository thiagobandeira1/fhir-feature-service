-- Reference data: value-set membership, loaded at startup from committed JSON
-- (src/fhir_features/features/value_sets/). SNOMED/LOINC/RxNorm/CVX only in v1 — no CPT.

CREATE TABLE value_set_members (
    value_set_id       VARCHAR NOT NULL,
    code_system        VARCHAR NOT NULL,
    code               VARCHAR NOT NULL,
    display            VARCHAR,
    valuesets_version  VARCHAR NOT NULL,
    PRIMARY KEY (value_set_id, code_system, code)
);

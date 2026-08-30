"""The feature dictionary — single source of truth for ``/v1/features/schema`` and docs.

A schema-contract test asserts this registry matches the actual columns produced by
``patient_features_v1.sql`` (names AND order) and that every ``value_set_id`` referenced here
exists in the loaded value sets — registry, SQL, and value sets cannot drift.
"""

from dataclasses import dataclass

FEATURE_VERSION = "v1"

AS_OF_SEMANTICS = "event included iff source-local event date <= as_of"


@dataclass(frozen=True)
class FeatureSpec:
    name: str
    type: str
    nullable: bool
    description: str
    value_set_id: str | None = None
    added_in: str = "v1"


FEATURES: tuple[FeatureSpec, ...] = (
    FeatureSpec("source", "string", False, "Data source token ('synthea' | 'mimic')."),
    FeatureSpec("patient_id", "string", False, "Source-native patient id."),
    FeatureSpec("as_of", "date", False, "Echoed request parameter; all logic is relative to it."),
    FeatureSpec("age_years", "integer", True, "Floor whole years between birth_date and as_of."),
    FeatureSpec("sex", "string", False, "male | female | other | unknown."),
    FeatureSpec("race", "string", True, "US Core race extension text."),
    FeatureSpec("ethnicity", "string", True, "US Core ethnicity extension text."),
    FeatureSpec("is_deceased", "boolean", False, "death_date <= as_of."),
    FeatureSpec(
        "has_diabetes",
        "boolean",
        False,
        "Any diabetes condition with onset <= as_of and no abatement <= as_of. Date-derived; "
        "clinical_status is never consulted.",
        "diabetes_snomed",
    ),
    FeatureSpec("has_hypertension", "boolean", False, "Same pattern.", "hypertension_snomed"),
    FeatureSpec(
        "has_ascvd", "boolean", False, "Same pattern (statin-measure input).", "ascvd_snomed"
    ),
    FeatureSpec("has_ckd", "boolean", False, "Same pattern.", "ckd_snomed"),
    FeatureSpec("has_chf", "boolean", False, "Same pattern.", "chf_snomed"),
    FeatureSpec("has_copd", "boolean", False, "Same pattern.", "copd_snomed"),
    FeatureSpec("chronic_condition_count", "integer", False, "Count of TRUE chronic flags above."),
    FeatureSpec(
        "latest_sbp",
        "number",
        True,
        "Most recent systolic (LOINC 8480-6) on/before as_of.",
        "bp_loinc",
    ),
    FeatureSpec(
        "latest_dbp",
        "number",
        True,
        "Diastolic (8462-4) from the SAME panel as latest_sbp — never independently latest.",
        "bp_loinc",
    ),
    FeatureSpec("latest_bp_date", "date", True, "Date of that panel."),
    FeatureSpec("latest_hba1c", "number", True, "Most recent HbA1c % (4548-4).", "hba1c_loinc"),
    FeatureSpec("latest_hba1c_date", "date", True, "Date of that result."),
    FeatureSpec("latest_bmi", "number", True, "Most recent BMI kg/m2 (39156-5).", "bmi_loinc"),
    FeatureSpec("latest_bmi_date", "date", True, "Date of that result."),
    FeatureSpec(
        "tobacco_status_code",
        "string",
        True,
        "Raw SNOMED answer of the latest tobacco screening (72166-2). NULL = never screened — "
        "the gap signal. Descriptive: P1 owns any verdict.",
        "tobacco_status_loinc",
    ),
    FeatureSpec("tobacco_status_date", "date", True, "Date of that screening."),
    FeatureSpec(
        "statin_authored_365d",
        "boolean",
        False,
        "Any statin order authored in (as_of-365d, as_of]. A recency proxy, NOT adherence "
        "(Synthea has no reliable stop dates); named descriptively on purpose.",
        "statin_rxnorm",
    ),
    FeatureSpec(
        "last_statin_authored_date",
        "date",
        True,
        "Most recent statin order on/before as_of.",
        "statin_rxnorm",
    ),
    FeatureSpec(
        "distinct_meds_authored_365d",
        "integer",
        False,
        "Distinct RxNorm codes authored in the window (date-derived med burden).",
    ),
    FeatureSpec("last_mammogram_date", "date", True, "Latest mammography.", "mammogram_proc"),
    FeatureSpec("last_colonoscopy_date", "date", True, "Latest colonoscopy.", "colonoscopy_proc"),
    FeatureSpec(
        "last_fobt_fit_date", "date", True, "Latest stool-based screening lab.", "fobt_fit_loinc"
    ),
    FeatureSpec(
        "last_retinal_exam_date", "date", True, "Latest retinal exam.", "retinal_exam_proc"
    ),
    FeatureSpec(
        "last_flu_immunization_date", "date", True, "Latest influenza vaccine.", "flu_vaccine_cvx"
    ),
    FeatureSpec("encounters_365d", "integer", False, "Encounters starting in (as_of-365d, as_of]."),
    FeatureSpec("encounters_90d", "integer", False, "Encounters starting in (as_of-90d, as_of]."),
    FeatureSpec("ambulatory_visits_365d", "integer", False, "Class AMB in the 365d window."),
    FeatureSpec("wellness_visits_365d", "integer", False, "Class WELLNESS in the window."),
    FeatureSpec("ed_visits_365d", "integer", False, "Class EMER in the window."),
    FeatureSpec("inpatient_admits_365d", "integer", False, "Class IMP starting in the window."),
    FeatureSpec(
        "inpatient_days_365d",
        "integer",
        False,
        "Sum of LOS days for IMP encounters starting in the window (end date via UTC ts — "
        "documented one-day approximation).",
    ),
    FeatureSpec(
        "lab_results_365d", "integer", False, "Top-level laboratory observations in the window."
    ),
    FeatureSpec(
        "days_since_last_encounter", "integer", True, "as_of - latest start_date; NULL if none."
    ),
)


def feature_names() -> list[str]:
    return [f.name for f in FEATURES]

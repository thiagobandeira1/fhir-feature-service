-- patient_features v1 — computed at query time for one as_of date (ADR-0002, ADR-0005).
--
-- THE inclusion rule (tested by goldens at two pinned dates): an event counts iff its
-- source-local-derived DATE <= as_of. Every feature below is date-derived only; status
-- columns are never consulted (they are ingest-time snapshots that would leak future state
-- into historical as_of rows).
--
-- Bound parameters, in order: as_of (DATE), repeated once — the params CTE fans it out.

WITH params AS (
    SELECT CAST(? AS DATE) AS as_of
),

chronic AS (
    SELECT
        c.source,
        c.patient_id,
        bool_or(v.value_set_id = 'diabetes_snomed')     AS has_diabetes,
        bool_or(v.value_set_id = 'hypertension_snomed') AS has_hypertension,
        bool_or(v.value_set_id = 'ascvd_snomed')        AS has_ascvd,
        bool_or(v.value_set_id = 'ckd_snomed')          AS has_ckd,
        bool_or(v.value_set_id = 'chf_snomed')          AS has_chf,
        bool_or(v.value_set_id = 'copd_snomed')         AS has_copd
    FROM conditions c
    JOIN value_set_members v
      ON v.code_system = c.code_system AND v.code = c.code
    CROSS JOIN params
    WHERE c.onset_date <= params.as_of
      AND (c.abatement_date IS NULL OR c.abatement_date > params.as_of)
      AND v.value_set_id IN ('diabetes_snomed', 'hypertension_snomed', 'ascvd_snomed',
                             'ckd_snomed', 'chf_snomed', 'copd_snomed')
    GROUP BY c.source, c.patient_id
),

-- Latest systolic child row; diastolic comes from the SAME parent panel (never
-- independently latest — mismatched-pair readings would be clinically wrong).
latest_sbp AS (
    SELECT source, patient_id, parent_observation_id, effective_date, value_num
    FROM (
        SELECT
            o.*,
            row_number() OVER (
                PARTITION BY o.source, o.patient_id
                ORDER BY o.effective_date DESC, o.observation_id DESC
            ) AS rn
        FROM observations o
        CROSS JOIN params
        WHERE o.code = '8480-6' AND o.effective_date <= params.as_of
    )
    WHERE rn = 1
),
latest_bp AS (
    SELECT
        s.source,
        s.patient_id,
        s.value_num       AS latest_sbp,
        d.value_num       AS latest_dbp,
        s.effective_date  AS latest_bp_date
    FROM latest_sbp s
    LEFT JOIN observations d
      ON d.source = s.source
     AND d.parent_observation_id = s.parent_observation_id
     AND d.code = '8462-4'
     AND s.parent_observation_id IS NOT NULL
),

latest_lab AS (
    SELECT source, patient_id, code, value_num, effective_date
    FROM (
        SELECT
            o.source, o.patient_id, o.code, o.value_num, o.effective_date,
            row_number() OVER (
                PARTITION BY o.source, o.patient_id, o.code
                ORDER BY o.effective_date DESC, o.observation_id DESC
            ) AS rn
        FROM observations o
        CROSS JOIN params
        WHERE o.code IN ('4548-4', '39156-5') AND o.effective_date <= params.as_of
    )
    WHERE rn = 1
),

latest_tobacco AS (
    SELECT source, patient_id, value_code, effective_date
    FROM (
        SELECT
            o.source, o.patient_id, o.value_code, o.effective_date,
            row_number() OVER (
                PARTITION BY o.source, o.patient_id
                ORDER BY o.effective_date DESC, o.observation_id DESC
            ) AS rn
        FROM observations o
        CROSS JOIN params
        WHERE o.code = '72166-2' AND o.effective_date <= params.as_of
    )
    WHERE rn = 1
),

statins AS (
    SELECT
        m.source,
        m.patient_id,
        max(m.authored_date) AS last_statin_authored_date,
        bool_or(m.authored_date > params.as_of - INTERVAL 365 DAY) AS statin_authored_365d
    FROM medication_requests m
    JOIN value_set_members v
      ON v.value_set_id = 'statin_rxnorm'
     AND v.code_system = m.code_system
     AND v.code = m.code
    CROSS JOIN params
    WHERE m.authored_date <= params.as_of
    GROUP BY m.source, m.patient_id
),

meds_365 AS (
    SELECT m.source, m.patient_id, count(DISTINCT m.code) AS distinct_meds_authored_365d
    FROM medication_requests m
    CROSS JOIN params
    WHERE m.authored_date <= params.as_of
      AND m.authored_date > params.as_of - INTERVAL 365 DAY
    GROUP BY m.source, m.patient_id
),

screenings AS (
    SELECT
        p.source,
        p.patient_id,
        max(CASE WHEN v.value_set_id = 'mammogram_proc'    THEN p.performed_date END)
            AS last_mammogram_date,
        max(CASE WHEN v.value_set_id = 'colonoscopy_proc'  THEN p.performed_date END)
            AS last_colonoscopy_date,
        max(CASE WHEN v.value_set_id = 'retinal_exam_proc' THEN p.performed_date END)
            AS last_retinal_exam_date
    FROM procedures p
    JOIN value_set_members v
      ON v.code_system = p.code_system AND v.code = p.code
    CROSS JOIN params
    WHERE p.performed_date <= params.as_of
      AND v.value_set_id IN ('mammogram_proc', 'colonoscopy_proc', 'retinal_exam_proc')
    GROUP BY p.source, p.patient_id
),

fobt AS (
    SELECT o.source, o.patient_id, max(o.effective_date) AS last_fobt_fit_date
    FROM observations o
    JOIN value_set_members v
      ON v.value_set_id = 'fobt_fit_loinc'
     AND v.code_system = o.code_system
     AND v.code = o.code
    CROSS JOIN params
    WHERE o.effective_date <= params.as_of
    GROUP BY o.source, o.patient_id
),

flu AS (
    SELECT i.source, i.patient_id, max(i.occurrence_date) AS last_flu_immunization_date
    FROM immunizations i
    JOIN value_set_members v
      ON v.value_set_id = 'flu_vaccine_cvx'
     AND v.code_system = i.code_system
     AND v.code = i.code
    CROSS JOIN params
    WHERE i.occurrence_date <= params.as_of
    GROUP BY i.source, i.patient_id
),

utilization AS (
    SELECT
        e.source,
        e.patient_id,
        count(*) FILTER (WHERE e.start_date > params.as_of - INTERVAL 365 DAY)
            AS encounters_365d,
        count(*) FILTER (WHERE e.start_date > params.as_of - INTERVAL 90 DAY)
            AS encounters_90d,
        count(*) FILTER (WHERE e.encounter_class = 'AMB'
                           AND e.start_date > params.as_of - INTERVAL 365 DAY)
            AS ambulatory_visits_365d,
        count(*) FILTER (WHERE e.encounter_class = 'WELLNESS'
                           AND e.start_date > params.as_of - INTERVAL 365 DAY)
            AS wellness_visits_365d,
        count(*) FILTER (WHERE e.encounter_class = 'EMER'
                           AND e.start_date > params.as_of - INTERVAL 365 DAY)
            AS ed_visits_365d,
        count(*) FILTER (WHERE e.encounter_class = 'IMP'
                           AND e.start_date > params.as_of - INTERVAL 365 DAY)
            AS inpatient_admits_365d,
        -- LOS from the UTC end timestamp's date: a documented approximation (end dates can
        -- shift one day across the UTC boundary; start_date is local-true). The endpoint is
        -- clamped to as_of: a discharge after as_of must not leak future days into the row.
        coalesce(sum(
            CASE WHEN e.encounter_class = 'IMP'
                  AND e.start_date > params.as_of - INTERVAL 365 DAY
                 THEN greatest(date_diff('day', e.start_date,
                                         least(coalesce(CAST(e.end_ts AS DATE), e.start_date),
                                               params.as_of)), 0)
            END), 0) AS inpatient_days_365d,
        max(e.start_date) AS last_encounter_date
    FROM encounters e
    CROSS JOIN params
    WHERE e.start_date <= params.as_of
    GROUP BY e.source, e.patient_id
),

labs_365 AS (
    SELECT o.source, o.patient_id, count(*) AS lab_results_365d
    FROM observations o
    CROSS JOIN params
    WHERE o.parent_observation_id IS NULL
      AND o.category = 'laboratory'
      AND o.effective_date <= params.as_of
      AND o.effective_date > params.as_of - INTERVAL 365 DAY
    GROUP BY o.source, o.patient_id
)

SELECT
    p.source,
    p.patient_id,
    params.as_of,
    -- Floor age in whole years at as_of.
    CASE WHEN p.birth_date IS NULL THEN NULL
         ELSE date_diff('year', p.birth_date, params.as_of)
              - CASE WHEN (month(params.as_of), day(params.as_of))
                          < (month(p.birth_date), day(p.birth_date))
                     THEN 1 ELSE 0 END
    END AS age_years,
    p.sex,
    p.race,
    p.ethnicity,
    coalesce(p.death_date <= params.as_of, FALSE) AS is_deceased,
    coalesce(ch.has_diabetes, FALSE)     AS has_diabetes,
    coalesce(ch.has_hypertension, FALSE) AS has_hypertension,
    coalesce(ch.has_ascvd, FALSE)        AS has_ascvd,
    coalesce(ch.has_ckd, FALSE)          AS has_ckd,
    coalesce(ch.has_chf, FALSE)          AS has_chf,
    coalesce(ch.has_copd, FALSE)         AS has_copd,
    (coalesce(ch.has_diabetes, FALSE)::INT + coalesce(ch.has_hypertension, FALSE)::INT
     + coalesce(ch.has_ascvd, FALSE)::INT + coalesce(ch.has_ckd, FALSE)::INT
     + coalesce(ch.has_chf, FALSE)::INT + coalesce(ch.has_copd, FALSE)::INT)
        AS chronic_condition_count,
    bp.latest_sbp,
    bp.latest_dbp,
    bp.latest_bp_date,
    a1c.value_num       AS latest_hba1c,
    a1c.effective_date  AS latest_hba1c_date,
    bmi.value_num       AS latest_bmi,
    bmi.effective_date  AS latest_bmi_date,
    tob.value_code      AS tobacco_status_code,
    tob.effective_date  AS tobacco_status_date,
    coalesce(st.statin_authored_365d, FALSE) AS statin_authored_365d,
    st.last_statin_authored_date,
    coalesce(m365.distinct_meds_authored_365d, 0) AS distinct_meds_authored_365d,
    scr.last_mammogram_date,
    scr.last_colonoscopy_date,
    fobt.last_fobt_fit_date,
    scr.last_retinal_exam_date,
    flu.last_flu_immunization_date,
    coalesce(u.encounters_365d, 0)         AS encounters_365d,
    coalesce(u.encounters_90d, 0)          AS encounters_90d,
    coalesce(u.ambulatory_visits_365d, 0)  AS ambulatory_visits_365d,
    coalesce(u.wellness_visits_365d, 0)    AS wellness_visits_365d,
    coalesce(u.ed_visits_365d, 0)          AS ed_visits_365d,
    coalesce(u.inpatient_admits_365d, 0)   AS inpatient_admits_365d,
    coalesce(u.inpatient_days_365d, 0)     AS inpatient_days_365d,
    coalesce(l365.lab_results_365d, 0)     AS lab_results_365d,
    date_diff('day', u.last_encounter_date, params.as_of) AS days_since_last_encounter
FROM patients p
CROSS JOIN params
-- Patients not yet born at as_of have no meaningful feature row (and would otherwise
-- surface negative ages and pollute the panel rollup).
LEFT JOIN chronic ch        ON ch.source = p.source AND ch.patient_id = p.patient_id
LEFT JOIN latest_bp bp      ON bp.source = p.source AND bp.patient_id = p.patient_id
LEFT JOIN latest_lab a1c    ON a1c.source = p.source AND a1c.patient_id = p.patient_id
                           AND a1c.code = '4548-4'
LEFT JOIN latest_lab bmi    ON bmi.source = p.source AND bmi.patient_id = p.patient_id
                           AND bmi.code = '39156-5'
LEFT JOIN latest_tobacco tob ON tob.source = p.source AND tob.patient_id = p.patient_id
LEFT JOIN statins st        ON st.source = p.source AND st.patient_id = p.patient_id
LEFT JOIN meds_365 m365     ON m365.source = p.source AND m365.patient_id = p.patient_id
LEFT JOIN screenings scr    ON scr.source = p.source AND scr.patient_id = p.patient_id
LEFT JOIN fobt              ON fobt.source = p.source AND fobt.patient_id = p.patient_id
LEFT JOIN flu               ON flu.source = p.source AND flu.patient_id = p.patient_id
LEFT JOIN utilization u     ON u.source = p.source AND u.patient_id = p.patient_id
LEFT JOIN labs_365 l365     ON l365.source = p.source AND l365.patient_id = p.patient_id
WHERE p.birth_date IS NULL OR p.birth_date <= params.as_of

SELECT
    {identity_columns}
    COALESCE(app.ext_source_1, stats.median_es1) AS ext_source_1,
    COALESCE(app.ext_source_2, stats.median_es2) AS ext_source_2,
    COALESCE(app.ext_source_3, stats.median_es3) AS ext_source_3,

    COALESCE(
        (COALESCE(app.ext_source_1, stats.median_es1) +
         COALESCE(app.ext_source_2, stats.median_es2) +
         COALESCE(app.ext_source_3, stats.median_es3)) / 3.0,
    stats.median_es_mean) AS ext_source_mean,

    CAST(app.region_rating_client_w_city AS BIGINT) AS region_rating_client_w_city,
    COALESCE(app.days_last_phone_change, stats.median_phone) AS days_last_phone_change,
    app.days_id_publish,
    app.days_registration,

    COALESCE(app.reg_city_not_work_city, 0) AS reg_city_not_work_city,
    COALESCE(app.reg_city_not_live_city, 0) AS reg_city_not_live_city,
    COALESCE(app.live_city_not_work_city, 0) AS live_city_not_work_city,

    CASE WHEN TRIM(app.flag_own_car) = 'Y' THEN 1 ELSE 0 END AS has_car,
    CASE
        WHEN TRIM(app.flag_own_car) = 'Y' THEN COALESCE(app.own_car_age, stats.median_car_age)
        ELSE 0
    END AS own_car_age,

    COALESCE(app.def_60_cnt_social_circle, 0) AS def_60_cnt_social_circle,
    COALESCE(app.amt_req_credit_bureau_year, 0) AS amt_req_credit_bureau_year,
    CAST(COALESCE(app.cnt_children, 0) AS INTEGER) AS cnt_children,
    COALESCE(app.cnt_fam_members, stats.median_fam) AS cnt_fam_members,

    LEAST(
        COALESCE(NULLIF(app.amt_income_total, 0), stats.median_income),
        stats.p_limit_income
    ) AS amt_income_total,

    app.amt_credit,
    COALESCE(app.amt_annuity, stats.median_annuity) AS amt_annuity,

    COALESCE(TRIM(app.occupation_type), 'Unknown') AS occupation_type,
    CASE WHEN o.organization_type IS NOT NULL THEN TRIM(app.organization_type) ELSE 'Other_low_freq' END AS organization_type,
    CASE WHEN i.name_income_type IS NOT NULL THEN TRIM(app.name_income_type) ELSE 'Other_low_freq' END AS name_income_type,
    COALESCE(TRIM(app.name_education_type), 'Unknown') AS name_education_type,
    COALESCE(REPLACE(TRIM(app.code_gender), 'XNA', 'Unknown'), 'Unknown') AS code_gender,

    ABS(app.days_birth) / 365.25 AS age,
    CASE WHEN app.days_employed = {employment_days_anomaly_sentinel} THEN 0 ELSE ABS(app.days_employed) / 365.25 END AS years_employed,
    CASE WHEN app.days_employed = {employment_days_anomaly_sentinel} THEN 1 ELSE 0 END AS days_employed_anom

FROM {input_rows}
CROSS JOIN {stats}
LEFT JOIN {valid_orgs} ON app.organization_type = o.organization_type
LEFT JOIN {valid_incs} ON app.name_income_type = i.name_income_type
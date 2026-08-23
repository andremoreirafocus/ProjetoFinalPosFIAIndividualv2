SELECT
    percentile_cont(0.5) WITHIN GROUP (ORDER BY ext_source_1) AS median_es1,
    percentile_cont(0.5) WITHIN GROUP (ORDER BY ext_source_2) AS median_es2,
    percentile_cont(0.5) WITHIN GROUP (ORDER BY ext_source_3) AS median_es3,
    percentile_cont(0.5) WITHIN GROUP (ORDER BY (COALESCE(ext_source_1, 0) + COALESCE(ext_source_2, 0) + COALESCE(ext_source_3, 0))/3.0) AS median_es_mean,
    percentile_cont(0.5) WITHIN GROUP (ORDER BY days_last_phone_change) AS median_phone,
    percentile_cont(0.5) WITHIN GROUP (ORDER BY cnt_fam_members) AS median_fam,
    percentile_cont(0.5) WITHIN GROUP (ORDER BY amt_annuity) AS median_annuity,
    percentile_cont(0.5) WITHIN GROUP (ORDER BY NULLIF(amt_income_total, 0)) AS median_income,
    percentile_cont({income_winsor_q}) WITHIN GROUP (ORDER BY NULLIF(amt_income_total, 0)) AS p_limit_income,
    percentile_cont(0.5) WITHIN GROUP (ORDER BY own_car_age) FILTER (WHERE TRIM(flag_own_car) = 'Y') AS median_car_age,
    ARRAY(SELECT organization_type FROM "{input_table}" GROUP BY 1 HAVING COUNT(*) >= {cardinalidade_min_freq}) AS valid_orgs,
    ARRAY(SELECT name_income_type FROM "{input_table}" GROUP BY 1 HAVING COUNT(*) >= {cardinalidade_min_freq}) AS valid_incs,
    {cardinalidade_min_freq}::integer AS cardinalidade_min_freq,
    {income_winsor_q}::double precision AS income_winsor_q,
    '{application_sanitization_projection_sha256}' AS application_sanitization_projection_sha256,
    NOW() AS run_at
FROM "{input_table}"
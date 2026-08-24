SELECT
    a.*,
    -- 2. Features Derivadas da Renda
    CASE WHEN COALESCE(a.amt_income_total, 0) > 0 THEN a.amt_credit / a.amt_income_total ELSE NULL END AS fe_credit_income_percent,
    CASE WHEN COALESCE(a.amt_income_total, 0) > 0 THEN a.amt_annuity / a.amt_income_total ELSE NULL END AS fe_annuity_income_percent,
    -- 3. Features Agregadas de Previous Application
    CASE WHEN p.sk_id_curr IS NOT NULL THEN 1 ELSE 0 END AS has_prev_app,
    COALESCE(p.prev_refused_rate, 0) AS prev_refused_rate,
    -- 4. Features Agregadas de Bureau
    CASE WHEN b.sk_id_curr IS NOT NULL THEN 1 ELSE 0 END AS has_bureau,
    COALESCE(b.bureau_avg_days_credit, 0) AS bureau_avg_days_credit,
    COALESCE(b.bureau_last_days_credit, 0) AS bureau_last_days_credit,
    COALESCE(b.bureau_active_rate, 0) AS bureau_active_rate,
    COALESCE(b.bureau_active_count, 0) AS bureau_active_count,
    COALESCE(b.bureau_closed_rate, 0) AS bureau_closed_rate,
    COALESCE(b.bureau_debt_credit_ratio, 0) AS bureau_debt_credit_ratio,
    COALESCE(b.bureau_overdue_count, 0) AS bureau_overdue_count,
    -- 5. Features Agregadas de Installments (Parcelas)
    CASE WHEN i.sk_id_curr IS NOT NULL THEN 1 ELSE 0 END AS has_installments_history,
    COALESCE(i.inst_late_payment_rate, 0) AS inst_late_payment_rate
FROM {input_rows}
LEFT JOIN {prev_agg} ON a.sk_id_curr = p.sk_id_curr
LEFT JOIN {bureau_agg} ON a.sk_id_curr = b.sk_id_curr
LEFT JOIN {inst_agg} ON a.sk_id_curr = i.sk_id_curr

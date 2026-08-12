# -*- coding: utf-8 -*-
"""
data_sanitization.py — Limpeza e padronização (Home Credit) via ELT (SQL Puro)
Processamento transferido 100% para dentro do PostgreSQL.
Funções puras: todas as configurações são recebidas por parâmetro via DAG (Airflow).
"""
from db import log_row_count

def get_table_columns(cursor, table_name: str) -> list:
    """Busca dinamicamente a lista de colunas de uma tabela no PostgreSQL."""
    cursor.execute(f"""
        SELECT column_name 
        FROM information_schema.columns 
        WHERE table_name = '{table_name}'
        ORDER BY ordinal_position;
    """)
    return [row[0] for row in cursor.fetchall()]

# ---------------------------------------------------------------------------
# application_train
# ---------------------------------------------------------------------------
def run_sanitization(conn, input_table: str, output_table: str, min_freq: int, winsor_q: float):
    """Higieniza application_train usando SQL nativo para estatísticas globais e regras lógicas."""
    cursor = conn.cursor()

    print(f"Limpando '{input_table}' -> '{output_table}' (ELT via PostgreSQL)...")
    
    log_row_count(cursor, input_table, "Entrada")
    
    sql_elt = f"""
    DROP TABLE IF EXISTS "{output_table}" CASCADE;
    
    CREATE TABLE "{output_table}" AS
    WITH global_stats AS (
        SELECT
            percentile_cont(0.5) WITHIN GROUP (ORDER BY ext_source_1) AS median_es1,
            percentile_cont(0.5) WITHIN GROUP (ORDER BY ext_source_2) AS median_es2,
            percentile_cont(0.5) WITHIN GROUP (ORDER BY ext_source_3) AS median_es3,
            percentile_cont(0.5) WITHIN GROUP (ORDER BY (COALESCE(ext_source_1, 0) + COALESCE(ext_source_2, 0) + COALESCE(ext_source_3, 0))/3.0) AS median_es_mean,
            percentile_cont(0.5) WITHIN GROUP (ORDER BY days_last_phone_change) AS median_phone,
            percentile_cont(0.5) WITHIN GROUP (ORDER BY cnt_fam_members) AS median_fam,
            percentile_cont(0.5) WITHIN GROUP (ORDER BY amt_annuity) AS median_annuity,
            percentile_cont(0.5) WITHIN GROUP (ORDER BY NULLIF(amt_income_total, 0)) AS median_income,
            percentile_cont({winsor_q}) WITHIN GROUP (ORDER BY NULLIF(amt_income_total, 0)) AS p99_income,
            percentile_cont(0.5) WITHIN GROUP (ORDER BY own_car_age) FILTER (WHERE TRIM(flag_own_car) = 'Y') AS median_car_age
        FROM "{input_table}"
    ),
    valid_orgs AS (
        SELECT organization_type FROM "{input_table}" GROUP BY 1 HAVING COUNT(*) >= {min_freq}
    ),
    valid_incs AS (
        SELECT name_income_type FROM "{input_table}" GROUP BY 1 HAVING COUNT(*) >= {min_freq}
    )
    SELECT
        CAST(app.sk_id_curr AS BIGINT) AS sk_id_curr,
        CAST(app.target AS BIGINT) AS target,

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
            stats.p99_income
        ) AS amt_income_total,
        
        app.amt_credit,
        COALESCE(app.amt_annuity, stats.median_annuity) AS amt_annuity,

        COALESCE(TRIM(app.occupation_type), 'Unknown') AS occupation_type,
        CASE WHEN o.organization_type IS NOT NULL THEN TRIM(app.organization_type) ELSE 'Other_low_freq' END AS organization_type,
        CASE WHEN i.name_income_type IS NOT NULL THEN TRIM(app.name_income_type) ELSE 'Other_low_freq' END AS name_income_type,
        COALESCE(TRIM(app.name_education_type), 'Unknown') AS name_education_type,
        COALESCE(REPLACE(TRIM(app.code_gender), 'XNA', 'Unknown'), 'Unknown') AS code_gender,

        ABS(app.days_birth) / 365.25 AS age,
        CASE WHEN app.days_employed = 365243 THEN 0 ELSE ABS(app.days_employed) / 365.25 END AS years_employed,
        CASE WHEN app.days_employed = 365243 THEN 1 ELSE 0 END AS days_employed_anom

    FROM "{input_table}" app
    CROSS JOIN global_stats stats
    LEFT JOIN valid_orgs o ON app.organization_type = o.organization_type
    LEFT JOIN valid_incs i ON app.name_income_type = i.name_income_type;
    """
    
    cursor.execute(sql_elt)
    conn.commit()
    log_row_count(cursor, output_table, "Saída")
    cursor.close()
    print(f"--- Application Train higienizado! Tabela: '{output_table}' ---")


# ---------------------------------------------------------------------------
# previous_application 
# ---------------------------------------------------------------------------
def run_prev_sanitization(conn, input_table: str, output_table: str):
    """Constrói SQL dinâmico para limpar previous_application preservando colunas não alteradas."""
    cursor = conn.cursor()

    print(f"Limpando '{input_table}' -> '{output_table}' (ELT via SQL dinâmico)...")
    cols = get_table_columns(cursor, input_table)
    
    select_exprs = []
    for col in cols:
        if col == "name_contract_status":
            select_exprs.append(f'INITCAP(TRIM("{col}")) AS "{col}"')
        elif col == "amt_application":
            select_exprs.append(f'GREATEST(COALESCE("{col}", 0), 0) AS "{col}"')
        else:
            select_exprs.append(f'"{col}"')

    log_row_count(cursor, input_table, "Entrada")

    sql_elt = f"""
    DROP TABLE IF EXISTS "{output_table}" CASCADE;
    CREATE TABLE "{output_table}" AS
    SELECT {", ".join(select_exprs)} FROM "{input_table}";
    """

    cursor.execute(sql_elt)
    conn.commit()
    log_row_count(cursor, output_table, "Saída")
    cursor.close()
    print(f"--- Previous Application limpo! Tabela '{output_table}' ---")


# ---------------------------------------------------------------------------
# bureau 
# ---------------------------------------------------------------------------
def run_bureau_sanitization(conn, input_table: str, output_table: str):
    """Constrói SQL dinâmico para limpar bureau preservando colunas não alteradas."""
    cursor = conn.cursor()

    print(f"Limpando '{input_table}' -> '{output_table}' (ELT via SQL dinâmico)...")
    cols = get_table_columns(cursor, input_table)
    
    select_exprs = []
    for col in cols:
        if col in ["credit_active", "credit_type"]:
            select_exprs.append(f'TRIM(CAST("{col}" AS TEXT)) AS "{col}"')
        elif col in ["amt_credit_sum", "amt_credit_sum_debt", "amt_credit_sum_overdue", "credit_day_overdue", "cnt_credit_prolong"]:
            select_exprs.append(f'COALESCE(CAST("{col}" AS NUMERIC), 0) AS "{col}"')
        elif col in ["days_credit", "days_credit_update"]:
            select_exprs.append(f'CAST("{col}" AS NUMERIC) AS "{col}"')
        else:
            select_exprs.append(f'"{col}"')

    log_row_count(cursor, input_table, "Entrada")
    
    sql_elt = f"""
    DROP TABLE IF EXISTS "{output_table}" CASCADE;
    CREATE TABLE "{output_table}" AS
    SELECT {", ".join(select_exprs)} FROM "{input_table}";
    """

    cursor.execute(sql_elt)
    conn.commit()
    log_row_count(cursor, output_table, "Saída")
    cursor.close()
    print(f"--- Bureau limpo! Tabela '{output_table}' ---")


# ---------------------------------------------------------------------------
# installments_payments
# ---------------------------------------------------------------------------
def run_installments_sanitization(conn, input_table: str, output_table: str):
    """Filtro de linhas válidas em SQL nativo."""
    cursor = conn.cursor()

    print(f"Filtrando '{input_table}' -> '{output_table}' (ELT)...")
    log_row_count(cursor, input_table, "Entrada")

    cursor.execute(f'DROP TABLE IF EXISTS "{output_table}" CASCADE;')
    cursor.execute(f"""
        CREATE TABLE "{output_table}" AS
        SELECT
            sk_id_curr, sk_id_prev,
            num_instalment_version, num_instalment_number,
            days_instalment, days_entry_payment,
            amt_instalment, amt_payment
        FROM "{input_table}"
        WHERE sk_id_curr IS NOT NULL
          AND sk_id_prev IS NOT NULL
          AND days_instalment IS NOT NULL
          AND amt_instalment IS NOT NULL;
    """)
    conn.commit()
    log_row_count(cursor, output_table, "Saída")
    cursor.close()
    print(f"--- Installments filtrado! Tabela '{output_table}' ---")
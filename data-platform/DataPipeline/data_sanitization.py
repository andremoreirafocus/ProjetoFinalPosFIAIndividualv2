# -*- coding: utf-8 -*-
"""
data_sanitization.py — Limpeza e padronização (Home Credit) via ELT (SQL Puro)
Processamento transferido 100% para dentro do PostgreSQL.
Funções puras: todas as configurações são recebidas por parâmetro via DAG (Airflow).
"""
import hashlib
from pathlib import Path

from infra.db import log_row_count

SQL_DIR = Path(__file__).resolve().parent / "sql"
"""Asset do componente — os `.sql` versionados que este módulo carrega e executa."""


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
def run_sanitization(
    conn, input_table: str, output_table: str, sanitization_last_run_table: str,
    cardinalidade_min_freq: int, income_winsor_q: float,
):
    """Higieniza application_train em duas tabelas: as estatísticas da execução, depois a
    projeção por registro que as consome. As duas confirmam juntas, num commit só."""
    cursor = conn.cursor()

    print(f"Limpando '{input_table}' -> '{output_table}' (ELT via PostgreSQL)...")

    log_row_count(cursor, input_table, "Entrada")

    projection_path = SQL_DIR / "application_sanitization_projection.sql"
    projection_sha256 = hashlib.sha256(projection_path.read_bytes()).hexdigest()

    stats_select = (SQL_DIR / "application_sanitization_stats.sql").read_text(
        encoding="utf-8"
    ).format(
        input_table=input_table,
        cardinalidade_min_freq=cardinalidade_min_freq,
        income_winsor_q=income_winsor_q,
        application_sanitization_projection_sha256=projection_sha256,
    )
    stats_sql = f"""
    DROP TABLE IF EXISTS "{sanitization_last_run_table}" CASCADE;
    CREATE TABLE "{sanitization_last_run_table}" AS
    {stats_select};
    """
    cursor.execute(stats_sql)

    projection_select = projection_path.read_text(encoding="utf-8").format(
        identity_columns=(
            "CAST(app.sk_id_curr AS BIGINT) AS sk_id_curr, "
            "CAST(app.target AS BIGINT) AS target,"
        ),
        input_rows=f'"{input_table}" app',
        stats=f'"{sanitization_last_run_table}" stats',
        valid_orgs=(
            f'(SELECT unnest(valid_orgs) FROM "{sanitization_last_run_table}") '
            "AS o(organization_type)"
        ),
        valid_incs=(
            f'(SELECT unnest(valid_incs) FROM "{sanitization_last_run_table}") '
            "AS i(name_income_type)"
        ),
    )
    clean_sql = f"""
    DROP TABLE IF EXISTS "{output_table}" CASCADE;
    CREATE TABLE "{output_table}" AS
    {projection_select};
    """
    cursor.execute(clean_sql)

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
# -*- coding: utf-8 -*-
"""
Módulo responsável pela construção da Analytical Base Table (ABT).

Este módulo utiliza a arquitetura ELT (Extract, Load, Transform), empurrando 
todo o processamento de agregações e JOINs para o motor do PostgreSQL.
Inclui a criação de índices intermediários e logs de volumetria.
"""
import os
import json
import hashlib
from pathlib import Path

from infra.db import get_db_connection_str_from_env, get_pg_database_connection, log_row_count

SQL_DIR = Path(__file__).resolve().parent / "sql"
"""Asset do componente — os `.sql` versionados que este módulo carrega e executa."""

# --- TASKS INTERMEDIÁRIAS (AGREGAÇÕES EM SQL NO BANCO) ---
def create_agg_previous_application(conn, output_prev_table: str):
    """Agrega o histórico de aplicações anteriores por cliente (sk_id_curr)."""
    tbl_dest = "tmp_prev_application_agg"
    cur = conn.cursor()
    
    print(f"[AGREGAÇÃO] Processando '{output_prev_table}' -> '{tbl_dest}'...")
    log_row_count(cur, output_prev_table, "Base Histórica Bruta")
    
    cur.execute(f'DROP TABLE IF EXISTS "{tbl_dest}" CASCADE;')
    cur.execute(f"""
        CREATE TABLE "{tbl_dest}" AS
        SELECT
            sk_id_curr,
            SUM(CASE WHEN name_contract_status = 'Refused' THEN 1 ELSE 0 END)::float
                / NULLIF(COUNT(sk_id_prev), 0) AS prev_refused_rate
        FROM "{output_prev_table}"
        GROUP BY sk_id_curr;
    """)
    conn.commit()
    
    # Criação de índice para acelerar o JOIN final
    cur.execute(f'CREATE INDEX idx_{tbl_dest}_curr ON "{tbl_dest}" (sk_id_curr);')
    conn.commit()
    
    log_row_count(cur, tbl_dest, "Agregado por Cliente")
    cur.close()


def create_agg_bureau(conn, output_bureau_table: str):
    """Agrega bureau_clean por cliente trazendo todas as métricas necessárias para o modelo."""
    tbl_dest = "tmp_bureau_agg"
    cur = conn.cursor()
    
    print(f"[AGREGAÇÃO] Processando '{output_bureau_table}' -> '{tbl_dest}'...")
    log_row_count(cur, output_bureau_table, "Base Histórica Bruta")
    
    cur.execute(f'DROP TABLE IF EXISTS "{tbl_dest}" CASCADE;')
    cur.execute(f"""
        CREATE TABLE "{tbl_dest}" AS
        SELECT
            sk_id_curr,
            COUNT(sk_id_bureau) AS bureau_credit_count,
            AVG(days_credit) AS bureau_avg_days_credit,
            MAX(days_credit) AS bureau_last_days_credit,
            SUM(CASE WHEN credit_active = 'Active' THEN 1 ELSE 0 END)::float 
                / NULLIF(COUNT(sk_id_bureau), 0) AS bureau_active_rate,
            SUM(CASE WHEN credit_active = 'Active' THEN 1 ELSE 0 END) AS bureau_active_count,
            SUM(CASE WHEN credit_active = 'Closed' THEN 1 ELSE 0 END)::float 
                / NULLIF(COUNT(sk_id_bureau), 0) AS bureau_closed_rate,
            SUM(COALESCE(amt_credit_sum_debt, 0)) 
                / NULLIF(SUM(COALESCE(amt_credit_sum, 0)), 0) AS bureau_debt_credit_ratio,
            SUM(CASE WHEN COALESCE(credit_day_overdue, 0) > 0 THEN 1 ELSE 0 END) AS bureau_overdue_count
        FROM "{output_bureau_table}"
        GROUP BY sk_id_curr;
    """)
    conn.commit()
    
    cur.execute(f'CREATE INDEX idx_{tbl_dest}_curr ON "{tbl_dest}" (sk_id_curr);')
    conn.commit()
    
    log_row_count(cur, tbl_dest, "Agregado por Cliente")
    cur.close()


def create_agg_installments(conn, output_installments_table: str):
    """Agrega installments_clean por cliente no Postgres."""
    tbl_dest = "tmp_installments_agg"
    cur = conn.cursor()
    
    print(f"[AGREGAÇÃO] Processando '{output_installments_table}' -> '{tbl_dest}'...")
    log_row_count(cur, output_installments_table, "Base Histórica Bruta")
    
    cur.execute(f'DROP TABLE IF EXISTS "{tbl_dest}" CASCADE;')
    cur.execute(f"""
        CREATE TABLE "{tbl_dest}" AS
        SELECT
            sk_id_curr,
            AVG(CASE WHEN (days_entry_payment - days_instalment) > 0 THEN 1.0 ELSE 0.0 END)
                AS inst_late_payment_rate
        FROM "{output_installments_table}"
        GROUP BY sk_id_curr;
    """)
    conn.commit()
    
    cur.execute(f'CREATE INDEX idx_{tbl_dest}_curr ON "{tbl_dest}" (sk_id_curr);')
    conn.commit()
    
    log_row_count(cur, tbl_dest, "Agregado por Cliente")
    cur.close()


# --- PIPELINE PRINCIPAL (ELT FINAL) ---
def run_abt_generation(conn, config: dict):
    """Monta a ABT final via SQL puro unindo a aplicação limpa com os agregados intermediários.
    A projeção e o registro da execução em `abt_last_run_table` confirmam juntos, num commit só."""
    clean_table = config["output_table"]
    abt_table = config["abt_table"]
    abt_last_run_table = config["abt_last_run_table"]

    projection_path = SQL_DIR / "application_abt_record_projection.sql"
    projection_sha256 = hashlib.sha256(projection_path.read_bytes()).hexdigest()
    projection_select = projection_path.read_text(encoding="utf-8").format(
        input_rows=f'"{clean_table}" a',
        prev_agg="tmp_prev_application_agg p",
        bureau_agg="tmp_bureau_agg b",
        inst_agg="tmp_installments_agg i",
    )

    cursor = conn.cursor()

    print(f"[ELT] Construindo a tabela final ABT '{abt_table}' a partir de '{clean_table}'...")
    log_row_count(cursor, clean_table, "Entrada Application Clean")

    cursor.execute(f'DROP TABLE IF EXISTS "{abt_table}" CASCADE;')

    sql_elt = f"""
    CREATE TABLE "{abt_table}" AS
    {projection_select};
    """

    last_run_sql = f"""
    DROP TABLE IF EXISTS "{abt_last_run_table}" CASCADE;
    CREATE TABLE "{abt_last_run_table}" AS
    SELECT
        '{projection_sha256}'::text AS application_abt_record_projection_sha256,
        NOW() AS run_at;
    """

    try:
        cursor.execute(sql_elt)
        cursor.execute(last_run_sql)
        conn.commit()

        print("[LIXEIRA] Limpando tabelas temporárias agregadas...")
        cursor.execute("DROP TABLE IF EXISTS tmp_prev_application_agg CASCADE;")
        cursor.execute("DROP TABLE IF EXISTS tmp_bureau_agg CASCADE;")
        cursor.execute("DROP TABLE IF EXISTS tmp_installments_agg CASCADE;")
        conn.commit()

        print(f"[ELT] Sucesso absoluto na geração da ABT!")
        log_row_count(cursor, abt_table, "ABT Final Pronta para Treino")

    except Exception as e:
        conn.rollback()
        raise RuntimeError(f"Erro na execução do processo ELT da ABT: {str(e)}")
    finally:
        cursor.close()


if __name__ == "__main__":
    # Execução isolada, fora do Airflow: quem abre a conexão aqui é quem a fecha, e o
    # entrypoint carrega o ambiente. Import local porque a imagem do Airflow nao tem
    # python-dotenv — as tasks recebem ambiente do compose.
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parents[1] / ".env")

    conn = get_pg_database_connection(get_db_connection_str_from_env("localhost"))
    try:
        run_abt_generation(
            conn,
            {
                "output_table": "application_clean",
                "abt_table": "application_abt",
                "abt_last_run_table": "application_abt_last_run",
            },
        )
    finally:
        conn.close()
# -*- coding: utf-8 -*-
"""
Módulo responsável pela construção da Analytical Base Table (ABT).

Este módulo utiliza a arquitetura ELT (Extract, Load, Transform), empurrando 
todo o processamento de agregações e JOINs para o motor do PostgreSQL.
Inclui a criação de índices intermediários e logs de volumetria.
"""
import os
import json
from infra.db import get_db_connection_str_from_env, get_pg_database_connection, log_row_count

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
    """Monta a ABT final via SQL puro unindo a aplicação limpa com os agregados intermediários."""
    clean_table = config.get("output_table")
    abt_table = config.get("abt_table")
    
    cursor = conn.cursor()

    print(f"[ELT] Construindo a tabela final ABT '{abt_table}' a partir de '{clean_table}'...")
    log_row_count(cursor, clean_table, "Entrada Application Clean")

    cursor.execute(f'DROP TABLE IF EXISTS "{abt_table}" CASCADE;')
    
    sql_elt = f"""
    CREATE TABLE "{abt_table}" AS
    SELECT 
        a.*,
        
        -- 2. Features Derivadas da Renda (Tratando divisão por zero)
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

    FROM "{clean_table}" a
    LEFT JOIN tmp_prev_application_agg p ON a.sk_id_curr = p.sk_id_curr
    LEFT JOIN tmp_bureau_agg b ON a.sk_id_curr = b.sk_id_curr
    LEFT JOIN tmp_installments_agg i ON a.sk_id_curr = i.sk_id_curr;
    """

    try:
        cursor.execute(sql_elt)
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
    from pathlib import Path

    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parents[1] / ".env")

    conn = get_pg_database_connection(get_db_connection_str_from_env("localhost"))
    try:
        run_abt_generation(
            conn, {"output_table": "application_clean", "abt_table": "application_abt"}
        )
    finally:
        conn.close()
from infra.db import get_db_connection_str_from_env, get_pg_database_connection, log_row_count
import os

def run_postgres_to_csv_export(conn, source_table: str, output_dir_path: str):
    """Extrai dados de uma tabela Postgres e salva em um arquivo CSV 
    usando o nome da tabela como nome do arquivo.
    """
    
    # Monta o caminho completo: pasta + nome_da_tabela.csv
    output_csv_path = os.path.join(output_dir_path, f"{source_table}.csv")
    
    # Garante que a pasta de destino exista
    if output_dir_path and not os.path.exists(output_dir_path):
        os.makedirs(output_dir_path, exist_ok=True)

    print(f"Iniciando exportação: Postgres['{source_table}'] -> CSV['{output_csv_path}']...")
    
    cursor = conn.cursor()

    try:
        log_row_count(cursor, source_table, "Extração CSV")

        with open(output_csv_path, "w", encoding="utf-8") as f:
            sql_query = f"""COPY "{source_table}" TO STDOUT WITH CSV HEADER DELIMITER ',' NULL '';"""
            cursor.copy_expert(sql_query, f)

        print(f"[SUCESSO] Exportação concluída! Arquivo salvo em: {os.path.abspath(output_csv_path)}")

    except Exception as e:
        raise RuntimeError(f"Falha ao exportar a tabela {source_table} para CSV: {str(e)}")
    
    finally:
        cursor.close()

if __name__ == "__main__":
    tables_to_export = [
        "application_clean",
        "previous_application_clean",
        "bureau_clean",
        "installments_clean",
        "application_abt"
    ]
    # Execução manual, fora do Airflow: quem abre a conexão aqui é quem a fecha.
    conn = get_pg_database_connection(get_db_connection_str_from_env("localhost"))
    try:
        for table in tables_to_export:
            run_postgres_to_csv_export(
                conn=conn,
                source_table=table,
                output_dir_path="../airflow/data/csv"  # Apenas a pasta de destino
            )
    finally:
        conn.close()
    
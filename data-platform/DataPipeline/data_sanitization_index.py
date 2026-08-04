from utils import get_database_connection

def run_abt_indexes(conn_id: str, config: dict):
    """
    Cria índices nas tabelas higienizadas (_clean) para otimizar os JOINs da ABT.
    
    Como as tabelas _clean são recriadas a cada execução pelo data_sanitization,
    elas perdem os índices originais. Esta etapa garante a performance do mega JOIN.

    Args:
        conn_id (str): Identificador da conexão com o banco (Airflow ou SQLAlchemy).
        config (dict): Dicionário de configuração contendo os nomes das tabelas.
    """
    conn = get_database_connection(conn_id)
    cursor = conn.cursor()
    db = config.get("database", {})
    table_names = [
        "output_table",
        "output_prev_table",
        "output_bureau_table",
        "output_installments_table"
    ]
    print("[ABT INDEXES] Iniciando criação de índices nas tabelas higienizadas...")
    for table_name in table_names:
        tb = db.get(table_name)
        if tb:
            idx_name = f"idx_abt_{tb}_sk_id_curr"
            sql = f'CREATE INDEX IF NOT EXISTS "{idx_name}" ON "{tb}" (sk_id_curr);'
            print(f"   -> Indexando '{tb}' na chave 'sk_id_curr'...")
            cursor.execute(sql)
            conn.commit()
            print(f"   -> Índice '{idx_name}' criado com sucesso!")
        else:
            cursor.close()
            conn.close()
            raise ValueError(f"Tabela '{table_name}' não encontrada na configuração. Indexação falhou!")
    cursor.close()
    conn.close()
    print("[ABT INDEXES] Índices intermediários criados com sucesso!")
from utils import get_database_connection

def run_abt_indexes(conn_id: str, config: dict):
    """
    Cria os índices declarados em ``config["indexes"]["clean"]`` nas tabelas
    higienizadas (_clean), otimizando os JOINs da ABT.

    Como as tabelas _clean são recriadas a cada execução pelo data_sanitization,
    elas perdem os índices originais. Esta etapa garante a performance do mega JOIN.

    Cada entrada resolve sua tabela física por ``table_ref`` em
    ``config["database"]``; um `table_ref` que resolve para um nome vazio ou
    ausente falha com ``ValueError``, identificando a entrada malformada.

    Args:
        conn_id (str): Identificador da conexão com o banco (Airflow ou SQLAlchemy).
        config (dict): Dicionário de configuração já carregado.
    """
    conn = get_database_connection(conn_id)
    cursor = conn.cursor()

    db_config = config["database"]
    clean_indexes = config["indexes"]["clean"]

    print("[ABT INDEXES] Iniciando criação de índices nas tabelas higienizadas...")

    for entrada in clean_indexes:
        table_ref = entrada["table_ref"]
        tabela = db_config.get(table_ref)
        if not tabela:
            cursor.close()
            conn.close()
            raise ValueError(
                f"table_ref '{table_ref}' não resolve para um nome de tabela válido em config['database']."
            )
        colunas = ", ".join(entrada["columns"])
        print(
            f"   -> Criando índice '{entrada['name']}' na tabela '{tabela}' "
            f"(table_ref '{table_ref}'), colunas ({colunas})..."
        )
        cursor.execute(
            f'CREATE INDEX IF NOT EXISTS "{entrada["name"]}" ON "{tabela}" ({colunas});'
        )
        conn.commit()
        print(f"   -> Índice '{entrada['name']}' criado com sucesso!")

    cursor.close()
    conn.close()
    print("[ABT INDEXES] Índices intermediários criados com sucesso!")
from utils import get_database_connection

# ---------------------------------------------------------------------------
# Task: Criação de Índices Otimizados (Rodar ANTES das limpezas)
# ---------------------------------------------------------------------------
def run_create_indexes(conn_id: str, config: dict):
    """
    Cria os índices declarados em ``config["indexes"]["raw"]`` nas tabelas raw.

    Cada entrada resolve sua tabela física por ``table_ref`` em
    ``config["database"]``, então renomear a tabela nesse bloco redireciona o
    índice para o novo nome sem alterar esta função.
    """
    conn = get_database_connection(conn_id)
    cursor = conn.cursor()

    db_config = config["database"]
    raw_indexes = config["indexes"]["raw"]

    print("--- Criando índices para otimizar leitura nas tabelas de origem. ---")

    for entrada in raw_indexes:
        tabela = db_config[entrada["table_ref"]]
        colunas = ", ".join(entrada["columns"])
        print(
            f"   -> Criando índice '{entrada['name']}' na tabela '{tabela}' "
            f"(table_ref '{entrada['table_ref']}'), colunas ({colunas})..."
        )
        cursor.execute(
            f'CREATE INDEX IF NOT EXISTS "{entrada["name"]}" ON "{tabela}" ({colunas});'
        )
        conn.commit()
        print(f"   -> Índice '{entrada['name']}' criado com sucesso!")

    cursor.close()
    conn.close()
    print("--- Índices criados com sucesso! Banco pronto para processamento ELT. ---")
def run_abt_indexes(conn, config: dict):
    """
    Cria os índices declarados em ``config["indexes"]["clean"]`` nas tabelas
    higienizadas (_clean), otimizando os JOINs da ABT.

    Como as tabelas _clean são recriadas a cada execução pelo data_sanitization,
    elas perdem os índices originais. Esta etapa garante a performance do mega JOIN.

    Cada entrada resolve sua tabela física por ``table_ref`` em
    ``config["database"]``; um `table_ref` que resolve para um nome vazio ou
    ausente falha com ``ValueError``, identificando a entrada malformada.

    Args:
        conn: Conexão DBAPI já aberta, fornecida pelo chamador.
        config (dict): Dicionário de configuração já carregado.
    """
    cursor = conn.cursor()

    db_config = config["database"]
    clean_indexes = config["indexes"]["clean"]

    print("[ABT INDEXES] Iniciando criação de índices nas tabelas higienizadas...")

    for entrada in clean_indexes:
        table_ref = entrada["table_ref"]
        tabela = db_config.get(table_ref)
        if not tabela:
            cursor.close()
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
    print("[ABT INDEXES] Índices intermediários criados com sucesso!")
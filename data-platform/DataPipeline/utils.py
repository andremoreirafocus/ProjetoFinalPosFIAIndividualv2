import io
import pandas as pd
import os

def get_database_connection(conn_id: str|None = None, silent: bool = False):
    """Retorna uma conexão ativa com o banco.

    Detecta automaticamente se está rodando dentro do fluxo do Airflow (usa
    PostgresHook) ou de forma isolada (usa SQLAlchemy).
    """
    # Se a variável de ambiente do Airflow existir, usamos o Hook Nativo
    if "AIRFLOW_HOME" in os.environ:
        try:
            from airflow.providers.postgres.hooks.postgres import PostgresHook

            if not silent:
                print(f"[CONEXÃO] Ambiente Airflow detectado. Usando PostgresHook('{conn_id}').")
            pg_hook = PostgresHook(postgres_conn_id=conn_id)
            return pg_hook.get_conn()
        except ImportError:
            if not silent:
                print("[CONEXÃO] Aviso: AIRFLOW_HOME ativa, mas falha ao importar PostgresHook. Tentando fallback para SQLAlchemy...")

    # Fallback para execução local/notebook via SQLAlchemy
    from sqlalchemy import create_engine

    # Mantém a seleção original de host: nome do serviço no Docker e localhost fora dele.
    host = os.getenv("POSTGRES_HOST") if os.path.exists("/.dockerenv") else "localhost"
    conn_str = (
        f"postgresql://{os.getenv('POSTGRES_USER')}:{os.getenv('POSTGRES_PASSWORD')}"
        f"@{host}:{os.getenv('POSTGRES_PORT')}/{os.getenv('POSTGRES_DATA_DB')}"
    )

    if not silent:
        print(f"[CONEXÃO] Execução isolada detectada (Local/Notebook). Conectando via SQLAlchemy em '{host}'.")
    engine = create_engine(conn_str)
    return engine.raw_connection()


def get_database_engine(conn_id: str | None = None, silent: bool = False):
    """Retorna um Engine do SQLAlchemy (ideal para pd.read_sql em notebooks).

    Usa a mesma deteccao de ambiente da get_database_connection, mas devolve o
    Engine (nao a conexao crua) — evitando o warning do pandas com DBAPI cru.
    """
    if "AIRFLOW_HOME" in os.environ:
        try:
            from airflow.providers.postgres.hooks.postgres import PostgresHook

            if not silent:
                print(f"[CONEXÃO] Ambiente Airflow detectado. Engine via PostgresHook('{conn_id}').")
            return PostgresHook(postgres_conn_id=conn_id).get_sqlalchemy_engine()
        except ImportError:
            if not silent:
                print("[CONEXÃO] AIRFLOW_HOME ativa, mas falha ao importar PostgresHook. Fallback SQLAlchemy...")

    from sqlalchemy import create_engine

    host = os.getenv("POSTGRES_HOST") if os.path.exists("/.dockerenv") else "localhost"
    conn_str = (
        f"postgresql://{os.getenv('POSTGRES_USER')}:{os.getenv('POSTGRES_PASSWORD')}"
        f"@{host}:{os.getenv('POSTGRES_PORT')}/{os.getenv('POSTGRES_DATA_DB')}"
    )
    if not silent:
        print(f"[CONEXÃO] Execução isolada detectada (Local/Notebook). Engine SQLAlchemy em '{host}'.")
    return create_engine(conn_str)


def load_pipeline_config(path: str) -> dict:
    """Carrega e retorna o conteúdo de `config_pipeline.json` a partir de `path`.

    `path` é obrigatório: não há caminho default nem inferência de arquivo "ao
    lado" deste módulo. Isola o I/O de configuração da camada de orquestração.
    """
    import json

    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def map_pandas_to_postgres_types(df: pd.DataFrame) -> list:
    """Mapeia os dtypes do Pandas para tipos de dados compatíveis com o PostgreSQL."""
    colunas = []
    for col, dtype in zip(df.columns, df.dtypes):
        col_nome = str(col).lower().replace("-", "_").replace(" ", "_").replace(".", "_")
        
        if "int" in str(dtype):
            pg_type = "BIGINT"
        elif "float" in str(dtype):
            pg_type = "DOUBLE PRECISION"
        elif "bool" in str(dtype):
            pg_type = "BOOLEAN"
        elif "datetime" in str(dtype):
            pg_type = "TIMESTAMP"
        else:
            pg_type = "TEXT"
            
        colunas.append(f'"{col_nome}" {pg_type}')
    return colunas

def append_dataframe_to_postgres(df: pd.DataFrame, table_name: str, conn_id: str):
    """Insere os dados de um chunk em uma tabela já existente usando a conexão híbrida."""
    conn = get_database_connection(conn_id, silent=True)
    cursor = conn.cursor()
    linhas = len(df)

    try:
        output = io.StringIO()
        df.to_csv(output, sep="\t", header=False, index=False)
        output.seek(0)

        cursor.copy_expert(f'COPY "{table_name}" FROM STDIN WITH CSV DELIMITER \'\t\' NULL \'\'', output)
        print(f"[CHUNK APPEND] +{linhas:,} linhas inseridas em '{table_name}'.")
        conn.commit()

    except Exception as e:
        conn.rollback()
        raise RuntimeError(f"Falha no append do chunk na tabela {table_name}: {str(e)}")
    finally:
        cursor.close()
        conn.close()

def save_dataframe_to_postgres(df: pd.DataFrame, table_name: str, conn_id: str):
    """Cria/Recria a tabela e insere os dados de forma ultra rápida usando a conexão híbrida."""
    # Busca a conexão com banco de dados
    conn = get_database_connection(conn_id, silent=True)
    cursor = conn.cursor()

    linhas = len(df)
    print(f"[LOAD INIT] Recriando tabela '{table_name}'...")
    try:
        colunas_sql = map_pandas_to_postgres_types(df)
        cursor.execute(f'DROP TABLE IF EXISTS "{table_name}" CASCADE;')
        cursor.execute(cursor.execute(f'CREATE TABLE "{table_name}" ({", ".join(colunas_sql)});'))

        output = io.StringIO()
        df.to_csv(output, sep="\t", header=False, index=False)
        output.seek(0)

        print(f"Carregando {len(df)} linhas na tabela '{table_name}' via COPY...")
        cursor.copy_expert(f'COPY "{table_name}" FROM STDIN WITH CSV DELIMITER \'\t\' NULL \'\'',output)

        conn.commit()
        print(f"[LOAD INIT] Sucesso! Tabela '{table_name}' carregada com {linhas:,} linhas.")

    except Exception as e:
        conn.rollback()
        raise RuntimeError(f"Falha crítica na gravação da tabela {table_name}: {str(e)}")
    finally:
        cursor.close()
        conn.close()

def log_row_count(cursor, table_name: str, context: str):
    """
    Função auxiliar para registrar a volumetria das tabelas no log do Airflow.

    Args:
        cursor: Cursor ativo do banco de dados.
        table_name (str): Nome da tabela para contagem.
        context (str): Contexto da mensagem (Ex: 'Entrada', 'Saída').
    """
    try:
        cursor.execute(f'SELECT COUNT(*) FROM "{table_name}";')
        count = cursor.fetchone()[0]
        print(f"[VOLUMETRIA - {context}] Tabela '{table_name}': {count:,} registros.")
    except Exception as e:
        print(f"[AVISO] Não foi possível contar as linhas da tabela '{table_name}': {e}")

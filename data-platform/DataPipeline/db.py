"""Acesso ao banco de dados do pipeline.

Reúne a resolução de conexão, o mapeamento de dtypes para DDL, a gravação de DataFrame via
`COPY` e a contagem de linhas. É a fronteira única de banco do componente, consumida pelas
tarefas do pipeline, pela task de treino do `Model` e pelos notebooks de análise.
"""

import io
import pandas as pd
import os

ENV_CONNECTION_VARIABLES = (
    "POSTGRES_USER",
    "POSTGRES_PASSWORD",
    "POSTGRES_HOST",
    "POSTGRES_PORT",
    "POSTGRES_DATA_DB",
)


def get_db_connection_str_from_env() -> str:
    """Monta a string de conexão a partir das variáveis de ambiente do PostgreSQL.

    É a única fronteira que lê o ambiente. `POSTGRES_HOST` vale em qualquer ambiente:
    o host é configurado, não inferido. Toda variável é obrigatória — a ausência falha
    nomeando quais faltam, em vez de compor uma string com `None`.
    """
    ausentes = [nome for nome in ENV_CONNECTION_VARIABLES if not os.environ.get(nome)]
    if ausentes:
        raise ValueError(
            "Configuração de conexão incompleta: variáveis de ambiente obrigatórias "
            f"ausentes ou vazias: {', '.join(ausentes)}."
        )

    return (
        f"postgresql://{os.environ['POSTGRES_USER']}:{os.environ['POSTGRES_PASSWORD']}"
        f"@{os.environ['POSTGRES_HOST']}:{os.environ['POSTGRES_PORT']}"
        f"/{os.environ['POSTGRES_DATA_DB']}"
    )


def get_pg_database_connection(connection_str: str, silent: bool = False):
    """Abre uma conexão com o PostgreSQL a partir da string recebida.

    Para execução fora do Airflow — script local, notebook e suíte de testes. Não lê
    ambiente: a conexão é inteiramente determinada pelo argumento.
    """
    from sqlalchemy import create_engine
    from sqlalchemy.engine import make_url

    engine = create_engine(connection_str)
    if not silent:
        url = make_url(connection_str)
        print(f"[CONEXÃO] SQLAlchemy em '{url.host}', banco '{url.database}'.")
    return engine.raw_connection()


def get_pghook_database_connection(conn_id: str, silent: bool = False):
    """Abre uma conexão com o PostgreSQL pelo `PostgresHook` do Airflow.

    Para execução como tarefa da DAG, onde a credencial é resolvida pelo `conn_id`.
    Fora do Airflow o import do provider falha — que é o comportamento correto para
    quem chamou a função do contexto errado.
    """
    from airflow.providers.postgres.hooks.postgres import PostgresHook

    if not silent:
        print(f"[CONEXÃO] PostgresHook('{conn_id}').")
    return PostgresHook(postgres_conn_id=conn_id).get_conn()


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


def get_database_engine(connection_str: str, silent: bool = False):
    """Retorna um Engine do SQLAlchemy a partir da string recebida.

    Para os notebooks, onde o Engine — e não a conexão crua — é o que `pd.read_sql`
    espera. Não lê ambiente: o destino é inteiramente determinado pelo argumento.
    """
    from sqlalchemy import create_engine
    from sqlalchemy.engine import make_url

    engine = create_engine(connection_str)
    if not silent:
        url = make_url(connection_str)
        print(f"[CONEXÃO] Engine SQLAlchemy em '{url.host}', banco '{url.database}'.")
    return engine


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

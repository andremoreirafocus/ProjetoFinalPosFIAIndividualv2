"""Acesso ao banco de dados da plataforma.

Reúne a resolução de conexão, o mapeamento de dtypes para DDL, a gravação de DataFrame via
`COPY` e a contagem de linhas. É a fronteira única de banco, comum a todos os componentes:
consumida pelas tarefas do pipeline, pela task de treino do `Model`, pelos notebooks de
análise e pelos utilitários manuais.

Não decide contexto: quem chama escolhe a função adequada ao seu — `PostgresHook` dentro do
Airflow, SQLAlchemy fora dele — e recebe a conexão para abrir e fechar.
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


def get_db_connection_str_from_env(host: str | None = None) -> str:
    """Monta a string de conexão a partir das variáveis de ambiente do PostgreSQL.

    É a única fronteira que lê o ambiente. O comportamento normal é usar `POSTGRES_HOST`,
    que é o endereço correto para quem roda dentro da rede do compose. `host` é a exceção
    explícita, para o chamador que conhece o endereço do seu contexto — o CLI, que roda
    fora dessa rede; informado, dispensa `POSTGRES_HOST`.

    As demais variáveis são sempre obrigatórias: a ausência falha nomeando quais faltam,
    em vez de compor uma string com `None`.
    """
    exigidas = list(ENV_CONNECTION_VARIABLES)
    if host is not None:
        exigidas.remove("POSTGRES_HOST")

    ausentes = [nome for nome in exigidas if not os.environ.get(nome)]
    if ausentes:
        raise ValueError(
            "Configuração de conexão incompleta: variáveis de ambiente obrigatórias "
            f"ausentes ou vazias: {', '.join(ausentes)}."
        )

    endereco = host if host is not None else os.environ["POSTGRES_HOST"]
    return (
        f"postgresql://{os.environ['POSTGRES_USER']}:{os.environ['POSTGRES_PASSWORD']}"
        f"@{endereco}:{os.environ['POSTGRES_PORT']}"
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

def append_dataframe_to_postgres(df: pd.DataFrame, table_name: str, conn):
    """Insere os dados de um chunk numa tabela já existente, pela conexão recebida.

    Não abre nem fecha a conexão: quem a abriu é quem a fecha.
    """
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

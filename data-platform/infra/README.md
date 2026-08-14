# infra

Fronteira de infraestrutura compartilhada da plataforma. Hoje reúne o acesso ao PostgreSQL,
consumido pelo pipeline de dados, pelo treinamento do modelo, pelos notebooks e pelos
utilitários manuais.

## Responsabilidade

- resolver conexão com o banco de acordo com o contexto declarado por quem chama;
- montar a string de conexão a partir das variáveis de ambiente, em um lugar só;
- oferecer o mapeamento de dtypes do pandas para DDL do PostgreSQL;
- gravar DataFrames por `COPY` e registrar volumetria.

Não contém regra de negócio nem conhecimento de domínio: não sabe o que é ABT, cliente ou
score. Componentes dependem do `infra`; o `infra` não depende de componente algum.

## Conexão com o banco

O mecanismo é escolhido por qual função se chama — o contexto é declarado por quem já o
conhece, não inferido do ambiente:

| Função | Contexto |
|---|---|
| `get_pghook_database_connection(conn_id)` | tarefa da DAG do Airflow |
| `get_pg_database_connection(connection_str)` | script local e suíte de testes |
| `get_database_engine(connection_str)` | notebooks, onde `pd.read_sql` espera um Engine |

`get_db_connection_str_from_env()` é a única fronteira que lê o ambiente: monta a string a
partir das variáveis `POSTGRES_*`, todas obrigatórias. Aceita um `host` opcional que
sobrepõe `POSTGRES_HOST`, para quem roda fora da rede do compose — é o caso do CLI de
treinamento, que declara `localhost`.

```python
from infra.db import get_db_connection_str_from_env, get_pg_database_connection

conn = get_pg_database_connection(get_db_connection_str_from_env())
```

**Quem abre a conexão é quem a fecha.** As funções dos componentes recebem a conexão pronta
e não a resolvem: na DAG, cada task abre pelo `PostgresHook` e fecha em `finally`; na suíte
de testes, a conexão vem do banco de teste dedicado.

## Demais funções

| Função | Finalidade |
|---|---|
| `map_pandas_to_postgres_types(df)` | Traduz os dtypes de um DataFrame para tipos de coluna do PostgreSQL, usado na criação da tabela durante a ingestão. |
| `append_dataframe_to_postgres(df, table_name, conn)` | Insere um bloco de dados numa tabela existente por `COPY FROM STDIN`, sem materializar inserts linha a linha. |
| `log_row_count(cursor, table_name, context)` | Registra a volumetria de uma tabela no log da tarefa, para localizar quedas inesperadas entre camadas. |

## Importação

O import é `from infra.db import ...`, o que exige a pasta `data-platform` no caminho de
importação — e não a pasta `infra`. Cada runtime compõe esse caminho do seu jeito: os
`pytest.ini` dos componentes declaram `pythonpath`, a DAG acrescenta `/opt/airflow` ao
`sys.path`, os notebooks inserem a raiz do workspace, e a execução local usa `PYTHONPATH=.`
a partir de `data-platform`.

Nos contêineres, o componente chega por montagem: `/opt/airflow/infra` no Airflow e
`/home/jovyan/work/infra` no Jupyter.

## Dependências

[`requirements.txt`](./requirements.txt) declara o que este componente importa — `pandas`,
`SQLAlchemy` e `psycopg2-binary`. Os componentes que o consomem referenciam esse arquivo em
vez de repetir as versões.

## Componentes relacionados

- [Pipeline de dados](../DataPipeline/README.md)
- [Modelo](../Model/README.md)
- [Airflow](../airflow/README.md)
- [PostgreSQL](../postgres/README.md)

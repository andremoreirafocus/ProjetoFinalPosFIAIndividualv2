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

`get_database_engine` aceita `pool_pre_ping: bool = False`. Ligado, testa a conexão
emprestada do pool antes de cada uso e descarta a que morreu enquanto ociosa (timeout do
lado do servidor, rede caindo), abrindo outra no lugar — sem isso, a operação seguinte
falha com o erro da conexão morta. Quem chama decide: processo longo com conexões que
envelhecem no pool liga; processo curto que abre uma conexão e termina usa o padrão.

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

## Harness de teste

[`testing.py`](./testing.py) é o harness de banco compartilhado pelas suítes da plataforma.
Cada componente o declara no seu `conftest.py`:

```python
pytest_plugins = ["infra.testing"]
```

O que ele oferece:

| Fixture | Entrega |
|---|---|
| `test_db` | Auxiliar ligado ao banco de teste, com o schema público limpo na entrada e na saída, para arranjar tabelas e observar estado nas asserções. |
| `conexao` | Conexão DBAPI com o banco de teste — o mesmo tipo de objeto que a task da DAG entrega em produção. Sem `autocommit`, para que `commit` e `rollback` tenham efeito observável. |
| `ambiente_do_banco_de_teste` | Declara as variáveis `POSTGRES_*` apontando para o banco de teste, e as restaura ao fim. Só os testes da função que lê o ambiente precisam dela. |

Dois contratos de uso:

- **`conexao` deve ser declarada depois de `test_db`** na assinatura do teste. A ordem
  determina a finalização — `conexao` é fechada antes —, e sem isso a transação em aberto
  trava o `DROP TABLE` da limpeza.
- A configuração é **lida sob demanda**, dentro da fixture de sessão, não no import: uma
  suíte que não toca o banco roda sem exigir o arquivo nem o PostgreSQL.

A conexão vem de [`test_database.ini`](./test_database.ini), com todas as chaves
obrigatórias e sem fallback de ambiente. Um guard recusa executar se o alvo não for um
banco `*_test` distinto do banco do pipeline, de modo que a suíte não pode criar, recriar
ou remover tabelas no banco de produção. O provisionamento do banco e do papel de menor
privilégio está no [README do PostgreSQL](../postgres/README.md).

## Testes

A suíte deste componente fixa o contrato da fronteira que ele implementa:

- a montagem da string de conexão a partir das variáveis de ambiente, e a exceção do host
  informado, que sobrepõe e dispensa `POSTGRES_HOST`;
- a falha nomeando qual variável obrigatória falta, em vez de compor uma string com `None`;
- a abertura de conexão no banco indicado pela string recebida, e não pelo ambiente;
- o Engine do SQLAlchemy apontando para o destino declarado e alimentando `pandas.read_sql`,
  que é o uso real nos notebooks;
- com `pool_pre_ping=True`, uma conexão que morreu enquanto ociosa no pool não quebra a
  operação seguinte; sem ele, a mesma conexão morta quebra — os dois lados fixados, cada
  um pelo seu próprio caso;
- a garantia de isolamento: o papel de teste conecta ao banco de teste e é recusado pelo
  banco do pipeline.

Os contratos funcionais dos componentes que consomem esta fronteira são cobertos pelas
suítes deles, sem reexercitar o que já está fixado aqui.

Executa a partir desta pasta, reusando o ambiente do pipeline — o componente não tem
`.venv` próprio porque suas dependências são as mesmas, mais o pytest:

```bash
cd data-platform/infra
../DataPipeline/.venv/bin/python -m pytest
```

## Componentes relacionados

- [Pipeline de dados](../DataPipeline/README.md)
- [Modelo](../Model/README.md)
- [Airflow](../airflow/README.md)
- [PostgreSQL](../postgres/README.md)

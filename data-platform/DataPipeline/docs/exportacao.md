# DataPipeline — Exportação de tabelas para CSV

Utilitário de execução manual para preparar os CSVs de entrega. Parte do [DataPipeline](../README.md).

[`export_data.py`](../export_data.py) é um **utilitário de execução manual** para preparar os arquivos CSV exigidos na entrega acadêmica a partir de tabelas já existentes no banco PostgreSQL `data`. Ele não integra a DAG, não é executado automaticamente pelo Airflow e não faz parte do processamento operacional recorrente.

O pipeline continua responsável por ingerir, tratar e materializar as tabelas no PostgreSQL. Depois que essas etapas estiverem concluídas, o responsável pela entrega executa o script sob demanda para transportar uma tabela do banco para um arquivo CSV, sem duplicar as regras de ingestão, limpeza ou construção da ABT.

A função `run_postgres_to_csv_export` recebe três parâmetros:

| Parâmetro | Finalidade |
|---|---|
| `conn` | Conexão já aberta com o PostgreSQL. Quem chama abre e fecha; a função não resolve conexão. Na execução manual, o bloco `__main__` a abre em `localhost:5432/data`. |
| `source_table` | Nome da tabela que será exportada. |
| `output_dir_path` | Diretório de destino. O nome final é montado como `<source_table>.csv`. |

Antes da exportação, o script registra a quantidade de linhas da tabela. Em seguida, utiliza `COPY TO STDOUT WITH CSV HEADER`, fazendo o PostgreSQL transmitir os registros diretamente para o arquivo. Essa estratégia evita montar um `DataFrame` com toda a tabela em memória e é adequada para a volumetria da ABT.

## Preparação do ambiente local

Execute os comandos de preparação a partir da raiz do repositório:

```bash
python3 -m venv data-platform/DataPipeline/.venv
data-platform/DataPipeline/.venv/bin/python -m pip install \
  -r data-platform/DataPipeline/requirements.txt
```

O PostgreSQL deve estar ativo, o banco `data` deve estar acessível pela porta local `5432` e a tabela a ser exportada deve ter sido previamente materializada pelo pipeline. Para iniciar somente o banco:

```bash
docker compose -f data-platform/docker-compose.yml up -d postgres
```

## Execução manual

Entre na pasta `DataPipeline` para que o caminho relativo de saída seja resolvido para `data-platform/airflow/data/csv`:

```bash
cd data-platform/DataPipeline
set -a
source ../.env
set +a
.venv/bin/python export_data.py
```

O carregamento de `../.env` exporta as credenciais, a porta e o nome do banco. O host não
vem de lá: a execução é fora da rede do compose, e o bloco `__main__` declara `localhost`
na própria chamada.

Na configuração atual do bloco `__main__`, o comando exporta:

| Tabela PostgreSQL | Arquivo gerado |
|---|---|
| `application_clean` | `airflow/data/csv/application_clean.csv` |
| `previous_application_clean` | `airflow/data/csv/previous_application_clean.csv` |
| `bureau_clean` | `airflow/data/csv/bureau_clean.csv` |
| `installments_clean` | `airflow/data/csv/installments_clean.csv` |
| `application_abt` | `airflow/data/csv/application_abt.csv` |

Esses arquivos são gravados ao lado dos quatro CSVs brutos usados na ingestão. Assim, o diretório reúne as fontes originais, suas representações tratadas e a ABT final. O caminho é relativo ao diretório de execução; por isso, o comando deve ser iniciado em `data-platform/DataPipeline`.

Os arquivos já foram materializados em `data-platform/airflow/data/csv`, pasta originalmente destinada aos arquivos brutos. Atualmente ela reúne:

- as quatro fontes brutas: `application_train.csv`, `previous_application.csv`, `bureau.csv` e `installments_payments.csv`;
- as quatro bases tratadas: `application_clean.csv`, `previous_application_clean.csv`, `bureau_clean.csv` e `installments_clean.csv`;
- a base analítica final: `application_abt.csv`.

A convivência no mesmo diretório atende à preparação manual da entrega. Os sufixos `_clean` e `_abt` distinguem claramente os arquivos gerados pelo pipeline das fontes brutas usadas na ingestão.

## Exportação de outra tabela

O script expõe uma função reutilizável para chamadas manuais em outro módulo Python:

```python
from db import get_db_connection_str_from_env, get_pg_database_connection
from export_data import run_postgres_to_csv_export

conn = get_pg_database_connection(get_db_connection_str_from_env("localhost"))
try:
    run_postgres_to_csv_export(
        conn=conn,
        source_table="application_clean",
        output_dir_path="../airflow/data/csv",
    )
finally:
    conn.close()
```

Esse exemplo, executado a partir de `data-platform/DataPipeline`, gera `data-platform/airflow/data/csv/application_clean.csv`. A função exporta uma tabela por chamada e usa o nome da tabela para identificar claramente o conteúdo do arquivo.

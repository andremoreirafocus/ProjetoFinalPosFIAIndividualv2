# PostgreSQL

Esta pasta contém a inicialização do banco PostgreSQL usado pela plataforma. O mesmo servidor mantém o banco de metadados do Airflow (`airflow`) e o banco de dados do projeto (`data`).

## Papel arquitetural

O PostgreSQL não é apenas o destino da ingestão. Ele funciona como motor de transformação ELT e como contrato de integração entre pipeline, modelo e API. Percentis, padronizações, agregações históricas e joins da ABT são executados no banco, reduzindo movimentação de dados para processos Python.

O banco `data` atende três momentos distintos:

- **engenharia de dados:** recebe fontes e materializa tabelas tratadas;
- **modelagem:** fornece `application_abt` ao treinamento e aos notebooks;
- **inferência:** fornece a mesma ABT ao serviço de features da API.

Essa reutilização ajuda a manter consistência entre treino e predição por cliente.

## Responsabilidade

- disponibilizar a persistência relacional da plataforma;
- criar o banco `data` na primeira inicialização;
- armazenar tabelas brutas, tabelas tratadas e a ABT `application_abt`;
- atender Airflow, treinamento e API de predição.

## Estrutura

```text
postgres/
├── README.md
└── init/
    └── 01-create-data-db.sql
```

O script [`01-create-data-db.sql`](./init/01-create-data-db.sql) é executado automaticamente pela imagem oficial do PostgreSQL quando o volume é criado pela primeira vez.

## Inicialização

Na pasta [`data-platform`](../README.md):

```bash
docker compose up -d postgres
```

O serviço publica a porta `5432` e possui verificação de saúde com `pg_isready`.

## Conexões

| Uso | Banco | Host no Docker | Host local | Porta |
|---|---|---|---|---|
| Metadados do Airflow | `airflow` | `postgres` | `localhost` | `5432` |
| Dados do projeto | `data` | `postgres` | `localhost` | `5432` |

As credenciais e os nomes dos bancos do ambiente acadêmico estão definidos no arquivo [`.env`](../.env), lido pelo Docker Compose. Em outro ambiente, devem ser substituídos por variáveis e segredos próprios.

## Ciclo das tabelas no banco `data`

| Estágio | Tabelas | Ciclo de vida |
|---|---|---|
| Bruto | `application_train`, `previous_application`, `bureau`, `installments_payments` | Recriadas pela ingestão a partir dos CSVs. |
| Tratado | `application_clean`, `previous_application_clean`, `bureau_clean`, `installments_clean` | Recriadas pela sanitização. |
| Agregação | `tmp_prev_application_agg`, `tmp_bureau_agg`, `tmp_installments_agg` | Removidas após a construção da ABT. |
| Analítico | `application_abt` | Recriada pelo pipeline e consumida por modelo e API. |

As tabelas são recriadas para tornar explícita a reconstrução do estado derivado. O volume Docker preserva o banco entre reinicializações, mas não impede que a DAG substitua tabelas de destino durante uma nova execução.

## Implementação da inicialização

O Compose inicia a imagem `postgres:15` com o banco padrão `airflow`. O diretório `postgres/init` é montado como `/docker-entrypoint-initdb.d`, mecanismo nativo da imagem oficial. O script [`01-create-data-db.sql`](./init/01-create-data-db.sql) cria o banco adicional `data` antes da inicialização dos consumidores.

O health check executa `pg_isready` no banco `airflow`. Serviços dependentes podem aguardar esse estado antes de executar migrações ou abrir conexões.

## Consumidores

| Consumidor | Banco | Forma de acesso |
|---|---|---|
| Airflow interno | `airflow` | SQLAlchemy configurado pelo próprio Airflow. |
| Tarefas da DAG | `data` | Connection `postgres_data_db` e `PostgresHook`. |
| Execução local | `data` | SQLAlchemy em `localhost:5432`. |
| API | `data` | Engine SQLAlchemy com validação de conexão. |

Dentro da rede Docker o hostname é `postgres`; fora dela é `localhost`.

## Observação sobre o volume

Os scripts de `init/` só são aplicados automaticamente quando o volume do PostgreSQL ainda está vazio. O volume nomeado `pgdata` preserva os dados entre reinicializações dos containers.

Remover containers com `docker compose down` preserva o volume. O uso de `docker compose down --volumes` remove também os bancos e exige uma nova ingestão completa.

## Inspeção local

Para abrir um terminal SQL no banco de dados do projeto:

```bash
set -a
source .env
set +a
docker compose exec postgres psql -U "$POSTGRES_USER" -d "$POSTGRES_DATA_DB"
```

Consultas úteis para inspeção:

```sql
\dt

SELECT COUNT(*) FROM application_abt;

SELECT target, COUNT(*)
FROM application_abt
GROUP BY target
ORDER BY target;
```

## Componentes relacionados

- [Airflow](../airflow/README.md)
- [Pipeline de dados](../DataPipeline/README.md)
- [Modelo](../Model/README.md)
- [MLOps](../MLOps/README.md)

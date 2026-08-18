# DataPipeline

Esta pasta contém a lógica de ingestão, limpeza, agregação e construção da Analytical Base Table (ABT) do projeto de risco de crédito.

## Contexto do problema de dados

`application_train` é a tabela principal do cadastro: **uma linha por cliente** (`sk_id_curr`), com a coluna `target` a ser prevista. Ela define a população e a granularidade do problema — uma decisão de crédito por cliente.

As demais fontes descrevem **múltiplas operações por cliente** (relação um-para-muitos com `sk_id_curr`):

| Fonte | Grão (uma linha por) | O que traz |
|---|---|---|
| `application_train` | cliente (`sk_id_curr`) | Cadastro do solicitante e o `target`; base da ABT. |
| `previous_application` | proposta anterior (`sk_id_prev`) | Solicitações de crédito anteriores do cliente no Home Credit. |
| `bureau` | crédito externo (`sk_id_bureau`) | Créditos do cliente em outras instituições. |
| `installments_payments` | parcela (ligada por `sk_id_prev`/`sk_id_curr`) | Pagamentos de parcelas das propostas anteriores. |

Como bureau, propostas e parcelas têm muitos registros para o mesmo `sk_id_curr`, um join direto duplicaria clientes, distorceria o target e daria peso indevido a quem possui mais histórico.

O DataPipeline resolve isso em duas etapas: primeiro preserva e trata cada fonte; depois transforma os históricos um-para-muitos em indicadores agregados por cliente. A ABT final mantém a granularidade necessária ao aprendizado supervisionado: uma linha, um target e um conjunto consistente de features por cliente.

Além de preparar dados tecnicamente válidos, o componente busca preservar significado de negócio. Ausência de histórico é representada por flags próprias, anomalias cadastrais são isoladas e variáveis financeiras são tratadas sem apagar diferenças relevantes de risco.

## Responsabilidade

- carregar os CSVs de origem no PostgreSQL;
- criar índices para as etapas de transformação;
- limpar e padronizar as fontes de dados;
- agregar históricos por cliente;
- materializar a tabela `application_abt` com uma linha por cliente;
- documentar a exploração dos dados brutos e tratados.

## Fluxo

```text
CSVs
  → tabelas brutas no PostgreSQL
  → tabelas *_clean
  → agregações de previous_application, bureau e installments
  → application_abt
  → treinamento do modelo
```

A execução completa é coordenada pela DAG descrita no [README do Airflow](../airflow/README.md).

## Documentação detalhada

A referência aprofundada de cada área fica em documentos dedicados nesta pasta:

- [`docs/transformacoes.md`](./docs/transformacoes.md) — decisão de ELT, implementação da ingestão, regras de limpeza, agregações por cliente e construção da ABT, com as propriedades esperadas da tabela final.
- [`docs/eda.md`](./docs/eda.md) — metodologia da análise exploratória que originou as regras de preparação e o papel de cada notebook.
- [`docs/exportacao.md`](./docs/exportacao.md) — utilitário manual `export_data.py` para exportar tabelas do banco como CSV de entrega.

## Arquivos principais

| Arquivo | Finalidade |
|---|---|
| [`ingestion.py`](./ingestion.py) | Carrega os CSVs em blocos no PostgreSQL. |
| [`ingestion_index.py`](./ingestion_index.py) | Cria índices nas tabelas de origem. |
| [`data_sanitization.py`](./data_sanitization.py) | Aplica limpeza e padronização por SQL. |
| [`data_sanitization_index.py`](./data_sanitization_index.py) | Recria índices nas tabelas tratadas. |
| [`abt_transform.py`](./abt_transform.py) | Agrega históricos e constrói a ABT. |
| [`export_data.py`](./export_data.py) | Utilitário manual para exportar tabelas do PostgreSQL como arquivos CSV de entrega. |
| [`config.py`](./config.py) | Carga do `config_pipeline.json`. |
| [`config_pipeline.json`](./config_pipeline.json) | Define fontes, tabelas, chunks, índices e parâmetros de limpeza. |
| [`requirements.txt`](./requirements.txt) | Dependências para executar os scripts do pipeline fora do Airflow. |
| [`requirements-test.txt`](./requirements-test.txt) | Dependências dos testes: reusa `requirements.txt` e adiciona apenas as ferramentas de teste. |
| [`tests/`](./tests) | Suíte de testes de contrato do pipeline (ver seção [Testes](#testes)). |
| [`abt_fields.txt`](./abt_fields.txt) | Inventário textual dos campos da ABT. |
| [`df_correlations_with_target.txt`](./df_correlations_with_target.txt) | Registro auxiliar das correlações com o alvo. |

## Fontes ingeridas

Os arquivos devem ser colocados em `data-platform/airflow/data/csv`:

- `application_train.csv`;
- `previous_application.csv`;
- `bureau.csv`;
- `installments_payments.csv`.

O escopo e o tamanho dos blocos são controlados por [`config_pipeline.json`](./config_pipeline.json).

## Configuração do pipeline

| Seção | Função |
|---|---|
| `ingestion_table.using_csv` | Fontes autorizadas e tamanho de cada chunk. |
| `database` | Nomes das tabelas brutas, tratadas e da ABT. |
| `indexes.raw` | Índices de junção e de filtro criados nas tabelas brutas, antes da limpeza. |
| `indexes.clean` | Índices em `sk_id_curr` criados nas tabelas tratadas, antes do join da ABT. |
| `sanitization.cardinalidade_min_freq` | Frequência mínima antes de agrupar categorias raras. |
| `sanitization.income_winsor_q` | Quantil máximo aplicado à renda. |

O Airflow lê essa configuração no carregamento da DAG, via `load_pipeline_config` (`config.py`), que abre o caminho informado e interpreta o JSON como um objeto de configuração. Durante a definição da DAG, são extraídas as fontes de `ingestion_table`, as tabelas de `database` e as regras de `sanitization`, e o objeto completo ou os parâmetros correspondentes são distribuídos às tarefas. Na execução, a ingestão resolve cada fonte declarada e as rotinas de indexação relacionam cada `table_ref` ao nome definido em `database`. Alterar nomes de tabela ou regras de sanitização deve ser coordenado com a DAG, notebooks e configuração do modelo.

## Conexão com o banco

As funções deste componente **recebem a conexão já aberta** e não a resolvem: na DAG, cada
task abre pelo `PostgresHook` e fecha em `finally`; na suíte, a conexão vem do banco de
teste. A fronteira de banco — resolução de conexão, Engine e montagem da string a partir do
ambiente — é do [`infra`](../infra/README.md), e está documentada lá.

## Execução

O caminho recomendado é iniciar PostgreSQL e Airflow e disparar a DAG `pipeline_orchestration`:

```bash
cd data-platform
docker compose up -d --build postgres airflow-init airflow-webserver airflow-scheduler
```

Depois, acesse http://localhost:8080, localize `pipeline_orchestration` e inicie uma execução manual.

## Testes

A suíte valida os contratos funcionais de cada etapa do pipeline (ingestão, índices, sanitização, agregações e ABT) executando as funções reais contra um banco PostgreSQL **de testes dedicado** (`data_test`), isolado do banco de produção `data`. Não há mocks.

As funções são exercitadas pela mesma fronteira que a produção usa: onde a task da DAG entrega a conexão aberta pelo `PostgresHook`, o teste entrega a do `data_test`. A suíte não escreve em variáveis de ambiente.

A **fronteira de banco em si** — resolução de conexão, Engine e isolamento do banco de teste — é coberta pela suíte do [`infra`](../infra/README.md), que a implementa. Aqui os contratos do pipeline dependem desse comportamento sem reexercitá-lo.

### Pré-requisitos

1. **PostgreSQL ativo** em `localhost:5432`:

   ```bash
   docker compose -f data-platform/docker-compose.yml up -d postgres
   ```

2. **Banco e papel de teste provisionados** (`data_test` e `data_test_user`). Em um volume novo isso é automático; em um volume já existente, aplique uma vez o script de bootstrap descrito no [README do PostgreSQL](../postgres/README.md#ambiente-de-testes-isolado).

3. **Dependências de teste instaladas** (produção + ferramentas de teste, a partir da raiz do repositório):

   ```bash
   python3 -m venv data-platform/DataPipeline/.venv
   data-platform/DataPipeline/.venv/bin/python -m pip install \
     -r data-platform/DataPipeline/requirements-test.txt
   ```

A conexão da suíte vem do harness compartilhado em [`infra/testing.py`](../infra/testing.py), que lê [`infra/test_database.ini`](../infra/test_database.ini) — versionado com credenciais locais de demonstração, sem leitura de variáveis de ambiente com fallback. Um guard aborta a execução se o alvo não for um banco `*_test` distinto do banco de produção.

### Execução

A partir de `data-platform/DataPipeline`:

```bash
cd data-platform/DataPipeline
.venv/bin/python -m pytest                       # suíte completa
.venv/bin/python -m pytest -m integration        # apenas testes que tocam o banco
.venv/bin/python -m pytest -m "not integration"  # apenas validações puras (sem banco)
```

Os testes marcados como `integration` exigem o banco `data_test`; os demais rodam sem PostgreSQL.

## Saídas

- tabelas brutas no banco `data`;
- tabelas tratadas com sufixo `_clean`;
- agregações temporárias por cliente;
- ABT `application_abt`.

Os arquivos CSV de entrega não fazem parte das saídas automáticas da DAG. Eles são produzidos posteriormente, sob demanda, pelo utilitário manual [`export_data.py`](./export_data.py) — ver [`docs/exportacao.md`](./docs/exportacao.md).

## Observabilidade do processamento

As funções registram no log:

- tabela e etapa em processamento;
- quantidade de registros na entrada e saída;
- número do chunk durante a ingestão;
- criação de índices e agregações;
- as tasks `ingest_csv_source` e `generate_analytical_base_table` registram a
  conclusão e executam rollback em caso de erro.

Esses eventos aparecem nos logs das tarefas do Airflow e permitem localizar quedas inesperadas de volumetria entre as camadas.

## Componentes relacionados

- [PostgreSQL](../postgres/README.md)
- [Airflow](../airflow/README.md)
- [Jupyter](../jupyter/README.md)
- [Modelo](../Model/README.md)

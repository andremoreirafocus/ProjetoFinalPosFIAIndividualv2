# Airflow

Esta pasta define o ambiente de orquestração do pipeline de dados e treinamento. O Airflow coordena as funções implementadas em [`DataPipeline`](../DataPipeline/README.md) e [`Model`](../Model/README.md).

O Airflow não contém a lógica analítica principal: ele define dependências, paralelismo, parâmetros e ordem de execução. A ingestão, as transformações e o treinamento permanecem em módulos Python próprios, permitindo que notebooks e outros pontos de entrada reutilizem as mesmas regras.

## Objetivo no projeto

O pipeline trabalha com quatro fontes de tamanhos e granularidades diferentes. Executá-las manualmente cria risco de ordem incorreta, transformação sobre tabelas incompletas e treinamento com uma ABT desatualizada. A DAG `pipeline_orchestration` estabelece uma execução única e observável, desde os arquivos CSV até o artefato do modelo.

Os objetivos do componente são:

- garantir a sequência correta das etapas;
- paralelizar tarefas independentes sem exceder os limites configurados;
- centralizar parâmetros de infraestrutura e nomes de tabelas;
- registrar logs e volumetrias por tarefa;
- interromper dependências posteriores quando uma etapa falha;
- tornar explícita a relação entre atualização dos dados, ABT e modelo.

## Responsabilidade

- ingerir as fontes CSV em paralelo;
- criar índices de apoio;
- executar limpeza e padronização;
- agregar históricos e construir a ABT;
- treinar e persistir o modelo ao final do fluxo.

## Estrutura

```text
airflow/
├── dags/
│   └── pipeline_orchestration.py
├── data/
│   └── csv/
├── Dockerfile
├── requirements.txt
└── README.md
```

- [`pipeline_orchestration.py`](./dags/pipeline_orchestration.py): DAG principal da plataforma;
- [`Dockerfile`](./Dockerfile): estende a imagem Apache Airflow 2.9.3;
- [`requirements.txt`](./requirements.txt): dependências compartilhadas pelas tarefas;
- `data/csv/`: entrada local dos arquivos do Home Credit e destino das exportações CSV manuais usadas na entrega acadêmica.

## DAG `pipeline_orchestration`

```text
ingestão dos CSVs
  → índices nas fontes
  → limpeza paralela das quatro fontes
  → índices nas tabelas tratadas
  → agregações paralelas de históricos
  → application_abt
  → treinamento LightGBM
```

A DAG não possui agendamento periódico (`schedule=None`) e deve ser disparada manualmente.

### Etapas e dependências

| Ordem | Tarefa Airflow | Implementação chamada | Resultado |
|---:|---|---|---|
| 1 | `ingest_csv_source` | `run_csv_ingestion` | Quatro tabelas brutas carregadas por dynamic task mapping. |
| 2 | `task_criar_indices` | `run_create_indexes` | Índices nas fontes para apoiar leituras e joins. |
| 3 | `task_sanitize_app` | `run_sanitization` | Cadastro principal tratado. |
| 3 | `task_sanitize_prev` | `run_prev_sanitization` | Propostas anteriores tratadas. |
| 3 | `task_sanitize_bureau` | `run_bureau_sanitization` | Histórico de bureau tratado. |
| 3 | `task_sanitize_installments` | `run_installments_sanitization` | Parcelas válidas selecionadas. |
| 4 | `task_abt_indexes` | `run_abt_indexes` | Índices recriados nas tabelas tratadas. |
| 5 | `agg_intermediate_prev` | `create_agg_previous_application` | Taxa de propostas recusadas por cliente. |
| 5 | `agg_intermediate_bureau` | `create_agg_bureau` | Indicadores agregados de bureau. |
| 5 | `agg_intermediate_installments` | `create_agg_installments` | Indicadores de atraso em parcelas. |
| 6 | `generate_analytical_base_table` | `run_abt_generation` | ABT final com uma linha por cliente. |
| 7 | `train_machine_learning_model` | `run_training_pipeline` | LightGBM, métricas e referências estatísticas persistidos. |

As tarefas marcadas com a mesma ordem podem executar em paralelo. O treinamento só é liberado após a conclusão da ABT.

### Controle de concorrência

O `airflow-init` cria pools específicos:

| Pool | Limite | Uso |
|---|---:|---|
| `pool_ingestao` | 2 | Limita a quantidade simultânea de cargas CSV. |
| `pool_sanitization` | 2 | Controla transformações de limpeza concorrentes. |
| `pool_aggregation` | 2 | Controla agregações históricas simultâneas. |

Os pools evitam que tarefas intensivas concorram sem limite pelo PostgreSQL e pela memória disponível.

## Serviços do Airflow

| Serviço | Ciclo de vida | Responsabilidade |
|---|---|---|
| `airflow-init` | execução única | Prepara banco, usuário, pools, diretórios e permissões. |
| `airflow-webserver` | contínuo | Disponibiliza a interface web e o acompanhamento das DAGs. |
| `airflow-scheduler` | contínuo | Agenda e executa tarefas com `LocalExecutor`. |

O `LocalExecutor` permite paralelismo no próprio container do scheduler. Não há workers Celery separados nesta arquitetura.

## Dados de entrada

Coloque em `data-platform/airflow/data/csv`:

- `application_train.csv`;
- `previous_application.csv`;
- `bureau.csv`;
- `installments_payments.csv`.

O nome lógico de cada tabela e seu `chunk_size` são definidos em [`config_pipeline.json`](../DataPipeline/config_pipeline.json). A tarefa de ingestão valida se a fonte pertence ao escopo antes de carregá-la.

O mesmo diretório também pode conter as bases tratadas e a ABT geradas manualmente por [`export_data.py`](../DataPipeline/export_data.py), além do catálogo original de colunas. Esses arquivos adicionais apoiam a entrega e a análise, mas não são entradas da DAG nem saídas automáticas do Airflow.

## Volumes e caminhos no container

| Origem no projeto | Caminho no Airflow | Uso |
|---|---|---|
| `airflow/dags` | `/opt/airflow/dags` | Descoberta da DAG. |
| `infra` | `/opt/airflow/infra` | Fronteira de acesso ao banco, importada como `infra.db`. |
| `DataPipeline` | `/opt/airflow/DataPipeline` | Módulos de ingestão e transformação. |
| `Model` | `/opt/airflow/Model` | Treinamento, configuração e artefatos. |
| `airflow/data` | `/opt/airflow/data` | Arquivos CSV de entrada. |

A DAG adiciona os diretórios de pipeline e modelo ao caminho de importação para chamar os módulos compartilhados.

## Inicialização

Na pasta [`data-platform`](../README.md):

```bash
docker compose up -d --build postgres airflow-init
docker compose up -d airflow-webserver airflow-scheduler
```

O serviço `airflow-init`:

- migra o banco de metadados;
- cria o usuário administrativo;
- configura os pools usados pela DAG;
- prepara permissões para dados e artefatos.

## Acesso

- Interface: http://localhost:8080
- Usuário: `admin`
- Senha: `admin`

Na interface, habilite a DAG `pipeline_orchestration` e use o botão de execução manual.

## Acompanhamento

```bash
docker compose logs -f airflow-scheduler airflow-webserver
```

Para inspecionar as DAGs carregadas:

```bash
docker compose exec airflow-scheduler airflow dags list
```

## Configuração

- conexão de metadados: `AIRFLOW__DATABASE__SQL_ALCHEMY_CONN`;
- conexão com dados: `AIRFLOW_CONN_POSTGRES_DATA_DB`;
- tabelas e parâmetros: [`DataPipeline/config_pipeline.json`](../DataPipeline/config_pipeline.json);
- modelo e features: [`Model/config_model.json`](../Model/config_model.json).

### Conexões

- `AIRFLOW__DATABASE__SQL_ALCHEMY_CONN`: banco `airflow`, usado internamente pelo orquestrador;
- `AIRFLOW_CONN_POSTGRES_DATA_DB`: banco `data`, exposto às tarefas como conexão `postgres_data_db`.

Separar os dois bancos impede que tabelas analíticas sejam misturadas aos metadados operacionais do Airflow.

## Operação da DAG

### Antes de executar

1. Confirme que o PostgreSQL está saudável.
2. Confirme que os quatro CSVs estão em `airflow/data/csv`.
3. Confirme que `airflow-init` terminou com sucesso.
4. Verifique se a DAG aparece sem erro de importação.

```bash
docker compose ps
docker compose exec airflow-scheduler airflow dags list-import-errors
```

### Durante a execução

Na visualização Grid ou Graph, acompanhe as tarefas paralelas e consulte individualmente os logs. Cada módulo registra contagens de entrada e saída para facilitar a validação das transformações.

### Após a execução

Uma execução completa deve produzir:

- tabelas brutas e tratadas no banco `data`;
- tabela `application_abt`;
- artefato `Model/artifacts/lightgbm_abt.pkl`;
- arquivo `Model/artifacts/eval_model_metrics.json` atualizado;
- arquivo `Model/artifacts/feature_reference.json` atualizado.

Como evolução proposta, essa etapa deverá também gerar `monitoring_reference.json` e registrar no *model registry* uma nova versão candidata com o modelo, a configuração, as métricas e os baselines associados. O fluxo está descrito na [arquitetura de monitoramento do modelo em produção](../MLOps/MONITORING_ARCHITECTURE.md) e ainda não faz parte da implementação atual.

## Reexecução e recuperação

As etapas derivadas recriam suas tabelas de destino, permitindo reconstruir a ABT após mudanças de dados ou regras. Como o treinamento está no final da cadeia, ele não é executado quando uma dependência anterior falha. Após corrigir a causa, é possível disparar uma nova execução completa ou limpar tarefas específicas pela interface, considerando suas dependências.

Os CSVs e o volume `pgdata` persistem fora do ciclo de vida dos containers. `docker compose down` não remove o volume, salvo quando usado explicitamente com `--volumes`.

## Componentes relacionados

- [PostgreSQL](../postgres/README.md)
- [Pipeline de dados](../DataPipeline/README.md)
- [Modelo](../Model/README.md)
- [Monitoramento proposto](../MLOps/MONITORING_ARCHITECTURE.md)
- [Agente acelerador de revisão de crédito proposto](../MLOps/AGENT_ARCHITECTURE.md)
- [Jupyter](../jupyter/README.md)

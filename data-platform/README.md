# Plataforma de dados e MLOps para risco de crédito

Esta pasta implementa a arquitetura completa do projeto: ingestão e transformação dos dados, exploração analítica, treinamento do modelo e disponibilização do score por API e interface web.

O caso utiliza os dados da competição [Home Credit Default Risk](https://www.kaggle.com/competitions/home-credit-default-risk/overview) para construir um score de propensão à inadimplência. O score ordena clientes por risco e apoia a política de crédito; ele não substitui regras cadastrais, prevenção a fraude, capacidade de pagamento ou revisão humana.

## Contexto e objetivos da plataforma

Uma decisão de crédito precisa equilibrar dois erros com impactos distintos: aprovar um cliente que se tornará inadimplente e recusar um cliente que pagaria corretamente. Como a classe inadimplente é uma minoria expressiva da base, a acurácia isolada não é suficiente para avaliar a solução. A plataforma foi desenhada para transformar múltiplos históricos relacionais em um sinal de risco reproduzível, interpretável e consumível por uma aplicação.

Os objetivos arquiteturais são:

- **reprodutibilidade:** dados, transformações, features e hiperparâmetros possuem fontes de configuração identificáveis;
- **separação de responsabilidades:** pipeline, modelo, serviço de inferência e política de crédito evoluem em componentes distintos;
- **consistência entre treino e inferência:** API e treinamento utilizam a mesma ABT e o mesmo contrato de features;
- **processamento eficiente:** joins e agregações de grande volume são executados no PostgreSQL;
- **rastreabilidade acadêmica:** notebooks registram exploração, seleção, avaliação, interpretabilidade e critérios de negócio;
- **portabilidade local:** toda a infraestrutura necessária pode ser iniciada com Docker Compose;
- **decisão humana preservada:** o score apoia a política, sem automatizar sozinho a concessão de crédito.

## Escopo funcional

A plataforma cobre dois ciclos complementares:

1. **Ciclo de desenvolvimento e treinamento:** ingestão das fontes, preparação da ABT, análise, comparação de modelos, treinamento e persistência do artefato.
2. **Ciclo de inferência:** recuperação ou fornecimento das features, cálculo do score, aplicação da política demonstrativa e apresentação do resultado.

Monitoramento contínuo e agente acelerador de revisão de crédito são propostas de
evolução documentadas, respectivamente, em
[MONITORING_ARCHITECTURE.md](./MLOps/MONITORING_ARCHITECTURE.md) e
[AGENT_ARCHITECTURE.md](./MLOps/AGENT_ARCHITECTURE.md). Esses documentos distinguem a
implementação atual dos componentes propostos.

## Arquitetura

```text
Arquivos Home Credit
        │
        ▼
airflow/data/csv
        │
        ▼
┌──────────────────────────────────────────────────────────────┐
│ Airflow: pipeline_orchestration                              │
│ ingestão → limpeza → agregações → ABT → treinamento          │
└───────────────────────────────┬──────────────────────────────┘
                                │
                    ┌───────────▼───────────┐
                    │ PostgreSQL            │
                    │ raw, clean e ABT      │
                    └───────┬─────────┬─────┘
                            │         │
                    ┌───────▼───┐ ┌───▼────────────────┐
                    │ Jupyter   │ │ Modelo LightGBM    │
                    │ EDA       │ │ artefato + métricas│
                    │           │ │ + referências      │
                    └───────────┘ └─────────┬──────────┘
                                           │
                              ┌────────────▼────────────┐
                              │ FastAPI + política      │
                              └────────────┬────────────┘
                                           │
                                      ┌────▼─────┐
                                      │Streamlit │
                                      └──────────┘
```

### Decisões arquiteturais principais

- **ELT no PostgreSQL:** limpeza, agregações e joins são executados próximos aos dados.
- **Airflow como orquestrador:** a DAG coordena funções mantidas nas pastas de pipeline e modelo.
- **Configuração separada do código:** tabelas, features e hiperparâmetros ficam em arquivos JSON.
- **Bundle versionado de inferência:** modelo, referência estatística e contrato de transformação são publicados em conjunto para consumo pela API.
- **Modelo e política desacoplados:** o modelo gera score; a política converte faixas em recomendações.
- **Três formas de consumo:** predição por features fornecidas, por cliente recuperado da ABT, ou por registro bruto de um cliente novo, transformado pela mesma regra do pipeline.

## Topologia de execução

| Serviço do Compose | Imagem ou build | Dependência principal | Papel |
|---|---|---|---|
| `postgres` | `postgres:15` | volume `pgdata` | Bancos `airflow` e `data`. |
| `airflow-init` | `airflow/` | PostgreSQL saudável | Migração, usuário, pools e permissões. |
| `airflow-webserver` | `airflow/` | inicialização concluída | Interface e API do Airflow. |
| `airflow-scheduler` | `airflow/` | inicialização concluída | Agendamento e execução das tarefas. |
| `jupyter` | `jupyter/` | PostgreSQL | Ambiente de exploração e modelagem. |
| `credit-api` | `MLOps/Dockerfile.api` | PostgreSQL e artefato | Inferência e política de crédito. |
| `credit-frontend` | `MLOps/Dockerfile.frontend` | API | Interface demonstrativa. |

## Componentes

| Componente | Responsabilidade | Documentação |
|---|---|---|
| PostgreSQL | Persistência das fontes, tabelas tratadas e ABT | [postgres/README.md](./postgres/README.md) |
| infra | Fronteira de acesso ao banco e harness de teste, comuns aos componentes | [infra/README.md](./infra/README.md) |
| Airflow | Orquestração ponta a ponta do pipeline | [airflow/README.md](./airflow/README.md) |
| DataPipeline | Ingestão, limpeza, agregações e ABT | [DataPipeline/README.md](./DataPipeline/README.md) |
| Jupyter | Ambiente dos notebooks de análise e modelagem | [jupyter/README.md](./jupyter/README.md) |
| Model | Seleção, treinamento, avaliação e publicação dos artefatos | [Model/README.md](./Model/README.md) |
| MLOps | API, política de crédito, frontend, testes e propostas arquiteturais | [MLOps/README.md](./MLOps/README.md) |

## Testes automatizados

Cada componente documenta o comportamento coberto e o comando de sua suíte:
[infra](./infra/README.md), [DataPipeline](./DataPipeline/README.md#testes),
[Model](./Model/README.md#testes) e [MLOps](./MLOps/DEVELOPMENT.md).

## Fluxo de dados e modelo

1. Os CSVs são colocados em `airflow/data/csv`.
2. A DAG carrega as quatro fontes no banco `data`.
3. O pipeline cria tabelas tratadas e agregações por `sk_id_curr`.
4. A tabela `application_abt` consolida as features preditoras em uma linha por cliente.
5. O treinamento publica os artefatos versionados do modelo; o manifesto identifica o
   conjunto ativo para inferência.
6. A API acompanha o manifesto, carrega o bundle ativo e consulta a ABT quando recebe um
   identificador de cliente — ou, para um cliente novo, transforma o registro bruto pela
   mesma regra de sanitização e construção da ABT do pipeline, executada por `SELECT`
   sobre `VALUES`.
7. A política transforma o score em aprovação, revisão manual ou rejeição demonstrativa.
8. O Streamlit disponibiliza a submissão de um cliente novo, a recuperação editável e a
   consulta direta.

O fluxo operacional do treinamento está no [README do Airflow](./airflow/README.md) e
no [README do Model](./Model/README.md). Os cenários e contratos de inferência estão na
[documentação da API](./MLOps/API.md).

## Contratos entre componentes

| Contrato | Fonte de verdade | Consumidores |
|---|---|---|
| Fontes e tabelas do pipeline | `DataPipeline/config_pipeline.json` | DAG e módulos de transformação. |
| Features e hiperparâmetros | `Model/config_model.json` | treinamento, avaliação e validações. |
| Bundle ativo de inferência | `Model/artifacts/current_bundle.json` e `Model/artifacts/bundles/<bundle_id>/` | Serviços de inferência em `MLOps`. |
| Regra de transformação por registro | `DataPipeline/sql/application_sanitization_projection.sql` e `application_abt_record_projection.sql`, embutidos na imagem da API | `DataPipeline` (sobre a população) e `NewCustomerFeatureTransformationService` em `MLOps` (sobre um registro). |
| Schema HTTP | `MLOps/app/api/schemas.py` | API e frontend. |
| Limites da política | variáveis `CREDIT_*` | API e apresentação do resultado. |

Alterações nas features exigem atualização coordenada da ABT, configuração do modelo, novo treinamento e campos do frontend.

## Estrutura

```text
data-platform/
├── airflow/             # ambiente e DAG de orquestração
├── infra/               # fronteira de banco e harness de teste, compartilhados
├── DataPipeline/        # ingestão, transformações, ABT e EDA
├── jupyter/             # imagem do ambiente de notebooks
├── MLOps/               # aplicações, testes e propostas arquiteturais
├── Model/               # treinamento, avaliação e artefatos
├── postgres/            # inicialização do banco data
├── Dados/               # referência da entrega; CSVs redirecionados para airflow/data/csv
├── docker-compose.yml   # composição dos serviços
└── README.md
```

Os arquivos CSV foram redirecionados de `Dados/` para `airflow/data/csv`, conforme explicitado em [Dados da entrega](./Dados/README.md).

## Pré-requisitos

- Docker com suporte a Compose v2;
- aproximadamente 2 GB livres para os CSVs de origem e volumes locais;
- arquivos da competição Home Credit correspondentes às quatro fontes configuradas.

Para execução local fora de containers, também é necessário Python compatível com as dependências do componente utilizado.

## Configuração inicial

O Docker Compose lê automaticamente o arquivo `data-platform/.env`, localizado no
mesmo diretório de `docker-compose.yml`. Ele centraliza as credenciais e nomes dos
bancos, a administração e os pools do Airflow, o token do Jupyter, a localização e o
ciclo de atualização dos artefatos, os limites da política e as portas externas da API
e do frontend. A topologia, as imagens e as portas internas dos containers permanecem
definidas no `docker-compose.yml`.

Os valores vigentes estão no arquivo [`.env`](./.env). A finalidade das configurações
específicas da API está documentada em [MLOps/API.md](./MLOps/API.md), e a dos pools e
conexões do Airflow em [airflow/README.md](./airflow/README.md).

> **Importante:** os valores versionados no `.env` são apenas de demonstração,
> internos e sem valor em produção — por isso o arquivo é exposto propositalmente
> neste contexto acadêmico. Em um ambiente real, o `.env` **não** deve ser
> versionado e as credenciais devem ser substituídas por segredos próprios.

Para conferir a substituição das variáveis e visualizar a configuração final sem
iniciar os containers:

```bash
cd data-platform
docker compose config
```

O comando deve ser executado antes de `docker compose up`; ele também evidencia
variáveis obrigatórias ausentes ou vazias.

### Arquivos de origem

Baixe os arquivos na página de dados da competição
[Home Credit Default Risk](https://www.kaggle.com/competitions/home-credit-default-risk/data).
O Kaggle pode exigir autenticação e a aceitação das regras da competição antes de liberar o download.

Coloque estes arquivos em `data-platform/airflow/data/csv`:

```text
application_train.csv
previous_application.csv
bureau.csv
installments_payments.csv
```

Caso ainda não esteja nela, entre na pasta da plataforma antes de executar os demais comandos deste README:

```bash
cd data-platform
```

## Inicialização completa

```bash
docker compose up -d --build
```

O `airflow-init` termina após preparar o ambiente; os demais serviços permanecem ativos.

Para acompanhar o estado:

```bash
docker compose ps
docker compose logs -f airflow-scheduler credit-api credit-frontend
```

## Inicialização por camada

Infraestrutura e orquestração:

```bash
docker compose up -d --build postgres airflow-init
docker compose up -d airflow-webserver airflow-scheduler
```

Notebooks:

```bash
docker compose up -d --build jupyter
```

Serviço de predição:

```bash
docker compose up -d --build postgres credit-api credit-frontend
```

## URLs locais

| Componente | URL | Credencial |
|---|---|---|
| Airflow | http://localhost:8080 | valores `AIRFLOW_ADMIN_*` do `.env` |
| JupyterLab | http://localhost:8888 | `JUPYTER_TOKEN` |
| Swagger da API | http://localhost:8000/docs | — |
| Health check | http://localhost:8000/health | — |
| Streamlit | http://localhost:8501 | — |

### Prontidão da API e carregamento do modelo

O `credit-api` inicia e acompanha o conjunto de artefatos ativo. O comportamento de
carregamento, atualização e indisponibilidade está descrito na
[documentação da API](MLOps/API.md#carregamento-do-modelo).

## Execução do pipeline

1. Acesse o Airflow em http://localhost:8080.
2. Habilite a DAG `pipeline_orchestration`.
3. Inicie uma execução manual.
4. Acompanhe as tarefas até o treinamento e a persistência do modelo.

Detalhes das tarefas, pools e entradas estão no [README do Airflow](./airflow/README.md).

## Preparação manual dos CSVs de entrega

As quatro fontes baixadas e os CSVs exportados localmente ficam em
`data-platform/airflow/data/csv`. O procedimento manual de exportação das tabelas
materializadas está documentado em
[Exportação de tabelas para CSV](./DataPipeline/docs/exportacao.md).

## Notebooks oficiais

| Notebook | Finalidade |
|---|---|
| [`DataPipeline/exp_analysis_raw.ipynb`](./DataPipeline/exp_analysis_raw.ipynb) | Exploração e diagnóstico das fontes brutas. |
| [`DataPipeline/exp_analysis_abt.ipynb`](./DataPipeline/exp_analysis_abt.ipynb) | Validação e exploração da ABT tratada. |
| [`Model/validacao_modelos.ipynb`](./Model/validacao_modelos.ipynb) | Comparação, tuning e controle de overfitting. |
| [`Model/evaluation.ipynb`](./Model/evaluation.ipynb) | Avaliação final, threshold, explicabilidade e fairness. |

## Parada dos serviços

```bash
docker compose stop
```

Para remover apenas os containers e a rede, preservando o volume do PostgreSQL:

```bash
docker compose down
```

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

Monitoramento contínuo e agente acelerador de revisão de crédito estão detalhados como propostas futuras e não fazem parte da implementação atual. As propostas de [monitoramento do modelo em produção](./MLOps/MONITORING_ARCHITECTURE.md) e do [agente acelerador de revisão de crédito](./MLOps/AGENT_ARCHITECTURE.md) distinguem os pré-requisitos já disponíveis dos componentes ainda não implementados. Atualmente, os artefatos ficam em um único diretório persistente, compartilhado entre os containers por volumes do tipo *bind mount*, e são sobrescritos a cada treinamento. A proposta de monitoramento introduz um *model registry*, com MLflow como implementação inicial sugerida, para preservar versões, associar seus baselines e controlar promoção e rollback. Autenticação e implantação produtiva são apenas citadas como possíveis evoluções adicionais, sem definição arquitetural neste projeto.

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
- **Artefato único de inferência:** o LightGBM e seus metadados são persistidos para consumo pela API.
- **Modelo e política desacoplados:** o modelo gera score; a política converte faixas em recomendações.
- **Duas formas de consumo:** predição por features fornecidas ou por cliente recuperado da ABT.

## Camadas lógicas

| Camada | Artefatos principais | Papel na solução |
|---|---|---|
| Origem | CSVs do Home Credit | Dados cadastrais e históricos usados pelo estudo. |
| Persistência bruta | `application_train`, `previous_application`, `bureau`, `installments_payments` | Preserva as fontes carregadas antes das regras analíticas. |
| Tratamento | tabelas com sufixo `_clean` | Padroniza categorias, ausências, anomalias e valores financeiros. |
| Agregação | tabelas temporárias por `sk_id_curr` | Converte relações um-para-muitos em features por cliente. |
| Analítica | `application_abt` | Contrato tabular compartilhado entre análise, treinamento e inferência. |
| Modelagem | `config_model.json`, notebooks, `train.py` | Seleciona, avalia e treina o LightGBM. |
| Artefatos | `lightgbm_abt.pkl`, `eval_model_metrics.json`, `feature_reference.json` | Transportam o modelo e seus metadados, as métricas da avaliação e as referências estatísticas. |
| Serving | FastAPI e política de crédito | Expõe o score e converte faixas em recomendações. |
| Experiência | Streamlit | Permite demonstrar preenchimento, recuperação e consulta de clientes. |

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
| Model | Seleção, treinamento, avaliação e inferência local | [Model/README.md](./Model/README.md) |
| MLOps | API, política de crédito, frontend, testes e propostas arquiteturais | [MLOps/README.md](./MLOps/README.md) |

## Testes automatizados

Cada componente tem sua suíte, e elas fixam o comportamento esperado — não são verificação
acessória. O que cada uma cobre:

| Suíte | O que fixa | Como executa |
|---|---|---|
| [infra](./infra/README.md) | A fronteira de banco: montagem da string de conexão a partir do ambiente e a exceção do host declarado, a falha nomeada quando falta variável obrigatória, a abertura de conexão e do Engine, e a garantia de que o papel de teste não alcança o banco de produção. | Contra o banco de testes dedicado, com o papel de menor privilégio. |
| [DataPipeline](./DataPipeline/README.md#testes) | Os contratos funcionais de cada etapa do pipeline — ingestão em blocos, índices, regras de sanitização, agregações por cliente, construção da ABT e exportação. | Contra o mesmo banco dedicado, recebendo a conexão pela fronteira que o `infra` oferece e a task da DAG usa. |
| [Model](./Model/README.md#testes) | A leitura da ABT com conversão das categóricas, a composição do treinamento, o cálculo do baseline populacional e a recusa de publicar artefatos que não pertençam ao mesmo treino. | Sem PostgreSQL e sem artefato: as conexões chegam injetadas. |
| [MLOps](./MLOps/DEVELOPMENT.md) | Os contratos e erros HTTP da API, a carga do modelo em segundo plano, a política de crédito, a explicabilidade e a inicialização do frontend. | Offline, com fakes injetados por composição. |

Regra comum às quatro: nada de mocks ou interceptação de chamadas — colaboradores entram
por fixtures e fakes explícitos, pelas mesmas fronteiras que a produção usa. As suítes de
`infra` e `DataPipeline` dividem o mesmo banco de teste, então rodam em sequência, não em
paralelo; `Model` e `MLOps` não tocam o banco.

## Fluxo de dados e modelo

1. Os CSVs são colocados em `airflow/data/csv`.
2. A DAG carrega as quatro fontes no banco `data`.
3. O pipeline cria tabelas tratadas e agregações por `sk_id_curr`.
4. A tabela `application_abt` consolida as features preditoras em uma linha por cliente.
5. O treinamento selecionado gera `Model/artifacts/lightgbm_abt.pkl`, `eval_model_metrics.json` e `feature_reference.json`.
6. A API carrega o artefato e consulta a ABT quando recebe um identificador de cliente.
7. A política transforma o score em aprovação, revisão manual ou rejeição demonstrativa.
8. O Streamlit disponibiliza formulário, recuperação editável e consulta direta.

## Cenário de treinamento ponta a ponta

```text
Analista disponibiliza CSVs
  → Airflow valida o escopo configurado
  → cada fonte é carregada em chunks
  → índices apoiam limpeza e joins
  → fontes são padronizadas em tabelas clean
  → históricos são agregados por cliente
  → ABT é materializada
  → LightGBM é treinado e avaliado em holdout
  → modelo final é retreinado com toda a ABT
  → artefato, métricas e referências estatísticas são persistidos
```

O pipeline pode ser reexecutado para reconstruir as tabelas derivadas e atualizar o artefato. A seleção de algoritmo e hiperparâmetros permanece documentada nos notebooks, enquanto a DAG executa a configuração já escolhida.

## Cenários de inferência

### Features fornecidas

O consumidor envia as features esperadas (listadas por `GET /model/features`) para `POST /predict/features`. A API alinha tipos e ordem, calcula o score e aplica a política configurada.

### Cliente armazenado

O consumidor informa `sk_id_curr`. O serviço lê `application_abt`, remove identificador e target e envia as mesmas features ao modelo. Há duas modalidades:

- recuperar as features para edição com `GET /customers/{customer_id}/features`;
- calcular diretamente com `POST /predict/customer/{customer_id}`.

Essa abordagem reduz divergência entre engenharia de atributos offline e online, pois a inferência por cliente consome a ABT já materializada.

## Contratos entre componentes

| Contrato | Fonte de verdade | Consumidores |
|---|---|---|
| Fontes e tabelas do pipeline | `DataPipeline/config_pipeline.json` | DAG e módulos de transformação. |
| Features e hiperparâmetros | `Model/config_model.json` | treinamento, avaliação e validações. |
| Artefato de inferência | `Model/artifacts/lightgbm_abt.pkl` | script local e API. |
| Referências estatísticas | `Model/artifacts/feature_reference.json` | API e consumidores de explicações. |
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
mesmo diretório de `docker-compose.yml`. **Todas** as variáveis e credenciais dos
serviços foram externalizadas para esse arquivo — o `docker-compose.yml` não
contém mais valores fixos, apenas referências `${VARIÁVEL}` interpoladas a partir
do `.env`. Por ser um repositório acadêmico/público, o `.env` já está versionado
com valores de demonstração; basta revisá-lo caso queira trocar portas, senhas ou
o token do Jupyter:

```dotenv
# Postgres (credenciais e nomes dos bancos)
POSTGRES_USER=airflow
POSTGRES_PASSWORD=airflow
POSTGRES_DB=airflow
POSTGRES_DATA_DB=data
POSTGRES_HOST=postgres
POSTGRES_PORT=5432

# Airflow (segurança e usuário admin)
AIRFLOW_SECRET_KEY=tcc_fia_labdata_engenharia_dados
AIRFLOW_FERNET_KEY=7777777777777777777777777777777777777777777=
AIRFLOW_ADMIN_USERNAME=admin
AIRFLOW_ADMIN_PASSWORD=admin
AIRFLOW_ADMIN_FIRSTNAME=Admin
AIRFLOW_ADMIN_LASTNAME=User
AIRFLOW_ADMIN_ROLE=Admin
AIRFLOW_ADMIN_EMAIL=admin@example.com
POOL_INGESTAO_SIZE=2
POOL_SANITIZATION_SIZE=2
POOL_AGGREGATION_SIZE=2

# Jupyter
JUPYTER_TOKEN=analytics

# Credit API
MODEL_ARTIFACTS_DIR=/app/Model/artifacts
MODEL_BUNDLE_REFRESH_SECONDS=5
CREDIT_POLICY_VERSION=demo-v1
CREDIT_APPROVE_MAX_SCORE=0.50
CREDIT_MANUAL_REVIEW_MAX_SCORE=0.60
```

### Variáveis utilizadas pela composição

| Variável | Obrigatoriedade | Finalidade | Padrão |
|---|---|---|---:|
| `POSTGRES_USER` / `POSTGRES_PASSWORD` | Obrigatórias | Credenciais do PostgreSQL, reutilizadas nas connection strings do Airflow e da API. | Sem padrão |
| `POSTGRES_DB` | Obrigatória | Banco de metadados do Airflow. | Sem padrão |
| `POSTGRES_DATA_DB` | Obrigatória | Banco analítico (fontes, tabelas tratadas e ABT). | Sem padrão |
| `POSTGRES_HOST` / `POSTGRES_PORT` | Obrigatórias | Host e porta internos usados para montar as connection strings. | Sem padrão |
| `AIRFLOW_SECRET_KEY` | Obrigatória | Chave do webserver, compartilhada entre os serviços do Airflow. | Sem padrão |
| `AIRFLOW_FERNET_KEY` | Obrigatória | Chave de criptografia de conexões e variáveis do Airflow. | Sem padrão |
| `AIRFLOW_ADMIN_*` | Obrigatórias | Dados do usuário admin criado na inicialização (`USERNAME`, `PASSWORD`, `FIRSTNAME`, `LASTNAME`, `ROLE`, `EMAIL`). | Sem padrão |
| `POOL_INGESTAO_SIZE` / `POOL_SANITIZATION_SIZE` / `POOL_AGGREGATION_SIZE` | Obrigatórias | Tamanho dos pools do Airflow que limitam o paralelismo por etapa da DAG. | Sem padrão |
| `JUPYTER_TOKEN` | Obrigatória | Token usado para autenticar o acesso ao JupyterLab. | Sem padrão |
| `MODEL_ARTIFACTS_DIR` | Obrigatória | Diretório dentro do container da API onde o conjunto de artefatos publicado está visível — o manifesto (`current_bundle.json`) e o diretório `bundles/`. | Sem padrão |
| `MODEL_BUNDLE_REFRESH_SECONDS` | Obrigatória | Intervalo entre ciclos de verificação do manifesto. Enquanto nenhum bundle válido estiver ativo, a API permanece ativa e `/health` responde `503`. | Sem padrão |
| `CREDIT_POLICY_VERSION` | Obrigatória | Versão declarada da política de crédito, retornada nas respostas da API. | Sem padrão |
| `CREDIT_APPROVE_MAX_SCORE` | Obrigatória | Limite superior da aprovação automática. Scores abaixo desse valor recebem recomendação de aprovação. | Sem padrão |
| `CREDIT_MANUAL_REVIEW_MAX_SCORE` | Obrigatória | Limite superior da análise manual. Scores a partir desse valor recebem recomendação de rejeição. | Sem padrão |
| `CREDIT_API_PORT` | Opcional | Porta do host pela qual a API de crédito será acessada. | `8000` |
| `CREDIT_FRONTEND_PORT` | Opcional | Porta do host pela qual o frontend Streamlit será acessado. | `8501` |

Os limites da política devem respeitar a relação
`0 <= CREDIT_APPROVE_MAX_SCORE < CREDIT_MANUAL_REVIEW_MAX_SCORE <= 1`. Com os
valores do exemplo, scores abaixo de `0.50` são aprovados automaticamente, scores
entre `0.50` e `0.60` seguem para análise humana e scores a partir de `0.60`
recebem recomendação de rejeição.

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
| Airflow | http://localhost:8080 | `admin` / `admin` |
| JupyterLab | http://localhost:8888 | `JUPYTER_TOKEN` |
| Swagger da API | http://localhost:8000/docs | — |
| Health check | http://localhost:8000/health | — |
| Streamlit | http://localhost:8501 | — |

### Prontidão da API e carregamento do modelo

O processo do `credit-api` pode iniciar mesmo que nenhum conjunto de artefatos
tenha sido publicado ainda em `MODEL_ARTIFACTS_DIR`. A API verifica o manifesto
(`current_bundle.json`) a cada `MODEL_BUNDLE_REFRESH_SECONDS` e, em caso de
falha, registra o erro e mantém o último bundle válido — ou nenhum, se ainda
não houver um.

Enquanto nenhum bundle válido estiver disponível, `GET /health` responde HTTP
`503` com uma mensagem de indisponibilidade e o último erro de carregamento. Os
endpoints que dependem do modelo também respondem `503`. Assim que uma tentativa
é bem-sucedida, `/health` passa a responder HTTP `200` com `model_loaded: true`,
sem necessidade de reiniciar o container.

Para acompanhar as tentativas:

```bash
docker compose logs -f credit-api
```

O contrato completo e exemplos das respostas estão descritos na
[documentação da API](MLOps/API.md#carregamento-do-modelo).

## Execução do pipeline

1. Acesse o Airflow em http://localhost:8080.
2. Habilite a DAG `pipeline_orchestration`.
3. Inicie uma execução manual.
4. Acompanhe as tarefas até o treinamento e a persistência do modelo.

Detalhes das tarefas, pools e entradas estão no [README do Airflow](./airflow/README.md).

## Preparação manual dos CSVs de entrega

O componente `DataPipeline` inclui o utilitário [`export_data.py`](./DataPipeline/export_data.py), executado manualmente para preparar os CSVs da entrega acadêmica. Ele exporta tabelas já materializadas no PostgreSQL por meio de `COPY TO STDOUT`, sem carregar a tabela completa na memória.

O utilitário não integra a DAG e não altera o fluxo operacional da plataforma. Sua execução ocorre somente depois que o pipeline tiver criado as tabelas que serão entregues.

Os arquivos exportados já foram adicionados a `data-platform/airflow/data/csv`, a mesma pasta que contém os arquivos brutos de entrada. O diretório passa a concentrar as quatro fontes originais, suas quatro versões tratadas e `application_abt.csv`, com uma linha por cliente.

As dependências, os pré-requisitos, o comando de execução e a forma de selecionar a tabela de origem estão documentados na seção [Exportação de tabelas para CSV](./DataPipeline/README.md#exportação-de-tabelas-para-csv).

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

## Próximos passos

- calibrar o score quando houver necessidade de interpretação probabilística;
- validar thresholds com custos reais do negócio;
- implementar a proposta de [monitoramento contínuo de dados, modelo e serviço](./MLOps/MONITORING_ARCHITECTURE.md), incluindo o *model registry* e o versionamento dos artefatos;
- implementar a proposta do [agente acelerador de revisão de crédito](./MLOps/AGENT_ARCHITECTURE.md);
- formalizar versionamento, rastreabilidade e auditoria das decisões;
- automatizar testes, build e implantação.

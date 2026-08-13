# Projeto Final FIA — risco de crédito com IA

Projeto final da pós-graduação em Engenharia de Dados da FIA Labdata. A solução implementa o ciclo de uma aplicação de Machine Learning para risco de crédito: ingestão, qualidade e transformação dos dados, construção da ABT, seleção e avaliação do modelo, orquestração, API e interface web.

Os dados são baseados na competição [Home Credit Default Risk](https://www.kaggle.com/competitions/home-credit-default-risk/overview).

## O desafio

Decidir crédito envolve dois custos opostos: a perda causada por clientes inadimplentes e a receita perdida quando bons clientes são recusados. Na base utilizada, a classe inadimplente é uma **minoria expressiva** — um desbalanceamento forte que torna inadequado avaliar a solução apenas por acurácia e exige um fluxo que conecte engenharia de dados, modelagem, interpretabilidade e política de decisão.

O projeto foi construído como uma solução integrada, e não apenas como um experimento de notebook. Quatro fontes históricas são carregadas e transformadas, relações um-para-muitos são consolidadas em uma ABT, diferentes algoritmos são comparados e o modelo selecionado é disponibilizado por serviço e interface web.

## Objetivo de negócio

Produzir um score de propensão à inadimplência que ajude a priorizar clientes para aprovação, revisão manual ou rejeição. O modelo fornece um sinal de ordenação de risco; a decisão final permanece sujeita à política de crédito e à análise humana.

## O que foi entregue

- pipeline ELT em PostgreSQL para quatro fontes do Home Credit;
- ABT com uma linha por cliente, consolidando cadastro, bureau, propostas e parcelas;
- EDA das fontes brutas e da base tratada;
- comparação entre Regressão Logística, Random Forest, XGBoost e LightGBM;
- controle de overfitting com validação cruzada e teste externo;
- LightGBM treinado com categóricas nativas e artefato reproduzível;
- avaliação com AUC, Gini, KS, Average Precision, Brier, decis e thresholds;
- interpretabilidade por permutação e SHAP;
- análise de fairness e proposta de monitoramento;
- proposta do agente acelerador de revisão de crédito para apoiar a revisão humana;
- orquestração ponta a ponta com Airflow;
- API FastAPI, política de crédito configurável e frontend Streamlit;
- ambientes Docker para banco, Airflow, Jupyter, API e frontend.

## Visão da solução

![Diagrama de arquitetura da plataforma: ingestão dos CSVs do Home Credit no PostgreSQL, orquestração e engenharia de dados com Airflow, treinamento e artefatos do modelo (LightGBM), camada de serviço com FastAPI e Streamlit e infraestrutura em Docker Compose](./arquitetura-plataforma.png)

*Figura 1 — Arquitetura ponta a ponta, dividida em cinco blocos: (1) origem, ingestão e armazenamento; (2) orquestração e engenharia de dados; (3) treinamento e artefatos do modelo; (4) deploy e camada de serviço; (5) infraestrutura e containers.*

Em resumo, o fluxo principal de dados percorre:

```text
Home Credit CSVs
  → PostgreSQL
  → Airflow + pipeline ELT
  → ABT por cliente
  → LightGBM
  → FastAPI + política de crédito
  → Streamlit
```

A implementação completa e o desenho arquitetural estão documentados em [data-platform/README.md](./data-platform/README.md).

### Propostas arquiteturais

Os dois entregáveis propostos para evolução da solução estão documentados separadamente:

- [monitoramento do modelo em produção](./data-platform/MLOps/MONITORING_ARCHITECTURE.md), abrangendo falhas operacionais, versionamento por *model registry*, drift, maturação dos desfechos, performance, calibração e fairness;
- [agente acelerador de revisão de crédito](./data-platform/MLOps/AGENT_ARCHITECTURE.md), que produz de forma assíncrona um relatório de apoio ao analista sem substituir a decisão humana.

Esses componentes permanecem propostas arquiteturais. Os documentos distinguem explicitamente seus pré-requisitos já implementados das funcionalidades futuras.

## Resumo da metodologia utilizada

O projeto segue o método **CRISP-DM**, com ênfase na *justificativa* de cada escolha:

1. **Entendimento dos dados (EDA em duas etapas):** diagnóstico das fontes brutas para decidir tratamentos e, depois do pipeline, validação da base limpa. A força de cada variável é **medida** (Pearson, Cramér's V, WOE/IV) e a redundância é checada por multicolinearidade — não presumida.
2. **Preparação:** limpeza e engenharia por **regras** (imputação por mediana em variáveis assimétricas, winsorização de outliers, isolamento de anomalias em flags, condensação de categorias raras) e consolidação das relações um-para-muitos em uma **ABT** de uma linha por cliente, com **flags de presença** que separam "sem histórico" de "histórico observado".
3. **Modelagem:** comparação **curada** de quatro famílias (linear regularizado, *bagging*, dois *boostings*) por busca de hiperparâmetros com validação cruzada estratificada, medindo **treino × CV × conjunto externo** e aplicando um filtro de overfitting. A etapa comparativa adota uma representação comum com *one-hot encoding*; após a seleção, o LightGBM oficial utiliza categóricas nativas e é retreinado com toda a ABT.
4. **Avaliação:** medição da configuração oficial em uma partição não usada no seu ajuste, com métricas de crédito (AUC/KS/Gini/PR-AUC), leitura de negócio por **decis** e **threshold como decisão econômica** (valor esperado, com análise de sensibilidade), **interpretabilidade** (permutação + SHAP) e **governança/fairness** com plano de monitoramento.
5. **Implantação:** persistência do artefato reprodutível e disponibilização por API e interface web, com a **política de crédito separada do modelo**.

O score retornado pelo modelo deve ser tratado como uma **pontuação de ordenação de risco, não como probabilidade calibrada**.

## Por que confiar na solução

Em vez de fixar números que mudam a cada re-treino, a confiança na solução se apoia em **método**:

- **separação entre ajuste e medição**, somada à consistência entre treino, validação cruzada e conjunto externo, como evidência de estabilidade e generalização;
- **métricas de ordenação** adequadas ao desbalanceamento (AUC/Gini/KS/PR-AUC), em vez de acurácia;
- **coerência EDA → poder preditivo → modelo** (permutação/SHAP) como argumento contra vazamento;
- reconhecimento explícito de que o score é **ranking de risco, não probabilidade calibrada** (a calibração fica registrada como próximo passo);
- **governança** por subgrupo e um **plano de monitoramento** (desempenho, estabilidade/PSI, calibração, fairness).

Os **valores** de cada execução ficam nos notebooks e em `Model/artifacts/eval_model_metrics.json`, no contexto da execução que os produziu.

## Implementações críticas

### Engenharia de dados

Os CSVs são lidos em chunks e carregados por `COPY` no PostgreSQL. Limpeza, percentis, agregações e joins são executados em SQL. Antes do join final, bureau, propostas e parcelas são reduzidos a uma linha por cliente, evitando duplicação da aplicação principal.

### Orquestração

A DAG `pipeline_orchestration` usa dynamic task mapping para as quatro fontes, paraleliza limpezas e agregações com pools e só libera o treinamento depois da materialização da ABT.

### Modelagem

O LightGBM foi selecionado após comparação de quatro famílias, busca de hiperparâmetros e filtro de overfitting. As categorias são tratadas nativamente e o modelo final é retreinado com toda a ABT depois da avaliação da configuração.

### Inferência e decisão

A API restaura a ordem, os tipos e as categorias salvas no artefato antes de calcular o score. A política de crédito é separada do modelo e converte faixas configuráveis em aprovação, revisão manual ou rejeição demonstrativa.

Detalhes e justificativas estão nos READMEs de cada componente.

## Estrutura e documentação

| Pasta | Finalidade | README |
|---|---|---|
| `data-platform/` | Arquitetura e operação de toda a plataforma | [data-platform](./data-platform/README.md) |
| `data-platform/airflow/` | Orquestração do pipeline e treinamento | [Airflow](./data-platform/airflow/README.md) |
| `data-platform/DataPipeline/` | Ingestão, limpeza, ABT e EDA | [DataPipeline](./data-platform/DataPipeline/README.md) |
| `data-platform/jupyter/` | Ambiente de notebooks | [Jupyter](./data-platform/jupyter/README.md) |
| `data-platform/Model/` | Seleção, treinamento e avaliação do modelo | [Model](./data-platform/Model/README.md) |
| `data-platform/MLOps/` | FastAPI, Streamlit, política, testes e propostas arquiteturais | [MLOps](./data-platform/MLOps/README.md) |
| `data-platform/postgres/` | Inicialização e persistência relacional | [PostgreSQL](./data-platform/postgres/README.md) |

## Testes automatizados

Cada componente possui sua própria suíte, e elas fixam o comportamento esperado — não são
verificação acessória. O que cada uma cobre:

| Suíte | O que fixa | Como executa |
|---|---|---|
| [DataPipeline](./data-platform/DataPipeline/README.md#testes) | Os contratos funcionais de cada etapa do pipeline — ingestão em blocos, índices, regras de sanitização, agregações por cliente, construção da ABT e exportação — mais a fronteira de conexão com o banco. | Contra um PostgreSQL **de testes dedicado**, isolado do banco de produção por um papel de menor privilégio. Sem mocks: as funções recebem a conexão pela mesma fronteira que a tarefa do Airflow usa. |
| [Model](./data-platform/Model/README.md#testes) | A leitura da ABT com a conversão das categóricas, a composição do treinamento, o cálculo do baseline populacional e a recusa de publicar um conjunto de artefatos que não pertença ao mesmo treino. | Sem PostgreSQL e sem artefato treinado: as conexões chegam injetadas. |
| [MLOps](./data-platform/MLOps/DEVELOPMENT.md) | Os contratos e erros HTTP da API, a carga do modelo em segundo plano, a política de crédito, a explicabilidade e a inicialização do frontend. | Offline, com fakes injetados por composição; os casos que exigem o artefato treinado são pulados quando ele não existe. |

A regra que atravessa as três: nada de mocks ou interceptação de chamadas — colaboradores
entram por fixtures e fakes explícitos, pelas mesmas fronteiras que a produção usa.

## Execução rápida

1. Baixe os quatro arquivos indicados em [Arquivos de origem](./data-platform/README.md#arquivos-de-origem) e coloque-os em `data-platform/airflow/data/csv`.
2. Revise os valores das variáveis de ambiente definidas em `data-platform/.env`.
3. Inicie a plataforma:

```bash
cd data-platform
docker compose up -d --build
```

4. Acesse o Airflow usando as credenciais definidas em `data-platform/.env`.
5. Habilite e execute manualmente a DAG `pipeline_orchestration`.
6. Verifique que o pipeline foi concluído com sucesso incluindo a tarefa de treinamento do modelo
7. Acesse a API ou o frontend usando os links informados abaixo.

## Acessos locais

| Serviço | URL |
|---|---|
| Airflow | http://localhost:8080 |
| JupyterLab | http://localhost:8888 |
| Swagger da API | http://localhost:8000/docs |
| Streamlit | http://localhost:8501 |

## Notebooks principais

- [`exp_analysis_raw.ipynb`](./data-platform/DataPipeline/exp_analysis_raw.ipynb): análise das fontes brutas.
- [`exp_analysis_abt.ipynb`](./data-platform/DataPipeline/exp_analysis_abt.ipynb): análise da ABT tratada.
- [`validacao_modelos.ipynb`](./data-platform/Model/validacao_modelos.ipynb): comparação e seleção do modelo.
- [`evaluation.ipynb`](./data-platform/Model/evaluation.ipynb): avaliação, threshold, explicabilidade e fairness.

## Treinamento local

Com PostgreSQL e ABT disponíveis:

```bash
cd data-platform
python3 -m venv Model/.venv
Model/.venv/bin/python -m pip install -r Model/requirements.txt
set -a
source .env
set +a
PYTHONPATH=DataPipeline Model/.venv/bin/python Model/train.py
```

Para instruções detalhadas, consulte [Model/README.md](./data-platform/Model/README.md).

## Serviço de predição

```bash
cd data-platform
docker compose up -d --build postgres credit-api credit-frontend
```

Consulte a visão geral e o índice da documentação em [MLOps/README.md](./data-platform/MLOps/README.md). Contratos e endpoints estão em [MLOps/API.md](./data-platform/MLOps/API.md), e os testes estão em [MLOps/DEVELOPMENT.md](./data-platform/MLOps/DEVELOPMENT.md).

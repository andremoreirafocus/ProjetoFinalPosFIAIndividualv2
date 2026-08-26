# Projeto Final FIA — risco de crédito com IA

Projeto final da pós-graduação em Engenharia de Dados da FIA Labdata. A solução implementa o ciclo de uma aplicação de Machine Learning para risco de crédito: ingestão, qualidade e transformação dos dados, construção da ABT, seleção e avaliação do modelo, orquestração, API e interface web.

Os dados são baseados na competição [Home Credit Default Risk](https://www.kaggle.com/competitions/home-credit-default-risk/overview).

## O desafio

Decidir crédito envolve dois custos opostos: a perda causada por clientes inadimplentes e a receita perdida quando bons clientes são recusados. Na base utilizada, a classe inadimplente é uma **minoria expressiva** — um desbalanceamento forte que torna inadequado avaliar a solução apenas por acurácia e exige um fluxo que conecte engenharia de dados, modelagem, interpretabilidade e política de decisão.

O projeto foi construído como uma solução integrada, e não apenas como um experimento de notebook. Quatro fontes históricas são carregadas e transformadas, relações um-para-muitos são consolidadas em uma ABT, diferentes algoritmos são comparados e o modelo selecionado é disponibilizado por serviço e interface web.

## Objetivo de negócio

Produzir um score de propensão à inadimplência que ajude a priorizar clientes para aprovação, revisão manual ou rejeição. O modelo fornece um sinal de ordenação de risco; a decisão final permanece sujeita à política de crédito e à análise humana.

## O que foi entregue

- pipeline ELT orquestrado pelo Airflow, da ingestão à construção da ABT;
- notebooks de exploração, seleção e avaliação do modelo;
- treinamento e publicação versionada do modelo de machine learning escolhido após a avaliação;
- API FastAPI com política de crédito separada do modelo;
- frontend Streamlit para demonstrar as jornadas de inferência;
- ambiente local integrado por Docker Compose;
- propostas arquiteturais de monitoramento e apoio à revisão humana.

## Visão da solução

![Diagrama de arquitetura da plataforma: ingestão dos CSVs do Home Credit no PostgreSQL, orquestração e engenharia de dados com Airflow, treinamento e publicação do bundle versionado do modelo de Machine Learning, inferência por features, cliente na ABT ou registro bruto com FastAPI e Streamlit e infraestrutura em Docker Compose](./arquitetura-plataforma-v9.png)

*Figura 1 — Arquitetura ponta a ponta da solução implementada.*

O diagrama conecta dois ciclos. No desenvolvimento, o Airflow conduz os dados das
fontes até a ABT, os notebooks apoiam a exploração e as decisões de modelagem, e o
treinamento publica um bundle versionado que reúne o modelo de Machine Learning, o
contrato de transformação e as referências estatísticas. O manifesto
`current_bundle.json` identifica o conjunto que a FastAPI deve ativar. Na inferência,
a API recebe features prontas, recupera um cliente da ABT ou transforma um registro
bruto pelas mesmas regras do pipeline; então prepara a entrada e calcula o score. A
política transforma o score em recomendação e, nos casos de revisão manual, a API
produz a explicação. O Streamlit faz a interface com o analista e o Docker Compose
integra a execução local dos serviços.

A implementação completa e o desenho arquitetural estão documentados em [data-platform/README.md](./data-platform/README.md).

### Propostas arquiteturais

Os dois entregáveis propostos para evolução da solução estão documentados separadamente:

- [monitoramento do modelo em produção](./data-platform/MLOps/MONITORING_ARCHITECTURE.md), abrangendo falhas operacionais, versionamento por *model registry*, drift, maturação dos desfechos, performance, calibração e fairness;
- [agente acelerador de revisão de crédito](./data-platform/MLOps/AGENT_ARCHITECTURE.md), que produz de forma assíncrona um relatório de apoio ao analista sem substituir a decisão humana.

Esses componentes permanecem propostas arquiteturais. Os documentos distinguem explicitamente seus pré-requisitos já implementados das funcionalidades futuras.

## Resumo da metodologia utilizada

O projeto segue o **CRISP-DM**: entendimento do problema e dos dados, preparação da
ABT, comparação e seleção do modelo, avaliação e disponibilização da solução. As
decisões analíticas ficam registradas nos notebooks; os componentes operacionais
implementam o fluxo selecionado.

O score retornado pelo modelo deve ser tratado como uma **pontuação de ordenação de risco, não como probabilidade calibrada**.

Os métodos, métricas e contratos vigentes estão documentados nos READMEs de
`DataPipeline`, `Model` e `MLOps`.

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

As suítes e seus comandos são documentados pelos componentes responsáveis:
[infra](./data-platform/infra/README.md),
[DataPipeline](./data-platform/DataPipeline/README.md#testes),
[Model](./data-platform/Model/README.md#testes) e
[MLOps](./data-platform/MLOps/DEVELOPMENT.md).

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

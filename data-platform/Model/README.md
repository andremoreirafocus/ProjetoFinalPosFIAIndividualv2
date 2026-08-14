# Model

Esta pasta reúne a seleção, o treinamento, a avaliação e a inferência local do modelo de risco de crédito.

## Contexto do problema de modelagem

O target identifica clientes inadimplentes (`target = 1`) e a base é **fortemente desbalanceada**: a classe positiva é uma minoria expressiva. Um classificador pode alcançar alta acurácia prevendo majoritariamente bons pagadores e ainda assim não servir à política de crédito — **a acurácia é enganosa nesse cenário**.

Por isso o modelo não é avaliado por acerto, e sim por **capacidade de ordenar risco**: ROC AUC, Gini, KS e Average Precision. A saída é um **score de propensão à inadimplência**, adequado a ranking, decis e políticas de corte, e **não** uma probabilidade calibrada.

O modelo oficial é um **LightGBM Classifier** com categóricas nativas e `class_weight="balanced"`. A justificativa da escolha, o limite de interpretação do score e o método de avaliação estão em [`docs/modelagem.md`](./docs/modelagem.md).

## Responsabilidade

- ler a ABT `application_abt` e aplicar o contrato de features da configuração;
- avaliar a configuração oficial num holdout estratificado;
- ajustar o modelo final com toda a ABT;
- calcular o baseline populacional e a referência TreeSHAP global;
- publicar o conjunto versionado de artefatos consumido pela API;
- oferecer inferência local para inspeção de um cliente.

## Fluxo

```text
application_abt
  → holdout estratificado 80/20
  → modelo de avaliação + métricas de crédito
  → modelo final com 100% da ABT
  → baseline populacional e TreeSHAP global
  → lightgbm_abt.pkl + eval_model_metrics.json + feature_reference.json
  → API de inferência
```

O treinamento oficial é a última tarefa da DAG `pipeline_orchestration`, descrita no [README do Airflow](../airflow/README.md).

## Documentação detalhada

A referência aprofundada de cada área fica em documentos dedicados nesta pasta:

- [`docs/modelagem.md`](./docs/modelagem.md) — objetivo e métricas da modelagem, por que LightGBM, limite de interpretação do score, dados de entrada por família de features, ciclo de desenvolvimento, estratégia de regularização, como se estabelece confiança no modelo, thresholds e política de crédito, e o papel de cada notebook.
- [`docs/artefatos.md`](./docs/artefatos.md) — conjunto publicado a cada treinamento, contrato do artefato LightGBM, conteúdo do baseline populacional e as condições de aceitação pela API, além das regras de reprodutibilidade e compatibilidade.

## Arquivos principais

| Arquivo ou pasta | Finalidade |
|---|---|
| [`config_model.json`](./config_model.json) | Fonte de configuração das features, hiperparâmetros, split, threshold e resultados de referência. |
| [`train.py`](./train.py) | Treina, avalia e publica o conjunto de artefatos. |
| [`feature_reference.py`](./feature_reference.py) | Calcula o baseline populacional e a referência TreeSHAP global. |
| [`predict.py`](./predict.py) | Executa inferência local para um cliente da ABT. |
| [`validacao_modelos.ipynb`](./validacao_modelos.ipynb) | Compara algoritmos e configurações, controla overfitting e seleciona o modelo. |
| [`evaluation.ipynb`](./evaluation.ipynb) | Avalia desempenho, threshold, explicabilidade, fairness e monitoramento. |
| [`requirements.txt`](./requirements.txt) | Dependências da modelagem. |
| [`requirements-test.txt`](./requirements-test.txt) | Dependências de produção mais o pytest. |
| [`pytest.ini`](./pytest.ini) | Raiz de importação e caminho da suíte de testes. |
| [`tests/`](./tests/) | Testes do componente de modelagem. |
| [`artifacts/`](./artifacts/) | Saídas do treinamento e resultado histórico de comparação. |

## Configuração

[`config_model.json`](./config_model.json) é a fonte central para reprodução da modelagem.

| Seção | Conteúdo |
|---|---|
| `metadata` | Projeto, versão, algoritmo, origem, tabela e caminho do artefato. |
| `variables` | Identificador, target, features de entrada e categóricas. |
| `parameters.split` | Holdout, estratificação e semente. |
| `parameters.classifier` | Algoritmo e hiperparâmetros do LightGBM. |
| `parameters.inference` | Threshold de classe persistido no artefato. |
| `parameters.reference` | Tamanho da amostra TreeSHAP usada no baseline populacional. Obrigatória: sua ausência interrompe o treinamento. |
| `validation` | Folds, iterações e tamanho da amostra de busca. |
| `model_results` | Justificativa e métricas de referência da seleção. |

## Preparação do ambiente local

Na pasta `data-platform`:

```bash
python3 -m venv Model/.venv
Model/.venv/bin/python -m pip install -r Model/requirements.txt
```

O PostgreSQL deve estar disponível e a ABT `application_abt` deve ter sido criada pelo [pipeline de dados](../DataPipeline/README.md).

## Testes

A suíte de testes do componente roda com pytest, a partir da própria pasta `Model`:

```bash
cd data-platform/Model
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-test.txt
.venv/bin/python -m pytest
```

A suíte fixa a leitura da ABT com a conversão das categóricas e a seleção das features
configuradas, a composição do treinamento, o cálculo do baseline populacional e a recusa de
publicar um conjunto de artefatos que não pertença ao mesmo treino.

Ela roda **sem PostgreSQL e sem artefato treinado**, porque as conexões chegam injetadas: os
testes entregam uma conexão falsa pela mesma fronteira que a produção usa. A fixture de
banco do [`infra`](../infra/README.md) está disponível por `pytest_plugins` quando algum
teste precisar do banco real.

[`requirements-test.txt`](./requirements-test.txt) instala as dependências de produção mais
o pytest; [`pytest.ini`](./pytest.ini) declara a raiz de importação no componente — a mesma
que a DAG compõe em tempo de execução — mais a raiz `data-platform`, de onde vem o pacote
`infra`.

## Treinamento

```bash
cd data-platform
set -a
source .env
set +a
PYTHONPATH=. Model/.venv/bin/python Model/train.py
```

O carregamento de `.env` exporta as credenciais, a porta e o nome do banco. O host não
vem de lá: o CLI roda fora da rede do compose e conecta em `localhost`, declarado na
própria chamada em `main`. O `PYTHONPATH=.` aponta a raiz `data-platform`, de onde o pacote
`infra` é importado. No Airflow a conexão é aberta pelo `PostgresHook`, a partir do
`conn_id`, e essa preparação manual não é necessária.

Treinamento reduzido para validação rápida:

```bash
PYTHONPATH=. Model/.venv/bin/python Model/train.py \
  --sample-size 5000 \
  --output-path /tmp/lightgbm_abt_smoke.pkl
```

O parâmetro `--sample-size` limita a consulta e existe para smoke tests. Ele não deve ser usado para gerar o artefato oficial.

### O que `train.py` executa

`run_training_pipeline` (DAG) e `main` (CLI) compõem as mesmas etapas, com origem de
configuração e da conexão distintas:

1. Carrega e valida as seções obrigatórias da configuração.
2. O entrypoint abre a conexão — `PostgresHook` na DAG, SQLAlchemy em `localhost` no CLI —
   e a fecha ao fim da leitura. `load_training_data` a recebe pronta, consulta a ABT,
   seleciona as features de entrada configuradas e converte as categóricas.
3. `train` cria o holdout estratificado, treina o modelo de avaliação e calcula AUC,
   Gini, KS, Average Precision e Brier; em seguida retreina o LightGBM final com toda a
   ABT. Não acessa o banco — recebe os dados já carregados.
4. `build_feature_reference` calcula o baseline estatístico das features, do score e a
   importância TreeSHAP global sobre o modelo final e a mesma população do ajuste.
5. `save_artifacts` persiste os três artefatos da execução: o modelo com features,
   categorias e metadados em `lightgbm_abt.pkl`; as métricas do modelo de avaliação em
   `eval_model_metrics.json`; o baseline populacional em `feature_reference.json`.

## Inferência local

```bash
cd data-platform
Model/.venv/bin/python Model/predict.py --sk-id 100002
```

O comando consulta o cliente em `application_abt`, carrega `artifacts/lightgbm_abt.pkl` e apresenta score, threshold e decisão de classe.

## Artefatos

| Artefato | Finalidade | Versionado |
|---|---|---|
| `artifacts/lightgbm_abt.pkl` | Modelo LightGBM oficial e metadados necessários à inferência. | não |
| `artifacts/eval_model_metrics.json` | Fonte única das métricas do holdout, com o algoritmo, os hiperparâmetros e o threshold da execução persistida. | não |
| `artifacts/feature_reference.json` | Distribuições das features e do score, referências por target e importância TreeSHAP global. | não |
| [`artifacts/model_comparison.csv`](./artifacts/model_comparison.csv) | Resultado histórico de comparação de modelos. | sim |

As três saídas do treinamento não são versionadas: são reproduzíveis por `train.py` e
sobrescritas a cada execução. Versioná-las faria o clone criá-las com o dono e a
permissão do usuário local, que o usuário do contêiner do Airflow não consegue
sobrescrever — a gravação falharia no meio da sequência e o conjunto publicado ficaria
incoerente. Em uma cópia nova do repositório elas só aparecem após um treinamento; até
lá, a API não carrega e os notebooks de avaliação não rodam.

A publicação valida a identidade do conjunto antes de gravar qualquer arquivo:
`save_artifacts` recusa um artefato e um baseline que não pertençam ao mesmo
treinamento — `config_version`/`model_version` e `trained_at_utc` precisam coincidir.

O contrato de cada artefato está em [`docs/artefatos.md`](./docs/artefatos.md).

## Componentes relacionados

- [Pipeline de dados](../DataPipeline/README.md)
- [Airflow](../airflow/README.md)
- [MLOps](../MLOps/README.md)

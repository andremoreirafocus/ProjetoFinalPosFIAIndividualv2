# Model

Esta pasta reúne a seleção, o treinamento, a avaliação e a publicação dos artefatos do
modelo de risco de crédito. A inferência está implementada no componente
[`MLOps`](../MLOps/README.md).

## Contexto do problema de modelagem

O target identifica clientes inadimplentes (`target = 1`) e a base é **fortemente desbalanceada**: a classe positiva é uma minoria expressiva. Um classificador pode alcançar alta acurácia prevendo majoritariamente bons pagadores e ainda assim não servir à política de crédito — **a acurácia é enganosa nesse cenário**.

Por isso o modelo não é avaliado por acerto, e sim por **capacidade de ordenar risco**: ROC AUC, Gini, KS e Average Precision. A saída é um **score de propensão à inadimplência**, adequado a ranking, decis e políticas de corte, e **não** uma probabilidade calibrada.

O modelo oficial é um **LightGBM Classifier** com categóricas nativas e `class_weight="balanced"`. A justificativa da escolha, o limite de interpretação do score e o método de avaliação estão em [`docs/modelagem.md`](./docs/modelagem.md).

## Responsabilidade

- ler a ABT `application_abt` e aplicar o contrato de features da configuração;
- avaliar a configuração oficial num holdout estratificado;
- ajustar o modelo final com toda a ABT;
- calcular o baseline populacional e a referência TreeSHAP global;
- publicar o conjunto versionado de artefatos consumido pela API.

## Fluxo

```text
application_abt
  → holdout estratificado 80/20
  → modelo de avaliação + métricas de crédito
  → modelo final com 100% da ABT
  → baseline populacional e TreeSHAP global
  → lightgbm_abt.pkl + eval_model_metrics.json + feature_reference.json + transformation_contract.json
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
| [`artifact_bundle_contract.py`](./artifact_bundle_contract.py) | Declaração do contrato do manifesto — schema, nome constante e chaves obrigatórias do artefato. Sem I/O nem validação. |
| [`artifact_bundle_publisher.py`](./artifact_bundle_publisher.py) | Publica modelo, referência e contrato de transformação atomicamente, com o manifesto escrito por último. |
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
| `metadata` | Projeto, versão, algoritmo, origem, tabela, as duas tabelas em que o pipeline registra a sanitização e a geração da ABT, e diretório de artefatos (`artifacts_dir`). |
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
configuradas, a composição do treinamento, o cálculo do baseline populacional, a leitura do
contrato de transformação registrado pelo pipeline e a recusa de publicar um conjunto de
artefatos que não pertença ao mesmo treino.

`test_artifact_bundle_contract.py` e `test_artifact_bundle_publisher.py` fixam o contrato e
a publicação atômica do conjunto versionado (manifesto, checksums, diretório `bundles/`);
`test_feature_reference.py::test_save_artifacts_*` fixa que `save_artifacts` publica por
esse caminho, com `eval_model_metrics.json` gravado ao lado, fora do manifesto — plano de
refatoração do carregamento, predição e explicação
(`.internal/plano_refatoracao_carregamento_predicao_explicacao.md`).
`test_transformation_contract.py` fixa `load_transformation_contract`: lê
`application_sanitization_last_run` e `application_abt_generation_last_run` e monta o dicionário com as
sete chaves de `REQUIRED_TRANSFORMATION_CONTRACT_KEYS`, as dez estatísticas aninhadas em
`stats`, `run_at` descartado das duas tabelas, e falha nomeando a tabela quando a sanitização
ou a ABT ainda não têm execução registrada.

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
PYTHONPATH=. Model/.venv/bin/python Model/train.py
```

O entrypoint carrega o `.env` da plataforma por conta própria — credenciais, porta e nome
do banco. O host não vem de lá: o CLI roda fora da rede do compose e conecta em
`localhost`, declarado na própria chamada em `main`. Variável já exportada no shell vence o
arquivo, então apontar para outro banco continua possível sem editá-lo. O `PYTHONPATH=.`
aponta a raiz `data-platform`, de onde vem o pacote `infra`. No Airflow a conexão é aberta
pelo `PostgresHook` a partir do `conn_id`, e nada disso é necessário.

Treinamento reduzido para validação rápida, a partir do mesmo diretório:

```bash
PYTHONPATH=. Model/.venv/bin/python Model/train.py \
  --sample-size 5000 \
  --artifacts-dir /tmp/smoke
```

Cada execução publica um conjunto versionado, atomicamente: `current_bundle.json` (o
manifesto ativo) e `bundles/<bundle_id>/` com o modelo, a referência, o contrato de
transformação e seus checksums.
`eval_model_metrics.json` é gravado ao lado, no mesmo diretório, mas não entra no
manifesto — é informativo, sem checksum (decisão 1, seção 11 do plano). Um par cujo
artefato e referência não pertençam ao mesmo treinamento é recusado antes de qualquer
escrita.

O parâmetro `--sample-size` limita a consulta e existe para smoke tests. Ele não deve ser usado para gerar o artefato oficial.

`--artifacts-dir` sobrescreve o diretório onde o conjunto é publicado — o mesmo que
`metadata.artifacts_dir` aponta por padrão. O manifesto e o diretório `bundles/<bundle_id>/`
nascem dentro dele.

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
5. `save_artifacts` publica o conjunto versionado — modelo, referência, contrato de
   transformação e manifesto, atomicamente — e grava `eval_model_metrics.json` ao lado,
   fora do manifesto. Contrato completo em [`docs/artefatos.md`](./docs/artefatos.md).

A inferência local — antes `Model/predict.py` e `Model/find_customer_by_score.py` — é
transporte do serving desde a etapa 9 do plano de bundle: vive em
[`MLOps/app/cli/`](../MLOps/DEVELOPMENT.md), com a mesma cadeia e a mesma configuração que
a API usa. Não há segunda implementação de inferência neste componente.

## Artefatos

Cada treinamento publica um conjunto versionado em `artifacts/bundles/<bundle_id>/`, com
`artifacts/current_bundle.json` como manifesto ativo — modelo, referência e contrato de
transformação declarados com checksum, `eval_model_metrics.json` ao lado, fora do
manifesto. O contrato completo, o
formato do manifesto e a publicação atômica estão em
[`docs/artefatos.md`](./docs/artefatos.md).

| Artefato | Finalidade | Versionado |
|---|---|---|
| `artifacts/current_bundle.json` | Manifesto do conjunto ativo. | — |
| `artifacts/bundles/<bundle_id>/lightgbm_abt.pkl` | Modelo LightGBM oficial e metadados necessários à inferência. | sim |
| `artifacts/bundles/<bundle_id>/feature_reference.json` | Distribuições das features e do score, referências por target e importância TreeSHAP global. | sim |
| `artifacts/bundles/<bundle_id>/transformation_contract.json` | Estatísticas, listas de categorias válidas e digests de projeção registrados pelo pipeline na execução que produziu a ABT. | sim |
| `artifacts/bundles/<bundle_id>/eval_model_metrics.json` | Métricas do holdout, algoritmo, hiperparâmetros e threshold da execução. Fora do manifesto. | sim |
| [`artifacts/model_comparison.csv`](./artifacts/model_comparison.csv) | Resultado histórico de comparação de modelos. | sim |

Nenhum dos cinco primeiros é versionado no git — reproduzíveis por `train.py`, sob
`bundle_id` diferente a cada execução. Versioná-los faria o clone criá-los com o dono e a
permissão do usuário local, que o usuário do contêiner do Airflow não consegue
sobrescrever. Em uma cópia nova do repositório eles só aparecem após um treinamento.

A API de inferência lê o bundle versionado por `current_bundle.json`: o
`ModelBundleManager` acompanha o manifesto em segundo plano e só troca de bundle ativo
quando um candidato passa por todas as validações do `ArtifactBundleLoader`. Nenhum
consumidor lê mais um caminho fixo — os arquivos `artifacts/lightgbm_abt.pkl`,
`artifacts/feature_reference.json` e `artifacts/eval_model_metrics.json` de caminho fixo,
sobrescritos a cada treinamento, não existem mais. `Model/evaluation.ipynb` lê o mesmo
manifesto, pela chave `metadata.artifacts_dir` do `config_model.json`.

A publicação valida a identidade do conjunto antes de gravar qualquer arquivo:
`save_artifacts` recusa um artefato e uma referência que não pertençam ao mesmo
treinamento — `config_version`/`model_version` e `trained_at_utc` precisam coincidir —, e
nada é escrito, nem o manifesto nem o diretório versionado.

## Componentes relacionados

- [Pipeline de dados](../DataPipeline/README.md)
- [Airflow](../airflow/README.md)
- [MLOps](../MLOps/README.md)

# Model

Esta pasta reúne a seleção, o treinamento, a avaliação e a inferência local do modelo de risco de crédito.

## Contexto de modelagem

O target do projeto identifica clientes inadimplentes (`target = 1`). A base é **fortemente desbalanceada** — a classe positiva (inadimplente) é uma minoria expressiva. Por isso, um classificador pode alcançar alta acurácia prevendo majoritariamente bons pagadores e ainda assim oferecer pouco valor para a política de crédito: **a acurácia é enganosa nesse cenário**, o que orienta toda a escolha metodológica a seguir.

O objetivo da modelagem não é automatizar isoladamente a concessão de crédito. O modelo deve:

- ordenar clientes de acordo com a propensão à inadimplência;
- concentrar maus pagadores nas faixas superiores do score;
- generalizar para clientes não usados no ajuste;
- fornecer drivers interpretáveis e coerentes com o negócio;
- permitir que thresholds sejam avaliados segundo perdas, margem e capacidade operacional;
- manter o mesmo contrato de features no treinamento e na inferência.

Essa finalidade orienta a **escolha das métricas de avaliação**, que priorizam **ordenação/discriminação** em vez de acurácia:

- **ROC AUC** e **Gini** medem a capacidade de ordenar bons e maus **independentemente do ponto de corte**;
- **KS** mede a separação máxima acumulada entre as distribuições de score das duas classes (padrão em *scorecards* de crédito);
- **Average Precision (PR-AUC)** avalia a qualidade do ranking na **classe rara**, mais informativa que a acurácia sob desbalanceamento;
- **Brier** e a curva de calibração diagnosticam o quanto o score se afasta de uma probabilidade observável;
- **matriz de confusão, recall e métricas econômicas de corte** traduzem o modelo em decisão de negócio.

Os **valores** de cada execução vivem nos notebooks e em [`artifacts/metrics.json`](./artifacts/metrics.json) — esta documentação descreve o *método*, não os números (que variam a cada re-treino).

## Modelo atual

O modelo oficial é um **LightGBM Classifier** com variáveis categóricas nativas e tratamento de desbalanceamento por `class_weight="balanced"`. A saída deve ser interpretada como um **score de propensão à inadimplência**, adequado para ordenação de risco, e não como probabilidade calibrada.

### Por que LightGBM

A seleção não foi definida antecipadamente. Regressão Logística, Random Forest, XGBoost e LightGBM foram comparados sob validação cruzada estratificada e teste externo. O LightGBM foi escolhido por combinar:

- melhor capacidade de discriminação entre as configurações aceitas;
- diferença controlada entre treino, validação e teste;
- suporte eficiente a relações não lineares e interações;
- tratamento nativo das cinco features categóricas;
- bom desempenho em dados tabulares com centenas de milhares de linhas;
- mecanismos de regularização compatíveis com o controle de overfitting.

### Limite de interpretação do score

O método `predict_proba` produz um valor entre 0 e 1, mas `class_weight="balanced"` altera o peso relativo das classes no ajuste. A avaliação também identifica erro de calibração. Portanto:

- o valor é adequado para ranking, decis e políticas de corte;
- valores maiores representam maior propensão à inadimplência;
- `0.70` não deve ser comunicado como “70% de probabilidade real de default”;
- calibração adicional é necessária caso o uso exija probabilidade observável.

O frontend e a documentação da API adotam o termo `risk_score` para preservar essa distinção.

## Dados de entrada

O treinamento lê `application_abt` no PostgreSQL. A tabela tem **uma linha por `sk_id_curr`**, a coluna `target` e as features preditoras, distribuídas entre:

| Família | Exemplos | Informação representada |
|---|---|---|
| Scores externos | `ext_source_1/2/3`, `ext_source_mean` | Sinais externos consolidados de risco. |
| Perfil e estabilidade | `age`, `years_employed`, `days_employed_anom` | Idade, vínculo e anomalias cadastrais. |
| Capacidade financeira | `amt_income_total`, `amt_credit`, `amt_annuity` | Renda e valores da operação. |
| Razões derivadas | `fe_credit_income_percent`, `fe_annuity_income_percent` | Comprometimento relativo da renda. |
| Histórico interno | `prev_refused_rate`, `has_prev_app` | Experiência em propostas anteriores. |
| Bureau | `bureau_*`, `has_bureau` | Atividade, recência, dívida e atraso externos. |
| Parcelas | `inst_late_payment_rate`, `has_installments_history` | Comportamento de pagamento observado. |
| Categóricas | ocupação, organização, renda, educação e gênero | Segmentos cadastrais tratados. |

A lista ordenada completa está em [`config_model.json`](./config_model.json). `sk_id_curr` e `target` nunca entram como variáveis explicativas.

## Ciclo de desenvolvimento

```text
application_abt
  → split externo estratificado 80/20
  → amostra de busca no conjunto de treino
  → RandomizedSearchCV com 5 folds
  → comparação de quatro famílias de modelos
  → filtro de overfitting
  → seleção do LightGBM
  → avaliação no holdout
  → análise de threshold, explicabilidade e fairness
  → configuração oficial
  → treino final com 100% da ABT
  → artefato para inferência
```

O holdout mede generalização e não participa do ajuste final durante a comparação. Depois que a configuração é escolhida e avaliada, `train.py` treina um modelo de avaliação no split e, em seguida, ajusta o artefato final com toda a ABT.

## Configuração

[`config_model.json`](./config_model.json) é a fonte central para reprodução da modelagem.

| Seção | Conteúdo |
|---|---|
| `metadata` | Projeto, versão, algoritmo, origem, tabela e caminho do artefato. |
| `variables` | Identificador, target, features de entrada e categóricas. |
| `parameters.split` | Holdout, estratificação e semente. |
| `parameters.classifier` | Algoritmo e hiperparâmetros do LightGBM. |
| `parameters.inference` | Threshold de classe persistido no artefato. |
| `validation` | Folds, iterações e tamanho da amostra de busca. |
| `model_results` | Justificativa e métricas de referência da seleção. |

### Estratégia de regularização (controle de overfitting)

Os hiperparâmetros não foram fixados a priori: saíram da busca descrita em `validacao_modelos.ipynb`, dentro de uma faixa deliberadamente concentrada na **região regularizada**. O objetivo é um modelo que generaliza, não que memoriza o treino. A estratégia combina:

- **árvores rasas** (profundidade máxima baixa) — limitam interações espúrias e memorização;
- **folhas com amostra mínima elevada** — impedem que uma folha se apoie em poucos clientes;
- **regularização L2** e **amostragem de features por árvore** — reduzem variância;
- **taxa de aprendizado baixa** com número de árvores compatível — ganho incremental e estável;
- **`class_weight="balanced"`** — compensa o desbalanceamento no ajuste.

Os **valores exatos** de cada hiperparâmetro ficam em [`config_model.json`](./config_model.json) (`parameters.classifier.hyperparameters`), como fonte única — assim não divergem da documentação a cada re-tunagem.

## Estrutura

| Arquivo ou pasta | Finalidade |
|---|---|
| [`config_model.json`](./config_model.json) | Fonte de configuração das features, hiperparâmetros, split, threshold e resultados de referência. |
| [`train.py`](./train.py) | Treina, avalia e persiste o LightGBM. |
| [`predict.py`](./predict.py) | Executa inferência local para um cliente da ABT. |
| [`validacao_modelos.ipynb`](./validacao_modelos.ipynb) | Compara algoritmos e configurações, controla overfitting e seleciona o modelo. |
| [`evaluation.ipynb`](./evaluation.ipynb) | Avalia desempenho, threshold, explicabilidade, fairness e monitoramento. |
| [`requirements.txt`](./requirements.txt) | Dependências da modelagem. |
| [`artifacts/`](./artifacts/) | Modelos persistidos, métricas e resultados de comparação. |

## Notebooks

Os notebooks concentram as **decisões metodológicas** da modelagem. Este README descreve a **abordagem** de cada um — o que analisa, o que busca estabelecer, com que método e que artefatos produz; os **resultados numéricos** permanecem nos próprios notebooks.

### [`validacao_modelos.ipynb`](./validacao_modelos.ipynb) — seleção do modelo

- **O que analisa:** um conjunto **curado de quatro famílias** — linear regularizado (Logística L2), *bagging* (Random Forest) e *boosting* (XGBoost e LightGBM) — sobre a ABT, cobrindo as abordagens relevantes para dados tabulares de crédito, em vez de testar muitos algoritmos redundantes.
- **O que busca estabelecer:** qual família e configuração entregam o melhor **poder de ordenação** com **overfitting controlado**, e quais hiperparâmetros alimentam o treinamento oficial.
- **Método:** busca de hiperparâmetros por `RandomizedSearchCV` com **validação cruzada estratificada**, medindo cada configuração em **três frentes — treino × teste interno (CV) × teste externo (holdout)** para diagnosticar overfitting sem depender de uma única partição; um **filtro de overfitting** descarta configurações que caem demais do treino para o teste; o modelo escolhido é **retreinado no conjunto de treino completo**. Nesta comparação **todas as famílias** usam padronização + *one-hot* (inclusive o campeão); é o **treinamento oficial** (`train.py`, avaliado em `evaluation.ipynb`) que adota as **categóricas nativas** do LightGBM, com os hiperparâmetros aqui selecionados.
- **Dados que cria e apresenta:** tabela de comparação treino/CV/externo por configuração, ranking pós-filtro de overfitting, importância nativa (contagem de *splits*) do modelo final e curvas/decis do candidato.

### [`evaluation.ipynb`](./evaluation.ipynb) — avaliação do modelo escolhido

- **O que analisa:** exclusivamente o **modelo desenvolvido** (LightGBM regularizado, categóricas nativas), reproduzindo a lógica de `train.py` (mesmo split e mesma semente).
- **O que busca estabelecer:** se o modelo **generaliza** de forma honesta e pode virar política de crédito, quais variáveis o sustentam e como monitorá-lo — a defesa de *por que se pode confiar na solução*.
- **Método:** medição no **holdout** (e não no artefato retreinado em 100% da base, que seria vazamento); métricas de crédito; leitura de negócio por **decis/lift** e **varredura de threshold**; definição de uma **política de corte em três faixas** (aprovação automática, revisão humana e negação) roteada pelo **trade-off marginal de bons por mau aprovado** e pelos pontos de operação de **recall/precisão** ao longo do threshold; **interpretabilidade** por importância de permutação e SHAP; **governança/fairness** por subgrupo e **plano de monitoramento**.
- **Dados que cria e apresenta:** curvas ROC e Precision-Recall, matriz de confusão, distribuição de score por classe e curva de calibração, tabela de decis/lift, **tabela de operação por threshold (recall/precisão e trade-off marginal de bons por mau)**, ranking de permutação e *beeswarm* SHAP, tabelas de desempenho/decisão por subgrupo e a tabela de métricas de monitoramento.

Os notebooks podem ser executados pelo ambiente descrito em [Jupyter](../jupyter/README.md).

## Preparação do ambiente local

Na pasta `data-platform`:

```bash
python3 -m venv Model/.venv
Model/.venv/bin/python -m pip install -r Model/requirements.txt
```

O PostgreSQL deve estar disponível e a ABT `application_abt` deve ter sido criada pelo [pipeline de dados](../DataPipeline/README.md).

## Treinamento

```bash
cd data-platform
set -a
source .env
set +a
PYTHONPATH=DataPipeline Model/.venv/bin/python Model/train.py
```

O carregamento de `.env` exporta para o processo local as variáveis de conexão
com o PostgreSQL usadas por `DataPipeline/utils.py`. No Airflow, a conexão é
fornecida pelo `PostgresHook` e essa preparação manual não é necessária.

Treinamento reduzido para validação rápida:

```bash
PYTHONPATH=DataPipeline Model/.venv/bin/python Model/train.py \
  --sample-size 5000 \
  --output /tmp/lightgbm_abt_smoke.pkl
```

O treinamento oficial também é a última etapa da DAG `pipeline_orchestration`.

### O que `train.py` executa

1. Carrega e valida as seções obrigatórias da configuração.
2. Consulta a ABT no PostgreSQL.
3. Seleciona as features de entrada configuradas e converte as categóricas.
4. Cria holdout estratificado para avaliação da configuração.
5. Treina o modelo de avaliação e calcula AUC, Gini, KS, Average Precision e Brier.
6. Gera relatório de classificação no threshold configurado.
7. Retreina o LightGBM final com toda a ABT.
8. Calcula o baseline estatístico das features, do score e a importância TreeSHAP global.
9. Persiste modelo, features, categorias, métricas, metadados e referências.

O parâmetro `--sample-size` limita a consulta e existe para smoke tests. Ele não deve ser usado para gerar o artefato oficial.

## Inferência local

```bash
cd data-platform
Model/.venv/bin/python Model/predict.py --sk-id 100002
```

O comando consulta o cliente em `application_abt`, carrega `artifacts/lightgbm_abt.pkl` e apresenta score, threshold e decisão de classe.

## Artefatos

| Artefato | Finalidade |
|---|---|
| `artifacts/lightgbm_abt.pkl` | Modelo LightGBM oficial e metadados necessários à inferência. |
| [`artifacts/metrics.json`](./artifacts/metrics.json) | Métricas e hiperparâmetros da execução persistida. |
| `artifacts/feature_reference.json` | Distribuições das features e do score, referências por target e importância TreeSHAP global. |
| [`artifacts/model_comparison.csv`](./artifacts/model_comparison.csv) | Resultado histórico de comparação de modelos. |

Atualmente, os três artefatos da execução oficial são gravados nos mesmos caminhos e substituem os arquivos anteriores. A proposta de [monitoramento do modelo em produção](../MLOps/MONITORING_ARCHITECTURE.md) introduz um *model registry* para preservar cada versão junto com sua configuração, métricas e baselines, além de controlar promoção e rollback.

### Contrato do artefato LightGBM

O Pickle oficial é um dicionário com os elementos necessários para que outro processo reproduza a inferência:

| Chave | Conteúdo |
|---|---|
| `model` | Instância treinada do `LGBMClassifier`. |
| `features` | Lista ordenada das features esperadas. |
| `categorical_features` | Features que precisam manter dtype categórico. |
| `categories` | Categorias conhecidas durante o treinamento. |
| `decision_threshold` | Corte usado para produzir `predicted_class`. |
| `metrics` | Métricas do holdout do modelo de avaliação. |
| `algorithm` | Identificação do algoritmo. |
| `hyperparameters` | Configuração utilizada no ajuste. |
| `trained_at_utc` | Data e hora do treinamento. |
| `config_version` | Versão lógica da configuração. |

O `train.py` salva a lista ordenada na chave `features`, que é consumida diretamente pela API como contrato de entrada do modelo.

### Referências para explicação e para o agente acelerador de revisão de crédito

Após ajustar o modelo final, `train.py` gera `feature_reference.json` com a mesma
versão e instante de treinamento do artefato. Para features numéricas, o arquivo
registra contagem, ausências, média, desvio-padrão, mínimo, máximo, percentis de
0 a 100 e medianas por target. Para flags binárias, registra também a proporção
geral e por target. Para categóricas, registra contagem, frequência e taxa
histórica de inadimplência por categoria. Também inclui a distribuição do score
e, para cada feature, média e percentis 50, 75, 90, 95 e 99 do valor SHAP
absoluto em uma amostra reproduzível, cujo tamanho é definido por
`parameters.reference.shap_sample_size`.

Esse baseline permite combinar a contribuição SHAP local retornada pela API com
a posição estatística do cliente na população usada pelo treinamento. Os valores
SHAP permanecem na escala bruta do modelo e não representam variação percentual
de probabilidade.

Essas referências foram acrescentadas ao treinamento para preparar informações
determinísticas e versionadas que possam ser consumidas pelo futuro agente acelerador de revisão de crédito. O agente acelerador de revisão de crédito não acessará os dados de treino nem calculará estatísticas:
receberá da API a explicação local já enriquecida com este baseline e apenas a
converterá em um relatório para o analista. A arquitetura desse fluxo está em
[Arquitetura proposta para o agente acelerador de revisão de crédito](../MLOps/AGENT_ARCHITECTURE.md).

## Como estabelecemos confiança no modelo

Em vez de fixar números aqui (que mudam a cada re-treino), a confiabilidade da solução é sustentada por **método**:

- **Holdout honesto:** o desempenho é medido em um conjunto estratificado **nunca visto** no ajuste; avaliar o artefato final (retreinado em 100% da base) sobre esse conjunto seria vazamento.
- **Consistência teste × validação:** o desempenho no holdout é confrontado com o da validação cruzada — a proximidade entre os dois é a evidência de **ausência de overfitting escondido**.
- **Métricas de crédito, não acurácia:** AUC/Gini/KS/PR-AUC medem ordenação sob desbalanceamento; a calibração é inspecionada para deixar explícito que o score é **ranking de risco, não probabilidade calibrada**.
- **Coerência EDA → poder preditivo → modelo:** as variáveis mais importantes (permutação/SHAP) coincidem com as apontadas pela EDA e têm sentido de negócio — argumento contra vazamento.
- **Governança:** desempenho e decisão por subgrupo e um plano de monitoramento (desempenho, estabilidade dos dados/PSI, calibração, fairness) fecham o critério de rastreabilidade e conformidade.

Os **valores** de cada execução ficam em [`artifacts/metrics.json`](./artifacts/metrics.json) e nos notebooks, sempre no contexto da execução que os produziu — os notebooks podem refletir estágios de seleção ou execuções distintas do artefato oficial.

## Thresholds e política de crédito

Há dois conceitos diferentes:

- **threshold do modelo:** persistido no artefato e usado para `predicted_class`;
- **limites da política:** configurados na API e usados para recomendar aprovação, revisão ou rejeição.

O notebook de avaliação explora thresholds estatísticos e econômicos. Os limites da API são demonstrativos e não representam uma política final validada com custos reais.

## Reprodutibilidade e compatibilidade

- use a mesma versão de LightGBM e dependências registrada em [`requirements.txt`](./requirements.txt);
- não altere a ordem ou o tipo das features sem retreinar;
- mudanças na ABT devem ser refletidas em `config_model.json`;
- Pickle deve ser carregado apenas de origem confiável;
- alterações de categorias exigem novo artefato para preservar o contrato de inferência.

## Componentes relacionados

- [Pipeline de dados](../DataPipeline/README.md)
- [Airflow](../airflow/README.md)
- [MLOps](../MLOps/README.md)

# Jupyter

Esta pasta define o ambiente JupyterLab usado para exploração de dados, validação da ABT e desenvolvimento dos notebooks de modelagem.

## Papel no ciclo analítico

O Jupyter registra as decisões que transformaram exploração em implementação. Os notebooks não são o pipeline produtivo: eles permitem investigar hipóteses, comparar alternativas, visualizar resultados e documentar evidências que depois orientam os scripts e configurações oficiais.

Neste projeto, o ambiente cobre quatro momentos:

1. diagnóstico das fontes brutas;
2. validação da ABT construída pelo pipeline;
3. comparação e seleção do algoritmo;
4. avaliação aprofundada do modelo escolhido.

Separar esses momentos reduz o risco de misturar exploração com transformação operacional e deixa claro qual notebook responde a cada pergunta.

## Responsabilidade

- disponibilizar um ambiente padronizado para notebooks;
- montar os diretórios `infra`, `DataPipeline` e `Model` no workspace;
- instalar bibliotecas de análise, modelagem e interpretabilidade.

## Estrutura

```text
jupyter/
├── Dockerfile
├── README.md
└── requirements.txt
```

O [`Dockerfile`](./Dockerfile) estende a imagem `jupyter/datascience-notebook` e instala as dependências descritas em [`requirements.txt`](./requirements.txt).

As dependências adicionais incluem conectividade PostgreSQL, LightGBM, XGBoost, SHAP e scikit-learn. Assim, o mesmo ambiente consegue consultar a ABT, comparar modelos e gerar explicações.

## Inicialização

Na pasta [`data-platform`](../README.md):

```bash
docker compose up -d --build jupyter
```

Para acompanhar a inicialização:

```bash
docker compose logs -f jupyter
```

## Acesso

- JupyterLab: http://localhost:8888
- Token: valor de `JUPYTER_TOKEN` no arquivo `data-platform/.env`

No container, os diretórios são montados em:

| Diretório do projeto | Caminho no Jupyter |
|---|---|
| `infra/` | `/home/jovyan/work/infra` |
| `DataPipeline/` | `/home/jovyan/work/DataPipeline` |
| `Model/` | `/home/jovyan/work/Model` |

## Notebooks disponíveis

### Pipeline de dados

- [`exp_analysis_raw.ipynb`](../DataPipeline/exp_analysis_raw.ipynb): **diagnostica as fontes brutas** (qualidade, ausências, anomalias, cardinalidade, desbalanceamento) e mede o poder preditivo de cada variável para **decidir** os tratamentos de sanitização e as features da ABT.
- [`exp_analysis_abt.ipynb`](../DataPipeline/exp_analysis_abt.ipynb): **valida a ABT tratada** (integridade, redundâncias removidas, força preditiva, multicolinearidade) e sinaliza atributos sensíveis para governança.

### Modelagem

- [`validacao_modelos.ipynb`](../Model/validacao_modelos.ipynb): **seleciona o modelo** — compara as famílias de algoritmos sob o mesmo split, com busca de hiperparâmetros e critério de overfitting (treino × CV × teste externo).
- [`evaluation.ipynb`](../Model/evaluation.ipynb): **avalia o modelo escolhido** no holdout — métricas de discriminação, análise operacional de thresholds, interpretabilidade (permutação/SHAP), fairness e plano de monitoramento.

## Sequência recomendada

Os notebooks dependem de etapas diferentes do pipeline: a EDA bruta requer as quatro
fontes ingeridas; os demais requerem a ABT materializada. A sequência metodológica que
originou a implementação é:

```text
ingestão das fontes
  → exp_analysis_raw.ipynb
  → implementação e execução das transformações e da ABT
  → exp_analysis_abt.ipynb
  → validacao_modelos.ipynb
  → registro da configuração + train.py
  → evaluation.ipynb
```

A DAG atual reproduz o fluxo operacional já selecionado, da ingestão ao treinamento,
usando as configurações vigentes. Ela pode ser executada integralmente antes da análise
dos notebooks quando o objetivo for apenas reconstruir o estado atual da plataforma.

> As decisões de EDA sobre os dados brutos justificam as regras de `data_sanitization.py` e `abt_transform.py`; ao alterá-las, reexecute o pipeline para reconstruir a ABT antes de seguir para a modelagem.

### 1. Dados brutos

Use `exp_analysis_raw.ipynb` para compreender desbalanceamento, ausência, anomalias, cardinalidade e relações entre as fontes. As decisões relevantes devem ser refletidas em `data_sanitization.py` e `abt_transform.py`.

### 2. ABT tratada

Use `exp_analysis_abt.ipynb` depois da execução do pipeline. Ele valida granularidade, nulos, duplicidades, redundâncias, features históricas e possíveis atributos sensíveis.

### 3. Seleção do modelo

Use `validacao_modelos.ipynb` para comparar as famílias de algoritmos sob o mesmo split, validação cruzada e critérios de overfitting. O resultado escolhido deve alimentar `config_model.json`.

### 4. Avaliação final

Use `evaluation.ipynb` para avaliar o LightGBM oficial, interpretar drivers, analisar thresholds e registrar limitações, fairness e monitoramento.

## Relação com os componentes operacionais

| Notebook | Implementação que recebe suas decisões |
|---|---|
| EDA bruta | `DataPipeline/data_sanitization.py` e `abt_transform.py` |
| EDA da ABT | `Model/config_model.json` |
| Validação | `Model/config_model.json` e `train.py` |
| Avaliação | política de crédito, apresentação e próximos passos de MLOps |

Os notebooks contêm resultados persistidos de execuções específicas. Para comparar números, verifique se configuração, seed, split e artefato pertencem à mesma execução.

## Componentes relacionados

- [Pipeline de dados](../DataPipeline/README.md)
- [Modelo](../Model/README.md)

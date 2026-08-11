# DataPipeline — Transformações

Referência detalhada das etapas de transformação do pipeline. Parte do [DataPipeline](../README.md).

## Por que ELT no PostgreSQL

Os arquivos de bureau, propostas e parcelas possuem centenas de megabytes. Transferir todas essas tabelas para a memória de um processo Python apenas para agregá-las aumentaria consumo, tempo de execução e risco de falha. A implementação adota ELT:

1. Python controla conexão, parâmetros, arquivos e ciclo das tarefas.
2. Os dados são carregados no PostgreSQL.
3. Limpeza, percentis, agregações e joins são executados em SQL pelo banco.

Essa escolha aproveita o otimizador do PostgreSQL, reduz movimentação de dados e mantém as transformações observáveis como tabelas intermediárias.

## Visão geral da configuração

Todo o pipeline é dirigido por um único arquivo, [`config_pipeline.json`](../config_pipeline.json), com quatro blocos:

- `ingestion_table` — fontes CSV autorizadas para ingestão e o tamanho de chunk de cada uma.
- `database` — nomes das tabelas brutas, tratadas e da ABT, usados por todas as demais etapas.
- `indexes` — índices de banco a criar em cada fase (`raw`, antes da limpeza; `clean`, antes do join da ABT).
- `sanitization` — parâmetros da limpeza de `application_train`.

Cada seção abaixo detalha um desses blocos e mostra apenas o trecho de JSON correspondente — nunca o arquivo inteiro.

A DAG carrega o arquivo com `load_pipeline_config(path)` (`config.py`), que recebe o caminho explicitamente — sem default e sem inferir um arquivo "ao lado" do módulo. Todas as chaves usadas pelo pipeline são obrigatórias: nenhuma tem valor substituto aplicado pelo código, e a ausência de qualquer uma delas falha no carregamento da DAG.

## Nomenclatura das tabelas

O bloco `database` de `config_pipeline.json` nomeia as tabelas brutas (`input_*`), as tratadas (`output_*`) e a ABT (`abt_table`). É a fonte usada pela ingestão, pela indexação raw e clean, pela limpeza e pela construção da ABT.

Trecho de `config_pipeline.json` — apenas este bloco, não o arquivo completo:

```json
"database": {
  "input_table": "application_train",
  "output_table": "application_clean",
  "input_prev_table": "previous_application",
  "output_prev_table": "previous_application_clean",
  "input_bureau_table": "bureau",
  "output_bureau_table": "bureau_clean",
  "input_installments_table": "installments_payments",
  "output_installments_table": "installments_clean",
  "abt_table": "application_abt"
}
```

## Implementação da ingestão

[`ingestion.py`](../ingestion.py) recebe o objeto de configuração já carregado e o nome da tabela por tarefa Airflow e executa:

1. resolução da definição da fonte no escopo de ingestão do config e rejeição de fonte não declarada;
2. localização do CSV por nome normalizado;
3. tentativa de leitura UTF-8, com fallback para Latin-1;
4. leitura iterativa com o `chunk_size` declarado na definição da fonte;
5. inferência inicial de tipos Pandas → PostgreSQL;
6. criação da tabela no primeiro chunk;
7. append dos blocos por `COPY FROM STDIN` com delimitador tab;
8. log de volumetria após as cargas.

O uso de `COPY` evita inserts linha a linha. Os chunks controlam a memória e permitem tamanhos distintos de lote conforme o volume de cada fonte.

| Fonte | Chunk configurado | Motivo funcional |
|---|---:|---|
| `application_train` | 150.000 | Cadastro largo, com muitas colunas. |
| `previous_application` | 300.000 | Histórico com múltiplas propostas por cliente. |
| `bureau` | 150.000 | Histórico externo com valores e categorias. |
| `installments_payments` | 600.000 | Fonte longa, processada com lote maior. |

Trecho de `config_pipeline.json` — apenas este bloco, não o arquivo completo:

```json
"ingestion_table": {
  "using_csv": [
    { "table_name": "installments_payments", "chunk_size": 600000 },
    { "table_name": "application_train", "chunk_size": 150000 },
    { "table_name": "previous_application", "chunk_size": 300000 },
    { "table_name": "bureau", "chunk_size": 150000 }
  ]
}
```

## Implementação da indexação raw

[`ingestion_index.py`](../ingestion_index.py) cria, antes das limpezas, os índices
declarados em `indexes.raw` de [`config_pipeline.json`](../config_pipeline.json). Cada
entrada tem `name`, `table_ref` (uma chave `input_*` de `database`, resolvida para o
nome físico da tabela) e `columns`. Renomear uma tabela raw em `database` redireciona o
índice automaticamente, sem alterar o código. A execução é idempotente
(`CREATE INDEX IF NOT EXISTS`).

Trecho de `config_pipeline.json` — apenas este bloco, não o arquivo completo:

```json
"indexes": {
  "raw": [
    { "name": "idx_app_sk_id_curr", "table_ref": "input_table", "columns": ["sk_id_curr"] },
    { "name": "idx_app_org_type", "table_ref": "input_table", "columns": ["organization_type"] },
    { "name": "idx_app_inc_type", "table_ref": "input_table", "columns": ["name_income_type"] },
    { "name": "idx_app_flag_car", "table_ref": "input_table", "columns": ["flag_own_car"] },
    { "name": "idx_prev_sk_id_prev", "table_ref": "input_prev_table", "columns": ["sk_id_prev"] },
    { "name": "idx_prev_sk_id_curr", "table_ref": "input_prev_table", "columns": ["sk_id_curr"] },
    { "name": "idx_bur_sk_id_bureau", "table_ref": "input_bureau_table", "columns": ["sk_id_bureau"] },
    { "name": "idx_bur_sk_id_curr", "table_ref": "input_bureau_table", "columns": ["sk_id_curr"] },
    { "name": "idx_inst_sk_id_curr", "table_ref": "input_installments_table", "columns": ["sk_id_curr"] },
    { "name": "idx_inst_sk_id_prev", "table_ref": "input_installments_table", "columns": ["sk_id_prev"] }
  ]
}
```

## Implementação da limpeza

[`data_sanitization.py`](../data_sanitization.py) cria novas tabelas em vez de sobrescrever as fontes brutas.

### `application_train → application_clean`

Uma CTE calcula estatísticas globais uma única vez e as aplica a todos os clientes:

- medianas dos três scores externos e de `ext_source_mean`;
- medianas de telefone, família, anuidade e renda;
- percentil configurável da renda para winsorização;
- mediana da idade do carro apenas entre clientes que possuem veículo;
- categorias de organização e renda com frequência mínima configurada.

Trecho de `config_pipeline.json` — apenas este bloco, não o arquivo completo:

```json
"sanitization": {
  "cardinalidade_min_freq": 500,
  "income_winsor_q": 0.99
}
```

As principais regras são:

| Tema | Tratamento |
|---|---|
| Scores externos | Nulos preenchidos pela mediana e média consolidada em `ext_source_mean`. |
| Renda | Zero tratado como ausência, imputação pela mediana e limite superior no percentil 99. |
| Veículo | `has_car` binário; idade do carro é zero sem carro e mediana quando há carro sem idade informada. |
| Categorias raras | Organização e tipo de renda abaixo da frequência mínima viram `Other_low_freq`. |
| Ausências categóricas | Ocupação e educação recebem `Unknown`. |
| Gênero inválido | `XNA` é convertido em `Unknown`. |
| Idade | `days_birth` negativo é convertido para anos positivos. |
| Emprego | O sentinel `365243` vira `years_employed = 0` e ativa `days_employed_anom`. |
| Indicadores binários e contagens | Ausências selecionadas são preenchidas com zero. |

### Históricos

- `previous_application_clean` normaliza o status do contrato e impede valores negativos de aplicação;
- `bureau_clean` padroniza textos e converte campos monetários e de atraso para tipos numéricos com zero quando adequado;
- `installments_clean` mantém as colunas necessárias e remove linhas sem chaves, vencimento ou valor de parcela.

As tabelas tratadas recebem índices novamente porque são recriadas a cada execução.

## Implementação da indexação clean

[`data_sanitization_index.py`](../data_sanitization_index.py) cria, depois das limpezas
e antes do join da ABT, os índices declarados em `indexes.clean` de
`config_pipeline.json`. Cada entrada tem `name`, `table_ref` (uma chave `output_*` de
`database`, resolvida para o nome físico da tabela tratada) e `columns`. Um `table_ref`
que resolve para um nome vazio ou ausente falha com `ValueError`. A execução é
idempotente (`CREATE INDEX IF NOT EXISTS`).

Trecho de `config_pipeline.json` — apenas este bloco, não o arquivo completo:

```json
"indexes": {
  "clean": [
    { "name": "idx_abt_application_clean_sk_id_curr", "table_ref": "output_table", "columns": ["sk_id_curr"] },
    { "name": "idx_abt_previous_application_clean_sk_id_curr", "table_ref": "output_prev_table", "columns": ["sk_id_curr"] },
    { "name": "idx_abt_bureau_clean_sk_id_curr", "table_ref": "output_bureau_table", "columns": ["sk_id_curr"] },
    { "name": "idx_abt_installments_clean_sk_id_curr", "table_ref": "output_installments_table", "columns": ["sk_id_curr"] }
  ]
}
```

## Implementação das agregações

[`abt_transform.py`](../abt_transform.py) reduz cada histórico para uma linha por cliente antes do join final.

| Histórico | Feature agregada | Cálculo resumido |
|---|---|---|
| Propostas anteriores | `prev_refused_rate` | Proporção de propostas com status `Refused`. |
| Bureau | `bureau_avg_days_credit` | Média da antiguidade dos créditos. |
| Bureau | `bureau_last_days_credit` | Crédito mais recente observado. |
| Bureau | `bureau_active_rate` e `bureau_active_count` | Proporção e quantidade de créditos ativos. |
| Bureau | `bureau_closed_rate` | Proporção de créditos encerrados. |
| Bureau | `bureau_debt_credit_ratio` | Dívida total dividida pelo crédito total. |
| Bureau | `bureau_overdue_count` | Quantidade de créditos com atraso. |
| Parcelas | `inst_late_payment_rate` | Proporção de parcelas pagas depois do vencimento. |

Cada agregado é salvo temporariamente e indexado por `sk_id_curr`. Depois do join, as tabelas temporárias são removidas.

## Construção da ABT

A tabela `application_clean` é o lado esquerdo dos joins. Isso preserva todos os clientes do cadastro, mesmo quando não possuem histórico nas demais fontes.

Além das agregações, a etapa final cria:

- `fe_credit_income_percent`: crédito solicitado dividido pela renda;
- `fe_annuity_income_percent`: anuidade dividida pela renda;
- `has_prev_app`, `has_bureau` e `has_installments_history`.

As flags diferenciam ausência de histórico de um histórico cujo indicador agregado vale zero. Os valores agregados ausentes são preenchidos com zero, enquanto a flag preserva a informação de que não houve observação.

O resultado é `application_abt`, contendo identificador, target e as features preditoras definidas em [`Model/config_model.json`](../../Model/config_model.json).

## Propriedades esperadas da ABT

- exatamente uma linha por `sk_id_curr`;
- target preservado da aplicação principal;
- ausência de duplicação causada pelos históricos;
- nomes e tipos compatíveis com a configuração do modelo;
- flags de presença coerentes com os agregados;
- razões financeiras protegidas contra divisão por zero;
- categorias já reduzidas e padronizadas.

O notebook [`exp_analysis_abt.ipynb`](../exp_analysis_abt.ipynb) verifica qualidade, duplicidade, nulos, constantes, força preditiva e multicolinearidade após a materialização.

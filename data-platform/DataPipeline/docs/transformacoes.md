# DataPipeline — Transformações

Referência detalhada das etapas de transformação do pipeline. Parte do [DataPipeline](../README.md).

## Por que ELT no PostgreSQL

Os arquivos de bureau, propostas e parcelas possuem centenas de megabytes. Transferir todas essas tabelas para a memória de um processo Python apenas para agregá-las aumentaria consumo, tempo de execução e risco de falha. A implementação adota ELT:

1. Python controla conexão, parâmetros, arquivos e ciclo das tarefas.
2. Os dados são carregados no PostgreSQL.
3. Limpeza, percentis, agregações e joins são executados em SQL pelo banco.

Essa escolha aproveita o otimizador do PostgreSQL, reduz movimentação de dados e mantém as transformações observáveis como tabelas intermediárias.

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

## Implementação da limpeza

[`data_sanitization.py`](../data_sanitization.py) cria novas tabelas em vez de sobrescrever as fontes brutas.

### `application_train → application_clean`

Uma CTE calcula estatísticas globais uma única vez e as aplica a todos os clientes:

- medianas dos três scores externos e de `ext_source_mean`;
- medianas de telefone, família, anuidade e renda;
- percentil configurável da renda para winsorização;
- mediana da idade do carro apenas entre clientes que possuem veículo;
- categorias de organização e renda com frequência mínima configurada.

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

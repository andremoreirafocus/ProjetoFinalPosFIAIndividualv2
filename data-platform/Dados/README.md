# Dados da entrega

Esta pasta representa o local previsto na estrutura de entrega para os artefatos de dados. Os arquivos CSV estão armazenados em [`airflow/data/csv`](../airflow/data/csv/), diretório compartilhado com o processo de ingestão e utilizado para reunir as fontes originais, as bases tratadas e a ABT final.

Essa organização preserva separadamente as quatro fontes do projeto, em vez de condensá-las em um único arquivo, e mantém no mesmo local os dados usados na entrada e os arquivos materializados manualmente para a entrega.

> **Observação:** para que os links abaixo funcionem, os arquivos precisam estar presentes em `airflow/data/csv`. As fontes brutas devem ser baixadas e colocadas nesse diretório antes da execução da pipeline. As bases tratadas e a ABT ficam disponíveis como CSV depois que a pipeline materializa as tabelas no PostgreSQL e o script `export_data.py` realiza a exportação.

## Arquivos brutos

| Arquivo | Conteúdo |
|---|---|
| [`application_train.csv`](../airflow/data/csv/application_train.csv) | Cadastro principal e variável-alvo, com uma linha por cliente. |
| [`previous_application.csv`](../airflow/data/csv/previous_application.csv) | Histórico de propostas de crédito anteriores. |
| [`bureau.csv`](../airflow/data/csv/bureau.csv) | Histórico de créditos registrados no bureau. |
| [`installments_payments.csv`](../airflow/data/csv/installments_payments.csv) | Histórico de vencimentos e pagamentos de parcelas. |

## Arquivos tratados

| Arquivo | Conteúdo |
|---|---|
| [`application_clean.csv`](../airflow/data/csv/application_clean.csv) | Cadastro principal após limpeza, padronização e engenharia de atributos cadastrais. |
| [`previous_application_clean.csv`](../airflow/data/csv/previous_application_clean.csv) | Propostas anteriores após seleção e tratamento dos registros. |
| [`bureau_clean.csv`](../airflow/data/csv/bureau_clean.csv) | Histórico de bureau após seleção e tratamento dos registros. |
| [`installments_clean.csv`](../airflow/data/csv/installments_clean.csv) | Parcelas após seleção e tratamento dos registros. |

## Base analítica

| Arquivo | Conteúdo |
|---|---|
| [`application_abt.csv`](../airflow/data/csv/application_abt.csv) | Analytical Base Table final, com uma linha por cliente e as features utilizadas na modelagem. |

Os arquivos tratados e a ABT são exportados manualmente do PostgreSQL pelo script [`export_data.py`](../DataPipeline/export_data.py). O procedimento de geração está descrito no [README do DataPipeline](../DataPipeline/README.md#exportação-de-tabelas-para-csv).

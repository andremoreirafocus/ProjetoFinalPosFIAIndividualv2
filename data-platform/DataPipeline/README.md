# DataPipeline

Esta pasta contém a lógica de ingestão, limpeza, agregação e construção da Analytical Base Table (ABT) do projeto de risco de crédito.

## Contexto do problema de dados

As fontes do Home Credit possuem granularidades diferentes. `application_train` tem uma linha por cliente, enquanto bureau, propostas anteriores e parcelas podem conter muitos registros para o mesmo `sk_id_curr`. Um join direto duplicaria clientes, distorceria o target e daria peso indevido a quem possui mais histórico.

O DataPipeline resolve esse problema em duas etapas: primeiro preserva e trata cada fonte; depois transforma os históricos um-para-muitos em indicadores agregados por cliente. A ABT final mantém a granularidade necessária ao aprendizado supervisionado: uma linha, um target e um conjunto consistente de features por cliente.

Além de preparar dados tecnicamente válidos, o componente busca preservar significado de negócio. Ausência de histórico é representada por flags próprias, anomalias cadastrais são isoladas e variáveis financeiras são tratadas sem apagar diferenças relevantes de risco.

## Responsabilidade

- carregar os CSVs de origem no PostgreSQL;
- criar índices para as etapas de transformação;
- limpar e padronizar as fontes de dados;
- agregar históricos por cliente;
- materializar a tabela `application_abt` com uma linha por cliente;
- documentar a exploração dos dados brutos e tratados.

## Por que ELT no PostgreSQL

Os arquivos de bureau, propostas e parcelas possuem centenas de megabytes. Transferir todas essas tabelas para a memória de um processo Python apenas para agregá-las aumentaria consumo, tempo de execução e risco de falha. A implementação adota ELT:

1. Python controla conexão, parâmetros, arquivos e ciclo das tarefas.
2. Os dados são carregados no PostgreSQL.
3. Limpeza, percentis, agregações e joins são executados em SQL pelo banco.

Essa escolha aproveita o otimizador do PostgreSQL, reduz movimentação de dados e mantém as transformações observáveis como tabelas intermediárias.

## Fluxo

```text
CSVs
  → tabelas brutas no PostgreSQL
  → tabelas *_clean
  → agregações de previous_application, bureau e installments
  → application_abt
  → treinamento do modelo
```

A execução completa é coordenada pela DAG descrita no [README do Airflow](../airflow/README.md).

## Arquivos principais

| Arquivo | Finalidade |
|---|---|
| [`ingestion.py`](./ingestion.py) | Carrega os CSVs em blocos no PostgreSQL. |
| [`ingestion_index.py`](./ingestion_index.py) | Cria índices nas tabelas de origem. |
| [`data_sanitization.py`](./data_sanitization.py) | Aplica limpeza e padronização por SQL. |
| [`data_sanitization_index.py`](./data_sanitization_index.py) | Recria índices nas tabelas tratadas. |
| [`abt_transform.py`](./abt_transform.py) | Agrega históricos e constrói a ABT. |
| [`export_data.py`](./export_data.py) | Utilitário manual para exportar tabelas do PostgreSQL como arquivos CSV de entrega. |
| [`utils.py`](./utils.py) | Centraliza conexões, carga e utilitários compartilhados. |
| [`config_pipeline.json`](./config_pipeline.json) | Define fontes, tabelas, chunks, índices e parâmetros de limpeza. |
| [`requirements.txt`](./requirements.txt) | Dependências para executar os scripts do pipeline fora do Airflow. |
| [`requirements-test.txt`](./requirements-test.txt) | Dependências dos testes: reusa `requirements.txt` e adiciona apenas as ferramentas de teste. |
| [`tests/`](./tests) | Suíte de testes de contrato do pipeline (ver seção [Testes](#testes)). |
| [`abt_fields.txt`](./abt_fields.txt) | Inventário textual dos campos da ABT. |
| [`df_correlations_with_target.txt`](./df_correlations_with_target.txt) | Registro auxiliar das correlações com o alvo. |

## Implementação da ingestão

[`ingestion.py`](./ingestion.py) recebe uma configuração de tabela por tarefa Airflow e executa:

1. validação de que a tabela pertence ao escopo de `config_pipeline.json`;
2. localização do CSV por nome normalizado;
3. tentativa de leitura UTF-8, com fallback para Latin-1;
4. leitura iterativa com `chunksize` específico para cada fonte;
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

[`data_sanitization.py`](./data_sanitization.py) cria novas tabelas em vez de sobrescrever as fontes brutas.

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

[`abt_transform.py`](./abt_transform.py) reduz cada histórico para uma linha por cliente antes do join final.

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

O resultado é `application_abt`, contendo identificador, target e as features preditoras definidas em [`Model/config_model.json`](../Model/config_model.json).

## Propriedades esperadas da ABT

- exatamente uma linha por `sk_id_curr`;
- target preservado da aplicação principal;
- ausência de duplicação causada pelos históricos;
- nomes e tipos compatíveis com a configuração do modelo;
- flags de presença coerentes com os agregados;
- razões financeiras protegidas contra divisão por zero;
- categorias já reduzidas e padronizadas.

O notebook [`exp_analysis_abt.ipynb`](./exp_analysis_abt.ipynb) verifica qualidade, duplicidade, nulos, constantes, força preditiva e multicolinearidade após a materialização.

## Fontes ingeridas

Os arquivos devem ser colocados em `data-platform/airflow/data/csv`:

- `application_train.csv`;
- `previous_application.csv`;
- `bureau.csv`;
- `installments_payments.csv`.

O escopo e o tamanho dos blocos são controlados por [`config_pipeline.json`](./config_pipeline.json).

## Configuração do pipeline

| Seção | Função |
|---|---|
| `ingestion_table.using_csv` | Fontes autorizadas e tamanho de cada chunk. |
| `database` | Nomes das tabelas brutas, tratadas e da ABT. |
| `indexes` | Chaves declaradas para apoio à indexação. |
| `sanitization.cardinalidade_min_freq` | Frequência mínima antes de agrupar categorias raras. |
| `sanitization.income_winsor_q` | Quantil máximo aplicado à renda. |

O Airflow lê essa configuração no carregamento da DAG e distribui os parâmetros às tarefas. Alterar nomes de tabela ou regras de sanitização deve ser coordenado com a DAG, notebooks e configuração do modelo.

## Metodologia da EDA e das decisões de preparação

As regras de limpeza e de engenharia de atributos acima não são arbitrárias: derivam de uma **análise exploratória sistemática**, organizada em **duas etapas** e com **métodos de avaliação escolhidos por tipo de variável**.

### EDA em duas etapas

- **Diagnóstico dos dados brutos** (`exp_analysis_raw.ipynb`): mede qualidade e comportamento das fontes *antes* de qualquer tratamento, para **decidir** cada regra de sanitização e cada feature derivada.
- **Validação da base limpa** (`exp_analysis_abt.ipynb`): roda *depois* do pipeline, sobre a ABT materializada, para **confirmar** que a sanitização atingiu o objetivo (sem nulos, sem duplicatas, sem constantes, redundâncias removidas) e que o sinal preditivo se preservou.

Separar as duas etapas evita misturar exploração com transformação e deixa explícito qual decisão veio de qual evidência.

### Métodos de avaliação de variáveis

A força de um preditor é sempre **medida**, nunca presumida — cada tipo de variável com o método adequado:

- **Pearson** — correlação linear das numéricas com o target;
- **Cramér's V** — associação das categóricas com o target (independe de ordem);
- **WOE / IV** (*Weight of Evidence / Information Value*) — métrica-padrão de força preditiva em risco de crédito, usada para manter ou descartar variáveis;
- **Matriz de correlação** — detecção de **multicolinearidade** entre preditoras redundantes.

### Regras de qualidade de dados (o método por trás da sanitização)

O tratamento segue um conjunto de regras, não decisões caso a caso:

- **descartar** blocos majoritariamente vazios (imputar só adicionaria ruído);
- separar **ausência de valor** criando **flag + imputação**, para não confundir "não tem" com "valor baixo";
- isolar **códigos-sentinela/anomalias** em flags próprias, em vez de deixá-los distorcer a distribuição;
- **winsorizar** outliers monetários extremos;
- **imputar variáveis assimétricas pela mediana** (robusta à cauda);
- **condensar categorias raras** e normalizar códigos inválidos;
- **podar pares redundantes** (manter uma variável de cada par de alta correlação).

A mesma lógica separa **ausência de histórico** de **histórico observado** por meio das flags de presença (`has_prev_app`, `has_bureau`, `has_installments_history`), evitando mascarar "sem dado" como se fosse comportamento.

## Notebooks

Os notebooks **aplicam** a metodologia acima; os resultados numéricos ficam neles, não neste README.

### [`exp_analysis_raw.ipynb`](./exp_analysis_raw.ipynb) — diagnóstico dos dados brutos

- **O que analisa:** as quatro fontes em estado bruto (`application_train`, `previous_application`, `bureau`, `installments_payments`).
- **O que busca estabelecer:** qualidade e comportamento (nulos, duplicatas, constantes, desbalanceamento do target, anomalias, cardinalidade) e o **poder preditivo** de cada variável — para **decidir** as regras de sanitização e as features da ABT.
- **Dados que cria e apresenta:** rankings de correlação (Pearson) e de associação (Cramér's V), tabelas de WOE/IV, distribuições e taxas de risco por faixa/categoria, e a lista de tratamentos/derivações que alimentam `data_sanitization.py` e `abt_transform.py`.

### [`exp_analysis_abt.ipynb`](./exp_analysis_abt.ipynb) — validação da base limpa

- **O que analisa:** a ABT final (`application_abt`) já materializada pelo pipeline.
- **O que busca estabelecer:** que a sanitização cumpriu seu papel (integridade: sem nulos/duplicatas/constantes; redundâncias removidas) e que o sinal preditivo e as features de histórico se comportam como esperado — além de sinalizar atributos sensíveis para governança.
- **Dados que cria e apresenta:** validações de integridade, rankings de correlação/associação e WOE/IV sobre a base limpa, matriz de multicolinearidade e a nota de fairness.

Os notebooks podem ser abertos pelo ambiente descrito em [Jupyter](../jupyter/README.md).

## Exportação de tabelas para CSV

[`export_data.py`](./export_data.py) é um **utilitário de execução manual** para preparar os arquivos CSV exigidos na entrega acadêmica a partir de tabelas já existentes no banco PostgreSQL `data`. Ele não integra a DAG, não é executado automaticamente pelo Airflow e não faz parte do processamento operacional recorrente.

O pipeline continua responsável por ingerir, tratar e materializar as tabelas no PostgreSQL. Depois que essas etapas estiverem concluídas, o responsável pela entrega executa o script sob demanda para transportar uma tabela do banco para um arquivo CSV, sem duplicar as regras de ingestão, limpeza ou construção da ABT.

A função `run_postgres_to_csv_export` recebe três parâmetros:

| Parâmetro | Finalidade |
|---|---|
| `conn_id` | Identificador mantido pelo utilitário de conexão compartilhado. Na execução manual local, `utils.py` utiliza o PostgreSQL em `localhost:5432/data`. |
| `source_table` | Nome da tabela que será exportada. |
| `output_dir_path` | Diretório de destino. O nome final é montado como `<source_table>.csv`. |

Antes da exportação, o script registra a quantidade de linhas da tabela. Em seguida, utiliza `COPY TO STDOUT WITH CSV HEADER`, fazendo o PostgreSQL transmitir os registros diretamente para o arquivo. Essa estratégia evita montar um `DataFrame` com toda a tabela em memória e é adequada para a volumetria da ABT.

### Preparação do ambiente local

Execute os comandos de preparação a partir da raiz do repositório:

```bash
python3 -m venv data-platform/DataPipeline/.venv
data-platform/DataPipeline/.venv/bin/python -m pip install \
  -r data-platform/DataPipeline/requirements.txt
```

O PostgreSQL deve estar ativo, o banco `data` deve estar acessível pela porta local `5432` e a tabela a ser exportada deve ter sido previamente materializada pelo pipeline. Para iniciar somente o banco:

```bash
docker compose -f data-platform/docker-compose.yml up -d postgres
```

### Execução manual

Entre na pasta `DataPipeline` para que o caminho relativo de saída seja resolvido para `data-platform/airflow/data/csv`:

```bash
cd data-platform/DataPipeline
set -a
source ../.env
set +a
.venv/bin/python export_data.py
```

O carregamento de `../.env` exporta para o processo local as variáveis de conexão
com o PostgreSQL usadas por `utils.py`.

Na configuração atual do bloco `__main__`, o comando exporta:

| Tabela PostgreSQL | Arquivo gerado |
|---|---|
| `application_clean` | `airflow/data/csv/application_clean.csv` |
| `previous_application_clean` | `airflow/data/csv/previous_application_clean.csv` |
| `bureau_clean` | `airflow/data/csv/bureau_clean.csv` |
| `installments_clean` | `airflow/data/csv/installments_clean.csv` |
| `application_abt` | `airflow/data/csv/application_abt.csv` |

Esses arquivos são gravados ao lado dos quatro CSVs brutos usados na ingestão. Assim, o diretório reúne as fontes originais, suas representações tratadas e a ABT final. O caminho é relativo ao diretório de execução; por isso, o comando deve ser iniciado em `data-platform/DataPipeline`.

Os arquivos já foram materializados em `data-platform/airflow/data/csv`, pasta originalmente destinada aos arquivos brutos. Atualmente ela reúne:

- as quatro fontes brutas: `application_train.csv`, `previous_application.csv`, `bureau.csv` e `installments_payments.csv`;
- as quatro bases tratadas: `application_clean.csv`, `previous_application_clean.csv`, `bureau_clean.csv` e `installments_clean.csv`;
- a base analítica final: `application_abt.csv`.

A convivência no mesmo diretório atende à preparação manual da entrega. Os sufixos `_clean` e `_abt` distinguem claramente os arquivos gerados pelo pipeline das fontes brutas usadas na ingestão.

### Exportação de outra tabela

O script expõe uma função reutilizável para chamadas manuais em outro módulo Python:

```python
from export_data import run_postgres_to_csv_export

run_postgres_to_csv_export(
    conn_id="postgres_data_db",
    source_table="application_clean",
    output_dir_path="../airflow/data/csv",
)
```

Esse exemplo, executado a partir de `data-platform/DataPipeline`, gera `data-platform/airflow/data/csv/application_clean.csv`. A função exporta uma tabela por chamada e usa o nome da tabela para identificar claramente o conteúdo do arquivo.

## Execução

O caminho recomendado é iniciar PostgreSQL e Airflow e disparar a DAG `pipeline_orchestration`:

```bash
cd data-platform
docker compose up -d --build postgres airflow-init airflow-webserver airflow-scheduler
```

Depois, acesse http://localhost:8080, localize `pipeline_orchestration` e inicie uma execução manual.

## Saídas

- tabelas brutas no banco `data`;
- tabelas tratadas com sufixo `_clean`;
- agregações temporárias por cliente;
- ABT `application_abt`.

Os arquivos CSV de entrega não fazem parte das saídas automáticas da DAG. Eles são produzidos posteriormente, sob demanda, pelo utilitário manual [`export_data.py`](./export_data.py).

## Observabilidade do processamento

As funções registram no log:

- tabela e etapa em processamento;
- quantidade de registros na entrada e saída;
- número do chunk durante a ingestão;
- criação de índices e agregações;
- conclusão ou rollback em caso de erro.

Esses eventos aparecem nos logs das tarefas do Airflow e permitem localizar quedas inesperadas de volumetria entre as camadas.

## Testes

A suíte valida os contratos funcionais de cada etapa do pipeline (ingestão, índices, sanitização, agregações e ABT) executando as funções reais contra um banco PostgreSQL **de testes dedicado** (`data_test`), isolado do banco de produção `data`. Não há mocks: a configuração é injetada pelo mesmo limite de ambiente que a produção usa.

### Pré-requisitos

1. **PostgreSQL ativo** em `localhost:5432`:

   ```bash
   docker compose -f data-platform/docker-compose.yml up -d postgres
   ```

2. **Banco e papel de teste provisionados** (`data_test` e `data_test_user`). Em um volume novo isso é automático; em um volume já existente, aplique uma vez o script de bootstrap descrito no [README do PostgreSQL](../postgres/README.md#ambiente-de-testes-isolado).

3. **Dependências de teste instaladas** (produção + ferramentas de teste, a partir da raiz do repositório):

   ```bash
   python3 -m venv data-platform/DataPipeline/.venv
   data-platform/DataPipeline/.venv/bin/python -m pip install \
     -r data-platform/DataPipeline/requirements-test.txt
   ```

A conexão da suíte é lida de [`tests/test_database.ini`](./tests/test_database.ini) — versionado com credenciais locais de demonstração, sem leitura de variáveis de ambiente com fallback. Um guard aborta a execução se o alvo não for um banco `*_test` distinto do banco de produção.

### Execução

A partir de `data-platform/DataPipeline`:

```bash
cd data-platform/DataPipeline
.venv/bin/python -m pytest                       # suíte completa
.venv/bin/python -m pytest -m integration        # apenas testes que tocam o banco
.venv/bin/python -m pytest -m "not integration"  # apenas validações puras (sem banco)
```

Os testes marcados como `integration` exigem o banco `data_test`; os demais rodam sem PostgreSQL.

## Componentes relacionados

- [PostgreSQL](../postgres/README.md)
- [Airflow](../airflow/README.md)
- [Jupyter](../jupyter/README.md)
- [Modelo](../Model/README.md)

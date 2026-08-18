# Protótipo executável do agente de apoio à revisão humana

Este diretório materializa o fluxo proposto para gerar um relatório de apoio à
revisão manual de crédito. O protótipo combina dados produzidos pela API, regras de
governança do catálogo de features, composição narrativa por um LLM e montagem
controlada do JSON consumido pelo template do relatório, seguida da renderização
determinística do PDF.

O objetivo é validar concretamente:

- quais informações devem chegar ao modelo de linguagem;
- quais informações o LLM pode produzir;
- como impedir que o LLM altere score, política, SHAP ou referências estatísticas;
- como associar a narrativa validada aos dados originais do caso;
- se o relatório resultante é útil e verificável para o analista.

O protótipo não toma decisão de crédito. A recomendação da política é preservada e a
decisão final permanece com o analista humano.

## Por que usar um LLM

O LLM não é necessário para calcular o score, combinar arquivos JSON ou recuperar a
semântica das features. Antes da chamada ao modelo de linguagem, a solução já
selecionou as evidências autorizadas e associou cada fator ao seu valor, contribuição
SHAP, direção, significado e comparação com a população de treinamento.

O valor do LLM está na **síntese contextual em linguagem natural**. Cada caso pode
apresentar um conjunto diferente de fatores relevantes, com evidências numéricas ou
categóricas e diferentes posições em relação à população. O modelo de linguagem
transforma essa combinação variável em:

- uma síntese específica do caso;
- uma explicação do enquadramento na política;
- uma explicação compreensível de cada fator;
- uma conclusão que relaciona o valor do cliente, a direção da contribuição e as
  referências estatísticas disponíveis;
- limitações apresentadas de maneira consistente para o analista.

Produzir essa narrativa apenas com textos fixos exigiria reproduzir em condicionais
as diferentes combinações de fatores e contextos estatísticos. O template continua
sendo a escolha adequada para conteúdo fixo, estrutura e identidade visual; o LLM é
usado somente na parte variável de composição textual.

Essa flexibilidade não transfere ao LLM o controle dos fatos. O prompt restringe a
resposta ao contexto fornecido, e o processamento posterior exige exatamente as
features autorizadas, preserva suas direções e reassocia a narrativa aos valores
originais. Score, política, SHAP, referências estatísticas e rastreabilidade permanecem
sob controle determinístico.

Se o objetivo fosse apenas exibir campos fixos, o template seria suficiente e o LLM
não se justificaria. Neste protótipo, ele é utilizado porque o resultado esperado
inclui uma explicação contextualizada para combinações variáveis de evidências, sem
permitir que o modelo de linguagem altere a decisão ou os dados que a fundamentam.

O README anterior, que documentava a construção manual dos primeiros artefatos, foi
preservado em [`archive/README.md`](archive/README.md).

## Fluxo implementado

```text
resposta da API + catálogo de features
                  │
                  ▼
       prepare_llm_context.py
       associa · enriquece · filtra
                  │
                  ▼
       contexto governado para o LLM
                  │
                  ▼
             invoke_llm.py
       aplica o prompt · invoca Groq
                  │
                  ▼
          resposta narrativa JSON
                  │
                  ▼
       process_llm_response.py
       valida · reassocia · consolida
                  │
                  ▼
          JSON final do relatório
                  │
                  ▼
         render_report_pdf.py
       aplica template HTML/Jinja
                  │
                  ▼
                  PDF
```

Os quatro scripts separam responsabilidades que não devem ser confundidas:

1. preparar e governar o contexto;
2. invocar o modelo de linguagem;
3. validar sua resposta e montar o relatório final;
4. renderizar o relatório por meio de um template fixo.

O LLM recebe somente `llm_context`. Os fatores excluídos por governança e os dados de
controle do processamento não são incluídos no prompt.

O script `run_sample_report_pipeline.sh` apenas executa essas quatro fronteiras em
sequência. Ele não incorpora nem duplica a lógica interna das etapas.

## Requisitos

O ambiente Python usado pelo projeto deve receber as dependências específicas do
protótipo:

```bash
cd data-platform
MLOps/.venv/bin/python -m pip install \
  -r MLOps/agent-manual-review/agent-requirements.txt
```

O arquivo [`agent-requirements.txt`](agent-requirements.txt) fixa as versões de:

- `langchain-groq`, usado para acessar o Groq por meio do LangChain;
- `python-dotenv`, usado para ler a configuração local;
- `Jinja2`, usado para aplicar o relatório ao template HTML;
- `WeasyPrint`, usado para converter o HTML renderizado em PDF.

## Configuração local

Os scripts `invoke_llm.py` e `render_report_pdf.py` leem suas respectivas
configurações no arquivo local:

```text
MLOps/agent-manual-review/.env
```

Crie o arquivo local a partir do exemplo versionado:

```bash
cp MLOps/agent-manual-review/.env.example MLOps/agent-manual-review/.env
```

Consulte o arquivo de referência [`.env.example`](.env.example).

O exemplo contém a configuração do template atual:

```dotenv
REPORT_TEMPLATE=credit_review_report_v1.html.j2
```

Essa variável é obrigatória para `render_report_pdf.py` e deve conter somente o nome
do template, que deve existir no mesmo diretório dos scripts. O renderizador não
aceita um caminho alternativo e não escolhe outro template quando a configuração está
ausente ou inválida.

Para executar `invoke_llm.py`, substitua localmente o placeholder pelo valor da chave:

```dotenv
GROQ_API_KEY=insira_a_chave_aqui
```

A chave é lida exclusivamente desse arquivo e passada explicitamente ao `ChatGroq`.
Uma variável `GROQ_API_KEY` previamente exportada no processo não substitui o valor
do arquivo.

O `.env` é ignorado pelo Git e permanece somente no ambiente local. Assim, a
configuração do template e a `GROQ_API_KEY` usadas na execução não são versionadas.

## Execução orquestrada do sample

O sample da API contém `model_version: "1.0.0"`, correspondente à versão registrada
em `Model/config_model.json`. Portanto, ele atende ao contrato de rastreabilidade e
pode percorrer o fluxo completo.

Antes da execução, acrescente uma `GROQ_API_KEY` válida ao `.env` e confirme que os
quatro arquivos de saída ainda não existem no diretório do protótipo. Em seguida,
execute:

```bash
cd data-platform
bash MLOps/agent-manual-review/run_sample_report_pipeline.sh
```

O orquestrador usa diretamente:

- `sample_api_response_with_explanation.json`;
- `MLOps/config/feature_catalog.json`;
- `agent_report_prompt_v1.json`;
- o modelo Groq `openai/gpt-oss-20b`;
- o template definido por `REPORT_TEMPLATE`.

Cada script define como constantes seus arquivos de entrada e saída. O nome da saída
de uma etapa é exatamente o nome da entrada consumida pela etapa seguinte:

| Etapa | Nome do arquivo |
|---|---|
| Contexto preparado | `sample_agent_context_before_llm.json` |
| Resposta do LLM | `sample_llm_response_to_report_request.json` |
| Relatório consolidado | `sample_agent_report.json` |
| PDF final | `sample_credit_review_report_v4.pdf` |

Cada etapa recusa sua saída quando o arquivo já existe. O `set -e` do Bash interrompe
o fluxo na primeira falha, portanto as etapas seguintes não são executadas.

## Logging

Os quatro scripts usam a mesma configuração definida em `script_logging.py`. Cada
registro é enviado simultaneamente ao terminal e a um arquivo no diretório do
protótipo:

| Script | Arquivo de log |
|---|---|
| `prepare_llm_context.py` | `prepare_llm_context.log` |
| `invoke_llm.py` | `invoke_llm.log` |
| `process_llm_response.py` | `process_llm_response.log` |
| `render_report_pdf.py` | `render_report_pdf.log` |

Os arquivos são abertos em modo de acréscimo e estão ignorados pelo `.gitignore`. Os
registros informam início, entradas e saídas operacionais, conclusão e falhas, sem
gravar a chave do Groq nem o conteúdo do prompt.

## Execução manual etapa a etapa

Os scripts não recebem argumentos de linha de comando. Para executá-los
individualmente, use a ordem abaixo a partir de `data-platform`.

### 1. Preparar o contexto do LLM

```bash
MLOps/.venv/bin/python MLOps/agent-manual-review/prepare_llm_context.py
```

#### Entradas

`API_RESPONSE_PATH`

: Resposta da API contendo identificação do caso, score, classe, política,
  explicação local e `model_version`.

`FEATURE_CATALOG_PATH`

: Catálogo com semântica, formato, unidade, restrições e `allowed_in_report` para
  cada feature.

`PROMPT_CONTRACT_PATH`

: Contrato de prompt do qual a versão obrigatória é lida.

`CONTEXT_OUTPUT_PATH`

: Arquivo `sample_agent_context_before_llm.json`, que receberá o contexto preparado.

#### Processamento

O script:

1. valida a estrutura da resposta e do catálogo;
2. associa cada fator ao catálogo usando `feature`;
3. acrescenta rótulo, descrição, tipo, formato, unidade e semântica;
4. mantém no `llm_context` somente fatores com `allowed_in_report: true`;
5. registra separadamente os fatores excluídos e o motivo;
6. preserva valor do cliente, contribuição SHAP e referências estatísticas;
7. registra versões do modelo, da política, do catálogo e do prompt;
8. informa em `validation.ready_for_llm` se o contexto pode ser enviado ao LLM.

Uma feature explicada pela API e ausente do catálogo constitui erro de contrato. Nesse
caso, nenhum arquivo é escrito.

#### Rastreabilidade do sample atual

O arquivo
[`sample_api_response_with_explanation.json`](sample_api_response_with_explanation.json)
possui `model_version: "1.0.0"`. Com o catálogo e a versão do prompt atuais, o contexto
produzido recebe `ready_for_llm: true`.

O arquivo
[`sample_agent_context_before_llm.json`](archive/sample_agent_context_before_llm.json) foi
preservado como resultado histórico de uma execução anterior, realizada quando o
sample da API ainda não continha `model_version`. Por isso, esse arquivo arquivado
mantém `model_version: null` e `ready_for_llm: false`; ele não representa a saída que
será produzida pela execução atual.

### 2. Invocar o LLM com LangChain e Groq

```bash
MLOps/.venv/bin/python MLOps/agent-manual-review/invoke_llm.py
```

#### Entradas

`CONTEXT_INPUT_PATH`

: Contexto produzido por `prepare_llm_context.py`.

`PROMPT_CONTRACT_PATH`

: Contrato que contém `system_prompt`, `user_prompt_template`, versão e schema da
  resposta.

`LLM_MODEL`

: Identificador explícito do modelo disponível no Groq.

`LLM_TIMEOUT_SECONDS`

: Limite explícito de duração da chamada.

`LLM_RESPONSE_OUTPUT_PATH`

: Arquivo `sample_llm_response_to_report_request.json`, que receberá somente a
  resposta narrativa estruturada.

#### Processamento

Antes de chamar o Groq, o script:

- exige `validation.ready_for_llm: true`;
- confirma que a versão do prompt no contexto corresponde ao contrato informado;
- insere somente `llm_context` no template do prompt;
- exige saída estruturada conforme o JSON Schema do contrato;
- usa temperatura zero;
- desativa retry interno, pois retry pertence à futura orquestração.

O LLM produz:

- síntese do caso;
- explicação do enquadramento na política;
- explicação narrativa de cada fator;
- conclusão contextualizada de cada fator;
- limitações;
- aviso de decisão humana.

Ele não produz nem recalcula os valores do cliente, score, política, SHAP, percentis
ou estatísticas populacionais.

### 3. Validar a resposta e montar o relatório

```bash
MLOps/.venv/bin/python MLOps/agent-manual-review/process_llm_response.py
```

#### Entradas

`CONTEXT_INPUT_PATH`

: Mesmo contexto que foi enviado ao LLM.

`LLM_RESPONSE_INPUT_PATH`

: Resposta estruturada salva por `invoke_llm.py`.

`AGENT_REPORT_OUTPUT_PATH`

: Arquivo `sample_agent_report.json`, que receberá o relatório consolidado.

#### Etapa A — validação da resposta

O script rejeita a resposta quando:

- o schema possui campos ausentes ou extras;
- aparece uma feature não autorizada;
- uma feature autorizada é omitida ou duplicada;
- a direção da contribuição difere do contexto original;
- a feature aparece na lista incompatível com sua direção;
- os textos obrigatórios estão vazios;
- as limitações mínimas não foram apresentadas;
- o contexto original não estava pronto para o LLM.

#### Etapa B — montagem do relatório

Somente depois da validação, o script:

1. associa cada narrativa à feature original;
2. recupera do contexto o valor do cliente;
3. recupera contribuição SHAP e direção;
4. recupera comparações e referências estatísticas;
5. acrescenta semântica, score, política e rastreabilidade;
6. gera um `report_id` em UUID;
7. registra `generated_at` em UTC;
8. grava o JSON final consumido pelo template.

O processo de associação é determinístico: a narrativa vem do LLM, enquanto os dados
do caso e as referências estatísticas são copiados das fontes controladas.

### 4. Renderizar o PDF

```bash
MLOps/.venv/bin/python MLOps/agent-manual-review/render_report_pdf.py
```

#### Entradas

`AGENT_REPORT_INPUT_PATH`

: JSON consolidado produzido por `process_llm_response.py`.

`REPORT_TEMPLATE`

: Nome do template HTML/Jinja definido no `.env` local. O template deve estar no
  diretório `MLOps/agent-manual-review`.

`FINAL_PDF_OUTPUT_PATH`

: Arquivo `sample_credit_review_report_v4.pdf`, que receberá o relatório
  renderizado.

#### Processamento

O script:

1. exige a configuração explícita de `REPORT_TEMPLATE`;
2. carrega o relatório como um objeto JSON;
3. aplica o template com `report` como objeto raiz;
4. rejeita variáveis do template ausentes no relatório;
5. converte o HTML em PDF com WeasyPrint;
6. confirma que o renderizador devolveu um documento PDF;
7. grava o resultado sem sobrescrever arquivos existentes.

## Contrato de não sobrescrita

Os quatro scripts recusam seu arquivo de saída quando ele já existe. A verificação
ocorre antes da gravação e, no caso da chamada ao LLM, antes de consumir a API
externa.

Para uma nova execução, remova deliberadamente os resultados descartáveis da execução
anterior ou mova-os para um local apropriado. Os scripts não implementam sobrescrita
automática.

Para remover somente os quatro outputs reproduzíveis antes de uma nova execução:

```bash
cd data-platform
bash MLOps/agent-manual-review/cleanup_generated_artifacts.sh
```

O script usa caminhos explícitos, não acessa `archive/` e preserva os arquivos de
log.

## Entradas e contratos do protótipo

| Arquivo | Papel |
|---|---|
| [`sample_api_response_with_explanation.json`](sample_api_response_with_explanation.json) | Resposta técnica demonstrativa da API. |
| [`../config/feature_catalog.json`](../config/feature_catalog.json) | Catálogo semântico e de governança. |
| [`agent_report_prompt_v1.json`](agent_report_prompt_v1.json) | Prompt versionado e schema da resposta. |
| [`credit_review_report_v1.html.j2`](credit_review_report_v1.html.j2) | Template HTML/Jinja do PDF. |

Esses arquivos fornecem as entradas demonstrativas e os contratos usados para
executar o fluxo. O arquivo `sample_api_response_with_explanation.json` é uma amostra
de entrada, não uma saída a ser regenerada pelos scripts.

## Outputs demonstrativos arquivados

| Arquivo | Etapa que exemplifica |
|---|---|
| [`sample_agent_context_before_llm.json`](archive/sample_agent_context_before_llm.json) | Contexto preparado por `prepare_llm_context.py`. |
| [`sample_llm_response_to_report_request.json`](archive/sample_llm_response_to_report_request.json) | Resposta estruturada obtida após a solicitação de composição do relatório ao LLM. |
| [`sample_agent_report.json`](archive/sample_agent_report.json) | Relatório consolidado por `process_llm_response.py`. |
| [`sample_credit_review_report.pdf`](archive/sample_credit_review_report.pdf) | Primeira iteração do PDF. |
| [`sample_credit_review_report_v2.pdf`](archive/sample_credit_review_report_v2.pdf) | Segunda iteração do PDF. |
| [`sample_credit_review_report_v3.pdf`](archive/sample_credit_review_report_v3.pdf) | Terceira iteração histórica do PDF. |

Esses outputs são referências históricas imutáveis da execução demonstrativa. Os
scripts não os usam como fallback e não escrevem no diretório `archive`.

O arquivo [`sample_credit_review_report_v4.pdf`](sample_credit_review_report_v4.pdf),
mantido na raiz do protótipo, é o resultado demonstrativo atual e corresponde à saída
produzida pelo fluxo e pelo template vigentes.

## Testes

Execute:

```bash
cd data-platform/MLOps
.venv/bin/python -m pytest tests/test_agent_manual_review_scripts.py -v
```

Os testes usam fixtures de domínio e um fake explícito para o colaborador LLM. Não
fazem chamadas ao Groq, não dependem de uma chave real e não interceptam funções em
tempo de execução. A integração local com o WeasyPrint é exercitada em diretório
temporário para confirmar a geração de um PDF válido.

Os contratos testados incluem:

- enriquecimento pelo catálogo;
- filtragem e auditoria das features restritas;
- bloqueio por rastreabilidade incompleta;
- correspondência da versão do prompt;
- leitura da credencial no `.env` local;
- preparação das mensagens;
- invocação por uma interface de LLM estruturado;
- rejeição de feature não autorizada, omitida ou com direção alterada;
- reassociação dos dados originais à narrativa;
- leitura obrigatória de `REPORT_TEMPLATE`;
- aplicação do template ao relatório;
- validação do retorno do renderizador;
- correspondência entre a versão do sample e a configuração de treinamento;
- encadeamento dos nomes de entrada e saída das quatro etapas;
- logging simultâneo no terminal e no arquivo homônimo do script;
- proibição de sobrescrita das quatro saídas.

## O que está pronto e o que ainda falta

O protótipo já materializa de ponta a ponta:

- preparação governada do caso;
- contrato versionado do prompt;
- chamada real possível ao LLM pelo Groq;
- persistência da resposta narrativa;
- validação pós-LLM;
- montagem do JSON final;
- orquestração sequencial do fluxo demonstrativo;
- renderização determinística do PDF com o template configurado.

Para se tornar uma solução produtiva ainda são necessários:

- inclusão de `model_version` no contrato da API;
- orquestração produtiva assíncrona das quatro etapas;
- mensageria e processamento assíncrono;
- persistência durável de contexto, resposta e relatório;
- idempotência;
- política de retry e tratamento de indisponibilidade;
- observabilidade centralizada para o ambiente de produção;
- gestão de segredos apropriada ao ambiente;
- armazenamento durável do PDF.

A arquitetura produtiva proposta permanece documentada em
[`../AGENT_ARCHITECTURE.md`](../AGENT_ARCHITECTURE.md).

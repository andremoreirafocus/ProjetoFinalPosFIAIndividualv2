# Protótipo executável do agente de apoio à revisão humana

Este diretório materializa o fluxo proposto para gerar um relatório de apoio à
revisão manual de crédito. O protótipo combina dados produzidos pela API, regras de
governança do catálogo de features, composição narrativa por um LLM e montagem
controlada do JSON consumido pelo template do relatório.

O objetivo é validar concretamente:

- quais informações devem chegar ao modelo de linguagem;
- quais informações o LLM pode produzir;
- como impedir que o LLM altere score, política, SHAP ou referências estatísticas;
- como associar a narrativa validada aos dados originais do caso;
- se o relatório resultante é útil e verificável para o analista.

O protótipo não toma decisão de crédito. A recomendação da política é preservada e a
decisão final permanece com o analista humano.

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
       template HTML/Jinja → PDF
```

Os três scripts separam responsabilidades que não devem ser confundidas:

1. preparar e governar o contexto;
2. invocar o modelo de linguagem;
3. validar sua resposta e montar o relatório final.

O LLM recebe somente `llm_context`. Os fatores excluídos por governança e os dados de
controle do processamento não são incluídos no prompt.

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
- `python-dotenv`, usado para ler a credencial local.

## Configuração da credencial do Groq

O script `invoke_llm.py` lê obrigatoriamente:

```text
MLOps/agent-manual-review/.env
```

Conteúdo esperado:

```dotenv
GROQ_API_KEY=insira_a_chave_aqui
```

A chave é lida exclusivamente desse arquivo e passada explicitamente ao `ChatGroq`.
Uma variável `GROQ_API_KEY` previamente exportada no processo não substitui o valor
do arquivo.

O `.env` contém um segredo e não deve ser versionado. No estado atual do repositório,
esse caminho ainda não está protegido pelo `.gitignore`; essa proteção deve ser
adicionada antes da criação de um `.env` real dentro do diretório.

## Execução completa

Os exemplos abaixo escrevem as saídas em `/tmp` para não alterar nem sobrescrever os
artefatos de demonstração existentes:

```bash
mkdir -p /tmp/manual-review-agent-demo
cd data-platform
```

### 1. Preparar o contexto do LLM

```bash
MLOps/.venv/bin/python \
  MLOps/agent-manual-review/prepare_llm_context.py \
  --api-response /caminho/para/api_response_with_model_version.json \
  --feature-catalog MLOps/config/feature_catalog.json \
  --prompt-version 1.2.0 \
  --output /tmp/manual-review-agent-demo/context.json
```

#### Entradas

`--api-response`

: Resposta da API contendo identificação do caso, score, classe, política,
  explicação local e `model_version`.

`--feature-catalog`

: Catálogo com semântica, formato, unidade, restrições e `allowed_in_report` para
  cada feature.

`--prompt-version`

: Versão do contrato de prompt que será usada na chamada ao LLM. O parâmetro pode
  ser omitido para gerar um contexto de auditoria, mas esse contexto receberá
  `ready_for_llm: false`.

`--output`

: Novo arquivo que receberá o contexto preparado.

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

#### Limitação do sample atual

O arquivo
[`sample_api_response_with_explanation.json`](sample_api_response_with_explanation.json)
não possui `model_version`. Por isso, ele pode ser usado para demonstrar e reproduzir
a preparação do contexto, mas o resultado será corretamente marcado como
`ready_for_llm: false`.

O arquivo
[`sample_agent_context_before_llm.json`](archive/sample_agent_context_before_llm.json) foi
reproduzido pelo script a partir do sample da API e do catálogo. Os valores de
`source_files` refletem literalmente os caminhos fornecidos na linha de comando.

### 2. Invocar o LLM com LangChain e Groq

```bash
MLOps/.venv/bin/python \
  MLOps/agent-manual-review/invoke_llm.py \
  --context /tmp/manual-review-agent-demo/context.json \
  --prompt-contract MLOps/agent-manual-review/agent_report_prompt_v1.json \
  --model openai/gpt-oss-20b \
  --timeout-seconds 60 \
  --output /tmp/manual-review-agent-demo/llm_response.json
```

#### Entradas

`--context`

: Contexto produzido por `prepare_llm_context.py`.

`--prompt-contract`

: Contrato que contém `system_prompt`, `user_prompt_template`, versão e schema da
  resposta.

`--model`

: Identificador explícito do modelo disponível no Groq.

`--timeout-seconds`

: Limite explícito de duração da chamada.

`--output`

: Novo arquivo que receberá somente a resposta narrativa estruturada.

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
MLOps/.venv/bin/python \
  MLOps/agent-manual-review/process_llm_response.py \
  --context /tmp/manual-review-agent-demo/context.json \
  --llm-response /tmp/manual-review-agent-demo/llm_response.json \
  --output /tmp/manual-review-agent-demo/agent_report.json
```

#### Entradas

`--context`

: Mesmo contexto que foi enviado ao LLM.

`--llm-response`

: Resposta estruturada salva por `invoke_llm.py`.

`--output`

: Novo arquivo que receberá o relatório consolidado.

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

## Contrato de não sobrescrita

Os três scripts recusam um `--output` que já exista. A verificação ocorre antes da
gravação e, no caso da chamada ao LLM, antes de consumir a API externa.

Para uma nova execução, informe um novo caminho ou remova deliberadamente uma saída
descartável fora do repositório. Os scripts não implementam sobrescrita automática.

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
| [`sample_credit_review_report_v3.pdf`](archive/sample_credit_review_report_v3.pdf) | Terceira iteração e último PDF produzido durante a validação. |

Esses outputs são referências históricas imutáveis da execução demonstrativa. Os
scripts não os usam como fallback e uma nova execução não deve apontar `--output`
para o diretório `archive`. Use caminhos novos, como os exemplos em `/tmp`, para
preservar os resultados já validados.

## Renderização do PDF

O JSON produzido por `process_llm_response.py` corresponde à entrada esperada pelo
template [`credit_review_report_v1.html.j2`](credit_review_report_v1.html.j2).

A renderização HTML/Jinja para PDF ainda não foi encapsulada em um quarto script. O
template atual já contém a correção do título do apêndice para **“Indicadores do caso
e referências estatísticas”**. Portanto, o próximo PDF deverá ser salvo como uma nova
versão, preservando a v3.

## Testes

Execute:

```bash
cd data-platform
MLOps/.venv/bin/python \
  -m unittest MLOps.tests.test_agent_manual_review_scripts -v
```

Os testes usam fixtures e um fake explícito para o colaborador LLM. Não fazem chamadas
ao Groq, não dependem de uma chave real e não interceptam funções em tempo de
execução.

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
- proibição de sobrescrita das três saídas.

## O que está pronto e o que ainda falta

O protótipo já materializa de ponta a ponta:

- preparação governada do caso;
- contrato versionado do prompt;
- chamada real possível ao LLM pelo Groq;
- persistência da resposta narrativa;
- validação pós-LLM;
- montagem do JSON final;
- template e exemplo de PDF.

Para se tornar uma solução produtiva ainda são necessários:

- inclusão de `model_version` no contrato da API;
- orquestração das três etapas;
- mensageria e processamento assíncrono;
- persistência durável de contexto, resposta e relatório;
- idempotência;
- política de retry e tratamento de indisponibilidade;
- observabilidade;
- gestão de segredos apropriada ao ambiente;
- automatização da renderização e do armazenamento do PDF.

A arquitetura produtiva proposta permanece documentada em
[`../AGENT_ARCHITECTURE.md`](../AGENT_ARCHITECTURE.md).

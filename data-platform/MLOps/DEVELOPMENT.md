# Desenvolvimento, execução e testes

Este documento reúne instruções de empacotamento, execução local e validação dos componentes MLOps.

## Estrutura

```text
MLOps/
├── app/
│   ├── api/
│   │   ├── main.py
│   │   ├── config.py
│   │   ├── schemas.py
│   │   ├── artifact_bundle_loader.py
│   │   ├── model_bundle.py
│   │   ├── model_bundle_manager.py
│   │   ├── feature_input_processor.py
│   │   ├── prediction_service.py
│   │   ├── explanation_service.py
│   │   ├── feature_service.py
│   │   ├── credit_policy.py
│   │   └── requirements.txt
│   ├── cli/
│   │   ├── predict.py
│   │   ├── find_customer_by_score.py
│   │   └── requirements.txt
│   └── frontend/
│       ├── app.py
│       ├── field_config.py
│       └── requirements.txt
├── agent-manual-review/
│   ├── .env.example
│   ├── agent-requirements.txt
│   ├── agent_report_prompt_v1.json
│   ├── credit_review_report_v1.html.j2
│   ├── script_logging.py
│   ├── prepare_llm_context.py
│   ├── invoke_llm.py
│   ├── process_llm_response.py
│   ├── render_report_pdf.py
│   ├── run_sample_report_pipeline.sh
│   ├── cleanup_generated_artifacts.sh
│   └── README.md
├── config/
│   └── feature_catalog.json
├── tests/
├── API.md
├── FRONTEND.md
├── DEVELOPMENT.md
├── AGENT_ARCHITECTURE.md
├── MONITORING_ARCHITECTURE.md
├── monitoring_reference.json
├── Dockerfile.api
├── Dockerfile.frontend
├── pytest.ini
├── requirements-test.txt
└── README.md
```

## Inicialização com Docker

Na pasta `data-platform`:

```bash
docker compose up -d --build postgres credit-api credit-frontend
```

Para acompanhar os serviços:

```bash
docker compose logs -f credit-api credit-frontend
```

| Serviço | URL |
|---|---|
| Swagger | http://localhost:8000/docs |
| Health check | http://localhost:8000/health |
| Streamlit | http://localhost:8501 |

## Empacotamento

### API

`Dockerfile.api` instala as dependências da API, copia o código de `MLOps` e inicia Uvicorn na porta 8000.

O artefato não é embutido na imagem. O diretório `./Model/artifacts` é montado como somente leitura em `/app/Model/artifacts`. Um novo treinamento atualiza os arquivos no volume sem exigir novo build ou reinício da API: o modelo e suas referências são recarregados automaticamente quando formam um par compatível.

### Frontend

`Dockerfile.frontend` instala Streamlit e Requests, copia a aplicação e inicia o servidor na porta 8501. A comunicação interna utiliza `http://credit-api:8000`.

Como o código das aplicações é copiado durante o build, alterações em arquivos Python exigem reconstrução da imagem correspondente.

## Execução local

Com PostgreSQL e artefato disponíveis, crie o ambiente e inicie a API:

```bash
cd data-platform
python3 -m venv MLOps/.venv
MLOps/.venv/bin/python -m pip install -r MLOps/app/api/requirements.txt
set -a
source .env
set +a
export DATABASE_URL="postgresql+psycopg2://${POSTGRES_USER}:${POSTGRES_PASSWORD}@localhost:${POSTGRES_PORT}/${POSTGRES_DATA_DB}"
export MODEL_ARTIFACTS_DIR="$(pwd)/Model/artifacts"
MLOps/.venv/bin/python -m uvicorn MLOps.app.api.main:app --reload
```

O arquivo `.env` fornece as credenciais, os nomes dos bancos, a configuração da
política e `MODEL_BUNDLE_REFRESH_SECONDS`. Na execução local, `DATABASE_URL` usa
`localhost` porque a API roda fora da rede do Docker, enquanto
`MODEL_ARTIFACTS_DIR` aponta para o diretório de artefatos no sistema de arquivos
local, não para o caminho dentro do container. Esses dois valores substituem os
usados pelos containers.

Em outro terminal, inicie o frontend:

```bash
cd data-platform
MLOps/.venv/bin/python -m pip install -r MLOps/app/frontend/requirements.txt
CREDIT_API_URL=http://localhost:8000 \
  MLOps/.venv/bin/python -m streamlit run MLOps/app/frontend/app.py
```

O CLI (`MLOps/app/cli/predict.py`) é ferramenta de host — roda fora da rede do compose, com
a mesma configuração e o mesmo bundle que a API usa:

```bash
cd data-platform
MLOps/.venv/bin/python -m pip install -r MLOps/app/cli/requirements.txt
PYTHONPATH=. MLOps/.venv/bin/python MLOps/app/cli/predict.py --sk-id 100002
```

Não é preciso declarar `MODEL_ARTIFACTS_DIR`: o próprio `main` do CLI declara o diretório
de artefatos do repositório, como `train.py` declara `localhost` para o banco em vez do
`POSTGRES_HOST` do compose. `PYTHONPATH=.` aponta a raiz `data-platform`, de onde vêm os
pacotes `MLOps`, `Model` e `infra`.

Para localizar um cliente cujo score caia numa faixa:

```bash
PYTHONPATH=. MLOps/.venv/bin/python MLOps/app/cli/find_customer_by_score.py \
  --min-score 0.5 --max-score 0.6
```

## Testes

A suíte de testes do componente roda com pytest, a partir da própria pasta `MLOps`:

```bash
cd data-platform/MLOps
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-test.txt
.venv/bin/python -m pip install -r app/frontend/requirements.txt
.venv/bin/python -m pytest
```

`requirements-test.txt` inclui as dependências da API e do script de revisão manual assistida (`agent-manual-review`). A instalação dos requisitos do frontend, à parte, permite executar `test_frontend.py`.

## Cobertura existente

| Arquivo | Responsabilidade validada |
|---|---|
| `test_credit_policy.py` | Faixas de aprovação, revisão e rejeição; limites inválidos e score fora de `[0, 1]`. |
| `test_config.py` | `MODEL_ARTIFACTS_DIR`/`MODEL_BUNDLE_REFRESH_SECONDS` obrigatórias, limiares da política e o caminho do manifesto composto do diretório configurado mais o nome do contrato. |
| `test_model_bundle.py` | Os três objetos de dados do bundle de predição (`ModelBundle`, `PreparedModelInput`, `PredictionResult`) expõem exatamente os campos com que foram construídos. |
| `test_feature_input_processor.py` | `FeatureInputProcessor.prepare` ordena pelas features do bundle, ignora campos extras, recusa feature obrigatória ausente, reconstrói categóricas com as categorias persistidas e converte numéricas. |
| `test_prediction_service.py` | `PredictionService.predict` aplica o threshold do bundle recebido — não um valor fixo — e passa a mesma entrada preparada ao estimador, sem cópia. |
| `test_feature_service.py` | Recuperação da ABT, cliente inexistente e normalização de tipos. |
| `test_explanation_service.py` | `ExplanationService.explain` reproduz o cálculo TreeSHAP local e a comparação com as referências, recebendo bundle e entrada preparada — sem `PredictionService` nem leitura de referência de arquivo. |
| `test_artifact_bundle_loader.py` | `ArtifactBundleLoader.load` recusa manifesto ausente, schema inválido, arquivo declarado ausente, checksum divergente, artefato ou referência sem as chaves exigidas e identidade incompatível entre manifesto/artefato/referência; aceita referência que sobra com aviso; devolve `ModelBundle` completo só quando tudo passa. |
| `test_model_bundle_manager.py` | `ModelBundleManager` ativa o primeiro candidato válido, ignora manifesto inalterado sem chamar o loader, ativa candidato novo, preserva o bundle anterior e tenta de novo em candidato inválido, recusa conteúdo trocado sob o mesmo `bundle_id` sem chamar o loader, ativa um `bundle_id` anterior sem distinção, recusa `require_active()` antes da primeira ativação, e não expõe bundle corrompido a leituras concorrentes durante a troca. |
| `test_api_endpoints.py` | Contratos e erros HTTP via `TestClient`, contra um bundle publicado de verdade num diretório temporário. |
| `test_model_loading.py` | O laço de atualização do `main.py` chama `refresh_if_changed` repetidamente até ser cancelado. |
| `test_frontend.py` | Inicialização da aplicação Streamlit. |
| `test_predict.py` | `predict_for_customer` (transporte de CLI) devolve score sem arredondamento e falha em feature ausente — a inferência em si já está coberta por `test_feature_input_processor.py`/`test_prediction_service.py`. |
| `test_find_customer_by_score.py` | Leitura dos identificadores da ABT: devolve inteiros, respeita a ordenação da consulta e não fecha a conexão recebida. |
| `test_configuration.py` | Coerência entre configuração e o artefato do bundle ativo. |
| `test_agent_manual_review_scripts.py` | O pipeline de revisão manual assistida em `agent-manual-review`: enriquecimento dos fatores autorizados e registro dos restritos, recusa de fator fora do catálogo, duplicado ou omitido, bloqueio quando a versão do prompt falta ou diverge, montagem e invocação do LLM estruturado por fake, validação da resposta contra o que foi enviado, renderização do PDF pelo template configurado, encadeamento em que a saída de um estágio é a entrada do seguinte, e a recusa de todos os estágios em sobrescrever saída existente. |

Os testes da API e do CLI utilizam fakes e fixtures injetados por composição. A suíte
principal roda offline, sem PostgreSQL, LightGBM ou artefato treinado.

`ModelBundle`, `PreparedModelInput`, `PredictionResult`, `FeatureInputProcessor`,
`PredictionService`, `ExplanationService`, `ArtifactBundleLoader` e `ModelBundleManager` são
os componentes do plano de refatoração do carregamento, predição e explicação
(`.internal/plano_refatoracao_carregamento_predicao_explicacao.md`) que a API usa hoje —
`model_service.py` e a implementação antiga de `explanation_service.py` não existem mais. O
CLI (`MLOps/app/cli/predict.py`) é o segundo transporte da mesma cadeia, sem estado de
ciclo de vida.

O teste de integração `test_configuration.py` é pulado automaticamente quando não há bundle
publicado ou o LightGBM não está disponível. `test_frontend.py` é pulado quando o Streamlit
não está instalado.

## Documentos relacionados

- [Visão geral do MLOps](README.md)
- [API de risco de crédito](API.md)
- [Interface Streamlit](FRONTEND.md)
- [Modelo](../Model/README.md)
- [Plataforma](../README.md)

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
│   │   ├── feature_service.py
│   │   ├── model_service.py
│   │   ├── explanation_service.py
│   │   ├── credit_policy.py
│   │   └── requirements.txt
│   └── frontend/
│       ├── app.py
│       ├── field_config.py
│       └── requirements.txt
├── config/
│   └── feature_catalog.json
├── tests/
├── API.md
├── FRONTEND.md
├── DEVELOPMENT.md
├── AGENT_ARCHITECTURE.md
├── MONITORING_ARCHITECTURE.md
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
export MODEL_PATH="$(pwd)/Model/artifacts/lightgbm_abt.pkl"
MLOps/.venv/bin/python -m uvicorn MLOps.app.api.main:app --reload
```

O arquivo `.env` fornece as credenciais, os nomes dos bancos e a configuração
da política. Na execução local, `DATABASE_URL` usa `localhost` porque a API roda
fora da rede do Docker, enquanto `MODEL_PATH` aponta para o artefato no sistema de
arquivos local. Esses dois valores substituem os caminhos internos usados pelos
containers.

Em outro terminal, inicie o frontend:

```bash
cd data-platform
MLOps/.venv/bin/python -m pip install -r MLOps/app/frontend/requirements.txt
CREDIT_API_URL=http://localhost:8000 \
  MLOps/.venv/bin/python -m streamlit run MLOps/app/frontend/app.py
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
| `test_config.py` | Limiares da política e intervalo de retry. |
| `test_model_service.py` | Carga do artefato, predição, categóricas e features ausentes. |
| `test_model_bundle.py` | Os três objetos de dados do bundle de predição (`ModelBundle`, `PreparedModelInput`, `PredictionResult`) expõem exatamente os campos com que foram construídos. |
| `test_feature_input_processor.py` | `FeatureInputProcessor.prepare` ordena pelas features do bundle, ignora campos extras, recusa feature obrigatória ausente, reconstrói categóricas com as categorias persistidas e converte numéricas. |
| `test_prediction_service.py` | `PredictionService.predict` (novo, sem carregamento) aplica o threshold do bundle recebido — não um valor fixo — e passa a mesma entrada preparada ao estimador, sem cópia. |
| `test_feature_service.py` | Recuperação da ABT, cliente inexistente e normalização de tipos. |
| `test_explanation_service.py` | SHAP local, referências e validação de versão. |
| `test_bundle_explanation_service.py` | `ExplanationService.explain` (novo, sem `PredictionService` nem leitura de referência) reproduz o mesmo cálculo TreeSHAP e a mesma comparação com as referências, recebendo bundle e entrada preparada. |
| `test_api_endpoints.py` | Contratos e erros HTTP via `TestClient`. |
| `test_model_loading.py` | Carga do modelo em segundo plano com ramos de falha e sucesso. |
| `test_frontend.py` | Inicialização da aplicação Streamlit. |
| `test_predict.py` | Inferência pelo script local e contrato do resultado. |
| `test_configuration.py` | Coerência entre configuração e artefato. |
| `test_agent_manual_review_scripts.py` | O pipeline de revisão manual assistida em `agent-manual-review`: enriquecimento dos fatores autorizados e registro dos restritos, recusa de fator fora do catálogo, duplicado ou omitido, bloqueio quando a versão do prompt falta ou diverge, montagem e invocação do LLM estruturado por fake, validação da resposta contra o que foi enviado, renderização do PDF pelo template configurado, encadeamento em que a saída de um estágio é a entrada do seguinte, e a recusa de todos os estágios em sobrescrever saída existente. |

Os testes da API utilizam fakes e fixtures injetados por composição. A suíte principal roda offline, sem PostgreSQL, LightGBM ou artefato treinado.

`ModelBundle`, `PreparedModelInput`, `PredictionResult`, `FeatureInputProcessor` e o novo
`PredictionService` (`model_bundle.py`, `feature_input_processor.py`,
`prediction_service.py`) são a etapa 1 do plano de refatoração do carregamento, predição e
explicação (`.internal/plano_refatoracao_carregamento_predicao_explicacao.md`); o novo
`ExplanationService` (`explanation_service_v2.py`, etapa 2) recebe bundle e entrada
preparada em vez de `PredictionService` e caminho de referência. Todos coexistem com o
fluxo atual — `model_service.py` e o `explanation_service.py` de hoje — sem substituí-lo
ainda: nenhum entrypoint os usa até a etapa 8 do plano, que remove os antigos e renomeia
`explanation_service_v2.py` para `explanation_service.py`.

Os testes de integração `test_predict.py` e `test_configuration.py` são pulados automaticamente quando o artefato ou LightGBM não estão disponíveis. `test_frontend.py` é pulado quando o Streamlit não está instalado.

## Documentos relacionados

- [Visão geral do MLOps](README.md)
- [API de risco de crédito](API.md)
- [Interface Streamlit](FRONTEND.md)
- [Modelo](../Model/README.md)
- [Plataforma](../README.md)

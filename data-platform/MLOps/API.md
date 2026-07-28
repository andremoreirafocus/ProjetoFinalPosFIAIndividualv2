# API de risco de crédito

Este documento descreve a arquitetura interna, a configuração e os contratos da API FastAPI localizada em `app/api`.

## Responsabilidades

| Componente | Responsabilidade | Não é responsabilidade |
|---|---|---|
| `feature_service` | Recuperar uma linha da ABT e preparar suas features. | Reexecutar a engenharia de atributos sobre as fontes brutas. |
| `model_service` | Validar o artefato, alinhar tipos e calcular score e classe. | Definir aprovação ou rejeição de negócio. |
| `explanation_service` | Calcular contribuições TreeSHAP locais para revisão manual. | Calcular score ou definir a política de crédito. |
| `credit_policy` | Traduzir faixas de score em recomendação demonstrativa. | Retreinar ou calibrar o modelo. |
| FastAPI | Gerenciar ciclo de vida, contratos e erros HTTP. | Armazenar o histórico definitivo das decisões. |

Essa separação evita acoplar mudanças da política comercial ao treinamento do algoritmo.

## Fluxo em camadas

```text
Consumidor
   │ HTTP
   ▼
FastAPI — contrato e transporte
   │
   ├── FeatureService ──────→ recupera as features do cliente na ABT
   ├── PredictionService ───→ alinha o contrato e calcula o score
   ├── CreditPolicy ────────→ converte o score em recomendação
   └── ExplanationService ──→ explica casos em revisão manual
```

- acesso a dados e inferência não conhecem a regra de negócio;
- a política recebe apenas o score e não conhece o modelo;
- a API não reimplementa a engenharia de atributos do pipeline;
- a apresentação permanece fora do serviço.

## Decisões arquiteturais

- **Consistência treino e inferência pela ABT:** o `feature_service` lê a mesma `application_abt` usada no treinamento. A predição por cliente depende de a ABT estar atualizada.
- **Modelo e política desacoplados:** `predicted_class` usa o threshold do modelo, enquanto `recommendation` usa os limites configuráveis da política; os resultados podem divergir porque possuem finalidades diferentes.
- **Contrato dirigido pelo artefato:** features, categorias e threshold acompanham o modelo. A API valida e alinha a entrada contra esse contrato.
- **Dependências carregadas no startup:** modelo, serviços e engine do banco são criados no `lifespan` e reutilizados pelas requisições.
- **Núcleo único de predição:** muda apenas a origem das features, que podem ser fornecidas pelo consumidor ou recuperadas da ABT.

### Fluxo do contrato

```text
train.py
   → artefato com features, categorias e threshold
   → PredictionService valida e alinha a entrada
   → /model/features expõe o contrato
   → Streamlit renderiza os mesmos campos
```

## Configuração

| Variável | Finalidade | Padrão no Compose |
|---|---|---|
| `MODEL_PATH` | Caminho do artefato LightGBM | `/app/Model/artifacts/lightgbm_abt.pkl` |
| `MODEL_LOAD_RETRY_SECONDS` | Intervalo entre tentativas da carga inicial | `5` segundos |
| `DATABASE_URL` | Conexão com o banco `data` | PostgreSQL do Compose |
| `CREDIT_APPROVE_MAX_SCORE` | Limite superior para aprovação | `0.50` |
| `CREDIT_MANUAL_REVIEW_MAX_SCORE` | Limite superior para revisão manual | `0.60` |
| `CREDIT_POLICY_VERSION` | Identificador da política | `demo-v1` |

Os limites são demonstrativos, precisam ser validados com custos e regras reais e devem respeitar:

```text
0 <= CREDIT_APPROVE_MAX_SCORE < CREDIT_MANUAL_REVIEW_MAX_SCORE <= 1
```

## Carregamento do modelo

No startup, o `lifespan`:

1. valida os limites da política;
2. cria o `PredictionService` com `MODEL_PATH`;
3. inicia em segundo plano a carga conjunta do modelo e de suas referências;
4. cria o engine SQLAlchemy com `pool_pre_ping=True`;
5. instancia os serviços de features, explicação e política;
6. registra os serviços em `app.state`;
7. libera o pool de conexões no shutdown.

Se o modelo ou suas referências estiverem ausentes, corrompidos ou incompatíveis, a API registra o erro e tenta carregar novamente o bundle após `MODEL_LOAD_RETRY_SECONDS`. Enquanto nenhum bundle válido estiver disponível, `/health` e os endpoints dependentes do modelo respondem `503`.

Quando a carga termina, o modelo e suas referências permanecem em memória. A API verifica a assinatura dos dois arquivos a cada requisição e recarrega o conjunto quando ambos pertencem ao mesmo treinamento. Se apenas um deles tiver sido atualizado, a última versão válida continua em uso até que o novo par esteja completo.

O artefato precisa conter modelo, threshold, métricas e a lista de features na chave obrigatória `features`, que é a única aceita pela API.

## Preparação para inferência

Antes de `predict_proba`, o `PredictionService`:

- rejeita entradas sem todas as features obrigatórias;
- reorganiza as colunas na ordem do treinamento;
- ignora campos extras durante o reindex;
- restaura `pandas.Categorical` com as categorias do artefato;
- converte as demais features para tipo numérico;
- calcula `risk_score` para a classe positiva;
- compara o score com o threshold persistido para produzir `predicted_class`.

Restaurar as categorias é indispensável para o LightGBM com categóricas nativas: o mesmo texto precisa representar a mesma categoria lógica usada no ajuste.

## Recuperação do cliente

O `CustomerFeatureService` consulta `application_abt` por `sk_id_curr`. Identificador e target são removidos antes do retorno. O serviço também garante a presença das features de parcelas por compatibilidade com ABTs materializadas anteriormente. Consumir a ABT evita duplicar na API as agregações realizadas pelo pipeline.

## Política de crédito

```text
score < approve_max_score
  → approve

approve_max_score <= score < manual_review_max_score
  → manual_review

score >= manual_review_max_score
  → reject
```

A resposta inclui os limites e `policy_version`. O score é uma pontuação de ordenação de risco, não uma probabilidade calibrada de inadimplência.

## Endpoints

| Método e caminho | Finalidade |
|---|---|
| `GET /health` | Retorna `200` com um bundle válido carregado ou `503` enquanto ele não estiver disponível. |
| `GET /model/features` | Lista as features esperadas pelo modelo. |
| `GET /customers/{customer_id}/features` | Recupera as features de um cliente para edição. |
| `POST /predict/features` | Calcula o score a partir das features fornecidas. |
| `POST /predict/customer/{customer_id}` | Recupera o cliente na ABT e calcula o score. |

O Swagger gerado pelos contratos de `schemas.py` está disponível em http://localhost:8000/docs.

## Health check

Enquanto nenhum bundle válido está disponível:

```json
{
  "detail": {
    "message": "Modelo e referências ainda não estão disponíveis.",
    "last_error": "[Errno 2] No such file or directory: '/app/Model/artifacts/lightgbm_abt.pkl'"
  }
}
```

Depois da carga:

```json
{
  "status": "ok",
  "model_loaded": true,
  "model_path": "/app/Model/artifacts/lightgbm_abt.pkl"
}
```

## Requisição por features

O endpoint recebe um objeto `features` com todas as entradas listadas por `GET /model/features`:

```json
{
  "features": {
    "ext_source_1": 0.50,
    "ext_source_2": 0.62,
    "ext_source_3": 0.48,
    "ext_source_mean": 0.53,
    "age": 35.0,
    "occupation_type": "Laborers"
  }
}
```

O exemplo é abreviado; uma chamada válida deve conter todas as features obrigatórias.

## Resposta de predição

```json
{
  "source": "provided_features",
  "customer_id": null,
  "risk_score": 0.55,
  "predicted_class": 1,
  "model_decision_threshold": 0.5,
  "policy": {
    "recommendation": "manual_review",
    "reason": "Score de risco na faixa intermediária.",
    "policy_version": "demo-v1",
    "approve_max_score": 0.50,
    "manual_review_max_score": 0.60
  },
  "explanation": {
    "base_value": -1.42,
    "output_scale": "raw_score",
    "top_factors": [
      {
        "feature": "inst_late_payment_rate",
        "value": 0.27,
        "shap_value": 0.42,
        "direction": "increases_risk",
        "comparison": {
          "feature_type": "numeric",
          "numeric": {
            "training_percentile_low": 90.0,
            "training_percentile_high": 91.0,
            "population_mean": 0.06,
            "population_median": 0.0,
            "population_p25": 0.0,
            "population_p75": 0.08,
            "target_0_median": 0.0,
            "target_1_median": 0.03,
            "binary_rates": null
          },
          "categorical": null,
          "shap": {
            "global_mean_abs_shap": 0.17,
            "local_abs_shap": 0.42,
            "abs_shap_percentile_low": 95,
            "abs_shap_percentile_high": 99
          }
        }
      }
    ]
  }
}
```

`source` identifica a origem das features e `customer_id` associa resultados provenientes da ABT. `reason` apresenta a justificativa da faixa aplicada pela política.

Em `manual_review`, o `ExplanationService` calcula TreeSHAP local. Valores positivos aumentam o score de risco e valores negativos o reduzem. `base_value` e `shap_value` estão na escala bruta do modelo, não em pontos percentuais. Nas demais recomendações, `explanation` é `null`.

Cada fator inclui uma comparação com `feature_reference.json`: posição na população, estatísticas por target e referências globais da magnitude SHAP. A versão das referências é validada contra a versão do artefato carregado.

A resposta explicativa constitui o insumo quantitativo do futuro agente acelerador de revisão de crédito. A futura mensagem também deverá acrescentar a versão do modelo, que ainda não integra o contrato HTTP atual. Consulte a [arquitetura proposta do agente](AGENT_ARCHITECTURE.md).

## Tratamento de erros

| Situação | Resposta |
|---|---|
| Cliente inexistente na ABT | HTTP `404`. |
| Falha ao consultar PostgreSQL | HTTP `503`. |
| Features obrigatórias ausentes | HTTP `422` com a lista. |
| Modelo ou referências ausentes ou inválidos, sem bundle anterior | API ativa, retry da carga inicial e HTTP `503` nos endpoints dependentes. |
| Atualização incompleta com bundle anterior válido | A API mantém em memória a última versão válida até que o novo par esteja completo. |

As predições são registradas em JSON no stdout para demonstração e diagnóstico. Esse registro não substitui uma trilha de auditoria persistente.

## Documentos relacionados

- [Visão geral do MLOps](README.md)
- [Interface Streamlit](FRONTEND.md)
- [Desenvolvimento, execução e testes](DEVELOPMENT.md)
- [Arquitetura proposta do agente](AGENT_ARCHITECTURE.md)
- [Arquitetura proposta de monitoramento](MONITORING_ARCHITECTURE.md)

# API de risco de crédito

Este documento descreve a arquitetura interna, a configuração e os contratos da API FastAPI localizada em `app/api`.

## Responsabilidades

| Componente | Responsabilidade | Não é responsabilidade |
|---|---|---|
| `feature_service` | Recuperar uma linha da ABT, remover identificador e target e normalizar os valores retornados pelo banco. | Reexecutar a engenharia de atributos sobre as fontes brutas ou preparar a entrada conforme o contrato do modelo. |
| `new_customer_feature_transformation_service` | Reproduzir, por registro, a sanitização e a construção da ABT para um cliente sem histórico em nenhuma tabela. | Escrever no banco, decidir a ordem das projeções fora do que a API já conhece, ou preparar a entrada conforme o contrato do modelo. |
| `artifact_bundle_loader` | Ler, conferir e validar o conjunto de artefatos declarado pelo manifesto. | Decidir quando recarregar ou expor predição. |
| `model_bundle_manager` | Decidir se e quando trocar o bundle ativo, preservando o anterior em qualquer falha do candidato. | Validar o conteúdo do candidato — isso é do loader. |
| `feature_input_processor` | Alinhar a entrada ao contrato do bundle ativo: ordem, tipos, categorias. | Calcular score ou carregar artefato. |
| `prediction_service` | Calcular score e classe a partir do bundle e da entrada já preparada. | Preparar a entrada ou definir aprovação/rejeição. |
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
   ├── NewCustomerFeatureTransformationService → transforma o registro bruto de um cliente novo
   ├── FeatureService ──────────→ recupera as features do cliente na ABT
   ├── FeatureInputProcessor ───→ alinha a entrada ao contrato do bundle ativo
   ├── PredictionService ───────→ calcula score e classe
   ├── CreditPolicy ────────────→ converte o score em recomendação
   └── ExplanationService ──────→ explica casos em revisão manual
```

- acesso a dados e inferência não conhecem a regra de negócio;
- a política recebe apenas o score e não conhece o modelo;
- a API não reimplementa a engenharia de atributos do pipeline;
- a apresentação permanece fora do serviço.

## Decisões arquiteturais

- **Consistência treino e inferência:** o `feature_service` lê a mesma `application_abt` usada no treinamento; para um cliente novo, o serviço de transformação reutiliza as projeções SQL do pipeline e os parâmetros registrados no bundle. A predição por cliente depende de a ABT estar atualizada.
- **Modelo e política desacoplados:** `predicted_class` usa o threshold do modelo, enquanto `recommendation` usa os limites configuráveis da política; os resultados podem divergir porque possuem finalidades diferentes.
- **Contrato dirigido pelo artefato:** features, categorias e threshold acompanham o modelo. A API valida e alinha a entrada contra esse contrato.
- **Inicialização e ativação desacopladas:** serviços e engine do banco são criados no `lifespan`; o laço executado em segundo plano ativa o primeiro bundle válido e verifica novas versões. As requisições reutilizam os serviços e o snapshot ativo.
- **Núcleo único de predição:** muda apenas a origem das features, que podem ser fornecidas pelo consumidor, recuperadas da ABT ou produzidas pela transformação do registro bruto de um cliente novo.

### Fluxo do contrato

```text
train.py
   → publica o bundle (manifesto, modelo, referência e contrato de transformação versionados)
   → ArtifactBundleLoader valida e monta o bundle ativo
   → NewCustomerFeatureTransformationService usa o contrato e as projeções compartilhadas quando a entrada é um registro bruto
   → FeatureInputProcessor alinha a entrada ao contrato do bundle
   → /model/features expõe o contrato
   → Streamlit renderiza os mesmos campos
```

## Configuração

| Variável | Finalidade | Origem no Compose |
|---|---|---|
| `MODEL_ARTIFACTS_DIR` | Diretório onde o conjunto de artefatos publicado está visível | Variável homônima do `.env` |
| `MODEL_BUNDLE_REFRESH_SECONDS` | Intervalo entre ciclos de verificação do manifesto | Variável homônima do `.env` |
| `DATABASE_URL` | Conexão com o banco `data` | Composta com as variáveis `POSTGRES_*` do `.env` |
| `CREDIT_APPROVE_MAX_SCORE` | Limite superior para aprovação | Variável homônima do `.env` |
| `CREDIT_MANUAL_REVIEW_MAX_SCORE` | Limite superior para revisão manual | Variável homônima do `.env` |
| `CREDIT_POLICY_VERSION` | Identificador da política | Variável homônima do `.env` |

Os limites são demonstrativos, precisam ser validados com custos e regras reais e devem respeitar:

```text
0 <= CREDIT_APPROVE_MAX_SCORE < CREDIT_MANUAL_REVIEW_MAX_SCORE <= 1
```

## Carregamento do modelo

No startup, o `lifespan`:

1. valida a configuração (`settings.validate()`);
2. monta o `ArtifactBundleLoader` e o `ModelBundleManager`, apontado para o manifesto
   composto de `MODEL_ARTIFACTS_DIR`;
3. cria o engine SQLAlchemy por `infra.db.get_database_engine(..., pool_pre_ping=True)`;
4. instancia os serviços de preparo de entrada, predição, explicação, features, política e
   transformação de cliente novo, e registra tudo em `app.state`;
5. inicia em segundo plano um laço único que verifica o manifesto a cada
   `MODEL_BUNDLE_REFRESH_SECONDS`;
6. no shutdown, cancela o laço e libera o pool de conexões.

O manager lê o manifesto ativo e decide se há candidato novo. Quando há, delega ao loader
a leitura e a validação completas — schema do manifesto, checksums dos três artefatos,
chaves obrigatórias do artefato e da referência, identidade cruzada entre
manifesto/artefato/referência, cobertura estatística e SHAP de cada feature do modelo
(referências extras geram um warning no log, sem impedir a ativação), e a forma do
contrato de transformação — suas sete chaves, os tipos dentro de `stats` e dos dois
digests. Um candidato inválido não substitui o bundle ativo, e a próxima verificação
tenta de novo. Enquanto nenhum bundle válido estiver ativo, `/health` e os endpoints
dependentes do modelo respondem `503`, com o último erro registrado.

O artefato precisa conter modelo, threshold, features, categóricas, categorias e
identidade de treino — as sete chaves obrigatórias do contrato, declaradas em
`Model/artifact_bundle_contract.py`. O contrato de transformação tem as suas próprias
sete chaves, declaradas no mesmo módulo como `REQUIRED_TRANSFORMATION_CONTRACT_KEYS`; o
loader confere sua forma, mas não confere quais estatísticas existem dentro de `stats` —
isso é do serviço de transformação, contra o `.sql` que ele já lê.

## Transformação do registro bruto de um cliente novo

Para um cliente que ainda não existe em nenhuma tabela, a transformação precede a
preparação: `NewCustomerFeatureTransformationService` aplica as mesmas duas projeções que
`data_sanitization.py` e `abt_transform.py` aplicam à população inteira — por `SELECT` sobre
`VALUES`, um registro por vez, sem escrever no banco — e produz uma linha com as 42 features
do modelo mais um `sk_id_curr` técnico usado para compor a projeção da ABT. O
`FeatureInputProcessor` seleciona e ordena somente as 42 features declaradas pelo bundle. Os dois `.sql`
das projeções (`application_sanitization_projection.sql` e
`application_abt_record_projection.sql`) são embutidos na imagem; o serviço confere, a cada
transformação, que seus hashes ainda batem com os publicados no contrato do bundle ativo —
divergindo, recusa nomeando o arquivo, o digest calculado e o publicado — e que o contrato
cobre toda estatística que a projeção referencia, derivada do próprio `.sql`, nunca de uma
lista mantida à mão. Construído no `lifespan`, junto dos demais serviços, ele atende o
endpoint `POST /predict/new-customer`.

## Preparação para inferência

Antes de calcular o score, o `FeatureInputProcessor`:

- rejeita entradas sem todas as features obrigatórias do bundle;
- reorganiza as colunas na ordem do treinamento;
- ignora campos extras durante o reindex;
- restaura `pandas.Categorical` com as categorias persistidas no bundle;
- converte as demais features para tipo numérico.

A mesma entrada preparada é compartilhada entre `PredictionService` (que calcula
`risk_score` para a classe positiva e compara com o `decision_threshold` do bundle para
produzir `predicted_class`) e `ExplanationService`, quando a política pede revisão manual —
os dois nunca recebem entradas preparadas separadamente para o mesmo pedido.

Restaurar as categorias é indispensável para o LightGBM com categóricas nativas: o mesmo texto precisa representar a mesma categoria lógica usada no ajuste.

## Recuperação do cliente

O `CustomerFeatureService` consulta `application_abt` por `sk_id_curr`. Identificador e target são removidos antes do retorno. Consumir a ABT mantém na inferência por cliente as agregações materializadas pelo pipeline.

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
| `POST /predict/new-customer` | Transforma o registro bruto de um cliente novo e calcula o score. |

O Swagger gerado pelos contratos de `schemas.py` está disponível em http://localhost:8000/docs.

## Health check

Enquanto nenhum bundle válido está ativo:

```json
{
  "detail": {
    "message": "Modelo e referências ainda não estão disponíveis.",
    "last_error": "[Errno 2] No such file or directory: '/app/Model/artifacts/current_bundle.json'"
  }
}
```

Depois da carga, `model_path` reflete o pickle do bundle ativo, dentro do diretório
versionado:

```json
{
  "status": "ok",
  "model_loaded": true,
  "model_path": "/app/Model/artifacts/bundles/model-1.0.0-20260815T164748Z/lightgbm_abt.pkl"
}
```

## Contratos de entrada

Há dois contratos de entrada distintos, que não se confundem: features já transformadas
(a aba de edição, que carrega da ABT) e registro bruto de aplicação (um cliente que ainda
não existe em nenhuma tabela).

### Requisição por features

`POST /predict/features` recebe um objeto `features` com todas as entradas listadas por `GET /model/features`:

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

### Requisição de cliente novo

`POST /predict/new-customer` recebe `NewCustomerApplication`: um corpo **plano**, com os 26
campos brutos de `application_train` no nível de cima — sem a chave `features`. Os seis
obrigatórios (`amt_credit`, `region_rating_client_w_city`, `days_id_publish`,
`days_registration`, `days_birth`, `days_employed`) exigem valor; os vinte restantes são
obrigatórios na chave, mas aceitam `null` como afirmação explícita de "não disponível" —
omitir qualquer uma das 26 chaves é `422`:

```json
{
  "amt_credit": 450000.0,
  "region_rating_client_w_city": 2,
  "days_id_publish": -2500,
  "days_registration": -3500,
  "days_birth": -13000,
  "days_employed": -1800,
  "ext_source_1": 0.6,
  "ext_source_2": null,
  "ext_source_3": null,
  "days_last_phone_change": -300.0,
  "cnt_fam_members": 3.0,
  "amt_annuity": 28000.0,
  "amt_income_total": 180000.0,
  "reg_city_not_work_city": 1,
  "reg_city_not_live_city": 0,
  "live_city_not_work_city": 0,
  "def_60_cnt_social_circle": 1.0,
  "amt_req_credit_bureau_year": 2.0,
  "cnt_children": 1,
  "flag_own_car": null,
  "own_car_age": null,
  "occupation_type": "Laborers",
  "organization_type": "Business Entity Type 3",
  "name_income_type": "Working",
  "name_education_type": "Secondary",
  "code_gender": "F"
}
```

O `NewCustomerFeatureTransformationService` aplica a mesma regra de sanitização e
construção da ABT que o pipeline aplica à população. Os valores `null` são tratados pelas
regras de sanitização; a linha transformada contém as 42 features do modelo e um
`sk_id_curr` técnico, descartado pelo `FeatureInputProcessor` ao alinhar a entrada. As 42
features resultantes alimentam a mesma predição dos outros dois caminhos.

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

`source` identifica a origem das features — `provided_features`, `database` ou
`new_customer_transformed_application`, este último quando o registro veio de
`POST /predict/new-customer` e foi completado pela sanitização antes da inferência — e
`customer_id` associa resultados provenientes da ABT. `reason` apresenta a justificativa da
faixa aplicada pela política.

Em `manual_review`, o `ExplanationService` calcula TreeSHAP local. Valores positivos aumentam o score de risco e valores negativos o reduzem. `base_value` e `shap_value` estão na escala bruta do modelo, não em pontos percentuais. Nas demais recomendações, `explanation` é `null`.

Cada fator inclui uma comparação com `feature_reference.json`: posição na população, estatísticas por target e referências globais da magnitude SHAP. A versão das referências é validada contra a versão do artefato carregado.

A resposta explicativa constitui o insumo quantitativo do futuro agente acelerador de revisão de crédito. A futura mensagem também deverá acrescentar a versão do modelo, que ainda não integra o contrato HTTP atual. Consulte a [arquitetura proposta do agente](AGENT_ARCHITECTURE.md).

## Tratamento de erros

| Situação | Resposta |
|---|---|
| Cliente inexistente na ABT | HTTP `404`. |
| Falha ao consultar PostgreSQL | HTTP `503`. |
| Features obrigatórias ausentes | HTTP `422` com a lista. |
| Campo obrigatório omitido em `POST /predict/new-customer`, ou os 26 campos incompletos | HTTP `422` nomeando o campo, sem chegar ao serviço de transformação. |
| Falha de banco na transformação do cliente novo | HTTP `503`, com mensagem própria — distinta da falha ao consultar as fontes do cliente. |
| Hash de um dos `.sql` divergente do contrato do bundle ativo | HTTP `503`, nomeando o arquivo divergente e os dois digests — nunca um `500` genérico. |
| Manifesto ausente, inválido ou candidato incompatível, sem bundle ativo anterior | API ativa, HTTP `503` nos endpoints dependentes, nova verificação a cada `MODEL_BUNDLE_REFRESH_SECONDS`. |
| Candidato novo inválido com bundle ativo anterior válido | O manager preserva o bundle ativo; a próxima verificação tenta o candidato de novo. |

Para demonstração e diagnóstico, a API registra no stdout o payload da requisição em JSON e uma mensagem textual com o score e a classe calculados. Esses registros operacionais não substituem uma trilha de auditoria persistente.

## Documentos relacionados

- [Visão geral do MLOps](README.md)
- [Interface Streamlit](FRONTEND.md)
- [Desenvolvimento, execução e testes](DEVELOPMENT.md)
- [Arquitetura proposta do agente](AGENT_ARCHITECTURE.md)
- [Arquitetura proposta de monitoramento](MONITORING_ARCHITECTURE.md)

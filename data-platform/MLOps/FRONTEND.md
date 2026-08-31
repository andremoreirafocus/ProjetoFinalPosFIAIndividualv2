# Interface Streamlit

O frontend localizado em `app/frontend` é um simulador para o analista de crédito. Ele consome exclusivamente a API FastAPI e nunca acessa diretamente o modelo ou o arquivo Pickle.

## Responsabilidade

O Streamlit apresenta as jornadas de demonstração e explica o resultado da API. Inferência, acesso à ABT e política de crédito permanecem nos serviços da API.

```text
Analista
   │
   ▼
Streamlit ── HTTP ──→ FastAPI ──→ modelo, política e explicação
```

## Recursos implementados

- URL da API configurável na barra lateral;
- botão **Verificar conexão**, que consulta `/health`;
- campos agrupados por contexto;
- opções controladas para categóricas;
- seleção binária para flags;
- limites e passos para valores numéricos;
- seletor de data para os campos temporais da aba "Novo cliente", convertidos para o dia
  com sinal que a API espera antes do envio;
- representação explícita de indisponibilidade na aba "Novo cliente": cada campo opcional
  tem um controle de ausência ao lado, que apaga e desabilita o campo na hora e envia
  `null` — "Não disponível" na maioria, "Sem vínculo empregatício" em `days_employed`,
  onde `null` é uma resposta definitiva, não uma ausência de informação;
- exibição da requisição e da resposta JSON;
- aviso de que o score não é uma probabilidade calibrada.

## Jornadas

### Novo cliente

Renderiza os 26 campos brutos de `application_train` descritos em `APPLICATION_FIELDS`
(`field_config.py`), fora de `st.form` — cada campo opcional ganha um controle de ausência
ao lado e o efeito é imediato, o que um formulário do Streamlit não permite. Os seis
campos obrigatórios exigem valor; os vinte opcionais aceitam a marcação, que envia `null`.
A submissão confere os 26 antes de chamar a API e recusa nomeando os campos sem resposta.
O corpo enviado a `POST /predict/new-customer` é plano, com as 26 chaves no nível de
cima — sem a chave `features` que `/predict/features` usa. Os campos opcionais marcados
como indisponíveis seguem com valor `null`; o serviço de transformação aplica a eles a
mesma regra de sanitização usada na população de treino.

Cinco campos temporais (`days_birth`, `days_id_publish`, `days_registration`,
`days_last_phone_change`, `days_employed`) são apresentados como seletor de data, não
como número de dias — o analista escolhe a data e `signed_days_since_today`
(`signed_days.py`) converte para o dia com sinal que a API já espera, sem mudar o
contrato dela. Nenhum dos cinco começa preenchido; todos bloqueiam a submissão se
deixados vazios, com uma exceção: `days_employed` tem controle próprio, "Sem vínculo
empregatício", que envia `null` em vez de bloquear — sentido distinto do "não disponível"
dos demais opcionais, porque afirma uma resposta (ausência de vínculo), não uma
informação desconhecida. `0` (emprego iniciado hoje) é uma resposta real e nunca é
confundido com essa ausência, nem no frontend nem na API.

### Buscar cliente e editar

Recupera as features com `GET /customers/{customer_id}/features`, mantém o cliente no `session_state`, preenche um formulário editável e permite reavaliar o caso. As alterações simuladas não modificam a ABT.

### Consultar cliente do banco

Envia o identificador para `POST /predict/customer/{customer_id}`. A API recupera as features da ABT e calcula o resultado sem edição manual.

## Apresentação do resultado

Em todas as jornadas, o frontend apresenta:

- origem das features;
- `risk_score`;
- classe prevista;
- threshold do modelo;
- recomendação e justificativa da política;
- limites e versão da política;
- barra de posição na escala de risco;
- explicação local quando a recomendação é `manual_review`;
- JSONs enviado e recebido.

O frontend é apenas um consumidor do contrato HTTP. Alterações no modelo ou na política não devem ser implementadas na camada de apresentação.

## Configuração

| Variável | Finalidade | Padrão no Compose |
|---|---|---|
| `CREDIT_API_URL` | URL da API consumida pelo frontend | `http://credit-api:8000` |

## Execução

Com a API disponível:

```bash
cd data-platform
MLOps/.venv/bin/python -m pip install -r MLOps/app/frontend/requirements.txt
CREDIT_API_URL=http://localhost:8000 \
  MLOps/.venv/bin/python -m streamlit run MLOps/app/frontend/app.py
```

A interface estará disponível em http://localhost:8501.

## Evolução proposta

A futura interface de revisão poderá evoluir a partir do frontend atual para consultar os relatórios produzidos pelo agente acelerador de revisão de crédito. Ela continuará sendo consumidora dos relatórios e não executará diretamente o agente ou o modelo de linguagem.

Consulte a [arquitetura proposta do agente acelerador de revisão de crédito](AGENT_ARCHITECTURE.md).

## Documentos relacionados

- [Visão geral do MLOps](README.md)
- [API de risco de crédito](API.md)
- [Desenvolvimento, execução e testes](DEVELOPMENT.md)

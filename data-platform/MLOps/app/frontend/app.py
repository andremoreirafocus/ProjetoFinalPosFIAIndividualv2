"""Interface Streamlit para a API de risco de crédito."""

import os
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import requests
import streamlit as st

DATA_PLATFORM_DIR = Path(__file__).resolve().parents[3]
if str(DATA_PLATFORM_DIR) not in sys.path:
    # O Streamlit executa o arquivo como script e não inclui a raiz do projeto.
    sys.path.insert(0, str(DATA_PLATFORM_DIR))

from MLOps.app.frontend.field_config import (
    APPLICATION_FIELDS,
    APPLICATION_GROUPS,
    FIELDS,
    GROUPS,
    FieldConfig,
)
from MLOps.app.frontend.signed_days import signed_days_since_today


DEFAULT_API_URL = os.getenv("CREDIT_API_URL", "http://localhost:8000")
REQUEST_TIMEOUT = 30

RECOMMENDATIONS = {
    "approve": ("Aprovação recomendada", "success", "✅"),
    "manual_review": ("Revisão manual recomendada", "warning", "⚠️"),
    "reject": ("Reprovação recomendada", "error", "⛔"),
}

SOURCE_LABELS = {
    "database": "Banco de dados",
    "provided_features": "Formulário",
    "new_customer_transformed_application": "Novo cliente",
}


def api_request(method: str, url: str, **kwargs: Any) -> Any:
    """Executa uma chamada e converte erros HTTP em mensagens legíveis."""
    try:
        response = requests.request(method, url, timeout=REQUEST_TIMEOUT, **kwargs)
        response.raise_for_status()
        return response.json()
    except requests.ConnectionError as error:
        raise RuntimeError("Não foi possível conectar à API. Verifique se a FastAPI está em execução.") from error
    except requests.Timeout as error:
        raise RuntimeError("A API demorou mais que o esperado para responder.") from error
    except requests.HTTPError as error:
        try:
            detail = response.json().get("detail", response.text)
        except ValueError:
            detail = response.text
        raise RuntimeError(f"A API retornou HTTP {response.status_code}: {detail}") from error


def _unavailable_checkbox_key(field: FieldConfig, key_prefix: str) -> str:
    return f"{key_prefix}_{field.name}_unavailable"


def _render_field_widget(field: FieldConfig, default: Any, key: str, disabled: bool) -> Any:
    if field.kind == "date":
        min_date = date.today() - timedelta(days=round(field.date_max_years_ago * 365.25))
        picked = st.date_input(
            field.label, value=default, min_value=min_date, max_value=date.today(),
            key=key, help=field.help or None, disabled=disabled, format="DD/MM/YYYY",
        )
        return signed_days_since_today(picked)

    if field.kind == "category":
        sorted_options = sorted(field.options, key=str.lower)
        selected = None if default is None else str(default)
        index = sorted_options.index(selected) if selected in sorted_options else None
        return st.selectbox(
            field.label, sorted_options, index=index, key=key,
            help=field.help or None, disabled=disabled,
        )

    if field.kind == "boolean":
        true_value, false_value = field.boolean_values
        index = None if default is None else (1 if default == true_value else 0)
        selected = st.selectbox(
            field.label, ("Não", "Sim"), index=index, key=key, disabled=disabled,
        )
        if selected is None:
            return None
        return true_value if selected == "Sim" else false_value

    arguments: dict[str, Any] = {
        "label": field.label,
        "value": (
            None if default is None
            else (int(default) if field.kind == "integer" else float(default))
        ),
        "step": int(field.step) if field.kind == "integer" else float(field.step),
        "key": key,
        "help": field.help or None,
        "disabled": disabled,
    }
    if field.minimum is not None:
        arguments["min_value"] = int(field.minimum) if field.kind == "integer" else float(field.minimum)
    if field.maximum is not None:
        arguments["max_value"] = int(field.maximum) if field.kind == "integer" else float(field.maximum)
    value = st.number_input(**arguments)
    if value is None:
        return None
    return int(value) if field.kind == "integer" else float(value)


def render_input(
    field: FieldConfig,
    value_override: Any | None = None,
    key_prefix: str = "feature",
) -> Any:
    """Renderiza o componente adequado e devolve um valor serializável em JSON.

    Campos opcionais (`field.optional`) ganham, ao lado, o controle de ausência
    (`field.unavailable_checkbox_label` — "Não disponível" por padrão, próprio só em
    `days_employed`): marcá-lo apaga e desabilita o campo na hora, escrevendo `None` na
    própria chave do widget antes de ele renderizar de novo; desmarcá-lo devolve o campo
    vazio.
    """
    key = f"{key_prefix}_{field.name}"
    default = field.default if value_override is None else value_override

    if not field.optional:
        return _render_field_widget(field, default, key, disabled=False)

    unavailable_key = _unavailable_checkbox_key(field, key_prefix)

    def _clear_field_on_unavailable(widget_key: str = key, checkbox_key: str = unavailable_key) -> None:
        if st.session_state[checkbox_key]:
            st.session_state[widget_key] = None

    field_column, unavailable_column = st.columns([3, 1])
    with unavailable_column:
        unavailable = st.checkbox(
            field.unavailable_checkbox_label, key=unavailable_key,
            on_change=_clear_field_on_unavailable,
        )
    with field_column:
        return _render_field_widget(field, default, key, disabled=unavailable)


def render_feature_form(
    form_key: str,
    submit_label: str,
    loaded_features: dict[str, Any] | None = None,
    key_prefix: str = "feature",
) -> tuple[dict[str, Any], bool]:
    """Renderiza todos os campos agrupados e devolve as features preenchidas."""
    with st.form(form_key):
        features: dict[str, Any] = {}
        for group in GROUPS:
            st.subheader(group, anchor=False)
            group_fields = [field for field in FIELDS if field.group == group]
            # st.columns(3) precisa ser recriado a cada linha: ver o comentário
            # equivalente em render_new_customer_form.
            for row_start in range(0, len(group_fields), 3):
                row_columns = st.columns(3)
                for column, field in zip(row_columns, group_fields[row_start:row_start + 3]):
                    with column:
                        features[field.name] = render_input(
                            field,
                            value_override=(loaded_features or {}).get(field.name),
                            key_prefix=key_prefix,
                        )
        submitted = st.form_submit_button(
            submit_label, type="primary", use_container_width=True
        )
    return features, submitted


def render_new_customer_form(key_prefix: str = "new_customer") -> tuple[dict[str, Any], bool]:
    """Renderiza os campos brutos **fora** de `st.form`.

    O Streamlit recusa `on_change` em widget dentro de formulário — e mesmo sem
    callback o form não re-executa até a submissão, então acionar o controle de ausência
    não apagaria nem desabilitaria o campo na hora. Cada interação aqui re-executa a
    aplicação; a submissão é um `st.button`, não um `st.form_submit_button`.
    """
    application: dict[str, Any] = {}
    for group in APPLICATION_GROUPS:
        st.subheader(group, anchor=False)
        group_fields = [field for field in APPLICATION_FIELDS if field.group == group]
        # st.columns(3) precisa ser recriado a cada linha: reaproveitar o mesmo objeto
        # entre linhas (como um `index % 3` sobre colunas fixas faria) preenche cada
        # coluna inteira antes da próxima — ordem de DOM e de tabulação por coluna, não
        # por linha, mesmo a grade parecendo correta visualmente.
        for row_start in range(0, len(group_fields), 3):
            row_columns = st.columns(3)
            for column, field in zip(row_columns, group_fields[row_start:row_start + 3]):
                with column:
                    application[field.name] = render_input(field, key_prefix=key_prefix)

    submitted = st.button(
        "Analisar crédito",
        type="primary",
        use_container_width=True,
        key=f"{key_prefix}_submit",
    )
    return application, submitted


def show_result(result: dict[str, Any]) -> None:
    """Apresenta score, classificação do modelo e política de crédito."""
    policy = result["policy"]
    recommendation = policy["recommendation"]
    title, message_type, icon = RECOMMENDATIONS.get(
        recommendation, (recommendation, "info", "ℹ️")
    )

    st.subheader(f"{icon} {title}")
    getattr(st, message_type)(policy["reason"])

    score = float(result["risk_score"])
    col_score, col_class, col_source = st.columns(3)
    col_score.metric("Score de risco", f"{score:.2%}")
    col_class.metric("Classe prevista", "Inadimplente" if result["predicted_class"] else "Adimplente")
    col_source.metric("Origem", SOURCE_LABELS.get(result["source"], result["source"]))
    st.progress(score, text="Posição do cliente na escala de risco do modelo")

    st.caption(
        f"Limiar do modelo: {result['model_decision_threshold']:.2f} · "
        f"Política: {policy['policy_version']} · "
        f"Aprovar abaixo de {policy['approve_max_score']:.2f} · "
        f"Reprovar a partir de {policy['manual_review_max_score']:.2f}"
    )
    st.info(
        "Este score é uma pontuação para ordenação de risco e não uma probabilidade "
        "calibrada de inadimplência. A recomendação é demonstrativa e requer validação humana."
    )
    with st.expander("Resposta completa da API"):
        st.json(result)


st.set_option("client.toolbarMode", "minimal")
st.set_page_config(page_title="Análise de Crédito", page_icon="💳", layout="wide")
st.title("Análise de risco de crédito", anchor=False)
st.caption("Simulador para apoio ao analista de crédito")

with st.sidebar:
    st.header("Configuração")
    api_url = st.text_input("URL da FastAPI", value=DEFAULT_API_URL).rstrip("/")
    if st.button("Verificar conexão", use_container_width=True):
        try:
            health = api_request("GET", f"{api_url}/health")
            if health.get("status") == "ok" and health.get("model_loaded"):
                st.success("API conectada e modelo carregado.")
            else:
                st.warning("A API respondeu, mas o modelo não está disponível.")
        except RuntimeError as error:
            st.error(str(error))
    st.divider()
    st.caption("A interface envia os dados à API. O modelo permanece isolado no backend.")

tab_new_customer, tab_loaded_customer, tab_customer = st.tabs(
    (
        "Novo cliente",
        "Buscar cliente e editar",
        "Consultar cliente do banco",
    )
)

with tab_new_customer:
    st.write(
        "Preencha os campos que você tem sobre o cliente. Nos opcionais sem resposta, "
        "marque o controle de ausência ao lado — a API completa esses com a mesma regra "
        "aplicada à população de treino."
    )
    application, new_customer_submitted = render_new_customer_form(key_prefix="new_customer")

    if new_customer_submitted:
        missing_labels = [
            field.label
            for field in APPLICATION_FIELDS
            if application[field.name] is None
            and not st.session_state.get(_unavailable_checkbox_key(field, "new_customer"), False)
        ]
        if missing_labels:
            st.error("Preencha os campos obrigatórios: " + ", ".join(missing_labels))
        else:
            with st.expander("JSON enviado à API"):
                st.json(application)
            try:
                with st.spinner("Transformando o registro e calculando o score..."):
                    result = api_request(
                        "POST", f"{api_url}/predict/new-customer", json=application
                    )
                show_result(result)
            except RuntimeError as error:
                st.error(str(error))

with tab_loaded_customer:
    st.write(
        "Busque um cliente na base, carregue as features no formulário e ajuste "
        "os campos antes de enviar para análise."
    )

    lookup_columns = st.columns([2, 1])
    with lookup_columns[0]:
        lookup_customer_id = st.number_input(
            "Código do cliente para carregar dados",
            min_value=1,
            value=100002,
            step=1,
            key="lookup_customer_id",
        )
    with lookup_columns[1]:
        st.write("")
        st.write("")
        lookup_submitted = st.button(
            "Buscar cliente",
            type="primary",
            use_container_width=True,
            key="lookup_customer_button",
        )

    if lookup_submitted:
        try:
            with st.spinner("Buscando features do cliente..."):
                loaded = api_request(
                    "GET",
                    f"{api_url}/customers/{int(lookup_customer_id)}/features",
                )
            st.session_state["loaded_customer_id"] = loaded["customer_id"]
            st.session_state["loaded_customer_features"] = loaded["features"]
            st.success(f"Cliente {loaded['customer_id']} carregado. Você pode editar os campos abaixo.")
        except RuntimeError as error:
            st.error(str(error))

    loaded_features = st.session_state.get("loaded_customer_features")
    loaded_customer_id = st.session_state.get("loaded_customer_id")

    if loaded_features:
        st.caption(f"Formulário preenchido com dados do cliente {loaded_customer_id}.")
        edited_features, edited_submitted = render_feature_form(
            form_key="loaded_credit_features_form",
            submit_label="Analisar crédito com dados editados",
            loaded_features=loaded_features,
            key_prefix=f"loaded_feature_{loaded_customer_id}",
        )

        if edited_submitted:
            payload = {"features": edited_features}
            with st.expander("JSON enviado à API"):
                st.json(payload)
            try:
                with st.spinner("Calculando o score de risco..."):
                    result = api_request("POST", f"{api_url}/predict/features", json=payload)
                result["customer_id"] = loaded_customer_id
                show_result(result)
            except RuntimeError as error:
                st.error(str(error))
    else:
        st.info("Informe um código de cliente e clique em “Buscar cliente” para preencher o formulário.")

with tab_customer:
    st.write("Informe um identificador existente para usar o endpoint `POST /predict/customer/{customer_id}`.")
    with st.form("customer_id_form"):
        customer_id = st.number_input("Código do cliente", min_value=1, value=100002, step=1)
        customer_submitted = st.form_submit_button("Consultar e analisar", type="primary", use_container_width=True)

    if customer_submitted:
        try:
            with st.spinner("Consultando as fontes e calculando o risco..."):
                result = api_request("POST", f"{api_url}/predict/customer/{int(customer_id)}")
            show_result(result)
        except RuntimeError as error:
            st.error(str(error))

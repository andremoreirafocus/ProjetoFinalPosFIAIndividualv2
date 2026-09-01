"""Metadados dos campos enviados a POST /predict/features e a POST /predict/new-customer."""

from dataclasses import dataclass
from typing import Any, Literal


@dataclass(frozen=True)
class FieldConfig:
    name: str
    label: str
    group: str
    kind: Literal["number", "integer", "category", "boolean", "date"] = "number"
    default: float | int | str | None = 0.0
    help: str = ""
    options: tuple[str, ...] = ()
    minimum: float | None = None
    maximum: float | None = None
    step: float = 0.01
    optional: bool = False
    """Exibe o controle de ausência definido por `unavailable_checkbox_label` — só os
    campos brutos usam isto."""
    boolean_values: tuple[Any, Any] = (1, 0)
    """(valor de "Sim", valor de "Não") — só `flag_own_car` diverge do padrão `(1, 0)`,
    porque a coluna bruta é texto ("Y"/"N"), não a flag derivada que o pipeline calcula."""
    date_max_years_ago: float | None = None
    """Só para kind="date": o máximo de anos que o seletor permite voltar. O limite
    superior é sempre hoje — nenhum dos campos de data é um evento futuro."""
    unavailable_checkbox_label: str = "Não disponível"
    """Texto do controle de ausência, para optional=True. Só diverge do padrão quando o
    `null` do campo não significa "não sei" — caso de `days_employed`, onde significa uma
    resposta definitiva ("sem vínculo empregatício")."""


# Domínios de categóricas compartilhados entre FIELDS e APPLICATION_FIELDS. Em cada um, a
# versão de APPLICATION_FIELDS exclui o valor que só a sanitização produz — não é um
# domínio à parte, é subconjunto do mesmo domínio abaixo.
OCCUPATION_TYPE_OPTIONS = (
    "Accountants", "Cleaning staff", "Cooking staff", "Core staff", "Drivers",
    "High skill tech staff", "HR staff", "IT staff", "Laborers", "Low-skill Laborers",
    "Managers", "Medicine staff", "Private service staff", "Realty agents",
    "Sales staff", "Secretaries", "Security staff", "Unknown", "Waiters/barmen staff",
)
ORGANIZATION_TYPE_OPTIONS = (
    "Agriculture", "Bank", "Business Entity Type 1", "Business Entity Type 2",
    "Business Entity Type 3", "Construction", "Electricity", "Emergency",
    "Government", "Hotel", "Housing", "Industry: type 1", "Industry: type 11",
    "Industry: type 3", "Industry: type 4", "Industry: type 5", "Industry: type 7",
    "Industry: type 9", "Insurance", "Kindergarten", "Medicine", "Military",
    "Other", "Other_low_freq", "Police", "Postal", "Restaurant", "School",
    "Security", "Security Ministries", "Self-employed", "Services", "Telecom",
    "Trade: type 2", "Trade: type 3", "Trade: type 6", "Trade: type 7",
    "Transport: type 2", "Transport: type 3", "Transport: type 4", "University",
    "XNA",
)
NAME_INCOME_TYPE_OPTIONS = (
    "Commercial associate", "Other_low_freq", "Pensioner", "State servant", "Working",
)
NAME_EDUCATION_TYPE_OPTIONS = (
    "Academic degree", "Higher education", "Incomplete higher", "Lower secondary",
    "Secondary / secondary special", "Unknown",
)


FIELDS = (
    FieldConfig("ext_source_1", "Score externo 1", "Scores e localização", default=0.50, minimum=0, maximum=1, step=0.01),
    FieldConfig("ext_source_2", "Score externo 2", "Scores e localização", default=0.50, minimum=0, maximum=1, step=0.01),
    FieldConfig("ext_source_3", "Score externo 3", "Scores e localização", default=0.50, minimum=0, maximum=1, step=0.01),
    FieldConfig("ext_source_mean", "Média dos scores externos", "Scores e localização", default=0.50, minimum=0, maximum=1, step=0.01),
    FieldConfig("region_rating_client_w_city", "Classificação da região com cidade", "Scores e localização", "integer", 2, minimum=1, maximum=3, step=1),
    FieldConfig("reg_city_not_work_city", "Mora em cidade diferente do trabalho", "Scores e localização", "boolean", 0),
    FieldConfig("reg_city_not_live_city", "Registro em cidade diferente da residência", "Scores e localização", "boolean", 0),
    FieldConfig("live_city_not_work_city", "Residência em cidade diferente do trabalho", "Scores e localização", "boolean", 0),

    FieldConfig("age", "Idade (anos)", "Perfil pessoal", default=35.0, minimum=18, maximum=100, step=1),
    FieldConfig("years_employed", "Tempo empregado (anos)", "Perfil pessoal", default=5.0, minimum=0, maximum=70, step=0.5),
    FieldConfig("cnt_children", "Quantidade de filhos", "Perfil pessoal", "integer", 0, minimum=0, maximum=20, step=1),
    FieldConfig("cnt_fam_members", "Membros da família", "Perfil pessoal", default=1.0, minimum=1, maximum=30, step=1),
    FieldConfig("has_car", "Possui carro", "Perfil pessoal", "boolean", 0),
    FieldConfig("own_car_age", "Idade do veículo (anos)", "Perfil pessoal", default=0.0, minimum=0, maximum=100, step=1),
    FieldConfig("occupation_type", "Ocupação", "Perfil pessoal", "category", "Laborers", options=OCCUPATION_TYPE_OPTIONS),
    FieldConfig("organization_type", "Tipo de organização", "Perfil pessoal", "category", "Business Entity Type 3", options=ORGANIZATION_TYPE_OPTIONS),
    FieldConfig("name_income_type", "Tipo de renda", "Perfil pessoal", "category", "Working", options=NAME_INCOME_TYPE_OPTIONS),
    FieldConfig("name_education_type", "Escolaridade", "Perfil pessoal", "category", "Secondary / secondary special", options=NAME_EDUCATION_TYPE_OPTIONS),
    FieldConfig("code_gender", "Gênero cadastrado", "Perfil pessoal", "category", "F", options=("F", "M", "Unknown")),

    FieldConfig("amt_income_total", "Renda total", "Valores financeiros", default=202_500.0, minimum=0, step=500),
    FieldConfig("amt_credit", "Valor do crédito", "Valores financeiros", default=406_597.5, minimum=0, step=500),
    FieldConfig("amt_annuity", "Valor da anuidade/parcela", "Valores financeiros", default=24_700.5, minimum=0, step=100),
    FieldConfig("fe_credit_income_percent", "Crédito / renda", "Valores financeiros", default=2.0, minimum=0, step=0.01),
    FieldConfig("fe_annuity_income_percent", "Parcela / renda", "Valores financeiros", default=0.15, minimum=0, step=0.01),

    FieldConfig("days_last_phone_change", "Dias desde a última troca de telefone", "Histórico cadastral", default=-1134.0, maximum=0, step=1, help="A base representa eventos passados com valores negativos."),
    FieldConfig("days_id_publish", "Dias desde a emissão do documento", "Histórico cadastral", default=-2120, maximum=0, step=1),
    FieldConfig("days_registration", "Dias desde o registro", "Histórico cadastral", default=-3648.0, maximum=0, step=1),
    FieldConfig("days_employed_anom", "Tempo de emprego anômalo", "Histórico cadastral", "boolean", 0),
    FieldConfig("def_60_cnt_social_circle", "Inadimplências em 60 dias no círculo social", "Histórico cadastral", default=0.0, minimum=0, step=1),
    FieldConfig("amt_req_credit_bureau_year", "Consultas ao bureau no último ano", "Histórico cadastral", default=0.0, minimum=0, step=1),

    FieldConfig("prev_refused_rate", "Taxa de propostas anteriores recusadas", "Histórico de crédito", default=0.0, minimum=0, maximum=1, step=0.01),
    FieldConfig("has_prev_app", "Tem propostas anteriores", "Histórico de crédito", "boolean", 1),
    FieldConfig("bureau_avg_days_credit", "Média de dias dos créditos no bureau", "Histórico de crédito", default=-874.0, maximum=0, step=1),
    FieldConfig("bureau_last_days_credit", "Dias desde o crédito mais recente no bureau", "Histórico de crédito", default=-103.0, maximum=0, step=1),
    FieldConfig("bureau_active_rate", "Proporção de créditos ativos", "Histórico de crédito", default=0.25, minimum=0, maximum=1, step=0.01),
    FieldConfig("bureau_active_count", "Quantidade de créditos ativos", "Histórico de crédito", default=2.0, minimum=0, step=1),
    FieldConfig("bureau_closed_rate", "Proporção de créditos encerrados", "Histórico de crédito", default=0.75, minimum=0, maximum=1, step=0.01),
    FieldConfig("bureau_debt_credit_ratio", "Dívida / crédito no bureau", "Histórico de crédito", default=0.0, minimum=-1, maximum=1, step=0.01),
    FieldConfig("bureau_overdue_count", "Créditos em atraso no bureau", "Histórico de crédito", default=0.0, minimum=0, step=1),
    FieldConfig("has_bureau", "Tem histórico no bureau", "Histórico de crédito", "boolean", 1),
    FieldConfig("inst_late_payment_rate", "Taxa de parcelas pagas com atraso", "Histórico de parcelas", default=0.0, minimum=0, maximum=1, step=0.01),
    FieldConfig("has_installments_history", "Tem histórico de parcelas", "Histórico de parcelas", "boolean", 1),
)

FIELD_NAMES = tuple(field.name for field in FIELDS)
GROUPS = tuple(dict.fromkeys(field.group for field in FIELDS))


# Campos brutos que POST /predict/new-customer recebe — mesmo conjunto e mesmos
# tipos de `NewCustomerApplication` (MLOps/app/api/schemas.py), verificado por
# `test_application_fields_match_new_customer_application_fields`. Os domínios das
# categóricas são os valores brutos: sem `'Unknown'`/`'Other_low_freq'`, que a
# sanitização produz e o analista nunca informa; `code_gender` inclui `'XNA'`, valor
# bruto real ausente da lista de `FIELDS`.
APPLICATION_FIELDS = (
    # Mesma ordem de domínio de GROUPS/FIELDS, para que "Novo cliente" e "Buscar
    # cliente e editar" apresentem as mesmas seções, na mesma ordem. Obrigatoriedade
    # é atributo por campo (`optional`), não posição na tupla: os campos sem
    # `optional=True` são obrigatórios porque a sanitização não sabe preenchê-los —
    # não têm regra de imputação — e propagam NULL até a fronteira de validação.
    FieldConfig("ext_source_1", "Score externo 1", "Scores e localização", default=None, minimum=0, maximum=1, step=0.01, optional=True),
    FieldConfig("ext_source_2", "Score externo 2", "Scores e localização", default=None, minimum=0, maximum=1, step=0.01, optional=True),
    FieldConfig("ext_source_3", "Score externo 3", "Scores e localização", default=None, minimum=0, maximum=1, step=0.01, optional=True),
    FieldConfig("region_rating_client_w_city", "Classificação da região com cidade", "Scores e localização", "integer", None, minimum=1, maximum=3, step=1),
    FieldConfig("reg_city_not_work_city", "Mora em cidade diferente do trabalho", "Scores e localização", "boolean", None, optional=True),
    FieldConfig("reg_city_not_live_city", "Registro em cidade diferente da residência", "Scores e localização", "boolean", None, optional=True),
    FieldConfig("live_city_not_work_city", "Residência em cidade diferente do trabalho", "Scores e localização", "boolean", None, optional=True),

    FieldConfig("days_birth", "Data de nascimento", "Perfil pessoal", "date", None, date_max_years_ago=100.0),
    FieldConfig("days_employed", "Data de início do emprego", "Perfil pessoal", "date", None, date_max_years_ago=70.0, optional=True, unavailable_checkbox_label="Sem vínculo empregatício"),
    FieldConfig("cnt_children", "Quantidade de filhos", "Perfil pessoal", "integer", None, minimum=0, maximum=20, step=1, optional=True),
    FieldConfig("cnt_fam_members", "Membros da família", "Perfil pessoal", default=None, minimum=1, maximum=30, step=1, optional=True),
    FieldConfig("flag_own_car", "Possui carro", "Perfil pessoal", "boolean", None, boolean_values=("Y", "N"), optional=True),
    FieldConfig("own_car_age", "Idade do veículo (anos)", "Perfil pessoal", default=None, minimum=0, maximum=100, step=1, optional=True),
    FieldConfig("occupation_type", "Ocupação", "Perfil pessoal", "category", None, options=tuple(o for o in OCCUPATION_TYPE_OPTIONS if o != "Unknown"), optional=True),
    FieldConfig("organization_type", "Tipo de organização", "Perfil pessoal", "category", None, options=tuple(o for o in ORGANIZATION_TYPE_OPTIONS if o != "Other_low_freq"), optional=True),
    FieldConfig("name_income_type", "Tipo de renda", "Perfil pessoal", "category", None, options=tuple(o for o in NAME_INCOME_TYPE_OPTIONS if o != "Other_low_freq"), optional=True),
    FieldConfig("name_education_type", "Escolaridade", "Perfil pessoal", "category", None, options=tuple(o for o in NAME_EDUCATION_TYPE_OPTIONS if o != "Unknown"), optional=True),
    FieldConfig("code_gender", "Gênero cadastrado", "Perfil pessoal", "category", None, options=("F", "M", "XNA"), optional=True),

    FieldConfig("amt_income_total", "Renda total", "Valores financeiros", default=None, minimum=0, step=500, optional=True),
    FieldConfig("amt_credit", "Valor do crédito", "Valores financeiros", default=None, minimum=0, step=500),
    FieldConfig("amt_annuity", "Valor da anuidade/parcela", "Valores financeiros", default=None, minimum=0, step=100, optional=True),

    FieldConfig("days_last_phone_change", "Data da última troca de telefone", "Histórico cadastral", "date", None, date_max_years_ago=100.0, optional=True),
    FieldConfig("days_id_publish", "Data de emissão do documento", "Histórico cadastral", "date", None, date_max_years_ago=100.0),
    FieldConfig("days_registration", "Data de alteração do registro", "Histórico cadastral", "date", None, date_max_years_ago=100.0),
    FieldConfig("def_60_cnt_social_circle", "Inadimplências em 60 dias no círculo social", "Histórico cadastral", default=None, minimum=0, step=1, optional=True),
    FieldConfig("amt_req_credit_bureau_year", "Consultas ao bureau no último ano", "Histórico cadastral", default=None, minimum=0, step=1, optional=True),
)

APPLICATION_FIELD_NAMES = tuple(field.name for field in APPLICATION_FIELDS)
APPLICATION_GROUPS = tuple(dict.fromkeys(field.group for field in APPLICATION_FIELDS))

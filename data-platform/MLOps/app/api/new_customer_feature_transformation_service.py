"""Reproduz, por registro, a sanitização e a construção da ABT que o pipeline aplica à
população inteira — para um cliente novo, que ainda não existe em nenhuma tabela.

Executa as duas projeções compartilhadas com o `DataPipeline`
(`application_sanitization_projection.sql` e `application_abt_record_projection.sql`) por
`SELECT` sobre `VALUES`: nenhuma escrita no banco, e nenhuma tabela é lida — a origem de cada
marcador é literal, construída a partir do registro recebido e do contrato de transformação do
bundle ativo.
"""
from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any

from sqlalchemy import Engine, text

from .model_bundle import ModelBundle


class TransformationRuleMismatchError(Exception):
    """O `.sql` da imagem diverge do que o contrato do bundle publicou, ou o contrato não
    cobre uma estatística que a projeção referencia."""


# Mesmas 26 colunas e tipos de `application_train` que a sanitização lê — a mesma referência
# de tipos que `DataPipeline/tests/test_sanitization_app.py::APPLICATION_SCHEMA` declara.
_APPLICATION_COLUMN_TYPES: dict[str, str] = {
    "ext_source_1": "double precision",
    "ext_source_2": "double precision",
    "ext_source_3": "double precision",
    "days_last_phone_change": "double precision",
    "cnt_fam_members": "double precision",
    "amt_annuity": "double precision",
    "amt_income_total": "double precision",
    "own_car_age": "double precision",
    "flag_own_car": "text",
    "organization_type": "text",
    "name_income_type": "text",
    "region_rating_client_w_city": "bigint",
    "days_id_publish": "bigint",
    "days_registration": "bigint",
    "reg_city_not_work_city": "bigint",
    "reg_city_not_live_city": "bigint",
    "live_city_not_work_city": "bigint",
    "def_60_cnt_social_circle": "double precision",
    "amt_req_credit_bureau_year": "double precision",
    "cnt_children": "bigint",
    "amt_credit": "double precision",
    "occupation_type": "text",
    "name_education_type": "text",
    "code_gender": "text",
    "days_birth": "bigint",
    "days_employed": "bigint",
}

# As dez estatísticas de `application_sanitization_last_run`, todas `double precision` — a
# forma que `application_sanitization_stats.sql` produz.
_STATS_COLUMN_TYPES: dict[str, str] = {
    "median_es1": "double precision",
    "median_es2": "double precision",
    "median_es3": "double precision",
    "median_es_mean": "double precision",
    "median_phone": "double precision",
    "median_fam": "double precision",
    "median_annuity": "double precision",
    "median_income": "double precision",
    "p_limit_income": "double precision",
    "median_car_age": "double precision",
}

# As origens vazias dos três agregados — mesmos nomes e tipos que `abt_transform.py` produz
# em `tmp_prev_application_agg`, `tmp_bureau_agg` e `tmp_installments_agg`. Só as colunas que
# `application_abt_record_projection.sql` lê entram aqui.
_EMPTY_PREV_AGG = (
    "(SELECT NULL::bigint, NULL::double precision WHERE false) "
    "AS p(sk_id_curr, prev_refused_rate)"
)
_EMPTY_BUREAU_AGG = (
    "(SELECT NULL::bigint, NULL::numeric, NULL::numeric, NULL::double precision, "
    "NULL::bigint, NULL::double precision, NULL::numeric, NULL::bigint WHERE false) "
    "AS b(sk_id_curr, bureau_avg_days_credit, bureau_last_days_credit, bureau_active_rate, "
    "bureau_active_count, bureau_closed_rate, bureau_debt_credit_ratio, bureau_overdue_count)"
)
_EMPTY_INST_AGG = (
    "(SELECT NULL::bigint, NULL::numeric WHERE false) AS i(sk_id_curr, inst_late_payment_rate)"
)

_STATS_REFERENCE_PATTERN = re.compile(r"\bstats\.(\w+)")


class NewCustomerFeatureTransformationService:
    """Aplica as duas projeções compartilhadas com o pipeline a um único registro bruto.

    Os hashes dos dois `.sql` são calculados uma vez, na construção. A comparação com o
    contrato do bundle acontece a cada transformação, porque o bundle ativo pode ser trocado
    em execução.
    """

    def __init__(self, engine: Engine, sql_directory: Path) -> None:
        self._engine = engine

        sanitization_path = sql_directory / "application_sanitization_projection.sql"
        abt_path = sql_directory / "application_abt_record_projection.sql"

        self._sanitization_projection_text = sanitization_path.read_text(encoding="utf-8")
        self._abt_record_projection_text = abt_path.read_text(encoding="utf-8")
        self._sanitization_projection_sha256 = hashlib.sha256(
            sanitization_path.read_bytes()
        ).hexdigest()
        self._abt_record_projection_sha256 = hashlib.sha256(
            abt_path.read_bytes()
        ).hexdigest()
        self._referenced_stats_names = frozenset(
            _STATS_REFERENCE_PATTERN.findall(self._sanitization_projection_text)
        )

    def transform(
        self, bundle: ModelBundle, application_record: dict[str, Any]
    ) -> dict[str, Any]:
        contract = bundle.transformation_contract
        self._check_hash(
            "application_sanitization_projection.sql",
            self._sanitization_projection_sha256,
            contract["application_sanitization_projection_sha256"],
        )
        self._check_hash(
            "application_abt_record_projection.sql",
            self._abt_record_projection_sha256,
            contract["application_abt_record_projection_sha256"],
        )
        self._check_stats_coverage(contract["stats"])

        params: dict[str, Any] = {}

        app_source, app_params = _application_record_source(application_record)
        params.update(app_params)
        stats_source, stats_params = _stats_source(contract["stats"])
        params.update(stats_params)
        orgs_source, orgs_params = _category_source("o", "organization_type", "org", contract["valid_orgs"])
        params.update(orgs_params)
        incs_source, incs_params = _category_source("i", "name_income_type", "inc", contract["valid_incs"])
        params.update(incs_params)

        sanitization_select = self._sanitization_projection_text.format(
            identity_columns="",
            input_rows=app_source,
            stats=stats_source,
            valid_orgs=orgs_source,
            valid_incs=incs_source,
            employment_days_anomaly_sentinel=contract["employment_days_anomaly_sentinel"],
        )

        abt_select = self._abt_record_projection_text.format(
            input_rows=(
                "(SELECT 1::bigint AS sk_id_curr, sanitizado.* "
                f"FROM ({sanitization_select}) sanitizado) a"
            ),
            prev_agg=_EMPTY_PREV_AGG,
            bureau_agg=_EMPTY_BUREAU_AGG,
            inst_agg=_EMPTY_INST_AGG,
        )

        with self._engine.connect() as connection:
            row = connection.execute(text(abt_select), params).mappings().one()

        return {column: _python_value(value) for column, value in row.items()}

    def _check_hash(self, file_name: str, actual_sha256: str, expected_sha256: str) -> None:
        if actual_sha256 != expected_sha256:
            raise TransformationRuleMismatchError(
                f"'{file_name}' da imagem diverge do contrato do bundle ativo: "
                f"calculado {actual_sha256}, publicado {expected_sha256}."
            )

    def _check_stats_coverage(self, stats: dict[str, Any]) -> None:
        missing = self._referenced_stats_names.difference(stats)
        if missing:
            raise TransformationRuleMismatchError(
                "O contrato de transformação não cobre as estatísticas que "
                f"'application_sanitization_projection.sql' referencia: {sorted(missing)}."
            )


def _application_record_source(record: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    columns = list(_APPLICATION_COLUMN_TYPES)
    placeholders = ", ".join(
        f"CAST(:app_{column} AS {_APPLICATION_COLUMN_TYPES[column]})" for column in columns
    )
    column_list = ", ".join(columns)
    params = {f"app_{column}": record.get(column) for column in columns}
    return f"(VALUES ({placeholders})) AS app({column_list})", params


def _stats_source(stats: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    names = list(_STATS_COLUMN_TYPES)
    placeholders = ", ".join(
        f"CAST(:stat_{name} AS {_STATS_COLUMN_TYPES[name]})" for name in names
    )
    column_list = ", ".join(names)
    params = {f"stat_{name}": stats[name] for name in names}
    return f"(VALUES ({placeholders})) AS stats({column_list})", params


def _category_source(
    alias: str, column: str, prefix: str, values: list[str]
) -> tuple[str, dict[str, Any]]:
    if not values:
        return f"(SELECT NULL::text WHERE false) AS {alias}({column})", {}
    placeholder_names = [f"{prefix}_{index}" for index in range(len(values))]
    rows = ", ".join(f"(CAST(:{name} AS text))" for name in placeholder_names)
    params = dict(zip(placeholder_names, values))
    return f"(VALUES {rows}) AS {alias}({column})", params


def _python_value(value: Any) -> Any:
    return value.item() if hasattr(value, "item") else value

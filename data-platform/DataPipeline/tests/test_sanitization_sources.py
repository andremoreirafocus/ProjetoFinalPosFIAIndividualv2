"""T5 — Source sanitizations (prev / bureau / installments).

`run_prev_sanitization`: contract status normalized (INITCAP+TRIM); amount floored
at zero; other columns and row count preserved.
`run_bureau_sanitization`: null monetary/count columns → 0; categoricals trimmed;
row count preserved.
`run_installments_sanitization`: rows with a null required key/value dropped; valid
rows preserved; only the selected columns remain.
"""

import pytest

from data_sanitization import (
    run_bureau_sanitization,
    run_installments_sanitization,
    run_prev_sanitization,
)


# --- previous_application ----------------------------------------------------
PREV_SCHEMA = {
    "sk_id_curr": "BIGINT",
    "sk_id_prev": "BIGINT",
    "name_contract_status": "TEXT",
    "amt_application": "DOUBLE PRECISION",
    "name_contract_type": "TEXT",
}


def _prev(sk_id_prev, **overrides):
    row = {
        "sk_id_curr": 1,
        "sk_id_prev": sk_id_prev,
        "name_contract_status": "Approved",
        "amt_application": 1000.0,
        "name_contract_type": "Cash loans",
    }
    row.update(overrides)
    return row


def _run_prev(test_db, conexao, rows):
    test_db.create_table("previous_application", PREV_SCHEMA)
    test_db.insert("previous_application", rows)
    run_prev_sanitization(conexao, "previous_application", "previous_application_clean")


def _prev_by_id(test_db, sk_id_prev):
    return test_db.fetch_dicts(
        'SELECT * FROM previous_application_clean WHERE sk_id_prev = %s', (sk_id_prev,)
    )[0]


@pytest.mark.integration
def test_prev_contract_status_is_normalized(test_db, conexao):
    _run_prev(test_db, conexao, [_prev(1, name_contract_status="REFUSED "), _prev(2, name_contract_status="approved")])

    assert _prev_by_id(test_db, 1)["name_contract_status"] == "Refused"
    assert _prev_by_id(test_db, 2)["name_contract_status"] == "Approved"


@pytest.mark.integration
def test_prev_amount_is_floored_at_zero(test_db, conexao):
    _run_prev(
        test_db,
        conexao,
        [
            _prev(1, amt_application=-50),
            _prev(2, amt_application=None),
            _prev(3, amt_application=250),
        ],
    )

    assert float(_prev_by_id(test_db, 1)["amt_application"]) == 0
    assert float(_prev_by_id(test_db, 2)["amt_application"]) == 0
    assert float(_prev_by_id(test_db, 3)["amt_application"]) == 250


@pytest.mark.integration
def test_prev_untouched_columns_are_preserved(test_db, conexao):
    _run_prev(test_db, conexao, [_prev(1, name_contract_type="Revolving loans")])

    assert _prev_by_id(test_db, 1)["name_contract_type"] == "Revolving loans"


@pytest.mark.integration
def test_prev_row_count_is_preserved(test_db, conexao):
    rows = [_prev(1), _prev(2), _prev(3)]
    _run_prev(test_db, conexao, rows)

    assert test_db.row_count("previous_application_clean") == len(rows)


# --- bureau ------------------------------------------------------------------
BUREAU_SCHEMA = {
    "sk_id_curr": "BIGINT",
    "sk_id_bureau": "BIGINT",
    "credit_active": "TEXT",
    "credit_type": "TEXT",
    "amt_credit_sum": "DOUBLE PRECISION",
    "amt_credit_sum_debt": "DOUBLE PRECISION",
    "amt_credit_sum_overdue": "DOUBLE PRECISION",
    "credit_day_overdue": "DOUBLE PRECISION",
    "cnt_credit_prolong": "DOUBLE PRECISION",
    "days_credit": "DOUBLE PRECISION",
    "days_credit_update": "DOUBLE PRECISION",
}

BUREAU_ZERO_FILLED_COLUMNS = [
    "amt_credit_sum",
    "amt_credit_sum_debt",
    "amt_credit_sum_overdue",
    "credit_day_overdue",
    "cnt_credit_prolong",
]


def _bureau(sk_id_bureau, **overrides):
    row = {
        "sk_id_curr": 1,
        "sk_id_bureau": sk_id_bureau,
        "credit_active": "Active",
        "credit_type": "Consumer credit",
        "amt_credit_sum": 1000.0,
        "amt_credit_sum_debt": 500.0,
        "amt_credit_sum_overdue": 0.0,
        "credit_day_overdue": 0.0,
        "cnt_credit_prolong": 0.0,
        "days_credit": -100.0,
        "days_credit_update": -50.0,
    }
    row.update(overrides)
    return row


def _run_bureau(test_db, conexao, rows):
    test_db.create_table("bureau", BUREAU_SCHEMA)
    test_db.insert("bureau", rows)
    run_bureau_sanitization(conexao, "bureau", "bureau_clean")


def _bureau_by_id(test_db, sk_id_bureau):
    return test_db.fetch_dicts(
        'SELECT * FROM bureau_clean WHERE sk_id_bureau = %s', (sk_id_bureau,)
    )[0]


@pytest.mark.integration
def test_bureau_monetary_nulls_become_zero(test_db, conexao):
    overrides = {column: None for column in BUREAU_ZERO_FILLED_COLUMNS}
    _run_bureau(test_db, conexao, [_bureau(1, **overrides)])

    clean = _bureau_by_id(test_db, 1)
    for column in BUREAU_ZERO_FILLED_COLUMNS:
        assert float(clean[column]) == 0


@pytest.mark.integration
def test_bureau_categoricals_are_trimmed(test_db, conexao):
    _run_bureau(test_db, conexao, [_bureau(1, credit_active=" Active ", credit_type=" Consumer credit ")])

    clean = _bureau_by_id(test_db, 1)
    assert clean["credit_active"] == "Active"
    assert clean["credit_type"] == "Consumer credit"


@pytest.mark.integration
def test_bureau_row_count_is_preserved(test_db, conexao):
    rows = [_bureau(1), _bureau(2), _bureau(3)]
    _run_bureau(test_db, conexao, rows)

    assert test_db.row_count("bureau_clean") == len(rows)


# --- installments_payments ---------------------------------------------------
INSTALLMENTS_SCHEMA = {
    "sk_id_curr": "BIGINT",
    "sk_id_prev": "BIGINT",
    "num_instalment_version": "DOUBLE PRECISION",
    "num_instalment_number": "BIGINT",
    "days_instalment": "DOUBLE PRECISION",
    "days_entry_payment": "DOUBLE PRECISION",
    "amt_instalment": "DOUBLE PRECISION",
    "amt_payment": "DOUBLE PRECISION",
    "extra_col": "TEXT",
}

SELECTED_INSTALLMENT_COLUMNS = {
    "sk_id_curr",
    "sk_id_prev",
    "num_instalment_version",
    "num_instalment_number",
    "days_instalment",
    "days_entry_payment",
    "amt_instalment",
    "amt_payment",
}


def _installment(uid, **overrides):
    row = {
        "sk_id_curr": uid,
        "sk_id_prev": uid,
        "num_instalment_version": 1.0,
        "num_instalment_number": 1,
        "days_instalment": -100.0,
        "days_entry_payment": -98.0,
        "amt_instalment": 200.0,
        "amt_payment": 200.0,
        "extra_col": "kept-out",
    }
    row.update(overrides)
    return row


def _run_installments(test_db, conexao, rows):
    test_db.create_table("installments_payments", INSTALLMENTS_SCHEMA)
    test_db.insert("installments_payments", rows)
    run_installments_sanitization(conexao, "installments_payments", "installments_clean")


@pytest.mark.integration
def test_installments_rows_with_required_nulls_are_dropped(test_db, conexao):
    _run_installments(
        test_db,
        conexao,
        [
            _installment(1),
            _installment(2, sk_id_curr=None),
            _installment(3, sk_id_prev=None),
            _installment(4, days_instalment=None),
            _installment(5, amt_instalment=None),
            _installment(6),
        ],
    )

    survivors = {r["sk_id_curr"] for r in test_db.fetch_dicts("SELECT sk_id_curr FROM installments_clean")}
    assert survivors == {1, 6}


@pytest.mark.integration
def test_installments_valid_rows_are_preserved(test_db, conexao):
    _run_installments(test_db, conexao, [_installment(1), _installment(2)])

    survivors = {r["sk_id_curr"] for r in test_db.fetch_dicts("SELECT sk_id_curr FROM installments_clean")}
    assert survivors == {1, 2}


@pytest.mark.integration
def test_installments_keeps_only_selected_columns(test_db, conexao):
    _run_installments(test_db, conexao, [_installment(1)])

    assert set(test_db.table_columns("installments_clean")) == SELECTED_INSTALLMENT_COLUMNS


MARCADOR = "marcador_de_transacao"


@pytest.mark.integration
def test_sanitizacao_opera_na_conexao_recebida(test_db, conexao):
    """A conexão recebida é a que executa: o `commit` da função encerra esta transação."""
    test_db.create_table("previous_application", PREV_SCHEMA)
    test_db.create_table(MARCADOR, {"valor": "BIGINT"})
    with conexao.cursor() as cursor:
        cursor.execute(f'INSERT INTO "{MARCADOR}" (valor) VALUES (1)')

    run_prev_sanitization(conexao, "previous_application", "previous_application_clean")

    assert test_db.row_count(MARCADOR) == 1

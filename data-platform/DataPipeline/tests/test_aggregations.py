"""T7 — Per-customer aggregations (`create_agg_*`).

Each function collapses a cleaned history into one row per ``sk_id_curr`` in a
temporary aggregate table. Expected metrics are computed from the fixture rows.
"""

import pytest

from abt_transform import (
    create_agg_bureau,
    create_agg_installments,
    create_agg_previous_application,
)


# --- previous_application ----------------------------------------------------
PREV_CLEAN_SCHEMA = {
    "sk_id_curr": "BIGINT",
    "sk_id_prev": "BIGINT",
    "name_contract_status": "TEXT",
}


def _prev(customer, prev_id, status):
    return {"sk_id_curr": customer, "sk_id_prev": prev_id, "name_contract_status": status}


def _run_prev_agg(test_db, conexao, rows):
    test_db.create_table("previous_application_clean", PREV_CLEAN_SCHEMA)
    test_db.insert("previous_application_clean", rows)
    create_agg_previous_application(conexao, "previous_application_clean")


MARCADOR = "marcador_de_transacao"


@pytest.mark.integration
def test_agregacao_opera_na_conexao_recebida(test_db, conexao):
    """A conexão recebida é a que executa: o `commit` da função encerra esta transação.

    Se a função abrir a própria conexão, a escrita pendente aqui continua invisível para
    quem observa de fora — que é o defeito que esta etapa remove.
    """
    test_db.create_table("previous_application_clean", PREV_CLEAN_SCHEMA)
    test_db.create_table(MARCADOR, {"valor": "BIGINT"})
    with conexao.cursor() as cursor:
        cursor.execute(f'INSERT INTO "{MARCADOR}" (valor) VALUES (1)')

    create_agg_previous_application(conexao, "previous_application_clean")

    assert test_db.row_count(MARCADOR) == 1


@pytest.mark.integration
def test_prev_aggregation_is_one_row_per_customer(test_db, conexao):
    rows = [
        _prev(1, 11, "Refused"),
        _prev(1, 12, "Approved"),
        _prev(2, 21, "Approved"),
    ]
    _run_prev_agg(test_db, conexao, rows)

    distinct_customers = {row["sk_id_curr"] for row in rows}
    assert test_db.row_count("tmp_prev_application_agg") == len(distinct_customers)


@pytest.mark.integration
def test_prev_refused_rate_matches_fixture(test_db, conexao):
    rows = [
        _prev(1, 11, "Refused"),
        _prev(1, 12, "Approved"),
        _prev(1, 13, "Approved"),
        _prev(1, 14, "Approved"),
        _prev(2, 21, "Approved"),
        _prev(2, 22, "Approved"),
    ]
    _run_prev_agg(test_db, conexao, rows)

    agg = {r["sk_id_curr"]: r["prev_refused_rate"] for r in test_db.fetch_dicts("SELECT * FROM tmp_prev_application_agg")}

    def refused_rate(customer):
        total = [r for r in rows if r["sk_id_curr"] == customer]
        refused = [r for r in total if r["name_contract_status"] == "Refused"]
        return len(refused) / len(total)

    assert agg[1] == pytest.approx(refused_rate(1))
    assert agg[2] == pytest.approx(refused_rate(2))


# --- bureau ------------------------------------------------------------------
BUREAU_CLEAN_SCHEMA = {
    "sk_id_curr": "BIGINT",
    "sk_id_bureau": "BIGINT",
    "days_credit": "DOUBLE PRECISION",
    "credit_active": "TEXT",
    "amt_credit_sum": "DOUBLE PRECISION",
    "amt_credit_sum_debt": "DOUBLE PRECISION",
    "credit_day_overdue": "DOUBLE PRECISION",
}


def _bureau(customer, bureau_id, **overrides):
    row = {
        "sk_id_curr": customer,
        "sk_id_bureau": bureau_id,
        "days_credit": -100.0,
        "credit_active": "Active",
        "amt_credit_sum": 1000.0,
        "amt_credit_sum_debt": 0.0,
        "credit_day_overdue": 0.0,
    }
    row.update(overrides)
    return row


def _run_bureau_agg(test_db, conexao, rows):
    test_db.create_table("bureau_clean", BUREAU_CLEAN_SCHEMA)
    test_db.insert("bureau_clean", rows)
    create_agg_bureau(conexao, "bureau_clean")


@pytest.mark.integration
def test_bureau_aggregation_metrics_match_fixture(test_db, conexao):
    rows = [
        _bureau(1, 101, days_credit=-100, credit_active="Active", amt_credit_sum=1000, amt_credit_sum_debt=100, credit_day_overdue=5),
        _bureau(1, 102, days_credit=-200, credit_active="Closed", amt_credit_sum=500, amt_credit_sum_debt=200, credit_day_overdue=0),
        _bureau(1, 103, days_credit=-300, credit_active="Active", amt_credit_sum=500, amt_credit_sum_debt=0, credit_day_overdue=0),
    ]
    _run_bureau_agg(test_db, conexao, rows)

    agg = test_db.fetch_dicts("SELECT * FROM tmp_bureau_agg WHERE sk_id_curr = 1")[0]

    days = [row["days_credit"] for row in rows]
    active = [row for row in rows if row["credit_active"] == "Active"]
    closed = [row for row in rows if row["credit_active"] == "Closed"]
    debt_sum = sum(row["amt_credit_sum_debt"] for row in rows)
    credit_sum = sum(row["amt_credit_sum"] for row in rows)
    overdue = [row for row in rows if row["credit_day_overdue"] > 0]

    assert agg["bureau_credit_count"] == len(rows)
    assert float(agg["bureau_avg_days_credit"]) == pytest.approx(sum(days) / len(days))
    assert float(agg["bureau_last_days_credit"]) == pytest.approx(max(days))
    assert agg["bureau_active_count"] == len(active)
    assert float(agg["bureau_active_rate"]) == pytest.approx(len(active) / len(rows))
    assert float(agg["bureau_closed_rate"]) == pytest.approx(len(closed) / len(rows))
    assert float(agg["bureau_debt_credit_ratio"]) == pytest.approx(debt_sum / credit_sum)
    assert agg["bureau_overdue_count"] == len(overdue)


@pytest.mark.integration
def test_bureau_debt_credit_ratio_handles_zero_credit(test_db, conexao):
    rows = [_bureau(9, 900, amt_credit_sum=0, amt_credit_sum_debt=50)]
    _run_bureau_agg(test_db, conexao, rows)

    agg = test_db.fetch_dicts("SELECT * FROM tmp_bureau_agg WHERE sk_id_curr = 9")[0]
    assert agg["bureau_debt_credit_ratio"] is None


# --- installments_payments ---------------------------------------------------
INSTALLMENTS_CLEAN_SCHEMA = {
    "sk_id_curr": "BIGINT",
    "days_instalment": "DOUBLE PRECISION",
    "days_entry_payment": "DOUBLE PRECISION",
}


def _installment(customer, days_instalment, days_entry_payment):
    return {
        "sk_id_curr": customer,
        "days_instalment": days_instalment,
        "days_entry_payment": days_entry_payment,
    }


def _run_installments_agg(test_db, conexao, rows):
    test_db.create_table("installments_clean", INSTALLMENTS_CLEAN_SCHEMA)
    test_db.insert("installments_clean", rows)
    create_agg_installments(conexao, "installments_clean")


@pytest.mark.integration
def test_installments_late_rate_matches_fixture(test_db, conexao):
    rows = [
        _installment(1, -100, -90),   # paid late (diff +10)
        _installment(1, -100, -100),  # on time (diff 0)
        _installment(1, -100, -110),  # early (diff -10)
        _installment(1, -100, -80),   # paid late (diff +20)
    ]
    _run_installments_agg(test_db, conexao, rows)

    agg = test_db.fetch_dicts("SELECT * FROM tmp_installments_agg WHERE sk_id_curr = 1")[0]
    late = [r for r in rows if (r["days_entry_payment"] - r["days_instalment"]) > 0]
    assert float(agg["inst_late_payment_rate"]) == pytest.approx(len(late) / len(rows))


@pytest.mark.integration
def test_aggregations_group_by_customer(test_db, conexao):
    rows = [
        _installment(1, -100, -90),
        _installment(1, -100, -100),
        _installment(2, -100, -90),
        _installment(2, -100, -80),
    ]
    _run_installments_agg(test_db, conexao, rows)

    distinct_customers = {row["sk_id_curr"] for row in rows}
    assert test_db.row_count("tmp_installments_agg") == len(distinct_customers)

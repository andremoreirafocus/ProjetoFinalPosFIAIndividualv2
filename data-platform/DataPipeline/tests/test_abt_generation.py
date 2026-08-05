"""T8 — ABT generation (`run_abt_generation`).

The final ELT stitches the cleaned application table to the three per-customer
aggregates (`tmp_*_agg`) via LEFT JOINs. This module runs the *real* aggregations
to materialize those temporary tables, then runs the generation — exercising the
end-to-end coupling by convention that the code relies on.

Internal-parsing contract: reads the source table from ``config["output_table"]``
and the target from ``config["abt_table"]``.
Effect contract: one row per customer; customers without history keep zero flags and
coalesced rates; customers with history get flag 1 and the aggregates; income ratios
are computed when income > 0 and null when income = 0; the temporary aggregation
tables are dropped at the end.
"""

import statistics

import pytest

from abt_transform import (
    create_agg_bureau,
    create_agg_installments,
    create_agg_previous_application,
    run_abt_generation,
)


CONN_ID = "postgres_data_db"

DEFAULT_SOURCE = "application_clean"
DEFAULT_ABT = "application_abt"

TMP_AGG_TABLES = ["tmp_prev_application_agg", "tmp_bureau_agg", "tmp_installments_agg"]

CUSTOMER_WITH_HISTORY = 1
CUSTOMER_WITHOUT_HISTORY = 2


# --- schemas -----------------------------------------------------------------
APP_CLEAN_SCHEMA = {
    "sk_id_curr": "BIGINT",
    "amt_income_total": "DOUBLE PRECISION",
    "amt_credit": "DOUBLE PRECISION",
    "amt_annuity": "DOUBLE PRECISION",
}

PREV_CLEAN_SCHEMA = {
    "sk_id_curr": "BIGINT",
    "sk_id_prev": "BIGINT",
    "name_contract_status": "TEXT",
}

BUREAU_CLEAN_SCHEMA = {
    "sk_id_curr": "BIGINT",
    "sk_id_bureau": "BIGINT",
    "days_credit": "DOUBLE PRECISION",
    "credit_active": "TEXT",
    "amt_credit_sum": "DOUBLE PRECISION",
    "amt_credit_sum_debt": "DOUBLE PRECISION",
    "credit_day_overdue": "DOUBLE PRECISION",
}

INSTALLMENTS_CLEAN_SCHEMA = {
    "sk_id_curr": "BIGINT",
    "days_instalment": "DOUBLE PRECISION",
    "days_entry_payment": "DOUBLE PRECISION",
}


# --- canonical fixture -------------------------------------------------------
# Customer 1: positive income, history in all three sources.
# Customer 2: zero income, no history anywhere.
APP_ROWS = [
    {"sk_id_curr": 1, "amt_income_total": 100000.0, "amt_credit": 500000.0, "amt_annuity": 25000.0},
    {"sk_id_curr": 2, "amt_income_total": 0.0, "amt_credit": 300000.0, "amt_annuity": 15000.0},
]

PREV_ROWS = [
    {"sk_id_curr": 1, "sk_id_prev": 11, "name_contract_status": "Refused"},
    {"sk_id_curr": 1, "sk_id_prev": 12, "name_contract_status": "Approved"},
]


def _bureau(sk_id_bureau, days_credit):
    return {
        "sk_id_curr": 1,
        "sk_id_bureau": sk_id_bureau,
        "days_credit": days_credit,
        "credit_active": "Active",
        "amt_credit_sum": 1000.0,
        "amt_credit_sum_debt": 0.0,
        "credit_day_overdue": 0.0,
    }


BUREAU_ROWS = [_bureau(101, -100.0), _bureau(102, -300.0)]

INSTALLMENTS_ROWS = [
    {"sk_id_curr": 1, "days_instalment": -100.0, "days_entry_payment": -90.0},   # late (+10)
    {"sk_id_curr": 1, "days_instalment": -100.0, "days_entry_payment": -110.0},  # early (-10)
]


# Expected aggregates for the customer with history, derived from the fixture.
EXPECTED_PREV_REFUSED_RATE = sum(
    1 for r in PREV_ROWS if r["name_contract_status"] == "Refused"
) / len(PREV_ROWS)
EXPECTED_BUREAU_AVG_DAYS_CREDIT = statistics.mean(r["days_credit"] for r in BUREAU_ROWS)
EXPECTED_INST_LATE_RATE = sum(
    1 for r in INSTALLMENTS_ROWS if (r["days_entry_payment"] - r["days_instalment"]) > 0
) / len(INSTALLMENTS_ROWS)


def _generate(db, clean_table=DEFAULT_SOURCE, abt_table=DEFAULT_ABT):
    """Build the four cleaned tables, run the three aggregations, then the ABT ELT."""
    db.create_table(clean_table, APP_CLEAN_SCHEMA)
    db.insert(clean_table, APP_ROWS)

    db.create_table("previous_application_clean", PREV_CLEAN_SCHEMA)
    db.insert("previous_application_clean", PREV_ROWS)
    create_agg_previous_application(CONN_ID, "previous_application_clean")

    db.create_table("bureau_clean", BUREAU_CLEAN_SCHEMA)
    db.insert("bureau_clean", BUREAU_ROWS)
    create_agg_bureau(CONN_ID, "bureau_clean")

    db.create_table("installments_clean", INSTALLMENTS_CLEAN_SCHEMA)
    db.insert("installments_clean", INSTALLMENTS_ROWS)
    create_agg_installments(CONN_ID, "installments_clean")

    run_abt_generation(CONN_ID, {"output_table": clean_table, "abt_table": abt_table})


def _abt_by_customer(db, abt_table=DEFAULT_ABT):
    return {row["sk_id_curr"]: row for row in db.fetch_dicts(f'SELECT * FROM "{abt_table}"')}


@pytest.mark.integration
def test_abt_reads_source_and_target_from_config(db):
    source = "custom_clean_source"
    target = "custom_abt_target"

    _generate(db, clean_table=source, abt_table=target)

    assert db.table_exists(target)
    assert db.row_count(target) == len({row["sk_id_curr"] for row in APP_ROWS})


@pytest.mark.integration
def test_abt_has_one_row_per_customer(db):
    _generate(db)

    distinct_customers = {row["sk_id_curr"] for row in APP_ROWS}
    assert db.row_count(DEFAULT_ABT) == len(distinct_customers)


@pytest.mark.integration
def test_customers_without_history_get_zero_flags_and_rates(db):
    _generate(db)

    without = _abt_by_customer(db)[CUSTOMER_WITHOUT_HISTORY]
    assert without["has_prev_app"] == 0
    assert without["has_bureau"] == 0
    assert without["has_installments_history"] == 0
    assert float(without["prev_refused_rate"]) == pytest.approx(0)
    assert float(without["bureau_avg_days_credit"]) == pytest.approx(0)
    assert float(without["bureau_active_rate"]) == pytest.approx(0)
    assert float(without["inst_late_payment_rate"]) == pytest.approx(0)


@pytest.mark.integration
def test_customers_with_history_get_flags_and_aggregates(db):
    _generate(db)

    with_history = _abt_by_customer(db)[CUSTOMER_WITH_HISTORY]
    assert with_history["has_prev_app"] == 1
    assert with_history["has_bureau"] == 1
    assert with_history["has_installments_history"] == 1
    assert float(with_history["prev_refused_rate"]) == pytest.approx(EXPECTED_PREV_REFUSED_RATE)
    assert float(with_history["bureau_avg_days_credit"]) == pytest.approx(EXPECTED_BUREAU_AVG_DAYS_CREDIT)
    assert float(with_history["inst_late_payment_rate"]) == pytest.approx(EXPECTED_INST_LATE_RATE)


@pytest.mark.integration
def test_income_ratios_computed_when_income_positive(db):
    _generate(db)

    with_history = _abt_by_customer(db)[CUSTOMER_WITH_HISTORY]
    app = next(r for r in APP_ROWS if r["sk_id_curr"] == CUSTOMER_WITH_HISTORY)
    assert float(with_history["fe_credit_income_percent"]) == pytest.approx(
        app["amt_credit"] / app["amt_income_total"]
    )
    assert float(with_history["fe_annuity_income_percent"]) == pytest.approx(
        app["amt_annuity"] / app["amt_income_total"]
    )


@pytest.mark.integration
def test_income_ratios_null_when_income_zero(db):
    _generate(db)

    without = _abt_by_customer(db)[CUSTOMER_WITHOUT_HISTORY]
    assert without["fe_credit_income_percent"] is None
    assert without["fe_annuity_income_percent"] is None


@pytest.mark.integration
def test_temporary_aggregation_tables_are_dropped(db):
    _generate(db)

    for tmp_table in TMP_AGG_TABLES:
        assert not db.table_exists(tmp_table)

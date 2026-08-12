"""T4 — Application sanitization (`run_sanitization`).

`min_freq`/`winsor_q` are passed as scalars. Contracts: one output row per input
row; median imputation of external sources and their mean; income winsorized at the
configured quantile and zero/null income imputed with the median; rare categories
folded at the `min_freq` boundary; employment anomaly flagged and zeroed; car
ownership derived; age in years; missing categoricals → Unknown; identifiers
preserved. Expected values are derived from the fixture, never hardcoded blindly.
"""

import statistics

import pytest

from data_sanitization import run_sanitization


INPUT_TABLE = "application_train"
OUTPUT_TABLE = "application_clean"

APPLICATION_SCHEMA = {
    "sk_id_curr": "BIGINT",
    "target": "BIGINT",
    "ext_source_1": "DOUBLE PRECISION",
    "ext_source_2": "DOUBLE PRECISION",
    "ext_source_3": "DOUBLE PRECISION",
    "days_last_phone_change": "DOUBLE PRECISION",
    "cnt_fam_members": "DOUBLE PRECISION",
    "amt_annuity": "DOUBLE PRECISION",
    "amt_income_total": "DOUBLE PRECISION",
    "own_car_age": "DOUBLE PRECISION",
    "flag_own_car": "TEXT",
    "organization_type": "TEXT",
    "name_income_type": "TEXT",
    "region_rating_client_w_city": "BIGINT",
    "days_id_publish": "BIGINT",
    "days_registration": "BIGINT",
    "reg_city_not_work_city": "BIGINT",
    "reg_city_not_live_city": "BIGINT",
    "live_city_not_work_city": "BIGINT",
    "def_60_cnt_social_circle": "DOUBLE PRECISION",
    "amt_req_credit_bureau_year": "DOUBLE PRECISION",
    "cnt_children": "BIGINT",
    "amt_credit": "DOUBLE PRECISION",
    "occupation_type": "TEXT",
    "name_education_type": "TEXT",
    "code_gender": "TEXT",
    "days_birth": "BIGINT",
    "days_employed": "BIGINT",
}

# Benign, non-null defaults so a test only has to override the columns it exercises.
DEFAULTS = {
    "target": 0,
    "ext_source_1": 0.5,
    "ext_source_2": 0.5,
    "ext_source_3": 0.5,
    "days_last_phone_change": -500.0,
    "cnt_fam_members": 2.0,
    "amt_annuity": 25000.0,
    "amt_income_total": 150000.0,
    "own_car_age": None,
    "flag_own_car": "N",
    "organization_type": "Business Entity",
    "name_income_type": "Working",
    "region_rating_client_w_city": 2,
    "days_id_publish": -3000,
    "days_registration": -4000,
    "reg_city_not_work_city": 0,
    "reg_city_not_live_city": 0,
    "live_city_not_work_city": 0,
    "def_60_cnt_social_circle": 0.0,
    "amt_req_credit_bureau_year": 1.0,
    "cnt_children": 0,
    "amt_credit": 500000.0,
    "occupation_type": "Laborers",
    "name_education_type": "Secondary",
    "code_gender": "F",
    "days_birth": -12000,
    "days_employed": -2000,
}


def _row(sk_id_curr: int, **overrides) -> dict:
    return {"sk_id_curr": sk_id_curr, **DEFAULTS, **overrides}


def _sanitize(test_db, conexao, rows, min_freq, winsor_q):
    test_db.create_table(INPUT_TABLE, APPLICATION_SCHEMA)
    test_db.insert(INPUT_TABLE, rows)
    run_sanitization(conexao, INPUT_TABLE, OUTPUT_TABLE, min_freq, winsor_q)


def _clean_by_sk(test_db, sk_id_curr: int) -> dict:
    rows = test_db.fetch_dicts(
        f'SELECT * FROM "{OUTPUT_TABLE}" WHERE sk_id_curr = %s', (sk_id_curr,)
    )
    return rows[0]


@pytest.mark.integration
def test_output_has_one_row_per_input_row(test_db, conexao):
    rows = [_row(1), _row(2), _row(3), _row(4)]
    _sanitize(test_db, conexao, rows, min_freq=1, winsor_q=0.99)
    assert test_db.row_count(OUTPUT_TABLE) == len(rows)


@pytest.mark.integration
def test_ext_sources_null_imputed_with_median(test_db, conexao):
    rows = [
        _row(1, ext_source_1=0.2),
        _row(2, ext_source_1=0.4),
        _row(3, ext_source_1=0.6),
        _row(4, ext_source_1=None),
    ]
    _sanitize(test_db, conexao, rows, min_freq=1, winsor_q=0.99)

    expected_median = statistics.median([0.2, 0.4, 0.6])
    assert _clean_by_sk(test_db, 4)["ext_source_1"] == pytest.approx(expected_median)

    clean = test_db.fetch_dicts(f'SELECT ext_source_1 FROM "{OUTPUT_TABLE}"')
    assert all(row["ext_source_1"] is not None for row in clean)


@pytest.mark.integration
def test_ext_source_mean_reflects_imputed_sources(test_db, conexao):
    rows = [_row(1, ext_source_1=0.2, ext_source_2=0.4, ext_source_3=0.6), _row(2), _row(3)]
    _sanitize(test_db, conexao, rows, min_freq=1, winsor_q=0.99)

    assert _clean_by_sk(test_db, 1)["ext_source_mean"] == pytest.approx((0.2 + 0.4 + 0.6) / 3)


@pytest.mark.integration
def test_income_is_winsorized_at_configured_quantile(test_db, conexao):
    incomes = [100000, 120000, 140000, 160000, 5_000_000]
    rows = [_row(index + 1, amt_income_total=value) for index, value in enumerate(incomes)]
    winsor_q = 0.75

    _sanitize(test_db, conexao, rows, min_freq=1, winsor_q=winsor_q)

    position = winsor_q * (len(incomes) - 1)
    assert position == int(position)  # cap lands exactly on a data point
    cap = sorted(incomes)[int(position)]

    outlier_sk = incomes.index(5_000_000) + 1
    below_cap_sk = incomes.index(120000) + 1
    assert _clean_by_sk(test_db, outlier_sk)["amt_income_total"] == pytest.approx(cap)
    assert _clean_by_sk(test_db, below_cap_sk)["amt_income_total"] == pytest.approx(120000)


@pytest.mark.integration
def test_zero_or_null_income_imputed_with_median(test_db, conexao):
    valid_incomes = [100000, 150000, 200000]
    rows = [
        _row(1, amt_income_total=100000),
        _row(2, amt_income_total=150000),
        _row(3, amt_income_total=200000),
        _row(4, amt_income_total=0),
        _row(5, amt_income_total=None),
    ]
    _sanitize(test_db, conexao, rows, min_freq=1, winsor_q=0.99)

    expected_median = statistics.median(valid_incomes)
    assert _clean_by_sk(test_db, 4)["amt_income_total"] == pytest.approx(expected_median)
    assert _clean_by_sk(test_db, 5)["amt_income_total"] == pytest.approx(expected_median)


@pytest.mark.integration
def test_rare_categories_folded_at_min_freq_boundary(test_db, conexao):
    rows = [
        _row(1, organization_type="Frequent"),
        _row(2, organization_type="Frequent"),
        _row(3, organization_type="Rare"),
    ]
    min_freq = 2  # 'Frequent' count 2 (kept); 'Rare' count 1 (folded)

    _sanitize(test_db, conexao, rows, min_freq=min_freq, winsor_q=0.99)

    assert _clean_by_sk(test_db, 3)["organization_type"] == "Other_low_freq"
    assert _clean_by_sk(test_db, 1)["organization_type"] == "Frequent"


@pytest.mark.integration
def test_frequent_categories_are_preserved(test_db, conexao):
    rows = [_row(1, organization_type="Government"), _row(2, organization_type="Government")]
    _sanitize(test_db, conexao, rows, min_freq=2, winsor_q=0.99)

    assert _clean_by_sk(test_db, 1)["organization_type"] == "Government"


@pytest.mark.integration
def test_employment_anomaly_sets_flag_and_zeroes_years(test_db, conexao):
    rows = [_row(1, days_employed=365243), _row(2, days_employed=-3650)]
    _sanitize(test_db, conexao, rows, min_freq=1, winsor_q=0.99)

    anomalous = _clean_by_sk(test_db, 1)
    assert anomalous["days_employed_anom"] == 1
    assert float(anomalous["years_employed"]) == pytest.approx(0)

    normal = _clean_by_sk(test_db, 2)
    assert normal["days_employed_anom"] == 0
    assert float(normal["years_employed"]) == pytest.approx(3650 / 365.25)


@pytest.mark.integration
def test_car_ownership_derives_flag_and_age_imputation(test_db, conexao):
    rows = [
        _row(1, flag_own_car="Y", own_car_age=10),
        _row(2, flag_own_car="Y", own_car_age=20),
        _row(3, flag_own_car="Y", own_car_age=None),
        _row(4, flag_own_car="N", own_car_age=99),
    ]
    _sanitize(test_db, conexao, rows, min_freq=1, winsor_q=0.99)

    median_car_age = statistics.median([10, 20])  # over the 'Y' rows with a value

    imputed = _clean_by_sk(test_db, 3)
    assert imputed["has_car"] == 1
    assert imputed["own_car_age"] == pytest.approx(median_car_age)

    with_age = _clean_by_sk(test_db, 1)
    assert with_age["has_car"] == 1
    assert with_age["own_car_age"] == pytest.approx(10)

    without_car = _clean_by_sk(test_db, 4)
    assert without_car["has_car"] == 0
    assert without_car["own_car_age"] == pytest.approx(0)


@pytest.mark.integration
def test_age_is_derived_in_years(test_db, conexao):
    rows = [_row(1, days_birth=-12000)]
    _sanitize(test_db, conexao, rows, min_freq=1, winsor_q=0.99)

    assert float(_clean_by_sk(test_db, 1)["age"]) == pytest.approx(12000 / 365.25)


@pytest.mark.integration
def test_missing_categoricals_become_unknown(test_db, conexao):
    rows = [_row(1, occupation_type=None, name_education_type=None, code_gender="XNA")]
    _sanitize(test_db, conexao, rows, min_freq=1, winsor_q=0.99)

    clean = _clean_by_sk(test_db, 1)
    assert clean["occupation_type"] == "Unknown"
    assert clean["name_education_type"] == "Unknown"
    assert clean["code_gender"] == "Unknown"


@pytest.mark.integration
def test_identifier_and_target_are_preserved(test_db, conexao):
    rows = [_row(700, target=1), _row(701, target=0)]
    _sanitize(test_db, conexao, rows, min_freq=1, winsor_q=0.99)

    clean = _clean_by_sk(test_db, 700)
    assert clean["sk_id_curr"] == 700
    assert clean["target"] == 1

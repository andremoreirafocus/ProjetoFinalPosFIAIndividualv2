"""`signed_days_since_today` — conversão pura de data escolhida no formulário para o dia
com sinal que a API espera, mesma convenção do dataset bruto do Home Credit (negativo para
eventos passados). Sem Streamlit: só aritmética de data.
"""
from datetime import date, timedelta

from MLOps.app.frontend.signed_days import signed_days_since_today


def test_none_stays_none():
    assert signed_days_since_today(None) is None


def test_today_is_zero():
    assert signed_days_since_today(date.today()) == 0


def test_past_date_is_negative_by_the_number_of_days_elapsed():
    five_days_ago = date.today() - timedelta(days=5)
    assert signed_days_since_today(five_days_ago) == -5


def test_a_full_year_ago_is_about_minus_365():
    one_year_ago = date.today() - timedelta(days=365)
    assert signed_days_since_today(one_year_ago) == -365

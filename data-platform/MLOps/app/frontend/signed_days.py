"""Conversão de data escolhida no formulário para o dia com sinal que a API espera —
mesma convenção do dataset bruto do Home Credit: negativo para eventos passados.

Sem Streamlit e sem I/O: só aritmética de data, testável isoladamente.
"""
from __future__ import annotations

from datetime import date


def signed_days_since_today(picked_date: date | None) -> int | None:
    """`None` se nenhuma data foi escolhida; senão, `(picked_date - hoje).days`."""
    if picked_date is None:
        return None
    return (picked_date - date.today()).days

"""Busca exaustivamente na ABT um cliente com score dentro de uma faixa."""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv

from infra.db import get_db_connection_str_from_env, get_pg_database_connection


CLI_DIR = Path(__file__).resolve().parent
DATA_PLATFORM_DIR = CLI_DIR.parents[2]
PREDICT_SCRIPT = CLI_DIR / "predict.py"
RISK_SCORE_PATTERN = re.compile(r"Risk Score\s*:\s*([0-9]+(?:\.[0-9]+)?)")


def load_customer_ids(connection) -> list[int]:
    """Retorna todos os identificadores existentes na ABT em ordem crescente.

    `connection` e uma conexao DBAPI ja aberta. Nao e fechada aqui: quem abre, fecha.
    """
    customers = pd.read_sql_query(
        "SELECT sk_id_curr FROM application_abt ORDER BY sk_id_curr",
        connection,
    )

    return customers["sk_id_curr"].astype(int).tolist()


def run_prediction(customer_id: int) -> tuple[float, str]:
    """Executa predict.py para um cliente e extrai o score de sua saída.

    ``PYTHONPATH`` precisa ser passado explicitamente: predict.py roda como
    ``__main__`` neste subprocesso, e seus imports absolutos (``MLOps.app.api...``,
    ``Model...``, ``infra...``) só resolvem com data-platform no caminho — o mesmo
    que a execução manual pelo host declara (Model/README.md, seção de treinamento).
    """
    result = subprocess.run(
        [sys.executable, str(PREDICT_SCRIPT), "--sk-id", str(customer_id)],
        cwd=DATA_PLATFORM_DIR,
        env={**os.environ, "PYTHONPATH": str(DATA_PLATFORM_DIR)},
        capture_output=True,
        text=True,
        check=False,
    )

    output = result.stdout + result.stderr
    if result.returncode != 0:
        raise RuntimeError(
            f"A predição do cliente {customer_id} falhou com código "
            f"{result.returncode}:\n{output}"
        )

    match = RISK_SCORE_PATTERN.search(output)
    if not match:
        raise RuntimeError(
            f"Não foi possível extrair o score do cliente {customer_id}:\n{output}"
        )

    return float(match.group(1)), output


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Encontra na ABT o primeiro cliente com score na faixa informada."
    )
    parser.add_argument("--min-score", type=float, default=0.5)
    parser.add_argument("--max-score", type=float, default=0.6)
    return parser.parse_args()


def main() -> int:
    # Execucao manual, fora da rede do compose: o proprio entrypoint carrega o ambiente.
    load_dotenv(DATA_PLATFORM_DIR / ".env")

    args = parse_args()
    if not 0 <= args.min_score < args.max_score <= 1:
        raise ValueError("A faixa deve respeitar 0 <= min-score < max-score <= 1.")

    connection = get_pg_database_connection(get_db_connection_str_from_env("localhost"))
    try:
        customer_ids = load_customer_ids(connection)
    finally:
        connection.close()
    print(
        f"[BUSCA] Testando {len(customer_ids):,} clientes na faixa "
        f"{args.min_score} <= score < {args.max_score}."
    )

    for position, customer_id in enumerate(customer_ids, start=1):
        score, output = run_prediction(customer_id)
        print(
            f"[BUSCA] {position:,}/{len(customer_ids):,} — "
            f"cliente {customer_id}: score={score:.4f}"
        )
        if args.min_score <= score < args.max_score:
            print("\n[ENCONTRADO]")
            print(output, end="" if output.endswith("\n") else "\n")
            return 0

    print("[BUSCA] Nenhum cliente encontrado na faixa informada.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

"""Transporte de linha de comando para o serving — mesma cadeia da API, sem ciclo de vida.

Substitui Model/predict.py: aquele arquivo tinha carregamento, preparação e pontuação
próprios, uma segunda implementação da mesma cadeia de inferência que a API já executa.
Este orquestrador não guarda regra nenhuma — compõe os componentes do serving (etapas 1, 4)
e executa a cadeia da seção 6 do plano de bundle: carrega o bundle uma vez, resolve as
features do cliente, prepara a entrada pelo contrato do bundle, calcula score e classe. Sem
manager, sem snapshot ativo, sem polling — o manager existe porque o servidor é um processo
longo; o CLI carrega uma vez e termina.

Não imprime rótulo de decisão: vai até o score, e a política é da API (decisão registrada
no plano de bundle) — hoje um score de 0,55 seria "NEGAR_CREDITO" aqui e "manual_review" na
API.
"""
from __future__ import annotations

import argparse
from pathlib import Path

from dotenv import load_dotenv

from infra.db import get_database_engine, get_db_connection_str_from_env

# Imports absolutos, não relativos: este módulo roda tanto direto (`python
# MLOps/app/cli/predict.py`, invocado por find_customer_by_score.py e pelo host, com
# data-platform em PYTHONPATH) quanto importado como MLOps.app.cli.predict (pelos testes).
# Import relativo falha no primeiro modo — __package__ fica vazio quando o arquivo roda
# como __main__.
from Model.artifact_bundle_contract import MANIFEST_FILE_NAME

from MLOps.app.api.artifact_bundle_loader import ArtifactBundleLoader
from MLOps.app.api.feature_input_processor import FeatureInputProcessor
from MLOps.app.api.feature_service import CustomerFeatureService
from MLOps.app.api.model_bundle import ModelBundle, PredictionResult
from MLOps.app.api.prediction_service import PredictionService


CLI_DIR = Path(__file__).resolve().parent
DATA_PLATFORM_DIR = CLI_DIR.parents[2]


def predict_for_customer(
    sk_id: int,
    bundle: ModelBundle,
    feature_service: CustomerFeatureService,
) -> PredictionResult:
    """A cadeia da seção 6, sem ciclo de vida: resolve, prepara, pontua."""
    feature_input_processor = FeatureInputProcessor()
    prediction_service = PredictionService()

    features = feature_service.build(sk_id)
    prepared_input = feature_input_processor.prepare(bundle, features)
    return prediction_service.predict(bundle, prepared_input)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Inferência de risco de crédito via CLI")
    parser.add_argument(
        "--sk-id", type=int, required=True, help="ID do cliente para busca na ABT"
    )
    return parser.parse_args()


def main() -> None:
    # Execução manual, fora da rede do compose: o próprio entrypoint carrega o ambiente.
    load_dotenv(DATA_PLATFORM_DIR / ".env")
    args = parse_args()

    # Contexto de host: diretório de artefatos no próprio repositório — como train.py
    # declara "localhost" para o banco em vez do POSTGRES_HOST do compose.
    manifest_path = DATA_PLATFORM_DIR / "Model" / "artifacts" / MANIFEST_FILE_NAME

    database_engine = get_database_engine(get_db_connection_str_from_env("localhost"))
    try:
        bundle = ArtifactBundleLoader().load(manifest_path)
        feature_service = CustomerFeatureService(database_engine)
        result = predict_for_customer(args.sk_id, bundle, feature_service)
    finally:
        database_engine.dispose()

    print("\n" + "=" * 40)
    print(" RESULTADO DA ANÁLISE DE CRÉDITO ")
    print("=" * 40)
    print(f"  > Cliente ID    : {args.sk_id}")
    print(f"  > Risk Score    : {result.risk_score}")
    print(f"  > Ponto de Corte: {bundle.decision_threshold}")
    print(f"  > Classe Predita: {result.predicted_class}")
    print("=" * 40 + "\n")


if __name__ == "__main__":
    main()

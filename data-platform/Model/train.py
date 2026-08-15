"""Treina o modelo de risco de credito (LightGBM) usando ``config_model.json``.

Le a ABT ja limpa direto do Postgres (tabela ``application_abt``, saida da pipeline),
treina o LightGBM com **categoricas nativas** (sem one-hot) usando os hiperparametros
escolhidos na validacao, avalia num holdout e retreina o modelo final na base completa.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sklearn.model_selection import train_test_split
from sklearn.metrics import (average_precision_score, brier_score_loss,
                             classification_report, roc_auc_score, roc_curve)
from lightgbm import LGBMClassifier

from artifact_bundle_contract import BundleManifest
from artifact_bundle_publisher import publish_bundle
from feature_reference import build_feature_reference

from infra.db import (
    get_db_connection_str_from_env,
    get_pg_database_connection,
    get_pghook_database_connection,
)

MODEL_DIR = Path(__file__).resolve().parent
DATA_PLATFORM_DIR = MODEL_DIR.parent
DEFAULT_CONFIG_PATH = MODEL_DIR / "config_model.json"


def load_config(path: Path) -> dict[str, Any]:
    """Carrega e valida as secoes obrigatorias do config."""
    config = json.loads(path.read_text(encoding="utf-8"))
    missing = {"metadata", "variables", "parameters"}.difference(config)
    if missing:
        raise ValueError(f"Configuracao incompleta; secoes ausentes: {sorted(missing)}")
    return config


def project_path(configured_path: str) -> Path:
    """Resolve um caminho do config relativo a pasta data-platform."""
    return DATA_PLATFORM_DIR / configured_path


def load_training_data(config: dict[str, Any], conn: Any, sample_size: int | None = None):
    """Le a ABT do Postgres e devolve X, y com as categoricas como 'category'.

    `conn` e uma conexao DBAPI ja aberta, fornecida por quem conhece o contexto de
    execucao. Nao e fechada aqui: quem abre, fecha.
    """
    table = config["metadata"]["abt_table"]
    query = f'SELECT * FROM "{table}"'
    if sample_size:
        query += f" LIMIT {int(sample_size)}"

    frame = pd.read_sql_query(query, conn)

    print(f"[dados] ABT carregada: {frame.shape[0]:,} linhas x {frame.shape[1]} colunas")

    variables = config["variables"]
    features = variables["input_features"]
    target = variables["target"]
    categoricals = variables["categorical_features"]

    required = set(features) | {target}
    faltando = sorted(required.difference(frame.columns))
    if faltando:
        raise ValueError(f"A ABT nao contem as colunas configuradas: {faltando}")

    X = frame[features].replace([np.inf, -np.inf], np.nan).copy()
    y = frame[target].astype(int)
    
    for col in categoricals:
        if col in X.columns:
            X[col] = X[col].astype("category")
            
    return X, y


def build_model(config: dict[str, Any]) -> LGBMClassifier:
    """Instancia o LightGBM com os hiperparametros fixos do config."""
    hp = dict(config["parameters"]["classifier"]["hyperparameters"])
    return LGBMClassifier(
        random_state=config["parameters"]["random_state"],
        n_jobs=-1,
        verbosity=-1,
        **hp,
    )


def credit_metrics(y_true: np.ndarray, proba: np.ndarray) -> dict[str, float]:
    """Metricas de risco de credito a partir do score previsto."""
    fpr, tpr, _ = roc_curve(y_true, proba)
    auc = roc_auc_score(y_true, proba)
    return {
        "roc_auc": round(float(auc), 4),
        "gini": round(float(2 * auc - 1), 4),
        "ks": round(float((tpr - fpr).max()), 4),
        "average_precision": round(float(average_precision_score(y_true, proba)), 4),
        "brier": round(float(brier_score_loss(y_true, proba)), 4),
    }


def train(
    config: dict[str, Any], X: pd.DataFrame, y: pd.Series
) -> tuple[dict[str, Any], dict[str, float]]:
    """Avalia a configuração no holdout e retreina o modelo final com toda a população.

    Recebe os dados já carregados; não acessa o banco. Devolve o artefato do modelo e
    as métricas do modelo de avaliação como valores distintos.
    """
    params = config["parameters"]
    seed = params["random_state"]
    threshold = params["inference"]["decision_threshold"]
    # Log da proporção do Target original (bom para monitorar desbalanceamento)
    taxa_inadimplencia = y.mean() * 100
    print(f"[dados] Volumetria total da ABT: {len(y):,} registros")
    print(f"[dados] Proporção da classe positiva (Target=1): {taxa_inadimplencia:.2f}%")
    X_train, X_test, y_train, y_test = train_test_split(
        X, y,
        test_size=params["split"]["test_size"],
        stratify=y if params["split"]["stratify"] else None,
        random_state=seed,
    )  
    print(f"[split] Dados divididos com sucesso (test_size={params['split']['test_size']}):")
    print(f"        -> Treino: {X_train.shape[0]:,} linhas")
    print(f"        -> Teste (Holdout): {X_test.shape[0]:,} linhas")
    # 1) Modelo de avaliacao
    print("\n[treino] Ajustando modelo de avaliação no conjunto de Treino...")
    eval_model = build_model(config).fit(X_train, y_train)
    print("[avaliacao] Calculando predições e métricas no Holdout...")
    score = eval_model.predict_proba(X_test)[:, 1]
    eval_model_metrics = credit_metrics(y_test.to_numpy(), score)
    # Exibe as métricas de forma estruturada no log do Airflow
    print("-" * 50)
    print("[AVALIAÇÃO - MÉTRICAS DE RISCO DE CRÉDITO]")
    print(f"  - ROC AUC:           {eval_model_metrics['roc_auc']:.4f}")
    print(f"  - GINI:              {eval_model_metrics['gini']:.4f}")
    print(f"  - KS:                {eval_model_metrics['ks']:.4f}")
    print(f"  - Avg Precision:     {eval_model_metrics['average_precision']:.4f}")
    print(f"  - Brier Score Loss:  {eval_model_metrics['brier']:.4f}")
    print("-" * 50)
    # Adiciona o relatório padrão do scikit-learn para ver precision/recall por classe
    y_pred_class = (score >= threshold).astype(int)
    report = classification_report(y_test, y_pred_class, target_names=["Adimplente (0)", "Inadimplente (1)"])
    print("[avaliacao] Relatório de Classificação de Negócio:")
    print(report)
    # 2) Modelo final
    print("\n[treino] Retreinando o modelo final com 100% dos dados da ABT...")
    final_model = build_model(config).fit(X, y)
    print("[treino] Modelo final ajustado com sucesso.")
    categoricals = [c for c in config["variables"]["categorical_features"] if c in X.columns]
    trained_at_utc = datetime.now(timezone.utc).isoformat(timespec="seconds")
    model_artifact = {
        "model": final_model,
        "features": list(X.columns),
        "decision_threshold": threshold,
        "categorical_features": categoricals,
        "categories": {c: [str(v) for v in X[c].cat.categories] for c in categoricals},
        "algorithm": config["parameters"]["classifier"]["algorithm"],
        "hyperparameters": config["parameters"]["classifier"]["hyperparameters"],
        "trained_at_utc": trained_at_utc,
        "config_version": config["metadata"]["version"],
    }
    return model_artifact, eval_model_metrics


def save_artifacts(
    model_artifact: dict[str, Any],
    eval_model_metrics: dict[str, float],
    feature_reference: dict[str, Any],
    artifacts_dir: Path,
) -> BundleManifest:
    """Publica o conjunto versionado e grava as métricas do modelo de avaliação ao lado.

    Delega a publicação atômica (modelo, referência e manifesto) a ``publish_bundle``, que
    recusa um par cujo artefato e baseline não pertençam ao mesmo treinamento — nesse caso,
    nenhum arquivo é gravado, nem as métricas. ``eval_model_metrics.json`` não faz parte do
    manifesto: é informativo, sem checksum, publicado depois que o bundle já é o ativo.
    """
    manifest = publish_bundle(model_artifact, feature_reference, artifacts_dir)

    bundle_directory = artifacts_dir / "bundles" / manifest.bundle_id
    metrics_path = bundle_directory / "eval_model_metrics.json"
    resumo = {
        "algorithm": model_artifact["algorithm"],
        "hyperparameters": model_artifact["hyperparameters"],
        "test_metrics": eval_model_metrics,
        "decision_threshold": model_artifact["decision_threshold"],
        "trained_at_utc": model_artifact["trained_at_utc"],
    }
    metrics_path.write_text(json.dumps(resumo, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"[artefato] Bundle publicado: {manifest.bundle_id}")
    print(f"[artefato] Modelo salvo em: {bundle_directory / manifest.model.path.split('/')[-1]}")
    print(f"[artefato] Metricas do modelo de avaliacao salvas em: {metrics_path}")
    print(
        "[artefato] Referencias salvas em: "
        f"{bundle_directory / manifest.feature_reference.path.split('/')[-1]}"
    )
    return manifest


# Esta é a função chamada pelo Airflow através do script de orquestração
def run_training_pipeline(conn_id: str, abt_table: str):
    """Ponto de entrada oficial para a Task da DAG do Airflow."""
    print(f"[AIRFLOW TASK] Iniciando pipeline de treinamento para a tabela: {abt_table}")
    config = load_config(DEFAULT_CONFIG_PATH)
    # Garante que a tabela vinda da DAG sobrescreva a do config se necessário
    config["metadata"]["abt_table"] = abt_table
    conn = get_pghook_database_connection(conn_id)
    try:
        X, y = load_training_data(config, conn)
    finally:
        conn.close()
    print("\n" + "="*60)
    print(f"[MLOPS-TRAIN] Iniciando treinamento. Versão: {config['metadata']['version']}")
    print("="*60)
    model_artifact, eval_model_metrics = train(config, X, y)
    print("\n" + "="*60)
    print("[MLOPS-TRAIN] Treinamento concluído com sucesso.")
    print("="*60 + "\n")
    print("[referencias] Calculando baseline estatístico e TreeSHAP global...")
    feature_reference = build_feature_reference(
        model_artifact["model"],
        X,
        y,
        model_artifact["categorical_features"],
        config["metadata"]["version"],
        model_artifact["trained_at_utc"],
        config["parameters"]["reference"]["shap_sample_size"],
        config["parameters"]["random_state"],
    )
    print("[referencias] Baseline calculado com sucesso.")
    artifacts_dir = project_path(config["metadata"]["artifacts_dir"])
    print(f"Publicando bundle em: {artifacts_dir}")
    save_artifacts(model_artifact, eval_model_metrics, feature_reference, artifacts_dir)
    print("Artefatos salvos com sucesso.")
    print("[AIRFLOW TASK] Pipeline de treinamento finalizado com sucesso.")

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Treino local do modelo")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH, help="Caminho do config_model.json")
    parser.add_argument("--sample-size", type=int, default=None, help="Le apenas N linhas da ABT (smoke test rapido)")
    parser.add_argument("--artifacts-dir", type=Path, default=None, help="Sobrescreve o diretorio de artefatos")
    return parser.parse_args()


def main() -> None:
    # Execucao manual, fora da rede do compose: o proprio entrypoint carrega o ambiente.
    # Import local porque a imagem do Airflow nao tem python-dotenv e nao precisa dele:
    # a DAG importa run_training_pipeline, nunca main.
    from dotenv import load_dotenv

    load_dotenv(DATA_PLATFORM_DIR / ".env")

    args = parse_args()
    print(f"[CLI] Iniciando pipeline de treinamento com config: {args.config}")

    config = load_config(args.config)
    # O CLI roda na maquina do host, fora da rede do compose.
    conn = get_pg_database_connection(get_db_connection_str_from_env("localhost"))
    try:
        X, y = load_training_data(config, conn, sample_size=args.sample_size)
    finally:
        conn.close()
    print("\n" + "="*60)
    print(f"[CLI] Iniciando treinamento. Versão: {config['metadata']['version']}")
    print("="*60)
    model_artifact, eval_model_metrics = train(config, X, y)
    print("\n" + "="*60)
    print("[CLI] Treinamento concluído com sucesso.")
    print("="*60 + "\n")

    print("Calculando baseline estatístico e TreeSHAP global...")
    feature_reference = build_feature_reference(
        model_artifact["model"],
        X,
        y,
        model_artifact["categorical_features"],
        config["metadata"]["version"],
        model_artifact["trained_at_utc"],
        config["parameters"]["reference"]["shap_sample_size"],
        config["parameters"]["random_state"],
    )
    print("Baseline calculado com sucesso.")

    artifacts_dir = args.artifacts_dir or project_path(config["metadata"]["artifacts_dir"])
    print(f"Publicando bundle em: {artifacts_dir}")
    save_artifacts(model_artifact, eval_model_metrics, feature_reference, artifacts_dir)
    print("Artefatos salvos com sucesso.")
    print("[CLI] Pipeline de treinamento finalizado com sucesso.")

if __name__ == "__main__":
    main()

"""Treina o modelo de risco de credito (LightGBM) usando ``config_model.json``.

Le a ABT ja limpa direto do Postgres (tabela ``application_abt``, saida da pipeline),
treina o LightGBM com **categoricas nativas** (sem one-hot) usando os hiperparametros
escolhidos na validacao, avalia num holdout e retreina o modelo final na base completa.
"""

from __future__ import annotations

import argparse
import json
import pickle
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sklearn.model_selection import train_test_split
from sklearn.metrics import (average_precision_score, brier_score_loss,
                             classification_report, roc_auc_score, roc_curve)
from lightgbm import LGBMClassifier

from feature_reference import build_feature_reference

# Reaproveitando a conexão inteligente do projeto
from utils import get_database_connection

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


def load_training_data(config: dict[str, Any], conn_id: str = "postgres_data_db", sample_size: int | None = None):
    """Le a ABT do Postgres usando utils e devolve X, y com as categoricas como 'category'."""
    # Utilizando a conexão padrão do projeto para Airflow/Localbox
    conn = get_database_connection(conn_id=conn_id, silent=False)
    
    table = config["metadata"]["abt_table"]
    query = f'SELECT * FROM "{table}"'
    if sample_size:
        query += f" LIMIT {int(sample_size)}"
        
    try:
        frame = pd.read_sql_query(query, conn)
    finally:
        conn.close()

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
    config: dict[str, Any], conn_id: str = "postgres_data_db", sample_size: int | None = None
) -> tuple[dict[str, Any], dict[str, float], dict[str, Any]]:
    """Treina, avalia no holdout e retreina o modelo final na base completa.

    Devolve o artefato do modelo, as métricas do holdout e o baseline populacional
    como valores distintos.
    """
    print("\n" + "="*60)
    print(f"[MLOPS-TRAIN] INICIANDO PIPELINE DE MODELAGEM - VE REGISTRO: {config['metadata']['version']}")
    print("="*60)
    
    X, y = load_training_data(config, conn_id, sample_size)
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

    print("[referencias] Calculando baseline estatístico e TreeSHAP global...")
    feature_reference = build_feature_reference(
        final_model,
        X,
        y,
        categoricals,
        config["metadata"]["version"],
        trained_at_utc,
        params["reference"]["shap_sample_size"],
        seed,
    )
    print("[referencias] Baseline calculado com sucesso.")
    
    print("\n" + "="*60)
    print("[MLOPS-TRAIN] PIPELINE DE TREINAMENTO CONCLUÍDA COM SUCESSO")
    print("="*60 + "\n")

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
    return model_artifact, eval_model_metrics, feature_reference


def save_artifacts(
    model_artifact: dict[str, Any],
    eval_model_metrics: dict[str, float],
    feature_reference: dict[str, Any],
    output_path: Path,
) -> None:
    """Salva modelo, métricas e referências estatísticas versionadas."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("wb") as file:
        pickle.dump(model_artifact, file)

    metrics_path = output_path.parent / "eval_model_metrics.json"
    resumo = {
        "algorithm": model_artifact["algorithm"],
        "hyperparameters": model_artifact["hyperparameters"],
        "test_metrics": eval_model_metrics,
        "decision_threshold": model_artifact["decision_threshold"],
        "trained_at_utc": model_artifact["trained_at_utc"],
    }
    metrics_path.write_text(json.dumps(resumo, indent=2, ensure_ascii=False), encoding="utf-8")

    reference_path = output_path.parent / "feature_reference.json"
    reference_path.write_text(
        json.dumps(
            feature_reference, indent=2, ensure_ascii=False, allow_nan=False
        ),
        encoding="utf-8",
    )
    print(f"[artefato] Modelo salvo em: {output_path}")
    print(f"[artefato] Metricas do modelo de avaliacao salvas em: {metrics_path}")
    print(f"[artefato] Referencias salvas em: {reference_path}")


# Esta é a função chamada pelo Airflow através do script de orquestração
def run_training_pipeline(conn_id: str, abt_table: str):
    """Ponto de entrada oficial para a Task da DAG do Airflow."""
    print(f"[AIRFLOW TASK] Iniciando pipeline de treinamento para a tabela: {abt_table}")
    config = load_config(DEFAULT_CONFIG_PATH)
    
    # Garante que a tabela vinda da DAG sobrescreva a do config se necessário
    config["metadata"]["abt_table"] = abt_table
    
    model_artifact, eval_model_metrics, feature_reference = train(config, conn_id=conn_id)
    output_path = project_path(config["metadata"]["artifact"])
    save_artifacts(model_artifact, eval_model_metrics, feature_reference, output_path)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Treino local do modelo")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH, help="Caminho do config_model.json")
    parser.add_argument("--sample-size", type=int, default=None, help="Le apenas N linhas da ABT (smoke test rapido)")
    parser.add_argument("--output-path", type=Path, default=None, help="Sobrescreve o caminho do artefato")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    config = load_config(args.config)
    model_artifact, eval_model_metrics, feature_reference = train(
        config, conn_id="postgres_data_db", sample_size=args.sample_size
    )
    output_path = args.output_path or project_path(config["metadata"]["artifact"])
    save_artifacts(model_artifact, eval_model_metrics, feature_reference, output_path)


if __name__ == "__main__":
    main()

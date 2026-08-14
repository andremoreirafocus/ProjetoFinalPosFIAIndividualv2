"""
predict.py — Serviço de predição local de risco de crédito.

Lê o artefato `.pkl` gerado na pipeline, recebe os dados de um cliente
(via ID do banco ou via JSON local) e retorna o escore de risco e a decisão.
"""
import argparse
import pickle
import pandas as pd
from pathlib import Path
from dotenv import load_dotenv

from infra.db import get_db_connection_str_from_env, get_pg_database_connection

MODEL_DIR = Path(__file__).resolve().parent
DATA_PLATFORM_DIR = MODEL_DIR.parent
ARTIFACT_PATH = MODEL_DIR / "artifacts/lightgbm_abt.pkl"


def load_artifact(artifact_path: Path):
    if not artifact_path.exists():
        raise FileNotFoundError(f"Artefato não encontrado: {artifact_path}. Execute o train.py antes.")
    with open(artifact_path, "rb") as f:
        return pickle.load(f)

def load_features_from_abt(conn, sk_id: int) -> pd.DataFrame:
    """Busca os dados do cliente direto na ABT.

    `conn` e uma conexao DBAPI ja aberta, fornecida por quem conhece o contexto de
    execucao. Nao e fechada aqui: quem abre, fecha.
    """
    
    # Puxa o cliente, excluindo colunas não preditivas
    query = f'SELECT * FROM application_abt WHERE sk_id_curr = {sk_id} LIMIT 1;'
    df = pd.read_sql(query, conn)
    
    if df.empty:
        raise ValueError(f"Cliente sk_id_curr={sk_id} não encontrado na base de dados (ABT).")
        
    return df

def predict_score(df_features: pd.DataFrame, artifact: dict) -> dict:
    """Executa a inferência e retorna a decisão de negócio."""
    model = artifact["model"]
    features_esperadas = artifact["features"]
    threshold = artifact["decision_threshold"]
    
    # Filtra e alinha colunas
    df_inf = df_features[[c for c in features_esperadas if c in df_features.columns]].copy()
    
    # Garante tipagem categórica
    for col in df_inf.select_dtypes(include=['object', 'string']).columns:
        df_inf[col] = df_inf[col].astype('category')
        
    proba = model.predict_proba(df_inf)[0, 1]
    
    return {
        "risk_score": round(proba, 4),
        "decision_threshold": threshold,
        "predicted_class": int(proba >= threshold),
        "decision": "NEGAR_CREDITO" if proba >= threshold else "APROVAR_CREDITO"
    }

if __name__ == "__main__":
    # Execucao manual, fora da rede do compose: as credenciais vem do .env e o host e
    # declarado aqui, como no treinamento.
    load_dotenv(DATA_PLATFORM_DIR / ".env")

    parser = argparse.ArgumentParser(description="Inferencia de Risco de Crédito")
    parser.add_argument("--sk-id", type=int, required=True, help="ID do cliente para busca na ABT")
    args = parser.parse_args()

    print(f"[PREDICT] Carregando artefato...")
    print(ARTIFACT_PATH)
    artifact = load_artifact(ARTIFACT_PATH)
    
    print(f"[PREDICT] Buscando features para sk_id_curr = {args.sk_id}...")
    conn = get_pg_database_connection(get_db_connection_str_from_env("localhost"))
    try:
        df_client = load_features_from_abt(conn, args.sk_id)
    finally:
        conn.close()
    
    print("[PREDICT] Rodando modelo...")
    resultado = predict_score(df_client, artifact)
    
    print("\n" + "="*40)
    print(" RESULTADO DA ANÁLISE DE CRÉDITO ")
    print("="*40)
    print(f"  > Cliente ID    : {args.sk_id}")
    print(f"  > Risk Score    : {resultado['risk_score']}")
    print(f"  > Ponto de Corte: {resultado['decision_threshold']}")
    print(f"  > DECISÃO FINAL : {resultado['decision']}")
    print("="*40 + "\n")

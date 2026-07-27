"""Fixture de features para os testes de predição.

Constrói uma linha de features válida a partir do próprio contrato do artefato
(lista de features, colunas categóricas e categorias salvas no treinamento).

Não intercepta nem substitui código: apenas fornece uma entrada real e coerente
com o contrato do modelo, permitindo exercitar a inferência sem depender de CSV
ou de uma conexão com o banco.
"""
from typing import Any


def build_features_from_artifact(artifact: dict[str, Any]) -> dict[str, Any]:
    """Retorna um dicionário de features cobrindo todo o contrato do artefato.

    Numéricas recebem ``0.0``; categóricas recebem a primeira categoria válida
    salva no artefato (garantindo um valor conhecido pelo modelo).
    """
    features = artifact["features"]
    categorical = set(artifact.get("categorical_features", []))
    categories = artifact.get("categories", {})

    sample: dict[str, Any] = {}
    for column in features:
        if column in categorical:
            valid = categories.get(column) or []
            sample[column] = valid[0] if valid else "Unknown"
        else:
            sample[column] = 0.0
    return sample

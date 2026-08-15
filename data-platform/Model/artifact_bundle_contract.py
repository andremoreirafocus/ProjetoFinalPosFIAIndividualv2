"""Declaração do contrato do conjunto de artefatos publicado, sem comportamento.

É o contrato que se compartilha entre produtor (`Model`) e consumidor (loader do
serving) — não a inferência. Este módulo não lê, não escreve, não calcula checksum e
não valida: publicar é do produtor (``artifact_bundle_publisher.py``); ler, conferir e
recusar é do loader.
"""
from __future__ import annotations

from dataclasses import dataclass


MANIFEST_FILE_NAME = "current_bundle.json"
"""Nome constante do manifesto — não é configuração, não aparece no ambiente."""

MANIFEST_SCHEMA_VERSION = 1

REQUIRED_ARTIFACT_KEYS = frozenset(
    {
        "model",
        "features",
        "decision_threshold",
        "categorical_features",
        "categories",
        "config_version",
        "trained_at_utc",
    }
)
"""Chaves que a API consome, conferidas pelo loader antes de montar o bundle."""


@dataclass(frozen=True)
class ArtifactDeclaration:
    """Um artefato do manifesto: caminho relativo ao diretório do manifesto e digest."""

    path: str
    sha256: str


@dataclass(frozen=True)
class BundleManifest:
    """Estrutura de ``current_bundle.json``: identidade do treino e artefatos publicados."""

    schema_version: int
    bundle_id: str
    model_version: str
    trained_at_utc: str
    model: ArtifactDeclaration
    feature_reference: ArtifactDeclaration

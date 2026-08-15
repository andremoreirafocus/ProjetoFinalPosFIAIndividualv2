"""Ciclo de vida do conjunto de artefatos ativo — etapa 5 do plano de bundle.

Não conhece FastAPI, política de crédito, preparação de features, predição ou explicação
(seção 4.4). O manager decide se e quando trocar o bundle ativo; quem valida o conteúdo é
o loader (etapa 4).
"""
from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import Protocol

from .model_bundle import ModelBundle


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class BundleStatus:
    """Snapshot do ciclo de vida, sem revelar estado interno do manager."""

    is_active: bool
    bundle_id: str | None
    last_activated_at: str | None
    last_error: str | None


class _BundleLoader(Protocol):
    def load(self, manifest_path: Path) -> ModelBundle: ...


class ModelBundleManager:
    """Estado do bundle ativo e a troca atômica. Sem dependência de FastAPI."""

    def __init__(self, manifest_path: Path, loader: _BundleLoader) -> None:
        self._manifest_path = manifest_path
        self._loader = loader
        self._lock = RLock()
        self._active_bundle: ModelBundle | None = None
        self._active_digest: str | None = None
        self._last_activated_at: str | None = None
        self._last_error: str | None = None

    def refresh_if_changed(self) -> bool:
        try:
            raw_manifest = self._manifest_path.read_text(encoding="utf-8")
        except FileNotFoundError as error:
            self._last_error = str(error)
            return False

        digest = hashlib.sha256(raw_manifest.encode("utf-8")).hexdigest()
        with self._lock:
            if digest == self._active_digest:
                return False

            try:
                candidate_bundle_id = json.loads(raw_manifest)["bundle_id"]
            except (json.JSONDecodeError, KeyError) as error:
                self._last_error = str(error)
                return False

            if (
                self._active_bundle is not None
                and candidate_bundle_id == self._active_bundle.bundle_id
            ):
                self._last_error = (
                    "Conteúdo do manifesto mudou sob o mesmo bundle_id ativo: "
                    f"{candidate_bundle_id}"
                )
                return False

        try:
            candidate = self._loader.load(self._manifest_path)
        except Exception as error:  # noqa: BLE001
            # Fronteira de ciclo de vida (AGENTS.md): preserva o bundle ativo anterior e
            # registra contexto suficiente para a próxima tentativa, sem propagar.
            self._last_error = str(error)
            return False

        with self._lock:
            self._active_bundle = candidate
            self._active_digest = digest
            self._last_activated_at = datetime.now(timezone.utc).isoformat()
            self._last_error = None
        return True

    def require_active(self) -> ModelBundle:
        with self._lock:
            if self._active_bundle is None:
                raise RuntimeError("Nenhum bundle foi ativado ainda.")
            return self._active_bundle

    def status(self) -> BundleStatus:
        with self._lock:
            return BundleStatus(
                is_active=self._active_bundle is not None,
                bundle_id=(
                    self._active_bundle.bundle_id if self._active_bundle else None
                ),
                last_activated_at=self._last_activated_at,
                last_error=self._last_error,
            )

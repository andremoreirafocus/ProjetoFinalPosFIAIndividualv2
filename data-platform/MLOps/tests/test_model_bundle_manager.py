"""Testes de ModelBundleManager.

Sem dependência de FastAPI: o manager decide se e quando trocar o bundle ativo; quem
valida o conteúdo é o loader, aqui substituído por um FakeBundleLoader local — só este
arquivo o usa, então não vai para fakes.py (regra do segundo consumidor).
"""
import json
import threading
from pathlib import Path

import pytest

from MLOps.app.api.model_bundle import ModelBundle
from MLOps.app.api.model_bundle_manager import ModelBundleManager


class FakeBundleLoader:
    def __init__(self, results: list) -> None:
        self._results = list(results)
        self.received_manifest_paths: list[Path] = []

    def load(self, manifest_path: Path) -> ModelBundle:
        self.received_manifest_paths.append(manifest_path)
        result = self._results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


def _bundle(bundle_id: str) -> ModelBundle:
    return ModelBundle(
        bundle_id=bundle_id,
        schema_version="1",
        model_version="test-v1",
        trained_at_utc="2026-07-14T00:00:00+00:00",
        model_path=Path(f"/bundles/{bundle_id}/lightgbm_abt.pkl"),
        estimator=object(),
        feature_order=["ext_source_1", "occupation_type"],
        categorical_features=["occupation_type"],
        categories={"occupation_type": ["Laborers", "Managers"]},
        decision_threshold=0.5,
        target_rate=0.08,
        numeric_references={},
        categorical_references={},
        global_shap={"feature_importance": []},
        transformation_contract={},
    )


def _write_manifest(manifest_path: Path, bundle_id: str, marker: str = "") -> None:
    """Só ``bundle_id`` importa para o manager; ``marker`` muda o digest sem mudar o id."""
    manifest_path.write_text(
        json.dumps({"bundle_id": bundle_id, "marker": marker}), encoding="utf-8"
    )


def test_refresh_activates_first_valid_candidate(tmp_path: Path) -> None:
    manifest_path = tmp_path / "current_bundle.json"
    _write_manifest(manifest_path, "bundle-a")
    loader = FakeBundleLoader([_bundle("bundle-a")])
    manager = ModelBundleManager(manifest_path, loader)

    changed = manager.refresh_if_changed()

    assert changed is True
    assert manager.require_active().bundle_id == "bundle-a"


def test_refresh_skips_when_manifest_content_is_unchanged(tmp_path: Path) -> None:
    manifest_path = tmp_path / "current_bundle.json"
    _write_manifest(manifest_path, "bundle-a")
    loader = FakeBundleLoader([_bundle("bundle-a")])
    manager = ModelBundleManager(manifest_path, loader)
    manager.refresh_if_changed()

    changed = manager.refresh_if_changed()

    assert changed is False
    assert loader.received_manifest_paths == [manifest_path]


def test_refresh_activates_new_valid_candidate(tmp_path: Path) -> None:
    manifest_path = tmp_path / "current_bundle.json"
    _write_manifest(manifest_path, "bundle-a")
    loader = FakeBundleLoader([_bundle("bundle-a"), _bundle("bundle-b")])
    manager = ModelBundleManager(manifest_path, loader)
    manager.refresh_if_changed()

    _write_manifest(manifest_path, "bundle-b")
    changed = manager.refresh_if_changed()

    assert changed is True
    assert manager.require_active().bundle_id == "bundle-b"


def test_refresh_preserves_previous_bundle_when_candidate_is_invalid(
    tmp_path: Path,
) -> None:
    manifest_path = tmp_path / "current_bundle.json"
    _write_manifest(manifest_path, "bundle-a")
    loader = FakeBundleLoader([_bundle("bundle-a"), ValueError("candidato inválido")])
    manager = ModelBundleManager(manifest_path, loader)
    manager.refresh_if_changed()

    _write_manifest(manifest_path, "bundle-b")
    changed = manager.refresh_if_changed()

    assert changed is False
    assert manager.require_active().bundle_id == "bundle-a"


def test_refresh_retries_invalid_candidate_on_next_cycle(tmp_path: Path) -> None:
    manifest_path = tmp_path / "current_bundle.json"
    _write_manifest(manifest_path, "bundle-a")
    loader = FakeBundleLoader(
        [ValueError("candidato inválido"), ValueError("candidato inválido")]
    )
    manager = ModelBundleManager(manifest_path, loader)

    manager.refresh_if_changed()
    manager.refresh_if_changed()

    assert loader.received_manifest_paths == [manifest_path, manifest_path]


def test_refresh_rejects_content_change_under_same_bundle_id_without_calling_loader(
    tmp_path: Path,
) -> None:
    manifest_path = tmp_path / "current_bundle.json"
    _write_manifest(manifest_path, "bundle-a", marker="first")
    loader = FakeBundleLoader([_bundle("bundle-a")])
    manager = ModelBundleManager(manifest_path, loader)
    manager.refresh_if_changed()

    _write_manifest(manifest_path, "bundle-a", marker="tampered")
    changed = manager.refresh_if_changed()

    assert changed is False
    assert loader.received_manifest_paths == [manifest_path]
    assert manager.require_active().bundle_id == "bundle-a"


def test_refresh_activates_manifest_declaring_an_earlier_bundle_id_without_distinction(
    tmp_path: Path,
) -> None:
    manifest_path = tmp_path / "current_bundle.json"
    _write_manifest(manifest_path, "bundle-a")
    loader = FakeBundleLoader(
        [_bundle("bundle-a"), _bundle("bundle-b"), _bundle("bundle-a")]
    )
    manager = ModelBundleManager(manifest_path, loader)
    manager.refresh_if_changed()
    _write_manifest(manifest_path, "bundle-b")
    manager.refresh_if_changed()

    _write_manifest(manifest_path, "bundle-a")  # "rollback"
    changed = manager.refresh_if_changed()

    assert changed is True
    assert manager.require_active().bundle_id == "bundle-a"


def test_require_active_raises_before_first_successful_refresh(tmp_path: Path) -> None:
    manifest_path = tmp_path / "current_bundle.json"
    loader = FakeBundleLoader([])
    manager = ModelBundleManager(manifest_path, loader)

    with pytest.raises(RuntimeError):
        manager.require_active()


def test_concurrent_require_active_never_observes_a_torn_bundle_during_refresh(
    tmp_path: Path,
) -> None:
    manifest_path = tmp_path / "current_bundle.json"
    _write_manifest(manifest_path, "bundle-a")
    swap_count = 200
    results = [_bundle("bundle-a")]
    for i in range(swap_count):
        results.append(_bundle("bundle-b" if i % 2 == 0 else "bundle-a"))
    loader = FakeBundleLoader(results)
    manager = ModelBundleManager(manifest_path, loader)
    manager.refresh_if_changed()

    observed_invalid: list[str] = []
    stop = threading.Event()

    def read_loop() -> None:
        while not stop.is_set():
            bundle = manager.require_active()
            if bundle.bundle_id not in ("bundle-a", "bundle-b"):
                observed_invalid.append(repr(bundle))

    reader = threading.Thread(target=read_loop)
    reader.start()
    try:
        for i in range(swap_count):
            _write_manifest(manifest_path, "bundle-b" if i % 2 == 0 else "bundle-a")
            manager.refresh_if_changed()
    finally:
        stop.set()
        reader.join()

    assert observed_invalid == []

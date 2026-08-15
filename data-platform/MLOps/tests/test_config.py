from pathlib import Path

import pytest

from MLOps.app.api.config import MANIFEST_FILE_NAME, Settings


def _settings(**overrides) -> Settings:
    base = dict(
        database_url="postgresql+psycopg2://user:password@database:5432/data",
        model_artifacts_dir="/app/Model/artifacts",
        model_bundle_refresh_seconds="5",
        approve_max_score=0.50,
        manual_review_max_score=0.60,
    )
    base.update(overrides)
    return Settings(**base)


def test_valid_settings_pass() -> None:
    # Não deve levantar exceção.
    _settings().validate()


@pytest.mark.parametrize("model_artifacts_dir", [None, ""])
def test_missing_model_artifacts_dir_is_rejected(model_artifacts_dir) -> None:
    with pytest.raises(ValueError):
        _settings(model_artifacts_dir=model_artifacts_dir).validate()


@pytest.mark.parametrize("model_bundle_refresh_seconds", [None, ""])
def test_missing_model_bundle_refresh_seconds_is_rejected(
    model_bundle_refresh_seconds,
) -> None:
    with pytest.raises(ValueError):
        _settings(model_bundle_refresh_seconds=model_bundle_refresh_seconds).validate()


def test_non_numeric_refresh_seconds_is_rejected() -> None:
    with pytest.raises(ValueError):
        _settings(model_bundle_refresh_seconds="abc").validate()


@pytest.mark.parametrize("refresh_seconds", ["0", "-1"])
def test_non_positive_refresh_seconds_is_rejected(refresh_seconds: str) -> None:
    with pytest.raises(ValueError):
        _settings(model_bundle_refresh_seconds=refresh_seconds).validate()


@pytest.mark.parametrize("database_url", [None, ""])
def test_missing_database_url_is_rejected(database_url) -> None:
    with pytest.raises(ValueError):
        _settings(database_url=database_url).validate()


@pytest.mark.parametrize(
    "overrides",
    [
        {"approve_max_score": 0.70, "manual_review_max_score": 0.60},  # approve >= review
        {"approve_max_score": 0.50, "manual_review_max_score": 1.10},  # review > 1
        {"approve_max_score": -0.10, "manual_review_max_score": 0.60},  # approve < 0
    ],
)
def test_invalid_thresholds_are_rejected(overrides: dict) -> None:
    with pytest.raises(ValueError):
        _settings(**overrides).validate()


def test_manifest_path_is_composed_from_artifacts_dir_and_contract_file_name() -> None:
    settings = _settings(model_artifacts_dir="/app/Model/artifacts")

    assert settings.manifest_path == Path("/app/Model/artifacts") / MANIFEST_FILE_NAME

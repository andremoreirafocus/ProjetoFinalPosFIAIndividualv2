import pytest

from MLOps.app.api.config import Settings


def _settings(**overrides) -> Settings:
    base = dict(
        database_url="postgresql+psycopg2://user:password@database:5432/data",
        model_load_retry_seconds=5.0,
        approve_max_score=0.50,
        manual_review_max_score=0.60,
    )
    base.update(overrides)
    return Settings(**base)


def test_valid_settings_pass() -> None:
    # Não deve levantar exceção.
    _settings().validate()


@pytest.mark.parametrize("retry", [0.0, -1.0])
def test_non_positive_retry_is_rejected(retry: float) -> None:
    with pytest.raises(ValueError):
        _settings(model_load_retry_seconds=retry).validate()


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

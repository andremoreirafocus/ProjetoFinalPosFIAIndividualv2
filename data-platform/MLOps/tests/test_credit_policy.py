import pytest

from MLOps.app.api.credit_policy import CreditPolicy


@pytest.fixture
def policy() -> CreditPolicy:
    return CreditPolicy(0.35, 0.65, "test-v1")


def test_approve(policy: CreditPolicy) -> None:
    assert policy.evaluate(0.20).recommendation == "approve"


def test_manual_review(policy: CreditPolicy) -> None:
    assert policy.evaluate(0.50).recommendation == "manual_review"


def test_reject(policy: CreditPolicy) -> None:
    assert policy.evaluate(0.80).recommendation == "reject"


def test_invalid_thresholds() -> None:
    with pytest.raises(ValueError):
        CreditPolicy(0.70, 0.60, "invalid")


@pytest.mark.parametrize("score", [-0.1, 1.1])
def test_score_out_of_range_is_rejected(policy: CreditPolicy, score: float) -> None:
    with pytest.raises(ValueError):
        policy.evaluate(score)

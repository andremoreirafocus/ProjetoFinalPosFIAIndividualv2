import pytest

from MLOps.app.api.feature_service import (
    CustomerFeatureService,
    CustomerNotFoundError,
)
from MLOps.tests.fixtures import CustomerFeatureFixture, sqlite_customer_feature_fixture


@pytest.fixture
def fixture() -> CustomerFeatureFixture:
    built = sqlite_customer_feature_fixture()
    yield built
    built.engine.dispose()


@pytest.fixture
def service(fixture: CustomerFeatureFixture) -> CustomerFeatureService:
    return CustomerFeatureService(fixture.engine)


def test_build_returns_exact_abt_features(
    service: CustomerFeatureService, fixture: CustomerFeatureFixture
) -> None:
    features = service.build(fixture.selected_customer_id)

    assert features == fixture.selected_customer_features


def test_missing_customer_raises_not_found(
    service: CustomerFeatureService, fixture: CustomerFeatureFixture
) -> None:
    with pytest.raises(CustomerNotFoundError):
        service.build(fixture.absent_customer_id)

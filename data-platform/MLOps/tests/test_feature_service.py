import unittest

from MLOps.app.api.feature_service import (
    CustomerFeatureService,
    CustomerNotFoundError,
)
from MLOps.tests.fixtures import sqlite_customer_feature_fixture


class CustomerFeatureServiceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = sqlite_customer_feature_fixture()
        self.addCleanup(self.fixture.engine.dispose)
        self.service = CustomerFeatureService(self.fixture.engine)

    def test_build_returns_exact_abt_features(self) -> None:
        features = self.service.build(self.fixture.selected_customer_id)

        self.assertEqual(features, self.fixture.selected_customer_features)

    def test_missing_customer_raises_not_found(self) -> None:
        with self.assertRaises(CustomerNotFoundError):
            self.service.build(self.fixture.absent_customer_id)


if __name__ == "__main__":
    unittest.main()

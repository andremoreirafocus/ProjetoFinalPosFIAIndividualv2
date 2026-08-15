import os
from dataclasses import dataclass
from pathlib import Path

from Model.artifact_bundle_contract import MANIFEST_FILE_NAME


DATA_PLATFORM_DIR = Path(__file__).resolve().parents[3]


@dataclass(frozen=True)
class Settings:
    model_artifacts_dir: str | None = os.getenv("MODEL_ARTIFACTS_DIR")
    model_bundle_refresh_seconds: str | None = os.getenv("MODEL_BUNDLE_REFRESH_SECONDS")
    database_url: str | None = os.getenv("DATABASE_URL")
    approve_max_score: float = float(os.getenv("CREDIT_APPROVE_MAX_SCORE", "0.50"))
    manual_review_max_score: float = float(
        os.getenv("CREDIT_MANUAL_REVIEW_MAX_SCORE", "0.60")
    )
    policy_version: str = os.getenv("CREDIT_POLICY_VERSION", "demo-v1")

    def validate(self) -> None:
        if not self.database_url:
            raise ValueError("DATABASE_URL deve ser definida.")
        if not self.model_artifacts_dir:
            raise ValueError("MODEL_ARTIFACTS_DIR deve ser definida.")
        if not self.model_bundle_refresh_seconds:
            raise ValueError("MODEL_BUNDLE_REFRESH_SECONDS deve ser definida.")
        try:
            refresh_seconds = float(self.model_bundle_refresh_seconds)
        except ValueError as error:
            raise ValueError(
                "MODEL_BUNDLE_REFRESH_SECONDS deve ser numérica."
            ) from error
        if refresh_seconds <= 0:
            raise ValueError("MODEL_BUNDLE_REFRESH_SECONDS deve ser maior que zero.")
        if not 0 <= self.approve_max_score < self.manual_review_max_score <= 1:
            raise ValueError(
                "Os limiares devem respeitar: "
                "0 <= CREDIT_APPROVE_MAX_SCORE < "
                "CREDIT_MANUAL_REVIEW_MAX_SCORE <= 1."
            )

    @property
    def manifest_path(self) -> Path:
        """Composto do diretório configurado mais o nome constante do contrato (5.3)."""
        return Path(self.model_artifacts_dir) / MANIFEST_FILE_NAME


settings = Settings()

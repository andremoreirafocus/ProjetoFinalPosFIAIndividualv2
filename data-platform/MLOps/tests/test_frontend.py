from pathlib import Path

import pytest

try:
    from streamlit.testing.v1 import AppTest

    STREAMLIT_AVAILABLE = True
except ImportError:
    STREAMLIT_AVAILABLE = False


DATA_PLATFORM_DIR = Path(__file__).resolve().parents[2]


@pytest.mark.skipif(
    not STREAMLIT_AVAILABLE, reason="Requer streamlit instalado (frontend)."
)
def test_streamlit_app_starts_without_exceptions() -> None:
    app = AppTest.from_file(
        DATA_PLATFORM_DIR / "MLOps/app/frontend/app.py"
    ).run(timeout=30)
    assert list(app.exception) == []


def test_application_fields_match_new_customer_application_fields() -> None:
    """`APPLICATION_FIELDS` é a única lista de campos brutos do formulário — tem de
    coincidir exatamente com `NewCustomerApplication`, ou a aba omite/inventa um campo
    sem que nenhuma suíte perceba. Não depende de streamlit: `field_config.py` só
    importa `dataclasses`/`typing`, e `pydantic` já entra por `app/api/requirements.txt`.
    """
    from MLOps.app.api.schemas import NewCustomerApplication
    from MLOps.app.frontend.field_config import APPLICATION_FIELD_NAMES

    assert set(APPLICATION_FIELD_NAMES) == set(NewCustomerApplication.model_fields)

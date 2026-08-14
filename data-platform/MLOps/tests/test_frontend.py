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

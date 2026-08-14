import importlib.util
import json
import pickle
from pathlib import Path

import pytest


DATA_PLATFORM_DIR = Path(__file__).resolve().parents[2]
ARTIFACT_PATH = DATA_PLATFORM_DIR / "Model" / "artifacts" / "lightgbm_abt.pkl"
ARTIFACT_READY = (
    ARTIFACT_PATH.is_file() and importlib.util.find_spec("lightgbm") is not None
)


@pytest.mark.skipif(
    not ARTIFACT_READY,
    reason="Teste de integração: requer o artefato lightgbm_abt.pkl e o LightGBM instalado.",
)
def test_model_features_match_persisted_artifact() -> None:
    """Protege o contrato entre a configuração do modelo e o artefato treinado.

    Se a lista de features declarada em ``config_model.json`` divergir da lista
    persistida no artefato (por edição da configuração sem retreino, ou vice-versa),
    a API alinharia as colunas de forma incorreta na inferência. Este teste falha
    cedo diante dessa divergência.
    """
    config = json.loads(
        (DATA_PLATFORM_DIR / "Model/config_model.json").read_text(encoding="utf-8")
    )
    with (DATA_PLATFORM_DIR / "Model/artifacts/lightgbm_abt.pkl").open("rb") as file:
        artifact = pickle.load(file)

    assert config["variables"]["input_features"] == artifact["features"]

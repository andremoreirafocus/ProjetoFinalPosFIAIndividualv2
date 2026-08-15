import importlib.util
import json
import pickle
from pathlib import Path

import pytest

from Model.artifact_bundle_contract import MANIFEST_FILE_NAME


DATA_PLATFORM_DIR = Path(__file__).resolve().parents[2]
MANIFEST_PATH = DATA_PLATFORM_DIR / "Model" / "artifacts" / MANIFEST_FILE_NAME
ARTIFACT_READY = (
    MANIFEST_PATH.is_file() and importlib.util.find_spec("lightgbm") is not None
)


@pytest.mark.skipif(
    not ARTIFACT_READY,
    reason="Teste de integração: requer um bundle publicado e o LightGBM instalado.",
)
def test_model_features_match_persisted_artifact() -> None:
    """Protege o contrato entre a configuração do modelo e o artefato publicado.

    Se a lista de features declarada em ``config_model.json`` divergir da lista
    persistida no artefato do bundle ativo (por edição da configuração sem retreino,
    ou vice-versa), a API alinharia as colunas de forma incorreta na inferência. Este
    teste falha cedo diante dessa divergência.
    """
    config = json.loads(
        (DATA_PLATFORM_DIR / "Model/config_model.json").read_text(encoding="utf-8")
    )
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    artifact_path = MANIFEST_PATH.parent / manifest["model"]["path"]
    with artifact_path.open("rb") as file:
        artifact = pickle.load(file)

    assert config["variables"]["input_features"] == artifact["features"]

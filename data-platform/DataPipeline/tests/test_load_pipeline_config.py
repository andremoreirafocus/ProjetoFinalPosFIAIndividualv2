"""T5 — Pipeline config loading (`load_pipeline_config`).

Contract: the function receives an explicit path and returns the parsed JSON
content of `config_pipeline.json` — no default path, no inference "next to" the
module. A path that doesn't resolve to a file fails with `FileNotFoundError`.
"""

import json

import pytest

from config import load_pipeline_config


def test_load_pipeline_config_returns_parsed_content(tmp_path):
    config_path = tmp_path / "config_pipeline.json"
    domain_config = {"database": {"abt_table": "application_abt"}}
    config_path.write_text(json.dumps(domain_config))

    config = load_pipeline_config(str(config_path))

    assert config == domain_config


def test_load_pipeline_config_missing_file_fails_clearly(tmp_path):
    missing_path = tmp_path / "does_not_exist.json"

    with pytest.raises(FileNotFoundError):
        load_pipeline_config(str(missing_path))


def test_load_pipeline_config_requires_explicit_path():
    # No default path, and no inference of a file "next to" config.py: calling
    # without a path must fail on the missing argument itself.
    with pytest.raises(TypeError):
        load_pipeline_config()

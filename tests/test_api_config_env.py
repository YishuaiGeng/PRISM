from __future__ import annotations

import json

import pytest

from prism.core.llm_api import LLMAPI


def _write_configs(tmp_path):
    (tmp_path / "api_configs.json").write_text(
        json.dumps(
            {
                "providers": {
                    "demo": {
                        "api_key": "${PRISM_TEST_API_KEY}",
                        "base_url": "https://example.test/v1",
                        "timeout": 10,
                        "max_retries": 1,
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "model_configs.json").write_text(
        json.dumps(
            {
                "demo-model": {
                    "api_sources": [
                        {"api_name": "demo", "model_name": "demo-model"}
                    ]
                }
            }
        ),
        encoding="utf-8",
    )


def test_api_key_placeholder_resolves_from_environment(tmp_path, monkeypatch):
    _write_configs(tmp_path)
    monkeypatch.setenv("PRISM_TEST_API_KEY", "resolved-key")

    api = LLMAPI(config_dir=str(tmp_path))

    assert api.get_api_config("demo")["api_key"] == "resolved-key"


def test_missing_api_key_environment_variable_raises_clear_error(tmp_path):
    _write_configs(tmp_path)
    api = LLMAPI(config_dir=str(tmp_path))

    with pytest.raises(ValueError, match="PRISM_TEST_API_KEY"):
        api.get_api_config("demo")

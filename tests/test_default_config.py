from __future__ import annotations

import json

import yaml


def test_default_model_name_exists_in_model_configs():
    config = yaml.safe_load(open("config/default.yaml", encoding="utf-8"))
    models = json.load(open("config/api/model_configs.json", encoding="utf-8"))

    assert config["model_name"] in models

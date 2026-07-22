from __future__ import annotations

import prism.core.llm_client as llm_client_module


class _FakeAPIClient:
    def __init__(self, model_name, config_dir=None, temperature=0.0):
        self.model_name = model_name
        self.model_config = {"api_sources": []}
        self.calls = []

    def call_api(self, prompt, **kwargs):
        self.calls.append((prompt, kwargs))
        return "ok"


def test_llm_client_forwards_default_seed(monkeypatch):
    monkeypatch.setattr(llm_client_module, "APIClient", _FakeAPIClient)
    client = llm_client_module.LLMClient("demo", seed=123)

    assert client._call("prompt") == "ok"
    assert client._client.calls == [("prompt", {"seed": 123})]


def test_explicit_call_seed_overrides_default(monkeypatch):
    monkeypatch.setattr(llm_client_module, "APIClient", _FakeAPIClient)
    client = llm_client_module.LLMClient("demo", seed=123)

    client._call("prompt", seed=7)

    assert client._client.calls[0][1]["seed"] == 7

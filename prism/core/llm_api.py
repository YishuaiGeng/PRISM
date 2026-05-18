"""Configuration-based LLM API client with automatic provider failover.

Supports OpenAI-compatible, Anthropic, and Gemini providers.  Provider and
model configuration is read from ``config/api/api_configs.json`` and
``config/api/model_configs.json`` at the project root.
"""

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Any

import requests

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------- #
# Path resolution                                                               #
# --------------------------------------------------------------------------- #

def _find_config_dir() -> Path:
    """Locate the API config directory relative to the project root.

    When this module lives at ``prism/core/llm_api.py``, two ``parent`` calls
    reach the project root; the function then looks for ``config/api/`` there.
    Falls back to the module's own directory so the file remains importable
    from any location (useful in notebooks and standalone scripts).
    """
    here = Path(__file__).resolve().parent
    project_root = here.parent.parent
    canonical = project_root / "config" / "api"
    if canonical.is_dir():
        return canonical
    return here


# --------------------------------------------------------------------------- #
# LLMAPI                                                                        #
# --------------------------------------------------------------------------- #

class LLMAPI:
    """Multi-provider LLM client with configuration-driven failover."""

    def __init__(self, config_dir: str | None = None) -> None:
        self.config_dir = Path(config_dir) if config_dir else _find_config_dir()
        self.api_configs = self._load_config("api_configs.json")
        self.model_configs = self._load_config("model_configs.json")

    # ------------------------------------------------------------------
    # Config helpers
    # ------------------------------------------------------------------

    def _load_config(self, filename: str) -> dict[str, Any]:
        config_path = self.config_dir / filename
        if not config_path.exists():
            raise FileNotFoundError(f"Config not found: {config_path}")
        with open(config_path, encoding="utf-8") as fh:
            return json.load(fh)

    def get_api_config(self, api_name: str) -> dict[str, Any]:
        providers = self.api_configs.get("providers", {})
        if api_name not in providers:
            raise ValueError(f"Unknown API provider: {api_name!r}")
        return self._resolve_api_config(api_name, providers[api_name])

    @staticmethod
    def _resolve_api_config(api_name: str, api_config: dict[str, Any]) -> dict[str, Any]:
        resolved = dict(api_config)
        api_key = resolved.get("api_key")
        if isinstance(api_key, str) and api_key.startswith("${") and api_key.endswith("}"):
            env_name = api_key[2:-1]
            env_value = os.environ.get(env_name)
            if not env_value:
                raise ValueError(
                    f"API provider {api_name!r} requires environment variable {env_name!r}"
                )
            resolved["api_key"] = env_value
        return resolved

    def get_model_config(self, model_name: str) -> dict[str, Any]:
        if model_name not in self.model_configs:
            raise ValueError(f"Unknown model: {model_name!r}")
        return self.model_configs[model_name]

    def list_available_models(self) -> list[str]:
        return list(self.model_configs.keys())

    def get_api_status(self) -> dict[str, Any]:
        return {
            "total_apis": len(self.api_configs.get("providers", {})),
            "total_models": len(self.model_configs),
            "priority_order": self.api_configs.get("priority_order", []),
            "available_models": self.list_available_models(),
        }

    # ------------------------------------------------------------------
    # Internal: HTTP
    # ------------------------------------------------------------------

    def _request_with_retry(self, method: str, url: str, api_config: dict, **kwargs) -> requests.Response:
        max_retries = api_config.get("max_retries", 2)
        last_error: str | None = None

        for attempt in range(max_retries):
            try:
                response = requests.request(method, url, **kwargs)
                if response.status_code >= 500:
                    last_error = f"Server error {response.status_code}: {response.text}"
                    logger.warning("Request failed (attempt %d/%d): %s", attempt + 1, max_retries, last_error)
                    time.sleep(2 * (attempt + 1))
                    continue
                return response
            except requests.exceptions.RequestException as exc:
                last_error = str(exc)
                logger.warning("Request exception (attempt %d/%d): %s", attempt + 1, max_retries, last_error)
                time.sleep(2 * (attempt + 1))

        raise RuntimeError(f"Request failed after {max_retries} retries. Last error: {last_error}")

    # ------------------------------------------------------------------
    # Internal: normalization helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _coerce_int(value: Any) -> int:
        if value is None or isinstance(value, bool):
            return int(value or 0)
        try:
            return int(value)
        except (TypeError, ValueError):
            return 0

    @classmethod
    def _build_usage_record(
        cls,
        *,
        prompt_tokens: Any = 0,
        completion_tokens: Any = 0,
        total_tokens: Any = 0,
        reasoning_tokens: Any = 0,
        cached_prompt_tokens: Any = 0,
        cache_creation_tokens: Any = 0,
    ) -> dict[str, int]:
        prompt = cls._coerce_int(prompt_tokens)
        completion = cls._coerce_int(completion_tokens)
        total = cls._coerce_int(total_tokens) or (prompt + completion)
        return {
            "prompt_tokens": prompt,
            "completion_tokens": completion,
            "total_tokens": total,
            "reasoning_tokens": cls._coerce_int(reasoning_tokens),
            "cached_prompt_tokens": cls._coerce_int(cached_prompt_tokens),
            "cache_creation_tokens": cls._coerce_int(cache_creation_tokens),
        }

    @classmethod
    def _normalize_openai_usage(cls, usage: dict[str, Any]) -> dict[str, int]:
        pd = usage.get("prompt_tokens_details") or {}
        cd = usage.get("completion_tokens_details") or {}
        return cls._build_usage_record(
            prompt_tokens=usage.get("prompt_tokens", 0),
            completion_tokens=usage.get("completion_tokens", 0),
            total_tokens=usage.get("total_tokens", 0),
            reasoning_tokens=cd.get("reasoning_tokens", 0),
            cached_prompt_tokens=pd.get("cached_tokens", 0),
        )

    @classmethod
    def _normalize_gemini_usage(cls, usage: dict[str, Any]) -> dict[str, int]:
        return cls._build_usage_record(
            prompt_tokens=usage.get("promptTokenCount", 0),
            completion_tokens=usage.get("candidatesTokenCount", 0),
            total_tokens=usage.get("totalTokenCount", 0),
            reasoning_tokens=usage.get("thoughtsTokenCount", 0),
            cached_prompt_tokens=usage.get("cachedContentTokenCount", 0),
        )

    @classmethod
    def _normalize_anthropic_usage(cls, usage: dict[str, Any]) -> dict[str, int]:
        prompt = usage.get("input_tokens", 0)
        completion = usage.get("output_tokens", 0)
        return cls._build_usage_record(
            prompt_tokens=prompt,
            completion_tokens=completion,
            cached_prompt_tokens=usage.get("cache_read_input_tokens", 0),
            cache_creation_tokens=usage.get("cache_creation_input_tokens", 0),
        )

    # ------------------------------------------------------------------
    # Internal: text extraction
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_openai_text(content: Any) -> str:
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            return "".join(
                p if isinstance(p, str) else (p.get("text") or "") if isinstance(p, dict) else ""
                for p in content
            )
        return "" if content is None else str(content)

    @staticmethod
    def _extract_gemini_text(candidate: dict[str, Any]) -> str:
        parts = (candidate.get("content") or {}).get("parts") or []
        return "".join(p.get("text", "") for p in parts if isinstance(p, dict))

    @staticmethod
    def _extract_anthropic_text(blocks: Any) -> str:
        if not isinstance(blocks, list):
            return ""
        return "".join(
            b.get("text", "") for b in blocks
            if isinstance(b, dict) and b.get("type") == "text"
        )

    @staticmethod
    def _json_safe(value: Any) -> Any:
        if value is None or isinstance(value, (str, int, float, bool)):
            return value
        if isinstance(value, dict):
            return {str(k): LLMAPI._json_safe(v) for k, v in value.items()}
        if isinstance(value, (list, tuple)):
            return [LLMAPI._json_safe(v) for v in value]
        return str(value)

    # ------------------------------------------------------------------
    # Provider-specific call methods
    # ------------------------------------------------------------------

    def _call_openai_api(self, prompt: str, api_config: dict, model_name: str, return_usage: bool = False, **kwargs) -> Any:
        headers = {"Authorization": f"Bearer {api_config['api_key']}", "Content-Type": "application/json"}
        data: dict[str, Any] = {
            "model": model_name,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": kwargs.get("temperature", 0.0),
        }
        for key in ("max_tokens", "top_p", "frequency_penalty", "presence_penalty", "seed"):
            if key in kwargs:
                data[key] = kwargs[key]

        resp = self._request_with_retry(
            "POST", f"{api_config['base_url']}/chat/completions",
            api_config, headers=headers, json=data, timeout=api_config["timeout"],
        )
        if resp.status_code != 200:
            raise RuntimeError(f"OpenAI API {resp.status_code}: {resp.text}")

        result = resp.json()
        choice = (result.get("choices") or [{}])[0]
        content = self._extract_openai_text((choice.get("message") or {}).get("content"))
        if not return_usage:
            return content
        return {
            "content": content,
            "usage": self._normalize_openai_usage(result.get("usage") or {}),
            "raw_usage": result.get("usage") or {},
            "response_meta": {
                "finish_reason": choice.get("finish_reason"),
                "response_id": result.get("id"),
            },
        }

    def _call_gemini_api(self, prompt: str, api_config: dict, model_name: str, return_usage: bool = False, **kwargs) -> Any:
        headers = {"Content-Type": "application/json"}
        base_url = api_config["base_url"]

        if "google" in base_url.lower():
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent"
            params: dict = {"key": api_config["api_key"]}
        else:
            url = f"{base_url}/models/{model_name}:generateContent"
            params = {}
            headers["Authorization"] = f"Bearer {api_config['api_key']}"

        gen_config: dict[str, Any] = {"temperature": kwargs.get("temperature", 0.7)}
        if "max_tokens" in kwargs:
            gen_config["maxOutputTokens"] = kwargs["max_tokens"]
        data = {"contents": [{"parts": [{"text": prompt}]}], "generationConfig": gen_config}

        resp = self._request_with_retry(
            "POST", url, api_config, headers=headers, params=params, json=data, timeout=api_config["timeout"],
        )
        if resp.status_code != 200:
            raise RuntimeError(f"Gemini API {resp.status_code}: {resp.text}")

        result = resp.json()
        candidates = result.get("candidates") or [{}]
        content = self._extract_gemini_text(candidates[0]) if candidates else str(result)
        if not return_usage:
            return content
        usage_meta = result.get("usageMetadata") or {}
        return {
            "content": content,
            "usage": self._normalize_gemini_usage(usage_meta),
            "raw_usage": usage_meta,
            "response_meta": {"finish_reason": candidates[0].get("finishReason") if candidates else None},
        }

    def _call_anthropic_api(self, prompt: str, api_config: dict, model_name: str, return_usage: bool = False, **kwargs) -> Any:
        headers = {
            "Authorization": f"Bearer {api_config['api_key']}",
            "Content-Type": "application/json",
            "anthropic-version": "2023-06-01",
        }
        data: dict[str, Any] = {
            "model": model_name,
            "temperature": kwargs.get("temperature", 0.7),
            "messages": [{"role": "user", "content": prompt}],
        }
        if "max_tokens" in kwargs:
            data["max_tokens"] = kwargs["max_tokens"]

        resp = self._request_with_retry(
            "POST", f"{api_config['base_url']}/messages",
            api_config, headers=headers, json=data, timeout=api_config["timeout"],
        )
        if resp.status_code != 200:
            raise RuntimeError(f"Anthropic API {resp.status_code}: {resp.text}")

        result = resp.json()
        content = self._extract_anthropic_text(result.get("content") or [])
        if not return_usage:
            return content
        usage = result.get("usage") or {}
        return {
            "content": content,
            "usage": self._normalize_anthropic_usage(usage),
            "raw_usage": usage,
            "response_meta": {
                "stop_reason": result.get("stop_reason"),
                "response_id": result.get("id"),
            },
        }

    # ------------------------------------------------------------------
    # Dispatch
    # ------------------------------------------------------------------

    def call(self, prompt: str, api_name: str, model_name: str, return_usage: bool = False, **kwargs) -> Any:
        """Route a prompt to the specified provider and model."""
        api_config = self.get_api_config(api_name)
        name_lower = model_name.lower()
        if "gemini" in name_lower:
            return self._call_gemini_api(prompt, api_config, model_name, return_usage=return_usage, **kwargs)
        if "claude" in name_lower:
            return self._call_anthropic_api(prompt, api_config, model_name, return_usage=return_usage, **kwargs)
        return self._call_openai_api(prompt, api_config, model_name, return_usage=return_usage, **kwargs)

    def call_api(self, prompt: str, model_name: str, return_usage: bool = False, **kwargs) -> Any:
        """Call the best available provider for *model_name* with failover.

        The provider priority is read from ``model_configs.json``.  If the env var
        ``OPENZEBRA_API_PROVIDER`` is set, only that provider is tried.
        """
        model_config = self.get_model_config(model_name)
        api_sources: list[dict] = model_config.get("api_sources", [])

        preferred = os.environ.get("OPENZEBRA_API_PROVIDER", "").strip()
        if preferred:
            api_sources = [s for s in api_sources if s.get("api_name") == preferred]
            if not api_sources:
                raise ValueError(
                    f"Model {model_name} has no api_sources for provider {preferred!r}"
                )

        if not api_sources:
            raise ValueError(f"Model {model_name} has no configured API sources")

        last_error: Exception | None = None
        for idx, source in enumerate(api_sources, start=1):
            api_name = source["api_name"]
            source_model = source["model_name"]
            params = {**source.get("params", {}), **kwargs}
            try:
                logger.info("Trying %s / %s", api_name, source_model)
                result = self.call(prompt, api_name, source_model, return_usage=return_usage, **params)
                if return_usage and isinstance(result, dict):
                    result.setdefault("content", "")
                    result.setdefault("usage", self._build_usage_record())
                    result.setdefault("raw_usage", {})
                    result.setdefault("response_meta", {})
                    result["provider"] = api_name
                    result["requested_model"] = model_name
                    result["source_model"] = source_model
                    result["attempt_index"] = idx
                    result["request_params"] = self._json_safe(params)
                return result
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                logger.warning("%s call failed: %s", api_name, exc)

        raise RuntimeError(f"All providers failed for {model_name}. Last error: {last_error}")

    def batch_call(self, prompts: list[str], model_name: str, **kwargs) -> list[dict[str, Any]]:
        """Call the model for each prompt; return structured success/error dicts."""
        results: list[dict[str, Any]] = []
        for i, prompt in enumerate(prompts):
            logger.info("Batch call %d/%d", i + 1, len(prompts))
            try:
                response = self.call_api(prompt, model_name, **kwargs)
                results.append({"success": True, "index": i, "prompt": prompt, "response": response})
            except Exception as exc:  # noqa: BLE001
                results.append({"success": False, "index": i, "prompt": prompt, "error": str(exc)})
        return results

    def test_model(self, model_name: str, test_prompt: str = "Hello, how are you?") -> dict[str, Any]:
        try:
            result = self.call_api(test_prompt, model_name)
            return {"success": True, "model": model_name, "response": result}
        except Exception as exc:  # noqa: BLE001
            return {"success": False, "model": model_name, "error": str(exc)}

#!/usr/bin/env python3
"""
LLM API - Configuration-based LLM API Client
Supports model-name-based calls with automatic failover
"""

import json
import logging
import os
import time
from pathlib import Path
from typing import Any

import requests

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class LLMAPI:
    def __init__(self, config_dir: str = None):
        """
        Initialize LLM API

        Args:
            config_dir: Configuration directory, auto-detect if None
        """
        if config_dir is None:
            # Prefer repo-root config when present; otherwise use JSON next to this module (src/api/).
            here = Path(__file__).resolve().parent
            project_root = here.parent.parent
            legacy = project_root / "config" / "api"
            if (legacy / "api_configs.json").exists():
                self.config_dir = legacy
            else:
                self.config_dir = here
        else:
            self.config_dir = Path(config_dir)

        self.api_configs = self._load_config("api_configs.json")
        self.model_configs = self._load_config("model_configs.json")

    def _load_config(self, filename: str) -> dict[str, Any]:
        """Load configuration file"""
        config_path = self.config_dir / filename
        if not config_path.exists():
            raise FileNotFoundError(f"Configuration file not found: {config_path}")

        with open(config_path, encoding="utf-8") as f:
            return json.load(f)

    def get_apis_by_priority(self) -> list[str]:
        """Get API list sorted by priority"""
        return self.api_configs.get("priority_order", [])

    def get_api_config(self, api_name: str) -> dict[str, Any]:
        """Get API configuration"""
        providers = self.api_configs.get("providers", {})
        if api_name not in providers:
            raise ValueError(f"API configuration not found: {api_name}")
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
        """Get model configuration"""
        if model_name not in self.model_configs:
            raise ValueError(f"Model configuration not found: {model_name}")
        return self.model_configs[model_name]

    def call(
        self, prompt: str, api_name: str, model_name: str, return_usage: bool = False, **kwargs
    ):
        """
        Call API with support for different provider formats

        Args:
            prompt: Input prompt
            api_name: API provider name
            model_name: Model name
            return_usage: If True, return dict with content and usage info
            **kwargs: Additional parameters

        Returns:
            API response content (str) or dict with content and usage if return_usage=True
        """
        api_config = self.get_api_config(api_name)

        # Check if API provider supports this model
        if not self._is_model_supported(api_name, model_name):
            raise Exception(f"API provider {api_name} does not support model {model_name}")

        # Determine call method based on API name and model name
        if "gemini" in model_name.lower():
            return self._call_gemini_api(
                prompt, api_config, model_name, return_usage=return_usage, **kwargs
            )
        elif "claude" in model_name.lower():
            return self._call_anthropic_api(
                prompt, api_config, model_name, return_usage=return_usage, **kwargs
            )
        else:
            return self._call_openai_api(
                prompt, api_config, model_name, return_usage=return_usage, **kwargs
            )

    def _is_model_supported(self, api_name: str, model_name: str) -> bool:
        """
        Check if API provider supports the model.

        当前版本不再根据前缀做强限制，而是信任 `model_configs.json` 里的配置：
        - 只要 provider 在 `api_configs.json` 的 providers 里存在，就认为“支持”；
        - 具体是否真的可用，交由下游 HTTP 调用和返回结果来决定。

        这样可以避免因为前缀维护不全而误判“模型不支持”，让错误更直接反映真实的
        API 可用性问题（如模型名写错、账户无权限等）。
        """
        try:
            _ = self.get_api_config(api_name)
        except Exception:
            return False
        return True

    def _request_with_retry(self, method: str, url: str, api_config: dict, **kwargs):
        """Execute request with retry logic"""
        max_retries = api_config.get("max_retries", 2)
        last_error = None

        for attempt in range(max_retries):
            try:
                response = requests.request(method, url, **kwargs)
                # Check for 5xx errors which might be temporary
                if response.status_code >= 500:
                    last_error = f"Server error {response.status_code}: {response.text}"
                    logger.warning(
                        f"Request failed (attempt {attempt + 1}/{max_retries}): {last_error}"
                    )
                    time.sleep(2 * (attempt + 1))  # Simple backoff
                    continue
                return response
            except requests.exceptions.RequestException as e:
                last_error = str(e)
                logger.warning(
                    f"Request exception (attempt {attempt + 1}/{max_retries}): {last_error}"
                )
                time.sleep(2 * (attempt + 1))

        raise Exception(f"Request failed after {max_retries} retries. Last error: {last_error}")

    @staticmethod
    def _coerce_int(value: Any) -> int:
        """Best-effort coercion of provider usage values to int."""
        if value is None:
            return 0
        if isinstance(value, bool):
            return int(value)
        if isinstance(value, int):
            return value
        if isinstance(value, float):
            return int(value)
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
        """Normalize token accounting into a stable cross-provider schema."""
        prompt = cls._coerce_int(prompt_tokens)
        completion = cls._coerce_int(completion_tokens)
        total = cls._coerce_int(total_tokens)
        if total <= 0:
            total = prompt + completion
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
        prompt_details = usage.get("prompt_tokens_details", {}) or {}
        completion_details = usage.get("completion_tokens_details", {}) or {}
        return cls._build_usage_record(
            prompt_tokens=usage.get("prompt_tokens", 0),
            completion_tokens=usage.get("completion_tokens", 0),
            total_tokens=usage.get("total_tokens", 0),
            reasoning_tokens=completion_details.get("reasoning_tokens", 0),
            cached_prompt_tokens=prompt_details.get("cached_tokens", 0),
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
            total_tokens=cls._coerce_int(prompt) + cls._coerce_int(completion),
            cached_prompt_tokens=usage.get("cache_read_input_tokens", 0),
            cache_creation_tokens=usage.get("cache_creation_input_tokens", 0),
        )

    @classmethod
    def _json_safe_value(cls, value: Any) -> Any:
        if value is None or isinstance(value, (str, int, float, bool)):
            return value
        if isinstance(value, dict):
            return {str(k): cls._json_safe_value(v) for k, v in value.items()}
        if isinstance(value, (list, tuple)):
            return [cls._json_safe_value(v) for v in value]
        return str(value)

    @classmethod
    def _json_safe_params(cls, params: dict[str, Any]) -> dict[str, Any]:
        return {str(key): cls._json_safe_value(value) for key, value in params.items()}

    @staticmethod
    def _extract_openai_text(message_content: Any) -> str:
        if isinstance(message_content, str):
            return message_content
        if isinstance(message_content, list):
            chunks: list[str] = []
            for part in message_content:
                if isinstance(part, str):
                    chunks.append(part)
                elif isinstance(part, dict):
                    text = part.get("text")
                    if isinstance(text, str):
                        chunks.append(text)
            return "".join(chunks)
        if message_content is None:
            return ""
        return str(message_content)

    @staticmethod
    def _extract_gemini_text(candidate: dict[str, Any]) -> str:
        content = candidate.get("content", {}) or {}
        parts = content.get("parts", []) or []
        chunks: list[str] = []
        for part in parts:
            if isinstance(part, dict):
                text = part.get("text")
                if isinstance(text, str):
                    chunks.append(text)
        return "".join(chunks)

    @staticmethod
    def _extract_anthropic_text(content_blocks: Any) -> str:
        if isinstance(content_blocks, list):
            chunks: list[str] = []
            for block in content_blocks:
                if isinstance(block, dict) and block.get("type") == "text":
                    text = block.get("text")
                    if isinstance(text, str):
                        chunks.append(text)
            return "".join(chunks)
        return ""

    def _call_openai_api(
        self, prompt: str, api_config: dict, model_name: str, return_usage: bool = False, **kwargs
    ):
        """Call OpenAI-compatible API"""
        headers = {
            "Authorization": f"Bearer {api_config['api_key']}",
            "Content-Type": "application/json",
        }

        # 不主动限制 max_tokens，让后端使用其默认最大输出长度；
        # 如需限制，可在调用 call_api 时显式传入 max_tokens 覆盖。
        data = {
            "model": model_name,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": kwargs.get("temperature", 0.0),
        }
        if "max_tokens" in kwargs:
            data["max_tokens"] = kwargs["max_tokens"]

        # Add other optional parameters
        if "top_p" in kwargs:
            data["top_p"] = kwargs["top_p"]
        if "frequency_penalty" in kwargs:
            data["frequency_penalty"] = kwargs["frequency_penalty"]
        if "presence_penalty" in kwargs:
            data["presence_penalty"] = kwargs["presence_penalty"]

        response = self._request_with_retry(
            "POST",
            f"{api_config['base_url']}/chat/completions",
            api_config,
            headers=headers,
            json=data,
            timeout=api_config["timeout"],
        )

        if response.status_code == 200:
            result = response.json()
            choice = (result.get("choices") or [{}])[0]
            message = choice.get("message", {}) or {}
            content = self._extract_openai_text(message.get("content"))
            if return_usage:
                raw_usage = result.get("usage", {}) or {}
                return {
                    "content": content,
                    "usage": self._normalize_openai_usage(raw_usage),
                    "raw_usage": raw_usage,
                    "response_meta": {
                        "finish_reason": choice.get("finish_reason"),
                        "response_id": result.get("id"),
                        "created": result.get("created"),
                        "system_fingerprint": result.get("system_fingerprint"),
                    },
                }
            return content
        else:
            raise Exception(f"OpenAI API call failed: {response.status_code} - {response.text}")

    def _call_gemini_api(
        self, prompt: str, api_config: dict, model_name: str, return_usage: bool = False, **kwargs
    ):
        """Call Google Gemini API"""
        headers = {"Content-Type": "application/json"}

        # Gemini API uses different URL format
        if "google" in api_config.get("base_url", "").lower():
            # If using Google official API
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent"
            params = {"key": api_config["api_key"]}
        else:
            # If using third-party proxy API
            # 假设第三方代理的base_url已经包含了大部分路径，或者需要更灵活的拼接
            # 这里的base_url例如 "https://yunwu.ai/v1"
            # 我们需要构造出例如 "https://yunwu.ai/v1/models/gemini-2.5-pro:generateContent"
            # 或者 "https://api2.aigcbest.top/v1/models/gemini-2.5-pro-exp-03-25:generateContent"
            # 所以直接拼接 /models/{model_name}:generateContent 是正确的，但是原始的错误是因为base_url包含了v1
            # 假设base_url是 "https://api.example.com/v1", 那么url应该是 "https://api.example.com/v1/models/{model_name}:generateContent"
            # 根据报错 "Invalid URL (POST /v1/v1beta/models/gemini-2.5-pro:generateContent)"
            # 看起来是base_url里已经有/v1, 然后又多了一个/v1beta
            # 修改为：如果base_url以/v1结尾，则直接拼接models部分
            base_url = api_config["base_url"]
            if base_url.endswith("/v1"):
                url = f"{base_url}/models/{model_name}:generateContent"
            else:
                url = f"{base_url}/v1beta/models/{model_name}:generateContent"  # Fallback for other proxy formats
            params = {}
            headers["Authorization"] = f"Bearer {api_config['api_key']}"

        # 不主动限制 maxOutputTokens，让后端使用其默认最大输出长度；
        # 如需限制，可在调用 call_api 时显式传入 max_tokens 覆盖。
        data = {"contents": [{"parts": [{"text": prompt}]}]}
        generation_config = {"temperature": kwargs.get("temperature", 0.7)}
        if "max_tokens" in kwargs:
            generation_config["maxOutputTokens"] = kwargs["max_tokens"]
        data["generationConfig"] = generation_config

        # Add other optional parameters
        if "top_p" in kwargs:
            data["generationConfig"]["topP"] = kwargs["top_p"]
        if "top_k" in kwargs:
            data["generationConfig"]["topK"] = kwargs["top_k"]

        response = self._request_with_retry(
            "POST",
            url,
            api_config,
            headers=headers,
            params=params,
            json=data,
            timeout=api_config["timeout"],
        )

        if response.status_code == 200:
            result = response.json()
            # Gemini API response format
            content = None
            if "candidates" in result and len(result["candidates"]) > 0:
                candidate = result["candidates"][0]
                content = self._extract_gemini_text(candidate)

            if content is None:
                # If expected response format not found, return raw response for debugging
                logger.warning(f"Gemini API response format abnormal: {result}")
                content = str(result)

            if return_usage:
                # Gemini API usage info is in usageMetadata
                usage_metadata = result.get("usageMetadata", {}) or {}
                candidate = (result.get("candidates") or [{}])[0]
                return {
                    "content": content,
                    "usage": self._normalize_gemini_usage(usage_metadata),
                    "raw_usage": usage_metadata,
                    "response_meta": {
                        "finish_reason": candidate.get("finishReason"),
                        "model_version": result.get("modelVersion"),
                    },
                }
            return content
        else:
            raise Exception(f"Gemini API call failed: {response.status_code} - {response.text}")

    def _call_anthropic_api(
        self, prompt: str, api_config: dict, model_name: str, return_usage: bool = False, **kwargs
    ):
        """Call Anthropic Claude API"""
        headers = {
            "Authorization": f"Bearer {api_config['api_key']}",
            "Content-Type": "application/json",
            "anthropic-version": "2023-06-01",
        }

        # 不主动限制 max_tokens，让后端使用其默认最大输出长度；
        # 如需限制，可在调用 call_api 时显式传入 max_tokens 覆盖。
        data = {
            "model": model_name,
            "temperature": kwargs.get("temperature", 0.7),
            "messages": [{"role": "user", "content": prompt}],
        }
        if "max_tokens" in kwargs:
            data["max_tokens"] = kwargs["max_tokens"]

        response = self._request_with_retry(
            "POST",
            f"{api_config['base_url']}/messages",
            api_config,
            headers=headers,
            json=data,
            timeout=api_config["timeout"],
        )

        if response.status_code == 200:
            result = response.json()
            content_blocks = result.get("content", []) or []
            if content_blocks:
                content = self._extract_anthropic_text(content_blocks)
                if return_usage:
                    # Anthropic API usage info is in usage field
                    usage = result.get("usage", {}) or {}
                    return {
                        "content": content,
                        "usage": self._normalize_anthropic_usage(usage),
                        "raw_usage": usage,
                        "response_meta": {
                            "stop_reason": result.get("stop_reason"),
                            "stop_sequence": result.get("stop_sequence"),
                            "response_id": result.get("id"),
                        },
                    }
                return content
            else:
                raise Exception(f"Anthropic API response format abnormal: {result}")
        else:
            raise Exception(f"Anthropic API call failed: {response.status_code} - {response.text}")

    def call_api(self, prompt: str, model_name: str, return_usage: bool = False, **kwargs):
        """
        Call API with failover support

        Args:
            prompt: Input prompt
            model_name: Model name
            return_usage: If True, return dict with content and usage info
            **kwargs: Additional parameters

        Returns:
            API response content (str) or a structured dict when
            ``return_usage=True``.  The structured result includes
            normalized token usage, raw provider usage, resolved provider,
            resolved source model, attempt index, and response metadata.
        """
        model_config = self.get_model_config(model_name)
        api_sources = model_config.get("api_sources", [])
        preferred = os.environ.get("OPENZEBRA_API_PROVIDER", "").strip()
        if preferred:
            api_sources = [s for s in api_sources if s.get("api_name") == preferred]
            if not api_sources:
                raise ValueError(
                    f"Model {model_name} has no api_sources for provider {preferred!r} "
                    f"(set via OPENZEBRA_API_PROVIDER)"
                )

        if not api_sources:
            raise ValueError(f"Model {model_name} has no configured API sources")

        last_error = None

        for attempt_index, api_source in enumerate(api_sources, start=1):
            api_name = api_source["api_name"]
            source_model_name = api_source["model_name"]
            params = api_source.get("params", {})

            try:
                logger.info(f"Trying to use {api_name} to call {source_model_name}")

                # Merge parameters: config file params + runtime params
                all_params = {**params, **kwargs}

                # Call API
                result = self.call(
                    prompt, api_name, source_model_name, return_usage=return_usage, **all_params
                )

                if return_usage and isinstance(result, dict):
                    structured = dict(result)
                    structured.setdefault("content", "")
                    structured.setdefault(
                        "usage",
                        self._build_usage_record(),
                    )
                    structured.setdefault("raw_usage", {})
                    structured.setdefault("response_meta", {})
                    structured["provider"] = api_name
                    structured["requested_model"] = model_name
                    structured["source_model"] = source_model_name
                    structured["attempt_index"] = attempt_index
                    structured["request_params"] = self._json_safe_params(all_params)
                    return structured

                logger.info(f"Successfully got response using {api_name}")
                return result

            except Exception as e:
                last_error = e
                logger.warning(f"{api_name} call failed: {e}")
                continue

        # All APIs failed
        raise Exception(f"All API sources failed, last error: {last_error}")

    def list_available_models(self) -> list[str]:
        """List all available models"""
        return list(self.model_configs.keys())

    def get_model_info(self, model_name: str) -> dict[str, Any]:
        """Get model information"""
        if model_name not in self.model_configs:
            raise ValueError(f"Model does not exist: {model_name}")

        model_config = self.model_configs[model_name]
        api_sources = model_config.get("api_sources", [])

        return {
            "model_name": model_name,
            "api_sources": [
                {
                    "api_name": source["api_name"],
                    "model_name": source["model_name"],
                    "api_config": self.get_api_config(source["api_name"]),
                }
                for source in api_sources
            ],
        }

    def test_model(
        self, model_name: str, test_prompt: str = "Hello, how are you?"
    ) -> dict[str, Any]:
        """Test model"""
        try:
            result = self.call_api(test_prompt, model_name)
            return {"success": True, "model": model_name, "response": result, "prompt": test_prompt}
        except Exception as e:
            return {"success": False, "model": model_name, "error": str(e), "prompt": test_prompt}

    def batch_call(self, prompts: list[str], model_name: str, **kwargs) -> list[dict[str, Any]]:
        """
        Batch API calls

        Args:
            prompts: List of prompts
            model_name: Model name
            **kwargs: Additional parameters

        Returns:
            List of results, each containing success, response, error info
        """
        results = []
        for i, prompt in enumerate(prompts):
            logger.info(f"Processing prompt {i + 1}/{len(prompts)}")
            try:
                response = self.call_api(prompt, model_name, **kwargs)
                results.append(
                    {"success": True, "index": i, "prompt": prompt, "response": response}
                )
            except Exception as e:
                results.append({"success": False, "index": i, "prompt": prompt, "error": str(e)})
        return results

    def get_api_status(self) -> dict[str, Any]:
        """Get API status information"""
        status = {
            "total_apis": len(self.api_configs.get("providers", {})),
            "total_models": len(self.model_configs),
            "priority_order": self.get_apis_by_priority(),
            "available_models": self.list_available_models(),
        }
        return status


def main():
    """Main function - test and demo"""
    api = LLMAPI()

    print("=== LLM API Test ===")
    print(f"Available models: {api.list_available_models()}")

    # Show API status
    status = api.get_api_status()
    print("\nAPI Status:")
    print(f"- Total APIs: {status['total_apis']}")
    print(f"- Total models: {status['total_models']}")
    print(f"- Priority order: {status['priority_order']}")

    # Test first model
    models = api.list_available_models()
    if models:
        test_model = models[0]
        print(f"\nTesting model: {test_model}")

        try:
            result = api.call_api("Please introduce yourself briefly", test_model)
            print(f"Response: {result}")
        except Exception as e:
            print(f"Call failed: {e}")


if __name__ == "__main__":
    main()

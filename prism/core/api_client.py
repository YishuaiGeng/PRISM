"""Simplified single-model wrapper around LLMAPI for PRISM pipeline use."""

from __future__ import annotations

from typing import Any

from prism.core.llm_api import LLMAPI


class APIClient:
    """LLM client bound to a single model with optional default temperature.

    Args:
        model_name: Model key from ``config/api/model_configs.json``.
            Defaults to the first listed model if *None*.
        config_dir: Path to the API config directory.  *None* uses the
            auto-detected project ``config/api/`` directory.
        temperature: Default sampling temperature.
    """

    def __init__(
        self,
        model_name: str | None = None,
        config_dir: str | None = None,
        temperature: float = 0.0,
    ) -> None:
        self._llm = LLMAPI(config_dir=config_dir)
        available = self._llm.list_available_models()
        if model_name is None:
            if not available:
                raise ValueError("No models configured. Check config/api/model_configs.json.")
            self.model_name = available[0]
        else:
            if model_name not in available:
                raise ValueError(
                    f"Model {model_name!r} not in model_configs.json. Available: {available}"
                )
            self.model_name = model_name
        self.temperature = temperature

    # ------------------------------------------------------------------
    # Core API
    # ------------------------------------------------------------------

    def call_api(self, prompt: str, **kwargs) -> str:
        """Send *prompt* to the bound model and return the response text.

        Args:
            prompt: The user prompt.
            **kwargs: Overrides forwarded to LLMAPI (e.g. ``temperature``, ``max_tokens``).

        Returns:
            Response text string.
        """
        params: dict[str, Any] = {"temperature": self.temperature}
        params.update(kwargs)
        return self._llm.call_api(prompt, self.model_name, **params)

    def call_api_with_usage(self, prompt: str, **kwargs) -> dict[str, Any]:
        """Like :meth:`call_api` but also returns normalized token usage metadata."""
        params: dict[str, Any] = {"temperature": self.temperature}
        params.update(kwargs)
        return self._llm.call_api(prompt, self.model_name, return_usage=True, **params)

    def batch_call(self, prompts: list[str], **kwargs) -> list[dict[str, Any]]:
        """Call the model for each prompt in *prompts*."""
        params: dict[str, Any] = {"temperature": self.temperature}
        params.update(kwargs)
        return self._llm.batch_call(prompts, self.model_name, **params)

    # ------------------------------------------------------------------
    # Informational
    # ------------------------------------------------------------------

    @property
    def available_models(self) -> list[str]:
        return self._llm.list_available_models()

    @property
    def model_config(self) -> dict[str, Any]:
        """Return a copy of the configured provider/model candidates."""
        return dict(self._llm.get_model_config(self.model_name))

    def test(self, prompt: str = "What is 2+2?") -> dict[str, Any]:
        return self._llm.test_model(self.model_name, prompt)

    def __repr__(self) -> str:  # pragma: no cover
        return f"APIClient(model_name={self.model_name!r}, temperature={self.temperature})"

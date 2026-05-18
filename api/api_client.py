"""
APIClient – thin convenience wrapper around :class:`~api.llm_api.LLMAPI`.

This class provides a simplified single-model interface that is suitable
for use in evaluation harnesses, scripts, and notebooks that do not need
the full multi-provider failover machinery of :class:`LLMAPI`.
"""

from __future__ import annotations

from typing import Any

from .llm_api import LLMAPI


class APIClient:
    """Simplified LLM client bound to a single model.

    Parameters
    ----------
    model_name:
        The model to use for all calls (must be present in
        ``config/api/model_configs.json``).  Defaults to the first
        available model if *None*.
    config_dir:
        Path to the API configuration directory.  If *None*, the default
        ``<project_root>/config/api`` directory is used.
    temperature:
        Default sampling temperature passed to every call.
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
                    f"Model '{model_name}' not found in model_configs.json. Available: {available}"
                )
            self.model_name = model_name
        self.temperature = temperature

    # ------------------------------------------------------------------
    # Core API
    # ------------------------------------------------------------------

    def call_api(self, prompt: str, **kwargs) -> str:
        """Send *prompt* to the bound model and return the response text.

        Parameters
        ----------
        prompt:
            The user prompt to send.
        **kwargs:
            Overrides passed through to :meth:`LLMAPI.call_api`
            (e.g. ``temperature``, ``max_tokens``).

        Returns
        -------
        str
            The model's response text.
        """
        params: dict[str, Any] = {"temperature": self.temperature}
        params.update(kwargs)
        return self._llm.call_api(prompt, self.model_name, **params)

    def call_api_with_usage(self, prompt: str, **kwargs) -> dict[str, Any]:
        """Like :meth:`call_api` but also returns token usage metadata.

        Returns
        -------
        dict
            Structured response with at least:
            ``content``, ``provider``, ``requested_model``,
            ``source_model``, ``attempt_index``, normalized ``usage``,
            provider-native ``raw_usage``, and ``response_meta``.
        """
        params: dict[str, Any] = {"temperature": self.temperature}
        params.update(kwargs)
        return self._llm.call_api(prompt, self.model_name, return_usage=True, **params)

    def batch_call(self, prompts: list[str], **kwargs) -> list[dict[str, Any]]:
        """Call the model for each prompt in *prompts*.

        Returns
        -------
        list of dict
            Each dict has keys ``success`` (bool), ``index`` (int),
            ``prompt`` (str), and either ``response`` (str) or
            ``error`` (str).
        """
        params: dict[str, Any] = {"temperature": self.temperature}
        params.update(kwargs)
        return self._llm.batch_call(prompts, self.model_name, **params)

    # ------------------------------------------------------------------
    # Informational helpers
    # ------------------------------------------------------------------

    @property
    def available_models(self) -> list[str]:
        """Return all models available in the current configuration."""
        return self._llm.list_available_models()

    def test(self, prompt: str = "What is 2+2? Answer with only the number.") -> dict[str, Any]:
        """Quick connectivity test.  Returns a dict with ``success`` and ``response``."""
        return self._llm.test_model(self.model_name, prompt)

    def __repr__(self) -> str:  # pragma: no cover
        return f"APIClient(model_name={self.model_name!r}, temperature={self.temperature})"

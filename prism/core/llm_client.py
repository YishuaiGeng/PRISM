"""PRISM-specific LLM client facade.

Wraps ``APIClient`` and exposes task-oriented methods (translate, repair,
abstract_paradigm, etc.) with built-in call counting and structured prompt
construction.  All user-visible strings are in Chinese; docstrings are English.
"""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING, Any, List, Optional

from prism.core.api_client import APIClient

if TYPE_CHECKING:
    from prism.core.types import KDP, SolverState

_MAX_TOKENS_TRANSLATION: int = 2048
_MAX_TOKENS_REPAIR: int = 1024
_MAX_TOKENS_ABSTRACTION: int = 2048
_MAX_TOKENS_JUDGE: int = 64

_TEMPERATURE_EVAL: float = 0.0
_TEMPERATURE_COLLECT: float = 0.7


class LLMClient:
    """PRISM task-level LLM interface with call counting.

    Typical lifecycle::

        client = LLMClient("GPT-4o")
        z3_code = client.translate(puzzle_nl)
        repair  = client.repair(constraints, unsat_core, history)
        client.reset_call_count()

    Args:
        model_name: Model key from ``config/api/model_configs.json``.
        temperature: Sampling temperature (0.0 for eval, 0.7 for collection).
        config_dir: Override for API config directory (mainly for tests).
    """

    def __init__(
        self,
        model_name: str,
        temperature: float = _TEMPERATURE_EVAL,
        config_dir: Optional[str] = None,
    ) -> None:
        self._client = APIClient(
            model_name=model_name,
            config_dir=config_dir,
            temperature=temperature,
        )
        self._call_count: int = 0

    # ------------------------------------------------------------------
    # Call accounting
    # ------------------------------------------------------------------

    @property
    def call_count(self) -> int:
        """Total LLM API calls made since last reset."""
        return self._call_count

    def reset_call_count(self) -> None:
        """Reset the call counter (e.g. between puzzle instances)."""
        self._call_count = 0

    def _call(self, prompt: str, **kwargs: Any) -> str:
        """Internal dispatch: increments counter and calls the underlying client."""
        self._call_count += 1
        return self._client.call_api(prompt, **kwargs)

    # ------------------------------------------------------------------
    # Translation
    # ------------------------------------------------------------------

    def translate(self, puzzle_nl: str) -> str:
        """Request initial NL→Z3 translation for a puzzle.

        Args:
            puzzle_nl: Full natural-language puzzle description.

        Returns:
            Raw LLM response containing a Python code block with Z3 constraints.
        """
        prompt = _build_translation_prompt(puzzle_nl)
        return self._call(prompt, max_tokens=_MAX_TOKENS_TRANSLATION)

    def retranslate(
        self,
        puzzle_nl: str,
        failed_constraints: List[str],
        error_ctx: str,
    ) -> str:
        """Request a full re-translation after L4 strategy escalation.

        Args:
            puzzle_nl: Original natural-language puzzle description.
            failed_constraints: The constraint set that led to irrecoverable UNSAT.
            error_ctx: Error message or UNSAT core description for context.

        Returns:
            Raw LLM response with fresh Z3 constraints.
        """
        prompt = _build_retranslation_prompt(puzzle_nl, failed_constraints, error_ctx)
        return self._call(prompt, max_tokens=_MAX_TOKENS_TRANSLATION)

    # ------------------------------------------------------------------
    # Repair
    # ------------------------------------------------------------------

    def repair(
        self,
        constraints: List[str],
        unsat_core: List[str],
        history_summary: str,
        paradigm_hint: str = "",
        switch_prompt: str = "",
    ) -> str:
        """Request a targeted constraint repair.

        Args:
            constraints: All current constraints in Z3 Python syntax.
            unsat_core: Constraints identified by Z3 as the UNSAT subset.
            history_summary: Chinese-language summary of previous repair attempts.
            paradigm_hint: Optional paradigm suggestion injected as context.
            switch_prompt: Optional strategy-switch instruction from StrategySwitcher.

        Returns:
            Raw LLM response containing a corrected constraint expression.
        """
        prompt = _build_repair_prompt(
            constraints, unsat_core, history_summary, paradigm_hint, switch_prompt
        )
        return self._call(prompt, max_tokens=_MAX_TOKENS_REPAIR)

    # ------------------------------------------------------------------
    # Paradigm abstraction
    # ------------------------------------------------------------------

    def abstract_paradigm(self, kdps: list) -> str:
        """Request paradigm abstraction from a list of KDP objects.

        Args:
            kdps: List of ``KDP`` instances sampled from one cluster.

        Returns:
            Raw LLM response containing a JSON paradigm object.
        """
        prompt = _build_abstraction_prompt(kdps)
        return self._call(prompt, max_tokens=_MAX_TOKENS_ABSTRACTION)

    # ------------------------------------------------------------------
    # Semantic match (Layer 2 retrieval)
    # ------------------------------------------------------------------

    def judge_semantic_match(self, paradigm_summary: str, state_summary: str) -> bool:
        """Ask whether a paradigm semantically applies to the current solver state.

        Args:
            paradigm_summary: One-sentence description of the paradigm's trigger/operation.
            state_summary: Snapshot of current constraints and unsat core.

        Returns:
            True if the model responds with ``yes`` (case-insensitive prefix match).
        """
        prompt = _build_semantic_match_prompt(paradigm_summary, state_summary)
        response = self._call(prompt, max_tokens=_MAX_TOKENS_JUDGE)
        return response.strip().lower().startswith("yes")

    # ------------------------------------------------------------------
    # Parsing helpers (static)
    # ------------------------------------------------------------------

    @staticmethod
    def parse_constraints(response: str) -> List[str]:
        """Extract Z3 constraint strings from an LLM response.

        Looks for a ``python`` fenced code block first; falls back to scanning
        non-empty, non-comment lines from the raw response.

        Args:
            response: Raw LLM response text.

        Returns:
            List of Z3 Python expression strings, ready for ``Z3SolverWrapper.add_constraint()``.
        """
        block_match = re.search(r"```python\n(.*?)```", response, re.DOTALL)
        source = block_match.group(1) if block_match else response
        constraints: List[str] = []
        for line in source.splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                constraints.append(line)
        return constraints

    @staticmethod
    def parse_repair(response: str) -> Optional[str]:
        """Extract a single corrected constraint from a repair response.

        Prefers the first non-empty non-comment line inside a code block.

        Args:
            response: Raw LLM response text.

        Returns:
            A single Z3 expression string, or ``None`` if nothing parseable found.
        """
        block_match = re.search(r"```python\n(.*?)```", response, re.DOTALL)
        source = block_match.group(1) if block_match else response
        for line in source.splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                return line
        return None

    @staticmethod
    def parse_paradigm_json(response: str) -> Optional[dict]:
        """Extract a JSON paradigm object from an LLM response.

        Tries to isolate the outermost ``{...}`` block first; falls back to
        parsing the entire response as JSON.

        Args:
            response: Raw LLM response text.

        Returns:
            Parsed dict, or ``None`` on failure.
        """
        json_match = re.search(r"\{.*\}", response, re.DOTALL)
        if json_match:
            try:
                return json.loads(json_match.group(0))
            except json.JSONDecodeError:
                pass
        try:
            return json.loads(response)
        except json.JSONDecodeError:
            return None


# --------------------------------------------------------------------------- #
# Prompt builders (module-private)                                              #
# --------------------------------------------------------------------------- #

def _build_translation_prompt(puzzle_nl: str) -> str:
    return f"""你是一个约束形式化专家。请将以下逻辑谜题翻译为 Z3 Python 约束。

## 谜题描述
{puzzle_nl}

## Z3 编码规则
- 使用 Int('变量名') 表示整数变量，值域为谜题的实体编号（如 1 到 n）
- 使用 Distinct(a, b, c, ...) 表示所有不同约束
- 相邻位置：Abs(a - b) == 1
- "紧邻右侧"：a - b == 1（a 在 b 右边）
- "紧邻左侧"：b - a == 1（a 在 b 左边）
- "在...左边某处"：a < b

## 输出格式
请只输出一个 ```python``` 代码块，每行一个 Z3 表达式。
不要包含 solver.add() 调用，只输出原始表达式。

```python
# 域约束示例
And(Int('entity1') >= 1, Int('entity1') <= 5)
# 不同约束示例
Distinct(Int('entity1'), Int('entity2'), Int('entity3'))
# 位置约束示例
Int('entity1') == Int('entity2') + 1
```
"""


def _build_repair_prompt(
    constraints: List[str],
    unsat_core: List[str],
    history_summary: str,
    paradigm_hint: str,
    switch_prompt: str,
) -> str:
    constraints_str = "\n".join(f"  {c}" for c in constraints)
    core_str = "\n".join(f"  {c}" for c in unsat_core)
    hint_section = f"\n## 范式提示\n{paradigm_hint}" if paradigm_hint else ""
    switch_section = f"\n## 策略切换指令\n{switch_prompt}" if switch_prompt else ""

    return f"""你是一个约束修复专家。请修复以下约束满足问题中的错误约束。

## 历史修复记录
{history_summary}

## 当前 UNSAT Core（相互矛盾的约束）
{core_str}

## 所有当前约束
{constraints_str}
{hint_section}
{switch_section}

## 任务
请识别 UNSAT Core 中哪个约束的形式化有误，并输出修正后的版本。
只输出一个 Z3 Python 表达式（不要包含其他说明）。
"""


def _build_retranslation_prompt(
    puzzle_nl: str,
    failed_constraints: List[str],
    error_ctx: str,
) -> str:
    failed_str = "\n".join(f"  {c}" for c in failed_constraints)
    return f"""之前的约束形式化无法修复，请重新翻译整个谜题。

## 原始谜题描述
{puzzle_nl}

## 失败的约束集合（仅供参考，请忽略并重新翻译）
{failed_str}

## 错误信息
{error_ctx}

## 要求
请从头开始重新翻译，不要参考之前的约束集合。
按照标准 Z3 Python 格式输出，每行一个表达式，放在 ```python``` 块中。
"""


def _build_abstraction_prompt(kdps: list) -> str:
    kdp_strs = []
    for i, kdp in enumerate(kdps, 1):
        step = kdp.step
        kdp_strs.append(
            f"KDP {i}:\n"
            f"  约束类型: {kdp.constraint_types}\n"
            f"  步骤类型: {step.step_type}\n"
            f"  添加的约束: {step.constraint_added}\n"
            f"  域大小变化: {step.domain_sizes_before} → {step.domain_sizes_after}\n"
            f"  Z3 结果: {step.z3_result}"
        )

    return f"""你是一个推理模式提取专家。请从以下关键决策点（KDP）中抽象出一个通用的求解范式。

## 关键决策点
{chr(10).join(kdp_strs)}

## 任务
分析这些 KDP 的共同模式，提炼出一个可复用的求解策略。

## 输出格式（严格 JSON）
{{
  "name": "范式名称（3-5 个英文词或中文词）",
  "operation": "什么情况下做什么推断，以及为什么这个推断是有效的",
  "pre_condition": "触发该范式需要满足的 Z3 前置条件字符串",
  "post_condition": "预期的域缩减或推断结果描述",
  "scope": ["适用的约束类型列表"],
  "trigger": {{
    "constraint_types": ["触发所需的约束类型"],
    "domain_pattern": "触发所需的域模式描述"
  }}
}}

请只输出 JSON 对象，不要包含其他文字。
"""


def _build_semantic_match_prompt(paradigm_summary: str, state_summary: str) -> str:
    return f"""请判断以下求解范式是否适用于当前求解状态。

## 范式描述
{paradigm_summary}

## 当前求解状态
{state_summary}

请只回答 "yes" 或 "no"，不要包含其他内容。
"""

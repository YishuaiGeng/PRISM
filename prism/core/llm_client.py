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
_MAX_TOKENS_NORMALIZE: int = 3072
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

    def translate(
        self,
        puzzle_nl: str,
        schema_hint: str = "",
        paradigm_hint: str = "",
    ) -> str:
        """Request initial NL→Z3 translation for a puzzle.

        Args:
            puzzle_nl: Full natural-language puzzle description.
            schema_hint: Optional visible variable-key schema.
            paradigm_hint: Optional safe positive guidance templates.

        Returns:
            Raw LLM response containing a Python code block with Z3 constraints.
        """
        prompt = _build_translation_prompt_v2(puzzle_nl, schema_hint, paradigm_hint)
        return self._call(prompt, max_tokens=_MAX_TOKENS_TRANSLATION)

    def normalize_translation(
        self,
        puzzle_nl: str,
        draft_constraints: List[str],
        schema_hint: str = "",
        error_ctx: str = "",
    ) -> str:
        """Request a second-pass cleanup of translated Z3 constraints."""
        prompt = _build_translation_normalization_prompt_v2(
            puzzle_nl,
            draft_constraints,
            schema_hint,
            error_ctx,
        )
        return self._call(prompt, max_tokens=_MAX_TOKENS_NORMALIZE)

    def retranslate(
        self,
        puzzle_nl: str,
        failed_constraints: List[str],
        error_ctx: str,
        schema_hint: str = "",
    ) -> str:
        """Request a full re-translation after L4 strategy escalation.

        Args:
            puzzle_nl: Original natural-language puzzle description.
            failed_constraints: The constraint set that led to irrecoverable UNSAT.
            error_ctx: Error message or UNSAT core description for context.

        Returns:
            Raw LLM response with fresh Z3 constraints.
        """
        prompt = _build_retranslation_prompt_v2(
            puzzle_nl,
            failed_constraints,
            error_ctx,
            schema_hint,
        )
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
        prompt = _build_repair_prompt_v2(
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
        prompt = _build_semantic_match_prompt_v2(paradigm_summary, state_summary)
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
            f"  constraint_types: {kdp.constraint_types}\n"
            f"  kdp_type: {kdp.kdp_type}\n"
            f"  step_type: {step.step_type}\n"
            f"  constraint_added: {step.constraint_added}\n"
            f"  constraint_removed: {step.constraint_removed}\n"
            f"  z3_result: {step.z3_result}\n"
            f"  unsat_core: {step.unsat_core}\n"
            f"  domain_sizes_before: {step.domain_sizes_before}\n"
            f"  domain_sizes_after: {step.domain_sizes_after}"
        )

    return f"""You extract reusable CSP solving paradigms from solver trajectories.

Return exactly one JSON object and nothing else. Do not use Markdown, comments,
code fences, trailing commas, or explanatory prose.

The JSON object must conform to this schema:
{{
  "name": "short_snake_case_name",
  "operation": "one single-line Z3 Python boolean expression",
  "pre_condition": "one single-line Z3 Python boolean expression, or empty string",
  "post_condition": "brief natural-language effect description",
  "scope": ["one_or_more_constraint_type_tags"],
  "trigger": {{
    "constraint_types": ["one_or_more_constraint_type_tags"],
    "domain_pattern": "brief trigger description"
  }}
}}

Field rules:
- operation must be parseable by Python Z3 eval, for example: Int('x') > 0
- pre_condition must also be parseable if non-empty.
- Use only constraint type tags observed in the KDPs when possible.
- Extract a size-invariant Zebra reasoning or repair pattern. Prefer relation
  templates such as Int('a') == Int('b'), Int('a') != Int('b'),
  Int('a') == Int('b') + 1, Abs(Int('a') - Int('b')) == 1, Int('a') < Int('b'),
  Int('a') > Int('b'), Or(...), Not(...), or Implies(...).
- If the KDP is a successful repair, make operation the reusable repaired
  relation pattern, not a copy of a puzzle-specific variable assignment.
- Do not output schema invariants as positive paradigms: no pure domain bounds
  such as And(Int('x') >= 1, Int('x') <= n), no all-different/Distinct(...)
  constraints, and no puzzle-size-specific constants used only as bounds.
- If the only visible pattern is a schema invariant, still return the best
  non-schema relation/check visible in the KDP; otherwise return a conservative
  relation repair that avoids the same contradiction.
- Do not invent variable names unless the KDP evidence contains no reusable name;
  in that case use Int('a') and Int('b') style placeholders.
- Keep every string value on one line.

KDP evidence:
{chr(10).join(kdp_strs)}
"""


def _build_translation_prompt_v2(
    puzzle_nl: str,
    schema_hint: str = "",
    paradigm_hint: str = "",
) -> str:
    schema_section = _format_schema_hint(schema_hint)
    guidance_section = (
        "\nVerified reusable patterns from prior solved trajectories:\n"
        f"{paradigm_hint}\n"
        "Treat these as templates only. Replace placeholder variables with "
        "variables from this puzzle, and do not copy training-puzzle names.\n"
        if paradigm_hint
        else ""
    )
    return f"""You are translating a logic-grid CSP puzzle into Z3 Python constraints.

Return only one fenced python code block. Do not include prose, comments,
solver.add calls, imports, model extraction code, or markdown outside the code
block.

Use only single-line Z3 boolean expressions, one expression per line. Valid
constructs include Int('var'), And(...), Or(...), Not(...), Implies(...),
Distinct(...), Abs(...), ==, !=, <, <=, >, >=.

Encoding rules:
- Represent every puzzle attribute value as an integer position/domain value.
- Use one integer variable per semantic attribute value, for example
  Int('color_Blue'), Int('drink_Wine'), or Int('nationality_Norwegian').
- Do not encode answers as house-slot variables such as Int('house1_color') or
  Int('house2_pet'); those variables do not match the benchmark answer schema.
- If an expected variable-key schema is provided below, use exactly those key
  names as Int('...') variables. The schema lists variable names only, not
  answer values.
- Add domain constraints when useful, for example:
  And(Int('color_Blue') >= 1, Int('color_Blue') <= 5)
- Use Distinct(...) for all-different groups.
- Use these verified Zebra relation templates exactly:
  - Same house / same person: Int('A') == Int('B')
  - Different people/items: Int('A') != Int('B')
  - Adjacent / next to: Abs(Int('A') - Int('B')) == 1
  - A is immediately/directly left of B: Int('A') == Int('B') - 1
  - A is immediately/directly right of B: Int('A') == Int('B') + 1
  - A is somewhere/to the left of B: Int('A') < Int('B')
  - A is somewhere/to the right of B: Int('A') > Int('B')
- Avoid common verified translation errors:
  - Do not reverse left/right signs.
  - Do not encode left/right/next-to clues as equality.
  - Do not encode same-house clues as inequality.
  - Do not weaken directly-left/right clues into only < or >.

If a clue cannot be represented confidently, omit that clue rather than writing
invalid Python. Still return every valid constraint you can infer.
{schema_section}{guidance_section}

Puzzle:
{puzzle_nl}

Output format:
```python
And(Int('color_Blue') >= 1, Int('color_Blue') <= 5)
Distinct(Int('color_Blue'), Int('color_Green'))
Int('drink_Wine') == Int('drink_Water') - 1
```
"""


def _build_repair_prompt_v2(
    constraints: List[str],
    unsat_core: List[str],
    history_summary: str,
    paradigm_hint: str,
    switch_prompt: str,
) -> str:
    constraints_str = "\n".join(f"  {c}" for c in constraints)
    core_str = "\n".join(f"  {c}" for c in unsat_core)
    hint_section = f"\nGuidance:\n{paradigm_hint}\n" if paradigm_hint else ""
    switch_section = f"\nStrategy instruction:\n{switch_prompt}\n" if switch_prompt else ""

    return f"""You are repairing a Z3 constraint set for a CSP puzzle.

Return exactly one corrected Z3 Python boolean expression. Do not include
Markdown, comments, explanations, solver.add calls, or multiple alternatives.

Repair objective:
- Inspect the UNSAT core and identify the most likely mistranslated constraint.
- Preserve the intended clue when possible.
- Prefer a weaker or corrected relation over adding a new unrelated constraint.
- The returned expression will replace one constraint from the current UNSAT
  core, so it must be parseable by Z3 Python eval.
- If Guidance contains "Avoid these verified UNSAT-producing patterns", treat
  those as solver-verified negative examples. Do not repeat their bad_operation.
  Use their repair_hint as the preferred relation template when it matches the
  current UNSAT core.
- Prefer size-invariant Zebra relation repairs: equality for same-house binding,
  != for exclusion, Abs(a - b) == 1 for next-to, a == b - 1 for directly-left,
  a == b + 1 for directly-right, a < b or a > b for somewhere-left/right.
- Do not repair by adding pure domain bounds or Distinct(...) constraints unless
  the UNSAT core itself is a schema constraint.

Repair history:
{history_summary}

Current UNSAT core:
{core_str}

All current constraints:
{constraints_str}
{hint_section}{switch_section}
Corrected expression only:
"""


def _build_retranslation_prompt_v2(
    puzzle_nl: str,
    failed_constraints: List[str],
    error_ctx: str,
    schema_hint: str = "",
) -> str:
    failed_str = "\n".join(f"  {c}" for c in failed_constraints)
    schema_section = _format_schema_hint(schema_hint)
    return f"""The previous Z3 formalization could not be repaired. Translate the
entire CSP puzzle again from scratch.

Return only one fenced python code block. Do not include prose, comments,
solver.add calls, imports, or markdown outside the code block. Each non-empty
line inside the block must be one parseable Z3 Python boolean expression.

Ignore the failed constraints except as examples of what may be wrong.

Schema requirements:
- Include domain bounds for every declared integer variable, for example
  And(Int('x') >= 1, Int('x') <= N) where N is the number of houses.
- Include all-different constraints for each attribute category using
  Distinct(...).
- Do not create placeholder "other" variables unless the puzzle text explicitly
  contains such a value.
- Keep variable names consistent across all constraints for the same entity or
  attribute value.
- Use semantic attribute-value variables such as Int('color_Blue') and
  Int('drink_Wine'), not house-slot variables such as Int('house1_color').
- If an expected variable-key schema is provided below, use exactly those key
  names as Int('...') variables. The schema lists variable names only, not
  answer values.
{schema_section}

Original puzzle:
{puzzle_nl}

Failed constraints:
{failed_str}

Error context:
{error_ctx}

Output format:
```python
And(Int('color_Blue') >= 1, Int('color_Blue') <= 5)
Distinct(Int('color_Blue'), Int('color_Green'))
Int('drink_Wine') == Int('drink_Water') - 1
```
"""


def _build_translation_normalization_prompt_v2(
    puzzle_nl: str,
    draft_constraints: List[str],
    schema_hint: str = "",
    error_ctx: str = "",
) -> str:
    draft_str = "\n".join(f"  {constraint}" for constraint in draft_constraints)
    schema_section = _format_schema_hint(schema_hint)
    error_section = f"\nCleanup context:\n{error_ctx}\n" if error_ctx else ""
    return f"""You are cleaning up a draft Z3 translation of a logic-grid CSP puzzle.

Return only one fenced python code block. Do not include prose, comments,
solver.add calls, imports, model extraction code, or markdown outside the code
block.

Cleanup objective:
- Preserve the intended clue constraints from the draft whenever they are
  compatible with the puzzle text.
- Treat this as normalization, not a new translation: do not reverse, weaken,
  strengthen, or replace a clue relation that is already present in the draft.
  You may only drop a relation when it is clearly unsupported by the puzzle text.
- Normalize variable names to semantic attribute-value keys such as
  Int('color_Blue'), Int('drink_Wine'), or Int('Name_Alice').
- Do not use house-slot variables such as Int('house1_color').
- If a variable-key schema is provided, use exactly those Int('...') names for
  semantic variables and remove variables outside that schema.
- Add domain bounds for every semantic variable, using the number of houses in
  the puzzle, for example And(Int('x') >= 1, Int('x') <= N).
- Add one Distinct(...) constraint for every attribute category whose variables
  are present.
- Remove duplicate constraints and invalid Python/Z3 expressions.
- Do not invent answer assignments. Only keep direct house assignments that are
  explicitly stated by a clue in the puzzle text.
- Do not turn uncertainty into guessed constraints. If a draft clue mapping is
  not supported by the puzzle text, omit it.
- Keep every expression on a single line.

Valid constructs include Int('var'), And(...), Or(...), Not(...), Implies(...),
Distinct(...), Abs(...), ==, !=, <, <=, >, >=.
{schema_section}{error_section}

Puzzle:
{puzzle_nl}

Draft constraints:
{draft_str}

Output format:
```python
And(Int('color_Blue') >= 1, Int('color_Blue') <= 5)
Distinct(Int('color_Blue'), Int('color_Green'))
Int('drink_Wine') == Int('drink_Water') - 1
```
"""


def _build_semantic_match_prompt_v2(paradigm_summary: str, state_summary: str) -> str:
    return f"""Decide whether the reusable CSP paradigm applies to the current
solver state.

Paradigm:
{paradigm_summary}

Current state:
{state_summary}

Answer exactly one token: yes or no.
"""


def _format_schema_hint(schema_hint: str) -> str:
    if not schema_hint:
        return ""
    return f"""

Expected variable-key schema:
{schema_hint}
Use only these visible schema keys for semantic variables. If a category has
fewer keys than the number of houses, do not invent missing candidate values;
translate only constraints supported by visible clues.
"""

def _build_semantic_match_prompt(paradigm_summary: str, state_summary: str) -> str:
    return f"""请判断以下求解范式是否适用于当前求解状态。

## 范式描述
{paradigm_summary}

## 当前求解状态
{state_summary}

请只回答 "yes" 或 "no"，不要包含其他内容。
"""

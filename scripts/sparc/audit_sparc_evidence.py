"""Reproduce the SPARC evidence and provenance audit from saved traces.

The script performs only cached, solver-side analyses.  It never calls an
LLM.  Its outputs are intended to make three evidence boundaries explicit:

1. historical no-gate and SPARC runs were generated independently, so their
   pre-gate formalizations are not generally paired;
2. replaying the uniqueness probe on no-gate SAT outputs measures the gate's
   diagnostic scope without confounding it with a new translation;
3. the current implementation does not mechanically restrict completion
   constraints to an answer-variable whitelist.

Usage::

    python scripts/sparc/audit_sparc_evidence.py \
      results/sparc/zebra_v2_s42 results/sparc/zebra_v2_s123 results/sparc/zebra_v2_s7

The default output directory is ``results/sparc/sparc_evidence_audit`` and contains
JSON, Markdown, and CSV files used by the paper.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import random
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Iterator, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from prism.core.model_validation import normalise_schema_key
from prism.core.solver import Z3SolverWrapper
from prism.evaluation.benchmarks.zebralogic import answers_match, is_scorable


DEFAULT_RESULT_DIRS = (
    Path("results/sparc/zebra_v2_s42"),
    Path("results/sparc/zebra_v2_s123"),
    Path("results/sparc/zebra_v2_s7"),
)
PAIRINGS = (
    ("baseline", "basesparc", "baseline"),
    ("nopar", "noparsparc", "aggressive"),
)
NO_GATE_SYSTEMS = (("baseline", "baseline"), ("nopar", "aggressive"))
SPARC_SYSTEMS = ("basesparc", "noparsparc")
INT_VAR_RE = re.compile(r"Int\(['\"]([^'\"]+)['\"]\)")


@dataclass(frozen=True)
class TraceRecord:
    repetition: str
    group: str
    system: str
    source: str
    record: dict

    @property
    def puzzle_id(self) -> str:
        return str(self.record.get("puzzle_id", ""))

    @property
    def key(self) -> tuple[str, str, str]:
        return self.repetition, self.group, self.puzzle_id


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Audit SPARC pairing, gate diagnostics, and premise scope"
    )
    parser.add_argument(
        "result_dirs",
        nargs="*",
        type=Path,
        help="Result directories containing *_g*.trace.jsonl files",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("results/sparc/sparc_evidence_audit"),
    )
    parser.add_argument("--bootstrap-replicates", type=int, default=10_000)
    parser.add_argument("--bootstrap-seed", type=int, default=20260712)
    parser.add_argument(
        "--arlsat-dir",
        type=Path,
        default=Path("results/sparc/arlsat_gate_probe"),
        help="Optional AR-LSAT pilot directory containing baseline/gate CSV and traces",
    )
    parser.add_argument(
        "--ablation-dir",
        type=Path,
        default=Path("results/sparc/zebra_ablation_s42"),
        help="Optional directory containing blind/noinv component traces",
    )
    return parser.parse_args(argv)


def _group_from_path(path: Path, system: str) -> str:
    prefix = f"{system}_"
    name = path.name
    if name.startswith(prefix):
        name = name[len(prefix) :]
    return name.split(".trace.jsonl", 1)[0]


def load_records(result_dirs: Sequence[Path], system: str) -> list[TraceRecord]:
    records: list[TraceRecord] = []
    for result_dir in result_dirs:
        for path in sorted(result_dir.glob(f"{system}_g*.trace.jsonl")):
            with path.open(encoding="utf-8") as handle:
                for line_number, line in enumerate(handle, start=1):
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        record = json.loads(line)
                    except json.JSONDecodeError as exc:
                        raise ValueError(f"Invalid JSON at {path}:{line_number}") from exc
                    records.append(
                        TraceRecord(
                            repetition=result_dir.name,
                            group=_group_from_path(path, system),
                            system=system,
                            source=str(path),
                            record=record,
                        )
                    )
    return records


def _replace_constraint(
    constraints: list[str], old_constraint: object, new_constraint: object
) -> list[str]:
    old = str(old_constraint or "")
    new = str(new_constraint or "")
    if not new:
        return constraints
    updated = list(constraints)
    if old and old in updated:
        updated[updated.index(old)] = new
    elif not old:
        updated.append(new)
    else:
        # The online repair helper falls back to an assertion when its selected
        # target cannot be located.  Preserve that behavior in trace replay.
        updated.append(new)
    return updated


def advance_constraints(constraints: list[str], step: dict) -> list[str]:
    """Replay one trace step and return the resulting constraint list."""
    current = list(constraints)
    if isinstance(step.get("constraints"), list):
        current = [str(value) for value in step["constraints"]]
    if isinstance(step.get("constraints_before"), list):
        current = [str(value) for value in step["constraints_before"]]

    action = str(step.get("action", ""))
    if action in {"repair", "sparc_conflict_repair"}:
        current = _replace_constraint(
            current, step.get("old_constraint"), step.get("new_constraint")
        )
    elif action == "diff_completion" and step.get("new_constraint"):
        current.append(str(step["new_constraint"]))
    return current


def iter_constraint_states(record: dict) -> Iterator[tuple[dict, list[str], list[str]]]:
    current: list[str] = []
    for step in record.get("steps") or []:
        before = list(current)
        current = advance_constraints(current, step)
        yield step, before, list(current)


def reconstruct_constraints(record: dict, *, stop_before_gate: bool = False) -> list[str]:
    current: list[str] = []
    for step in record.get("steps") or []:
        if stop_before_gate and step.get("action") == "pi_gate":
            break
        current = advance_constraints(current, step)
    return current


def last_constraint_snapshot(record: dict, *, stop_before_gate: bool = False) -> list[str]:
    """Return the last explicit ``constraints`` snapshot in a trace.

    This deliberately does not replay later repair mutations.  It is reported
    as a provenance diagnostic because early exploratory analyses used these
    snapshots; it must not be mistaken for the actual pre-gate solver state.
    """
    snapshot: list[str] = []
    for step in record.get("steps") or []:
        if stop_before_gate and step.get("action") == "pi_gate":
            break
        if isinstance(step.get("constraints"), list):
            snapshot = [str(value) for value in step["constraints"]]
    return snapshot


def constraints_sha256(constraints: Sequence[str]) -> str:
    payload = json.dumps(list(constraints), ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def outcome(record: dict) -> str:
    if not is_scorable(record.get("ground_truth")):
        return "unscorable"
    final = record.get("final_z3_result")
    if final == "SAT":
        if answers_match(record.get("ground_truth"), record.get("predicted")):
            return "correct"
        return "sbw"
    if final == "SAT_NONUNIQUE":
        return "gate_abstain"
    return "other_nonanswer"


def uniqueness_probe(
    constraints: Sequence[str],
    answer_keys: frozenset = frozenset(),
) -> dict:
    """Replay the implementation's uniqueness probe on a constraint multiset.

    By default this reproduces the historical all-non-tracked-integer V_A
    approximation. Passing *answer_keys* (normalised via
    ``prism.core.model_validation.normalise_schema_key``) restricts the
    blocking clause to matching variables, mirroring the online gate's
    whitelist mode; when no model variable matches, it falls back to the
    all-integer approximation so both modes stay comparable per state.
    """
    solver = Z3SolverWrapper()
    parse_failures: list[str] = []
    for constraint in constraints:
        if not solver.add_constraint(str(constraint)):
            parse_failures.append(str(constraint))
    verdict = solver.check()
    if verdict != "SAT":
        return {
            "gate": verdict.lower(),
            "base_verdict": verdict,
            "parse_failures": parse_failures,
            "blocked_variables": 0,
        }

    model = solver.get_model()
    int_pairs = [
        (str(var), str(value))
        for var, value in model.items()
        if not str(var).startswith("_prism_track_")
        and str(value).lstrip("-").isdigit()
    ]
    va_mode = "all_int"
    if answer_keys:
        matched = [
            (var, value)
            for var, value in int_pairs
            if normalise_schema_key(var) in answer_keys
        ]
        if matched:
            int_pairs = matched
            va_mode = "whitelist"
    equalities = [f"Int('{var}') == {value}" for var, value in int_pairs]
    if not equalities:
        return {
            "gate": "skipped_no_model",
            "base_verdict": verdict,
            "parse_failures": parse_failures,
            "blocked_variables": 0,
        }
    probe = solver.clone()
    probe.add_constraint(f"Not(And({', '.join(equalities)}))")
    second_verdict = probe.check()
    if second_verdict == "UNSAT":
        gate = "unique"
    elif second_verdict == "SAT":
        gate = "non_unique"
    else:
        gate = "unknown"
    return {
        "gate": gate,
        "base_verdict": verdict,
        "parse_failures": parse_failures,
        "blocked_variables": len(equalities),
        "va_mode": va_mode,
    }


def _counter_dict(counter: Counter) -> dict[str, int]:
    return {str(key): int(counter[key]) for key in sorted(counter)}


def pairing_audit(
    no_gate_records: Sequence[TraceRecord], sparc_records: Sequence[TraceRecord]
) -> dict:
    left = {item.key: item for item in no_gate_records}
    right = {item.key: item for item in sparc_records}
    shared = sorted(set(left) & set(right))
    scorable = [
        key
        for key in shared
        if is_scorable(left[key].record.get("ground_truth"))
        and is_scorable(right[key].record.get("ground_truth"))
    ]
    exact: list[tuple[TraceRecord, TraceRecord]] = []
    snapshot_exact: list[tuple[TraceRecord, TraceRecord]] = []
    per_repetition: dict[str, Counter] = defaultdict(Counter)
    for key in scorable:
        a, b = left[key], right[key]
        a_constraints = reconstruct_constraints(a.record, stop_before_gate=True)
        b_constraints = reconstruct_constraints(b.record, stop_before_gate=True)
        # Constraint conjunctions are order-insensitive.  Counter equality
        # retains duplicate assertions while ignoring serialization order.
        matched = Counter(a_constraints) == Counter(b_constraints)
        snapshot_matched = sorted(
            last_constraint_snapshot(a.record, stop_before_gate=True)
        ) == sorted(last_constraint_snapshot(b.record, stop_before_gate=True))
        per_repetition[a.repetition]["paired"] += 1
        per_repetition[a.repetition]["exact"] += int(matched)
        if matched:
            exact.append((a, b))
        if snapshot_matched:
            snapshot_exact.append((a, b))

    left_outcomes = Counter(outcome(a.record) for a, _ in exact)
    right_outcomes = Counter(outcome(b.record) for _, b in exact)
    transitions = Counter(
        f"{outcome(a.record)}->{outcome(b.record)}" for a, b in exact
    )
    return {
        "shared_records": len(shared),
        "scorable_pairs": len(scorable),
        "exact_pre_gate_pairs": len(exact),
        "exact_match_rate": len(exact) / len(scorable) if scorable else None,
        "snapshot_only_pairs": len(snapshot_exact),
        "snapshot_only_no_gate_outcomes": _counter_dict(
            Counter(outcome(a.record) for a, _ in snapshot_exact)
        ),
        "snapshot_only_sparc_outcomes": _counter_dict(
            Counter(outcome(b.record) for _, b in snapshot_exact)
        ),
        "per_repetition": {
            repetition: {
                "paired": counts["paired"],
                "exact": counts["exact"],
                "rate": counts["exact"] / counts["paired"]
                if counts["paired"]
                else None,
            }
            for repetition, counts in sorted(per_repetition.items())
        },
        "exact_subset_no_gate_outcomes": _counter_dict(left_outcomes),
        "exact_subset_sparc_outcomes": _counter_dict(right_outcomes),
        "exact_subset_transitions": _counter_dict(transitions),
        "interpretation": (
            "post_hoc replayed-state multiset match; selection-conditioned and "
            "not a replacement for a prospectively frozen paired experiment. "
            "snapshot_only_* omits unsnapshotted repair mutations and is included "
            "only to reconcile earlier exploratory counts"
        ),
    }


def component_pairing_audit(
    full_records: Sequence[TraceRecord], ablation_records: Sequence[TraceRecord]
) -> dict:
    """Audit a component arm whose directory uses a different repetition label."""
    left = {(item.group, item.puzzle_id): item for item in full_records}
    right = {(item.group, item.puzzle_id): item for item in ablation_records}
    shared = sorted(set(left) & set(right))
    scorable = [
        key
        for key in shared
        if is_scorable(left[key].record.get("ground_truth"))
        and is_scorable(right[key].record.get("ground_truth"))
    ]
    replay_exact = []
    snapshot_exact = []
    for key in scorable:
        a, b = left[key], right[key]
        if Counter(reconstruct_constraints(a.record, stop_before_gate=True)) == Counter(
            reconstruct_constraints(b.record, stop_before_gate=True)
        ):
            replay_exact.append((a, b))
        if Counter(last_constraint_snapshot(a.record, stop_before_gate=True)) == Counter(
            last_constraint_snapshot(b.record, stop_before_gate=True)
        ):
            snapshot_exact.append((a, b))
    return {
        "scorable_pairs": len(scorable),
        "replayed_pre_gate_matches": len(replay_exact),
        "replayed_match_rate": len(replay_exact) / len(scorable) if scorable else None,
        "snapshot_only_matches": len(snapshot_exact),
        "matched_subset_full_outcomes": _counter_dict(
            Counter(outcome(a.record) for a, _ in replay_exact)
        ),
        "matched_subset_ablation_outcomes": _counter_dict(
            Counter(outcome(b.record) for _, b in replay_exact)
        ),
        "interpretation": (
            "configuration-matched but not frozen-input-paired; end-to-end "
            "differences do not isolate the toggled component"
        ),
    }


def _quantile(values: Sequence[float], probability: float) -> float:
    ordered = sorted(values)
    if not ordered:
        raise ValueError("Cannot compute a quantile of an empty sequence")
    position = (len(ordered) - 1) * probability
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - lower
    return ordered[lower] * (1.0 - fraction) + ordered[upper] * fraction


def cluster_bootstrap_ci(
    rows: Sequence[dict],
    metric: Callable[[Counter], float | None],
    *,
    replicates: int,
    seed: int,
) -> dict:
    by_puzzle: dict[str, Counter] = defaultdict(Counter)
    for row in rows:
        by_puzzle[str(row["puzzle_id"])].update(row["counts"])
    puzzle_ids = sorted(by_puzzle)
    observed = Counter()
    for counts in by_puzzle.values():
        observed.update(counts)
    estimate = metric(observed)
    if estimate is None or not puzzle_ids or replicates <= 0:
        return {
            "estimate": estimate,
            "low": None,
            "high": None,
            "valid_replicates": 0,
            "cluster_count": len(puzzle_ids),
        }

    rng = random.Random(seed)
    samples: list[float] = []
    for _ in range(replicates):
        sampled = Counter()
        for _ in puzzle_ids:
            sampled.update(by_puzzle[rng.choice(puzzle_ids)])
        value = metric(sampled)
        if value is not None:
            samples.append(value)
    return {
        "estimate": estimate,
        "low": _quantile(samples, 0.025) if samples else None,
        "high": _quantile(samples, 0.975) if samples else None,
        "valid_replicates": len(samples),
        "cluster_count": len(puzzle_ids),
    }


def _detection_rate(counts: Counter) -> float | None:
    denominator = counts["wrong_unique"] + counts["wrong_non_unique"]
    return counts["wrong_non_unique"] / denominator if denominator else None


def _false_rejection_rate(counts: Counter) -> float | None:
    denominator = counts["correct_unique"] + counts["correct_non_unique"]
    return counts["correct_non_unique"] / denominator if denominator else None


def _accuracy(counts: Counter) -> float | None:
    return counts["correct"] / counts["total"] if counts["total"] else None


def _coverage(counts: Counter) -> float | None:
    answered = counts["correct"] + counts["sbw"]
    return answered / counts["total"] if counts["total"] else None


def _risk(counts: Counter) -> float | None:
    answered = counts["correct"] + counts["sbw"]
    return counts["sbw"] / answered if answered else None


def historical_arm_summary(
    records: Sequence[TraceRecord], *, bootstrap_replicates: int, bootstrap_seed: int
) -> dict:
    counts = Counter()
    rows: list[dict] = []
    for item in records:
        label = outcome(item.record)
        if label == "unscorable":
            continue
        counts[label] += 1
        rows.append(
            {"puzzle_id": item.puzzle_id, "counts": {label: 1, "total": 1}}
        )
    metrics = {}
    for offset, (name, function) in enumerate(
        (("accuracy", _accuracy), ("coverage", _coverage), ("risk", _risk))
    ):
        metrics[name] = cluster_bootstrap_ci(
            rows,
            function,
            replicates=bootstrap_replicates,
            seed=bootstrap_seed + offset,
        )
    return {
        "counts": {
            "correct": counts["correct"],
            "sbw": counts["sbw"],
            "gate_abstain": counts["gate_abstain"],
            "other_nonanswer": counts["other_nonanswer"],
        },
        "metrics": metrics,
    }


def gate_diagnostic(
    records: Sequence[TraceRecord], *, bootstrap_replicates: int, bootstrap_seed: int
) -> dict:
    aggregate = Counter()
    per_repetition: dict[str, Counter] = defaultdict(Counter)
    bootstrap_rows: list[dict] = []
    invalid_replays: list[dict] = []
    for item in records:
        record = item.record
        if outcome(record) not in {"correct", "sbw"}:
            continue
        constraints = reconstruct_constraints(record)
        probe = uniqueness_probe(constraints)
        if probe["base_verdict"] != "SAT" or probe["gate"] not in {
            "unique",
            "non_unique",
        }:
            invalid_replays.append(
                {
                    "repetition": item.repetition,
                    "group": item.group,
                    "puzzle_id": item.puzzle_id,
                    "probe": probe,
                }
            )
            continue
        correctness = "correct" if outcome(record) == "correct" else "wrong"
        key = f"{correctness}_{probe['gate']}"
        aggregate[key] += 1
        per_repetition[item.repetition][key] += 1
        bootstrap_rows.append({"puzzle_id": item.puzzle_id, "counts": {key: 1}})

    detection_ci = cluster_bootstrap_ci(
        bootstrap_rows,
        _detection_rate,
        replicates=bootstrap_replicates,
        seed=bootstrap_seed,
    )
    false_rejection_ci = cluster_bootstrap_ci(
        bootstrap_rows,
        _false_rejection_rate,
        replicates=bootstrap_replicates,
        seed=bootstrap_seed + 1,
    )
    return {
        "aggregate": {
            "correct_unique": aggregate["correct_unique"],
            "correct_non_unique": aggregate["correct_non_unique"],
            "wrong_unique": aggregate["wrong_unique"],
            "wrong_non_unique": aggregate["wrong_non_unique"],
        },
        "per_repetition": {
            repetition: {
                "correct_unique": counts["correct_unique"],
                "correct_non_unique": counts["correct_non_unique"],
                "wrong_unique": counts["wrong_unique"],
                "wrong_non_unique": counts["wrong_non_unique"],
            }
            for repetition, counts in sorted(per_repetition.items())
        },
        "sbw_detection_rate": detection_ci,
        "correct_output_false_rejection_rate": false_rejection_ci,
        "invalid_replays": invalid_replays,
        "probe_scope": "all non-tracking integer variables in the reconstructed model",
    }


def variable_premise_audit(records: Iterable[TraceRecord]) -> dict:
    accepted = 0
    introduced_events: list[dict] = []
    for item in records:
        record = item.record
        current: list[str] = []
        for step in record.get("steps") or []:
            if step.get("action") == "diff_completion" and step.get("new_constraint"):
                accepted += 1
                candidate = str(step["new_constraint"])
                known = set(INT_VAR_RE.findall("\n".join(current)))
                candidate_vars = set(INT_VAR_RE.findall(candidate))
                introduced = sorted(candidate_vars - known)
                if introduced:
                    introduced_events.append(
                        {
                            "repetition": item.repetition,
                            "system": item.system,
                            "group": item.group,
                            "puzzle_id": item.puzzle_id,
                            "scorable": is_scorable(record.get("ground_truth")),
                            "candidate": candidate,
                            "introduced_variables": introduced,
                        }
                    )
            current = advance_constraints(current, step)
    distinct_variables = sorted(
        {
            variable
            for event in introduced_events
            for variable in event["introduced_variables"]
        }
    )
    return {
        "accepted_completion_constraints": accepted,
        "events_with_previously_unseen_variables": len(introduced_events),
        "scorable_events_with_previously_unseen_variables": sum(
            int(event["scorable"]) for event in introduced_events
        ),
        "distinct_previously_unseen_variables": distinct_variables,
        "events": introduced_events,
        "interpretation": (
            "The answer-variable-only premise is not mechanically enforced by "
            "the current implementation; incidence alone does not establish impact."
        ),
    }


def _load_jsonl_records(path: Path) -> dict[str, dict]:
    records: dict[str, dict] = {}
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSON at {path}:{line_number}") from exc
            records[str(record.get("puzzle_id", ""))] = record
    return records


def _csv_truth(value: object) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes"}


def arlsat_probe_audit(result_dir: Path) -> dict | None:
    required = (
        result_dir / "baseline.csv",
        result_dir / "gate.csv",
        result_dir / "baseline.trace.jsonl",
        result_dir / "gate.trace.jsonl",
    )
    if not all(path.is_file() for path in required):
        return None

    csv_rows: dict[str, list[dict]] = {}
    for system in ("baseline", "gate"):
        with (result_dir / f"{system}.csv").open(
            newline="", encoding="utf-8-sig"
        ) as handle:
            csv_rows[system] = list(csv.DictReader(handle))
    baseline = csv_rows["baseline"]
    gate = csv_rows["gate"]
    fallback = [row for row in baseline if _csv_truth(row.get("fallback_used"))]
    nonfallback = [row for row in baseline if not _csv_truth(row.get("fallback_used"))]
    gate_answered = [row for row in gate if str(row.get("predicted", "")).strip()]

    baseline_traces = _load_jsonl_records(result_dir / "baseline.trace.jsonl")
    gate_traces = _load_jsonl_records(result_dir / "gate.trace.jsonl")
    shared = sorted(set(baseline_traces) & set(gate_traces))
    exact_backgrounds = sum(
        Counter(reconstruct_constraints(baseline_traces[puzzle_id]))
        == Counter(reconstruct_constraints(gate_traces[puzzle_id]))
        for puzzle_id in shared
    )
    return {
        "sample_size": len(baseline),
        "baseline": {
            "correct": sum(_csv_truth(row.get("solved")) for row in baseline),
            "wrong": sum(not _csv_truth(row.get("solved")) for row in baseline),
            "fallback_count": len(fallback),
            "fallback_correct": sum(
                _csv_truth(row.get("solved")) for row in fallback
            ),
            "nonfallback_count": len(nonfallback),
            "nonfallback_correct": sum(
                _csv_truth(row.get("solved")) for row in nonfallback
            ),
            "nonfallback_risk": (
                sum(not _csv_truth(row.get("solved")) for row in nonfallback)
                / len(nonfallback)
                if nonfallback
                else None
            ),
        },
        "gate": {
            "answered": len(gate_answered),
            "correct": sum(_csv_truth(row.get("solved")) for row in gate_answered),
            "wrong": sum(not _csv_truth(row.get("solved")) for row in gate_answered),
            "risk": (
                sum(not _csv_truth(row.get("solved")) for row in gate_answered)
                / len(gate_answered)
                if gate_answered
                else None
            ),
        },
        "shared_trace_records": len(shared),
        "exact_background_constraint_multisets": exact_backgrounds,
        "interpretation": (
            "exploratory fixed-prefix pilot; baseline includes random fallback "
            "answers and independently generated backgrounds"
        ),
    }


def _percentage(value: float | None) -> str:
    return "NA" if value is None else f"{100.0 * value:.1f}%"


def render_markdown(report: dict) -> str:
    lines = [
        "# SPARC Evidence Audit",
        "",
        "> This report is generated from cached traces only. It makes no LLM calls.",
        "",
        "## Pairing audit",
        "",
        "| Comparison | Scorable pairs | Replayed pre-gate multiset match | Match rate | SBW before -> after on matched subset | Snapshot-only matches |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for name, result in report["pairing"].items():
        before = result["exact_subset_no_gate_outcomes"].get("sbw", 0)
        after = result["exact_subset_sparc_outcomes"].get("sbw", 0)
        lines.append(
            f"| {name} | {result['scorable_pairs']} | "
            f"{result['exact_pre_gate_pairs']} | "
            f"{_percentage(result['exact_match_rate'])} | {before} -> {after} |"
            f" {result['snapshot_only_pairs']} |"
        )
    lines.extend(
        [
            "",
            "The exact-match subset is selected after observing both runs. It is supportive, "
            "not a causal replacement for a prospectively frozen paired rerun.",
            "",
            "## Offline uniqueness diagnostic",
            "",
            "| Upstream system | Correct + unique | Correct + non-unique | Wrong + unique | Wrong + non-unique | SBW detection (95% cluster CI) | Correct-output false rejection (95% cluster CI) |",
            "|---|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for name, result in report["gate_diagnostic"].items():
        counts = result["aggregate"]
        detection = result["sbw_detection_rate"]
        false_rejection = result["correct_output_false_rejection_rate"]
        detection_text = (
            f"{_percentage(detection['estimate'])} "
            f"[{_percentage(detection['low'])}, {_percentage(detection['high'])}]"
        )
        false_text = (
            f"{_percentage(false_rejection['estimate'])} "
            f"[{_percentage(false_rejection['low'])}, {_percentage(false_rejection['high'])}]"
        )
        lines.append(
            f"| {name} | {counts['correct_unique']} | {counts['correct_non_unique']} | "
            f"{counts['wrong_unique']} | {counts['wrong_non_unique']} | "
            f"{detection_text} | {false_text} |"
        )
    premise = report["variable_premise"]
    lines.extend(
        [
            "",
            "## Historical arm-level intervals",
            "",
            "| Arm | Correct | SBW | Coverage (95% cluster CI) | Risk (95% cluster CI) |",
            "|---|---:|---:|---:|---:|",
        ]
    )
    for name, result in report["historical_arms"].items():
        counts = result["counts"]
        coverage = result["metrics"]["coverage"]
        risk = result["metrics"]["risk"]
        lines.append(
            f"| {name} | {counts['correct']} | {counts['sbw']} | "
            f"{_percentage(coverage['estimate'])} "
            f"[{_percentage(coverage['low'])}, {_percentage(coverage['high'])}] | "
            f"{_percentage(risk['estimate'])} "
            f"[{_percentage(risk['low'])}, {_percentage(risk['high'])}] |"
        )
    lines.extend(
        [
            "",
            "Bootstrap resampling uses puzzle IDs as clusters, preserving all repeated runs "
            "of a sampled puzzle.",
            "",
            "## Completion-variable premise",
            "",
            f"- Accepted completion constraints: {premise['accepted_completion_constraints']}",
            f"- Constraints introducing a previously unseen integer variable: "
            f"{premise['events_with_previously_unseen_variables']}",
            f"- Such events on scorable records: "
            f"{premise['scorable_events_with_previously_unseen_variables']}",
            "",
            "The current code therefore does not mechanically enforce the theorem's "
            "answer-variable-only premise. This is a low-incidence implementation gap, "
            "not evidence that the premise is unnecessary.",
            "",
        ]
    )
    if report.get("arlsat_pilot"):
        arlsat = report["arlsat_pilot"]
        baseline = arlsat["baseline"]
        gate = arlsat["gate"]
        lines.extend(
            [
                "## AR-LSAT pilot audit",
                "",
                f"- Baseline: {baseline['correct']}/{arlsat['sample_size']} correct; "
                f"{baseline['fallback_count']} answers were random fallbacks "
                f"({baseline['fallback_correct']} correct).",
                f"- Solver-derived baseline subset: {baseline['nonfallback_correct']}/"
                f"{baseline['nonfallback_count']} correct, risk "
                f"{_percentage(baseline['nonfallback_risk'])}.",
                f"- Gate arm: {gate['correct']}/{gate['answered']} answered questions "
                f"correct, risk {_percentage(gate['risk'])}.",
                f"- Identical reconstructed backgrounds: "
                f"{arlsat['exact_background_constraint_multisets']}/"
                f"{arlsat['shared_trace_records']}.",
                "",
                "This fixed-prefix pilot is protocol-confounded and is not an "
                "estimate of a causal gate effect.",
                "",
            ]
        )
    if report.get("component_pairing"):
        lines.extend(
            [
                "## Component-arm pairing audit",
                "",
                "| Comparison | Scorable pairs | Replayed pre-gate matches | Match rate | Snapshot-only matches |",
                "|---|---:|---:|---:|---:|",
            ]
        )
        for name, result in report["component_pairing"].items():
            lines.append(
                f"| {name} | {result['scorable_pairs']} | "
                f"{result['replayed_pre_gate_matches']} | "
                f"{_percentage(result['replayed_match_rate'])} | "
                f"{result['snapshot_only_matches']} |"
            )
        lines.extend(
            [
                "",
                "These runs match configuration labels but do not isolate a component, "
                "because most upstream formalizations differ.",
                "",
            ]
        )
    return "\n".join(lines)


def _write_csv(path: Path, rows: Sequence[dict], fieldnames: Sequence[str]) -> None:
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def write_outputs(report: dict, output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "audit.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (output_dir / "audit.md").write_text(render_markdown(report), encoding="utf-8")

    pairing_rows: list[dict] = []
    for name, result in report["pairing"].items():
        pairing_rows.append(
            {
                "comparison": name,
                "scorable_pairs": result["scorable_pairs"],
                "exact_pre_gate_pairs": result["exact_pre_gate_pairs"],
                "exact_match_rate": result["exact_match_rate"],
                "snapshot_only_pairs": result["snapshot_only_pairs"],
                "exact_subset_sbw_no_gate": result[
                    "exact_subset_no_gate_outcomes"
                ].get("sbw", 0),
                "exact_subset_sbw_sparc": result["exact_subset_sparc_outcomes"].get(
                    "sbw", 0
                ),
            }
        )
    _write_csv(
        output_dir / "pairing_audit.csv",
        pairing_rows,
        (
            "comparison",
            "scorable_pairs",
            "exact_pre_gate_pairs",
            "exact_match_rate",
            "snapshot_only_pairs",
            "exact_subset_sbw_no_gate",
            "exact_subset_sbw_sparc",
        ),
    )

    diagnostic_rows: list[dict] = []
    for name, result in report["gate_diagnostic"].items():
        row = {"system": name, **result["aggregate"]}
        for prefix, metric_name in (
            ("detection", "sbw_detection_rate"),
            ("false_rejection", "correct_output_false_rejection_rate"),
        ):
            metric = result[metric_name]
            row[f"{prefix}_estimate"] = metric["estimate"]
            row[f"{prefix}_ci_low"] = metric["low"]
            row[f"{prefix}_ci_high"] = metric["high"]
            row[f"{prefix}_clusters"] = metric["cluster_count"]
        diagnostic_rows.append(row)
    _write_csv(
        output_dir / "gate_diagnostic.csv",
        diagnostic_rows,
        (
            "system",
            "correct_unique",
            "correct_non_unique",
            "wrong_unique",
            "wrong_non_unique",
            "detection_estimate",
            "detection_ci_low",
            "detection_ci_high",
            "detection_clusters",
            "false_rejection_estimate",
            "false_rejection_ci_low",
            "false_rejection_ci_high",
            "false_rejection_clusters",
        ),
    )

    premise_rows = report["variable_premise"]["events"]
    _write_csv(
        output_dir / "introduced_variables.csv",
        [
            {**row, "introduced_variables": "|".join(row["introduced_variables"])}
            for row in premise_rows
        ],
        (
            "repetition",
            "system",
            "group",
            "puzzle_id",
            "scorable",
            "candidate",
            "introduced_variables",
        ),
    )


def build_report(
    result_dirs: Sequence[Path],
    *,
    bootstrap_replicates: int,
    bootstrap_seed: int,
    arlsat_dir: Path | None = None,
    ablation_dir: Path | None = None,
) -> dict:
    loaded: dict[str, list[TraceRecord]] = {}
    for system in {item for pair in PAIRINGS for item in pair[:2]}:
        loaded[system] = load_records(result_dirs, system)

    pairing: dict[str, dict] = {}
    for no_gate, sparc, display_name in PAIRINGS:
        pairing[f"{display_name} vs {display_name}+SPARC"] = pairing_audit(
            loaded[no_gate], loaded[sparc]
        )

    diagnostic: dict[str, dict] = {}
    for index, (system, display_name) in enumerate(NO_GATE_SYSTEMS):
        diagnostic[display_name] = gate_diagnostic(
            loaded[system],
            bootstrap_replicates=bootstrap_replicates,
            bootstrap_seed=bootstrap_seed + index * 100,
        )

    premise_records = [record for system in SPARC_SYSTEMS for record in loaded[system]]
    historical_arms = {}
    display_names = {
        "baseline": "baseline",
        "basesparc": "baseline+SPARC",
        "nopar": "aggressive",
        "noparsparc": "aggressive+SPARC",
    }
    for index, system in enumerate(("baseline", "basesparc", "nopar", "noparsparc")):
        historical_arms[display_names[system]] = historical_arm_summary(
            loaded[system],
            bootstrap_replicates=bootstrap_replicates,
            bootstrap_seed=bootstrap_seed + 1000 + index * 10,
        )
    component_pairing = None
    if ablation_dir and ablation_dir.is_dir():
        full = load_records([result_dirs[0]], "basesparc")
        component_pairing = {
            "full vs blind": component_pairing_audit(
                full, load_records([ablation_dir], "blind")
            ),
            "full vs no-protection": component_pairing_audit(
                full, load_records([ablation_dir], "noinv")
            ),
        }
    return {
        "schema_version": 1,
        "inputs": [str(path) for path in result_dirs],
        "analysis_scope": "cached trace replay; no LLM calls",
        "bootstrap": {
            "unit": "puzzle_id cluster",
            "replicates": bootstrap_replicates,
            "seed": bootstrap_seed,
            "interval": "percentile 95%",
        },
        "pairing": pairing,
        "gate_diagnostic": diagnostic,
        "historical_arms": historical_arms,
        "variable_premise": variable_premise_audit(premise_records),
        "arlsat_pilot": arlsat_probe_audit(arlsat_dir) if arlsat_dir else None,
        "component_pairing": component_pairing,
    }


def main(argv: Sequence[str] | None = None) -> None:
    args = parse_args(argv)
    result_dirs = tuple(args.result_dirs) or DEFAULT_RESULT_DIRS
    missing = [str(path) for path in result_dirs if not path.is_dir()]
    if missing:
        raise SystemExit(f"Missing result directories: {', '.join(missing)}")
    report = build_report(
        result_dirs,
        bootstrap_replicates=args.bootstrap_replicates,
        bootstrap_seed=args.bootstrap_seed,
        arlsat_dir=args.arlsat_dir,
        ablation_dir=args.ablation_dir,
    )
    write_outputs(report, args.output_dir)
    print(render_markdown(report))
    print(f"Wrote reproducible audit artifacts to {args.output_dir}")


if __name__ == "__main__":
    main()

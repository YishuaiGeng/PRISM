"""Test PRISM solver on a 5x6 puzzle using GPT-4o-mini.

Usage:
    python scripts/test_5x6_puzzle.py

    Or with custom model:
    python scripts/test_5x6_puzzle.py --model gpt-4o-mini
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from prism.core.llm_client import LLMClient
from prism.core.types import PuzzleInstance
from prism.online.guided_solver import GuidedSolver
from prism.paradigm_library.library import ParadigmLibrary

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def load_puzzle_from_jsonl(path: str, puzzle_id: str) -> dict | None:
    """Load a specific puzzle from JSONL file."""
    with open(path) as f:
        for line in f:
            puzzle = json.loads(line)
            if puzzle["id"] == puzzle_id:
                return puzzle
    return None


def puzzle_dict_to_instance(puzzle_dict: dict) -> PuzzleInstance:
    """Convert puzzle dict to PuzzleInstance."""
    return PuzzleInstance(
        puzzle_id=puzzle_dict["id"],
        nl_description=puzzle_dict["puzzle"],
        size=puzzle_dict["size"],
    )


def main():
    parser = argparse.ArgumentParser(description="Test PRISM on 5x6 puzzle with GPT-4o-mini")
    parser.add_argument("--model", default="gpt-4o-mini", help="Model name (default: gpt-4o-mini)")
    parser.add_argument("--library", default=":memory:", help="Paradigm library path")
    parser.add_argument("--no-paradigm", action="store_true", help="Disable paradigm guidance")
    parser.add_argument("--no-memory", action="store_true", help="Disable repair memory")
    parser.add_argument("--puzzle-id", default="lgp-test-5x6-16", help="Puzzle ID to test")
    parser.add_argument("--data-path", default="data/hf/zebralogic/grid_mode_test.jsonl")
    args = parser.parse_args()

    logger.info("=" * 70)
    logger.info("PRISM 5×6 Puzzle Solver Test")
    logger.info("=" * 70)
    logger.info(f"Model: {args.model}")
    logger.info(f"Paradigm: {'Enabled' if not args.no_paradigm else 'Disabled'}")
    logger.info(f"Memory: {'Enabled' if not args.no_memory else 'Disabled'}")

    # Load puzzle
    logger.info(f"\nLoading puzzle: {args.puzzle_id}")
    puzzle_dict = load_puzzle_from_jsonl(args.data_path, args.puzzle_id)
    if not puzzle_dict:
        logger.error(f"Puzzle {args.puzzle_id} not found in {args.data_path}")
        sys.exit(1)

    puzzle = puzzle_dict_to_instance(puzzle_dict)
    logger.info(f"Puzzle size: {puzzle.size}")
    logger.info(f"Puzzle description length: {len(puzzle.nl_description)} chars")
    logger.info(f"\n--- Puzzle Description ---")
    logger.info(puzzle.nl_description[:500] + "..." if len(puzzle.nl_description) > 500 else puzzle.nl_description)

    # Create LLM client
    logger.info(f"\nInitializing LLM client...")
    try:
        llm = LLMClient(model_name=args.model, temperature=0.0)
        logger.info(f"LLM client ready (model: {args.model})")
    except Exception as e:
        logger.error(f"Failed to initialize LLM: {e}")
        logger.error("Make sure API keys are set: OPENAI_API_KEY or equivalent")
        sys.exit(1)

    # Create solver
    logger.info(f"\nInitializing solver...")
    from prism.core.solver import Z3SolverWrapper
    library = ParadigmLibrary(args.library, Z3SolverWrapper())
    solver = GuidedSolver(
        llm_client=llm,
        library=library,
        max_repair_rounds=5,
        enable_paradigm=not args.no_paradigm,
        enable_memory=not args.no_memory,
    )

    # Solve
    logger.info(f"\n--- Starting Solver ---")
    logger.info(f"Max repair rounds: 5")
    logger.info(f"Paradigm guidance: {not args.no_paradigm}")
    logger.info(f"Repair memory: {not args.no_memory}")
    logger.info("")

    try:
        result = solver.solve(puzzle)
    except Exception as e:
        logger.error(f"Solver crashed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

    # Report results
    logger.info(f"\n{'=' * 70}")
    logger.info("RESULTS")
    logger.info(f"{'=' * 70}")
    logger.info(f"Puzzle ID: {result.puzzle_id}")
    logger.info(f"Solved: {result.solved}")
    logger.info(f"Total LLM calls: {result.total_llm_calls}")
    logger.info(f"Repair rounds: {result.repair_rounds}")
    logger.info(f"Paradigm triggered: {result.paradigm_triggered}")
    logger.info(f"Stagnation detected: {result.stagnation_detected}")
    logger.info(f"Final Z3 result: {result.final_z3_result}")

    if result.steps:
        logger.info(f"\nSolve steps:")
        for step in result.steps:
            logger.info(f"  - Iteration {step['iteration']}: {step['action']} → {step['z3_result']}")

    if result.solved:
        logger.info(f"\n🎉 SUCCESS! Puzzle solved in {result.repair_rounds} repair rounds")
        if result.solution:
            logger.info(f"Solution: {result.solution}")
    else:
        logger.error(f"\n❌ FAILED! Could not solve puzzle")
        logger.error(f"Final Z3 result: {result.final_z3_result}")

    logger.info(f"{'=' * 70}\n")


if __name__ == "__main__":
    main()

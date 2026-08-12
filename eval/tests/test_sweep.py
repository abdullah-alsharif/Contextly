"""Unit tests for the Phase 12 sweep driver (eval/sweep.py, docs/roadmap.md Phase 12).

Covers the pure surface of the driver: grid construction, config→env mapping, the
baseline-report non-clobber guard, and report determinism at the render level. The
subprocess harness runs themselves are exercised by `make eval-sweep` / quickstart.md.
"""

from __future__ import annotations

import pathlib
import sys

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import pytest

from eval.run_eval import DEFAULT_REPORT_PATH
from eval.sweep import (
    DEFAULT_CHUNK_SIZE,
    DEFAULT_OVERLAP,
    DEFAULT_TOP_K,
    EvalConfig,
    SweepResult,
    build_grid,
    env_for,
    render_sweep_report,
    validate_out_path,
)


def test_grid_default_row_first_and_count() -> None:
    grid = build_grid()
    assert grid[0].is_default
    expected = {
        (500, 50, 6),
        (300, 50, 6),
        (400, 50, 6),
        (600, 50, 6),
        (700, 50, 6),
        (500, 25, 6),
        (500, 75, 6),
        (500, 50, 4),
        (500, 50, 8),
    }
    assert {(c.chunk_size, c.chunk_overlap, c.top_k) for c in grid} == expected
    assert len(grid) == len(expected)  # no duplicates


def test_grid_respects_custom_center() -> None:
    grid = build_grid(chunk_size=400, overlap=30, top_k=5)
    assert grid[0] == EvalConfig(400, 30, 5, "fake")


def test_env_for_forces_hermetic_provider_and_chunk_bounds() -> None:
    env = env_for(EvalConfig(600, 75, 8))
    assert env["AI_PROVIDER"] == "fake"
    assert env["CHUNK_SIZE_TOKENS"] == "600"
    assert env["CHUNK_OVERLAP_TOKENS"] == "75"
    # The per-config top-K is a CLI flag (--top-k), not env.
    assert "RETRIEVAL_TOP_K" not in env


def test_is_default_marks_only_the_mvp_default() -> None:
    assert EvalConfig(DEFAULT_CHUNK_SIZE, DEFAULT_OVERLAP, DEFAULT_TOP_K).is_default
    assert not EvalConfig(300, DEFAULT_OVERLAP, DEFAULT_TOP_K).is_default
    assert not EvalConfig(DEFAULT_CHUNK_SIZE, 75, DEFAULT_TOP_K).is_default
    assert not EvalConfig(DEFAULT_CHUNK_SIZE, DEFAULT_OVERLAP, 8).is_default


@pytest.mark.parametrize(
    "out_path",
    [
        DEFAULT_REPORT_PATH,
        DEFAULT_REPORT_PATH.parent / "rag-eval.md",
        pathlib.Path("./eval/reports/rag-eval.md"),
    ],
)
def test_validate_out_path_rejects_baseline_report(out_path: pathlib.Path) -> None:
    with pytest.raises(SystemExit):
        validate_out_path(out_path)


def test_validate_out_path_allows_sweep_path(tmp_path: pathlib.Path) -> None:
    sweep = tmp_path / "tuning-sweep.md"
    validate_out_path(sweep)  # must not raise


def test_render_is_deterministic_and_flags_default_row() -> None:
    results = [
        SweepResult(
            config=EvalConfig(DEFAULT_CHUNK_SIZE, DEFAULT_OVERLAP, DEFAULT_TOP_K),
            recall_at_6=1.0,
            mrr=1.0,
            page_recall_at_6=1.0,
            page_mrr=0.956,
            grounding=1.0,
            correctness=0.033,
            gate="PASS",
        ),
        SweepResult(
            config=EvalConfig(300, DEFAULT_OVERLAP, DEFAULT_TOP_K),
            recall_at_6=1.0,
            mrr=0.99,
            page_recall_at_6=0.95,
            page_mrr=0.9,
            grounding=1.0,
            correctness=0.033,
            gate="PASS",
        ),
    ]
    first = render_sweep_report(results, 0.85)
    second = render_sweep_report(results, 0.85)
    assert first == second
    assert "**default**" in first
    assert "chunk=300/overlap=50/top-k=6" in first
    assert "recall@6" in first and "page recall@6" in first
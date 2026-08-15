"""Phase 12 RAG parameter sweep driver (docs/roadmap.md Phase 12, spec FR-001/002).

Runs the committed Phase-10 harness (`eval/run_eval.py`) one-at-a-time across the
parameter axes around the documented MVP defaults (chunk ~500 / overlap ~50 tokens,
top-K 6, docs/rag.md §2), records per-config metrics in `eval/reports/tuning-sweep.md`,
and never touches the committed baseline report (`eval/reports/rag-eval.md` — the
harness itself warns against overwriting it, run_eval.py:553-566).

Grid (research R2): one-at-a-time perturbations of each axis around the default —
  chunk size    500 ± [200, 100]  →  300, 400, 500, 600, 700
  chunk overlap 50 ± [25]         →  25, 50, 75
  top-K         6 ± [2]           →  4, 6, 8

Hermeticity (constitution VI): the driver FORCES `AI_PROVIDER=fake` for retrieval
metrics regardless of the local `.env` (which may point at a real provider), so the
sweep runs offline against `eval/datasets/qa.json`. Real-provider answer-quality runs
are opt-in via `--provider nvidia|openrouter` (spec FR-002, research R7); the
deterministic lexical embeddings under the fake provider keep re-runs byte-identical.

`ef_search` (docs/rag.md §2, backend/app/services/retrieval.py:135-138) is a pgvector
HNSW knob the hermetic harness cannot exercise (exhaustive in-memory ranking) — it is
deliberately NOT swept here; the trade-off is documented in docs/tuning.md (research
R3).

Reproduce:
    PYTHONPATH=backend python3 -m eval.sweep --out eval/reports/tuning-sweep.md
"""

from __future__ import annotations

import argparse
import os
import pathlib
import subprocess
import sys
from dataclasses import dataclass

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
BACKEND_DIR = REPO_ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from eval.run_eval import DEFAULT_REPORT_PATH  # noqa: E402

DEFAULT_SWEEP_PATH = REPO_ROOT / "eval" / "reports" / "tuning-sweep.md"
DEFAULT_CHUNK_SIZE = 500
DEFAULT_OVERLAP = 50
DEFAULT_TOP_K = 6
_HERMETIC_TIMEOUT_SECONDS = 300


@dataclass(frozen=True)
class EvalConfig:
    """One sweep point: chunk size / overlap (tokens) + top-K + provider."""

    chunk_size: int
    chunk_overlap: int
    top_k: int
    provider: str = "fake"

    @property
    def label(self) -> str:
        return (
            f"chunk={self.chunk_size}/overlap={self.chunk_overlap}/"
            f"top-k={self.top_k}"
        )

    @property
    def slug(self) -> str:
        """Filesystem-safe variant of the label (no slashes; used for artifact names)."""
        return f"chunk-{self.chunk_size}-overlap-{self.chunk_overlap}-topk-{self.top_k}"

    @property
    def is_default(self) -> bool:
        return (
            self.chunk_size == DEFAULT_CHUNK_SIZE
            and self.chunk_overlap == DEFAULT_OVERLAP
            and self.top_k == DEFAULT_TOP_K
        )


@dataclass(frozen=True)
class SweepResult:
    """Metrics captured for one EvalConfig (used to render the sweep table)."""

    config: EvalConfig
    recall_at_6: float
    mrr: float
    page_recall_at_6: float
    page_mrr: float
    grounding: float
    correctness: float
    gate: str


def build_grid(
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    overlap: int = DEFAULT_OVERLAP,
    top_k: int = DEFAULT_TOP_K,
) -> list[EvalConfig]:
    """One-at-a-time grid around the defaults (research R2).

    The default config row is always first so the report reads baseline-first.
    """
    grid: list[EvalConfig] = [EvalConfig(chunk_size, overlap, top_k)]
    for size in (300, 400, 600, 700):  # chunk axis, ±200 / ±100
        if size != chunk_size:
            grid.append(EvalConfig(size, overlap, top_k))
    for ov in (25, 75):  # overlap axis, ±25
        if ov != overlap:
            grid.append(EvalConfig(chunk_size, ov, top_k))
    for k in (4, 8):  # top-K axis, ±2
        if k != top_k:
            grid.append(EvalConfig(chunk_size, overlap, k))
    # De-duplicate (a perturbation equal to the default must not double-append).
    seen: set[tuple[int, int, int]] = set()
    out: list[EvalConfig] = []
    for cfg in grid:
        key = (cfg.chunk_size, cfg.chunk_overlap, cfg.top_k)
        if key not in seen:
            seen.add(key)
            out.append(cfg)
    return out


def env_for(config: EvalConfig) -> dict[str, str]:
    """Env overrides passed to the harness for one config.

    Forces hermetic provider + per-config chunk bounds so the local `.env` (which may
    hold real-provider keys or ad-hoc chunk settings) can never leak into the sweep.
    """
    return {
        "AI_PROVIDER": config.provider,
        "CHUNK_SIZE_TOKENS": str(config.chunk_size),
        "CHUNK_OVERLAP_TOKENS": str(config.chunk_overlap),
    }


def run_one(config: EvalConfig, out_dir: pathlib.Path) -> SweepResult:
    """Run the harness (subprocess) for one config and parse the metrics line.

    stdout format (run_eval.py:570-573):
        recall@6=0.000  MRR=0.000  page_recall@6=0.000  page_MRR=0.000  \
        grounding=0.000  correctness=0.000  gate=PASS|FAIL (>=0.85)
    """
    env = {**os.environ, **env_for(config)}
    out_path = out_dir / f"sweep-{config.slug}.md"
    cmd = [
        sys.executable,
        "-m",
        "eval.run_eval",
        "--top-k",
        str(config.top_k),
        "--out",
        str(out_path),
        "--no-gate",  # exit code stays 0; the sweep table carries PASS/FAIL per row
    ]
    proc = subprocess.run(
        cmd,
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=_HERMETIC_TIMEOUT_SECONDS,
        cwd=REPO_ROOT,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"{config.label}: harness failed ({proc.returncode})\n"
            f"{proc.stderr.strip()}"
        )
    metrics: dict[str, float | str] = {}
    _KEYS = ("recall@6", "MRR", "page_recall@6", "page_MRR", "grounding",
             "correctness", "gate")
    for line in proc.stdout.splitlines():
        if line.startswith("recall@6="):
            for token in line.split():
                if "=" not in token:
                    continue  # e.g. the "(>=0.85)" tail of "gate=PASS (>=0.85)"
                key, value = token.split("=", 1)
                if key in _KEYS:
                    metrics[key] = float(value) if key != "gate" else value
    missing = {"recall@6", "MRR", "page_recall@6", "page_MRR", "gate"} - metrics.keys()
    if missing:
        raise RuntimeError(f"{config.label}: metrics line missing {sorted(missing)}")
    gate_text = str(metrics["gate"])
    # The harness prints "gate=PASS|FAIL (>=0.85)" — keep only the token.
    return SweepResult(
        config=config,
        recall_at_6=float(metrics["recall@6"]),
        mrr=float(metrics["MRR"]),
        page_recall_at_6=float(metrics["page_recall@6"]),
        page_mrr=float(metrics["page_MRR"]),
        grounding=float(metrics.get("grounding", 0.0)),
        correctness=float(metrics.get("correctness", 0.0)),
        gate=gate_text.split("(")[0].strip(),
    )


def render_sweep_report(
    results: list[SweepResult], threshold: float
) -> str:
    """Deterministic markdown table of every sweep run (spec FR-001/002)."""
    lines: list[str] = []
    a = lines.append
    a("# Contextly - RAG Parameter Sweep Report (Phase 12)")
    a("")
    a("**Reproduce:** `PYTHONPATH=backend python3 -m eval.sweep "
      "--out eval/reports/tuning-sweep.md` (hermetic; `AI_PROVIDER=fake` forced)")
    a("")
    a("Sweeps the committed Phase-10 dataset (`eval/datasets/qa.json`, 60 queries) "
      "one-at-a-time around the MVP defaults (chunk ~500 / overlap ~50 tokens, "
      "top-K 6, docs/rag.md §2, docs/roadmap.md Phase 12). Retrieval metrics run on "
      "the deterministic lexical embeddings; `ef_search` is a pgvector HNSW knob "
      "invisible to the hermetic harness (see docs/tuning.md).")
    a("")
    a("| Config | recall@6 | MRR | page recall@6 | page MRR | grounding | "
      f"correctness | Gate (>= {threshold:.2f}) |")
    a("|---|---|---|---|---|---|---|---|")
    for r in results:
        flag = "**default**" if r.config.is_default else ""
        a(f"| {r.config.label} {flag} | {r.recall_at_6:.3f} | {r.mrr:.3f} | "
          f"{r.page_recall_at_6:.3f} | {r.page_mrr:.3f} | {r.grounding:.3f} | "
          f"{r.correctness:.3f} | {r.gate} |")
    a("")
    a("_Default row first; one axis perturbed at a time. `correctness` reflects the "
      "generation provider: the fake provider scores ~0 (plumbing only, "
      "docs/testing.md §6). Real-provider answer metrics are opt-in "
      "(`--provider nvidia|openrouter`, research R7)._")
    a("")
    a("## Methodology")
    a("")
    a("- Grid: chunk size 300/400/500/600/700, overlap 25/50/75, top-K 4/6/8, each "
      "axis perturbed around the defaults (research R2).")
    a("- Harness: `eval/run_eval.py` per config with `CHUNK_SIZE_TOKENS` / "
      "`CHUNK_OVERLAP_TOKENS` env overrides and `--top-k` (eval/run_eval.py:164-197, "
      "520-547); per-config reports written alongside this file.")
    a(f"- Gate: both recall@6 variants >= {threshold:.2f} (docs/testing.md §6). The "
      "sweep is measurement-only: it never changes defaults. If a config improves on "
      "the default, the decision to adopt it lives in `docs/tuning.md` (spec FR-003).")
    a("- Hermeticity: `AI_PROVIDER=fake` forced per run (constitution VI); real "
      "embeddings opt-in via `--provider` (research R7).")
    return "\n".join(lines) + "\n"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--out", type=pathlib.Path, default=None,
                        help=f"write the sweep report here (default: "
                             f"{DEFAULT_SWEEP_PATH.name})")
    parser.add_argument("--provider", choices=("fake", "nvidia", "openrouter"),
                        default="fake",
                        help="AI_PROVIDER for the sweep (default fake = hermetic; "
                             "real providers need keys in the environment)")
    parser.add_argument("--threshold", type=float, default=0.85,
                        help="recall@6 gate for the table's PASS/FAIL column")
    parser.add_argument("--max-runs", type=int, default=None,
                        help="cap the number of configs run (default: whole grid)")
    return parser.parse_args()


def validate_out_path(out_path: pathlib.Path) -> None:
    """Refuse to clobber the committed baseline report (spec Edge Cases).

    The sweep report lives at `eval/reports/tuning-sweep.md`; the committed
    Phase-10 baseline (`eval/reports/rag-eval.md`) must only ever be regenerated
    by `make eval` after a deliberate default change (T006).
    """
    if out_path.resolve() == DEFAULT_REPORT_PATH.resolve():
        raise SystemExit(
            "refusing to write the sweep into the committed baseline report path "
            f"({DEFAULT_REPORT_PATH}); use --out (spec Edge Cases, baseline guard)"
        )


def main() -> None:
    args = parse_args()
    out_path = args.out or DEFAULT_SWEEP_PATH
    validate_out_path(out_path)
    if not 0.0 <= args.threshold <= 1.0:
        raise SystemExit("--threshold must be in [0.0, 1.0]")

    grid = build_grid()
    if args.max_runs is not None:
        grid = grid[: max(1, args.max_runs)]
    out_path.parent.mkdir(parents=True, exist_ok=True)

    results: list[SweepResult] = []
    for config in grid:
        print(f"[sweep] {config.label} ({config.provider})", flush=True)
        results.append(run_one(config, out_path.parent))

    report = render_sweep_report(results, args.threshold)
    out_path.write_text(report, encoding="utf-8")
    print(f"[sweep] report: {out_path}")
    print(f"[sweep] configs run: {len(results)}")


if __name__ == "__main__":
    main()

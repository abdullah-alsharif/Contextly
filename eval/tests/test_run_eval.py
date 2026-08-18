"""Phase 10 harness tests: metrics, judge, gate, fixture integrity, determinism.

The fixture-integrity plus regression tests exercise the real seed corpus from
`eval/documents/` and `eval/datasets/qa.json`, so drift anywhere in the eval
(seed text, answer phrases, or the harness itself) fails loudly here —
mirroring the CI gate (recall@6 >= 0.85, docs/roadmap.md Phase 10 DoD,
docs/testing.md §6).
"""

from __future__ import annotations

import argparse
import asyncio

import pytest

from eval.run_eval import ChunkRecord, EvalSummary, _contains_all, rank_query
from eval.embedding import LexicalEmbedder

EVAL_ARGS = argparse.Namespace(threshold=0.85, embedding="auto", top_k=None)


# --- unit-level: metrics + judge built on a tiny synthetic corpus -----------


def _simple_corpus() -> list[ChunkRecord]:
    return [
        ChunkRecord("a-refunds.pdf", 1, 1, 0, "refund window is 30 days"),
        ChunkRecord("a-refunds.pdf", 2, 2, 1, "restocking fee is 15 percent"),
        ChunkRecord("b-shipping.pdf", 1, 1, 0, "ships within 2 business days"),
        ChunkRecord("b-shipping.pdf", 2, 2, 1, "standard delivery 5-7 days"),
        ChunkRecord("c-hr.pdf", 1, 3, 0, "health coverage begins after 90 days"),
    ]


def _query(**overrides):
    base = {
        "query": "what is the refund window in days",
        "expected_document": "a-refunds.pdf",
        "expected_page": 1,
        "answer_contains": ["30 days"],
        "hard_negative_document": "b-shipping.pdf",
    }
    base.update(overrides)
    return base


def test_recall_and_mrr_rankings() -> None:
    corpus = _simple_corpus()
    emb = LexicalEmbedder(dim=4096).fit([c.content for c in corpus])
    vecs = emb.embed([c.content for c in corpus])
    qvec = emb.embed(["what is the refund window in days"])[0]
    result = rank_query(_query(), 0, corpus, vecs, qvec, top_k=3)
    assert result.doc_recall is True
    assert result.doc_rank == 0
    assert result.mrr == 1.0
    assert result.page_recall is True
    assert result.page_rank == 0
    assert result.top_hit is not None
    # Expected doc at rank 0 → nothing can outrank it, incl. the hard negative.
    assert result.hard_negative_before_expected is False


def test_hard_negative_outranked_flag() -> None:
    """A similar-topic trap that beats the expected doc must be flagged (§6)."""
    corpus = _simple_corpus()
    emb = LexicalEmbedder(dim=4096).fit([c.content for c in corpus])
    vecs = emb.embed([c.content for c in corpus])
    # The query lexically targets b-shipping ("delivery ... days") while the
    # expected document is a-refunds — the trap should be flagged.
    qvec = emb.embed(["standard delivery arrives within how many business days"])[0]
    result = rank_query(
        _query(query="standard delivery arrives within how many business days",
               expected_document="a-refunds.pdf",
               expected_page=2,
               hard_negative_document="b-shipping.pdf"),
        0, corpus, vecs, qvec, top_k=3,
    )
    assert result.hard_negative_before_expected is True


def test_missing_expected_document_yields_zero_recall_and_mrr() -> None:
    corpus = _simple_corpus()
    emb = LexicalEmbedder(dim=4096).fit([c.content for c in corpus])
    vecs = emb.embed([c.content for c in corpus])
    qvec = emb.embed(["anything at all"])[0]
    result = rank_query(
        _query(expected_document="z-missing.pdf"), 0, corpus, vecs, qvec, top_k=3
    )
    assert result.doc_recall is False
    assert result.doc_rank is None
    assert result.mrr == 0.0


def test_page_coverage_spans_merged_chunks() -> None:
    corpus = _simple_corpus()
    emb = LexicalEmbedder(dim=4096).fit([c.content for c in corpus])
    vecs = emb.embed([c.content for c in corpus])
    qvec = emb.embed(["health coverage waiting period"])[0]
    # c-hr.pdf chunk spans pages 1-3; pinning page 3 is covered by that chunk.
    result = rank_query(
        _query(query="health coverage waiting period", expected_document="c-hr.pdf",
               expected_page=3),
        0, corpus, vecs, qvec, top_k=3,
    )
    assert result.page_recall is True
    assert result.page_rank == 0


def test_contains_all_normalizes_line_wraps() -> None:
    assert _contains_all("issued within 5\nbusiness days.", ["5 business days"])
    assert _contains_all("COVERAGE BEGINS after 90 Days", ["90 days"])
    assert not _contains_all("issued within 5 business days.", ["30 days"])


def test_gate_property() -> None:
    summary = EvalSummary(
        queries=[], corpus=[], embedding_name="x", provider_name="x", top_k=6,
        threshold=0.85, recall_at_6=0.90, mrr=0.9, page_recall_at_6=1.0,
        page_mrr=1.0, grounding=1.0, correctness=0.0,
    )
    assert summary.gate_pass is True
    summary.recall_at_6 = 0.80
    assert summary.gate_pass is False
    summary.recall_at_6 = 1.0
    # The page-coverage variant carries the discriminating signal on this
    # corpus (spec Edge Cases) — it must gate too, not just the doc variant.
    summary.page_recall_at_6 = 0.50
    assert summary.gate_pass is False


# --- fixture-level: integrity + regression on the seeded corpus -------------


def test_dataset_integrity() -> None:
    """Every answer_contains fact must sit on its expected page (docs/testing.md §6)."""
    from eval.run_eval import load_queries

    queries = load_queries()
    assert 40 <= len(queries) <= 60


def test_full_eval_passes_the_gate() -> None:
    """The committed fixtures must clear recall@6 >= 0.85 (Phase 10 DoD)."""
    from app.core.config import get_settings
    from eval.run_eval import load_corpus, load_queries, run

    settings = get_settings()
    corpus = load_corpus()
    queries = load_queries()
    summary = asyncio.run(run(settings, EVAL_ARGS, corpus, queries))
    assert summary.recall_at_6 >= 0.85
    assert summary.page_recall_at_6 >= 0.85


def test_report_is_deterministic() -> None:
    """Same inputs -> byte-identical report (reproducible with one command)."""
    from app.core.config import get_settings
    from eval.run_eval import load_corpus, load_queries, render_report, run

    settings = get_settings()
    corpus = load_corpus()
    queries = load_queries()

    async def _render() -> str:
        summary = await run(settings, EVAL_ARGS, corpus, queries)
        return render_report(summary, False)

    first = asyncio.run(_render())
    second = asyncio.run(_render())
    assert first == second


def test_dataset_detects_phrasing_drift(tmp_path) -> None:
    """A needle that no longer appears on its page must fail the integrity check."""
    from eval import run_eval as module

    tampered = tmp_path / "qa.json"
    tampered.write_text(module.DATASET_PATH.read_text().replace('"30 days"', '"31 days"', 1))
    original = module.DATASET_PATH
    module.DATASET_PATH = tampered
    try:
        with pytest.raises(SystemExit, match="dataset integrity failures"):
            module.load_queries()
    finally:
        module.DATASET_PATH = original


# --- Phase 13: conversational dataset (referential follow-ups) ---------------


def test_conversational_dataset_integrity() -> None:
    """Conversational entries: >= 10 referential follow-ups, each with history."""
    from eval.run_eval import load_queries

    queries = load_queries("conversational")
    assert len(queries) >= 10
    for item in queries:
        assert "history" in item and "question" in item
        assert any(
            m.get("role") == "user" and m.get("content") for m in item["history"]
        )


def test_conversational_dataset_detects_missing_history(tmp_path) -> None:
    """An entry without user turns must fail the conversational integrity check."""
    from eval import run_eval as module

    tampered = tmp_path / "conversational.json"
    tampered.write_text(
        module.CONVERSATIONAL_DATASET_PATH.read_text().replace(
            '"history"', '"nope"', 1
        )
    )
    original = module.CONVERSATIONAL_DATASET_PATH
    module.CONVERSATIONAL_DATASET_PATH = tampered
    try:
        with pytest.raises(SystemExit, match="dataset integrity failures"):
            module.load_queries("conversational")
    finally:
        module.CONVERSATIONAL_DATASET_PATH = original


def test_conversational_eval_derives_queries_from_history() -> None:
    """The Phase 13 fixtures must clear recall@6 >= 0.85 with the derived query.

    The hermetic derivation concatenates the history's user turns with the
    follow-up (docs/chat.md §4.1), which is what makes referential questions
    retrievable at all (specs/014-chat-multi-turn-context US1).
    """
    from app.core.config import get_settings
    from eval.run_eval import load_corpus, load_queries, run

    args = argparse.Namespace(
        threshold=0.85, embedding="auto", top_k=None, dataset="conversational"
    )
    settings = get_settings()
    corpus = load_corpus()
    queries = load_queries("conversational")
    summary = asyncio.run(run(settings, args, corpus, queries))
    assert summary.dataset == "conversational"
    assert summary.advisory is True
    assert all(r.raw_query for r in summary.queries)
    assert any(r.query != r.raw_query for r in summary.queries)
    assert summary.recall_at_6 >= 0.85
    assert summary.page_recall_at_6 >= 0.85


def test_conversational_report_is_deterministic() -> None:
    """Conversational report renders byte-identically across runs."""
    from app.core.config import get_settings
    from eval.run_eval import load_corpus, load_queries, render_report, run

    args = argparse.Namespace(
        threshold=0.85, embedding="auto", top_k=None, dataset="conversational"
    )
    settings = get_settings()
    corpus = load_corpus()
    queries = load_queries("conversational")

    async def _render() -> str:
        summary = await run(settings, args, corpus, queries)
        return render_report(summary, False)

    first = asyncio.run(_render())
    second = asyncio.run(_render())
    assert first == second
    assert "Phase 13" in first
    assert "advisory" in first

"""Determinism + feature tests for the hermetic lexical embedder (plan D2)."""

from __future__ import annotations

import hashlib
import struct

from eval.embedding import LexicalEmbedder

TEXTS = [
    "All refund requests must be submitted within 30 days of the purchase date.",
    "Standard shipping is delivered in 5-7 business days across the United States.",
    "Medical, dental, and vision coverage begins after 90 days of employment.",
]


def test_embedder_is_deterministic() -> None:
    emb = LexicalEmbedder(dim=4096).fit(TEXTS)
    first = emb.embed(TEXTS)
    emb2 = LexicalEmbedder(dim=4096).fit(TEXTS)
    second = emb2.embed(TEXTS)
    assert len(first) == len(TEXTS)
    for left, right in zip(first, second):
        assert left == right


def test_vectors_are_unit_length() -> None:
    emb = LexicalEmbedder(dim=1024).fit(TEXTS)
    for vector in emb.embed(TEXTS):
        norm = sum(v * v for v in vector) ** 0.5
        assert abs(norm - 1.0) < 1e-9


def test_lexically_similar_text_ranks_above_unrelated() -> None:
    emb = LexicalEmbedder(dim=8192).fit(TEXTS)
    query = "how long is the standard delivery window?"
    qv = emb.embed([query])[0]
    sims = [sum(a * b for a, b in zip(qv, vec)) for vec in emb.embed(TEXTS)]
    # "delivery"/"standard" content overlaps text 2, not the unrelated 1/3.
    assert sims.index(max(sims)) == 1


def test_fit_is_idempotent_by_text_order() -> None:
    emb_a = LexicalEmbedder().fit(TEXTS)
    emb_b = LexicalEmbedder().fit(list(reversed(TEXTS)))
    vec_a = emb_a.embed(TEXTS[0])[0]
    vec_b = emb_b.embed(TEXTS[0])[0]
    # IDF embeds change when the fitted corpus order changes only in doc counts,
    # not order — a corpus with the same documents must give the same vectors.
    assert vec_a == vec_b


def test_corpus_vectors_bit_stable_golden() -> None:
    """Pinned golden hash: corpus vectors must be bit-identical everywhere.

    The embedder uses only IEEE-754 basic arithmetic (frexp + odd-power series
    for the IDF log, correctly-rounded sqrt), so any libm/platform change would
    shift a bit and fail here — the guarantee that reports re-run byte-identical
    on any machine (docs/testing.md §6.1, embedding.py::_log). The golden
    covers the real committed corpus through the product's parse + chunk.
    """
    from eval.run_eval import load_corpus

    corpus = load_corpus()
    emb = LexicalEmbedder(dim=4096).fit([c.content for c in corpus])
    vectors = emb.embed([c.content for c in corpus])
    blob = b"".join(struct.pack(">d", v) for vec in vectors for v in vec)
    assert hashlib.sha256(blob).hexdigest() == (
        "9a96d95196969c5ab102cb5bd64bf7c8c6b6f64d9c6d9ce6150b4e623c2b3ce9"
    )
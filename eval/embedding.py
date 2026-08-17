"""Deterministic lexical embedding for the hermetic eval mode (docs/testing.md §6).

The FakeProvider's embeddings are deliberately content-blind (a SHA-256-seeded
`random.Random`, docs/ai-providers.md §2) — perfect for plumbing tests, useless
for retrieval *quality*. Phase 10 needs deterministic vectors that encode text
overlap, so the eval harness swaps in this hashed word-n-gram TF-IDF embedding
when `AI_PROVIDER=fake` (CI/hermetic default). It is:

- **Deterministic**: sha256-hashed slots, corpus-fixed IDF, L2 normalization —
  same texts, same bits, same vectors, reproducible across runs and machines.
  The IDF log uses only IEEE-754 basic arithmetic (a fixed frexp + series in
  `_log`), so results do not depend on the platform libm; `math.sqrt` is
  correctly rounded per the IEEE spec and the norm uses `math.fsum`
  (correctly rounded summation, identical across Python versions).
  Nothing platform-variable remains.
- **Purely offline**: stdlib only, no model, no network, no keys.
- **Lexically meaningful**: features are lowercased word unigrams + bigrams with
  stopwords dropped and corpus IDF weights, so co-occurring phrases in the
  curated fixtures reliably rank the chunk *covering* the expected page.

This is the hermetic *proxy* for retrieval quality; opt into the real provider
(`AI_PROVIDER=nvidia|openrouter` + keys) to score against true `bge-m3`
embeddings (docs/rag.md §2). See `specs/011-rag-evaluation/plan.md` D2.
"""

from __future__ import annotations

import hashlib
import math
import re
from collections import Counter

_TOKEN_RE = re.compile(r"[a-z0-9]+(?:[.'-][a-z0-9]+)*")

# Natural log of 2 as a source literal: parses to the same double on every
# platform, so _log is bit-identical everywhere (a platform's math.log(2.0)
# is NOT guaranteed to be).
_LN2 = 0.6931471805599453


def _log(x: float) -> float:
    """Natural log via IEEE-arithmetic-only operations (bit-identical everywhere).

    math.log comes from the platform libm and may differ in the last ULP
    across libms — enough to break byte-identical vectors/reports between
    machines. This computes log with frexp (exact) plus the odd-power series
    for ln over [0.5, 1): only IEEE-754 basic operations and a fixed loop, so
    every conforming platform produces the same bits (error < 1e-10 vs the
    true log, irrelevant for IDF weights). math.sqrt stays: it IS correctly
    rounded per IEEE-754.
    """
    mantissa, exponent = math.frexp(x)  # x = mantissa * 2**exponent, exact
    t = (mantissa - 1.0) / (mantissa + 1.0)  # ln(m) = 2*(t + t^3/3 + t^5/5 + ...)
    t2 = t * t
    # Horner in t2 with odd denominators down to the +1 constant term.
    series = 0.0
    for denom in range(17, 0, -2):
        series = series * t2 + 1.0 / denom
    ln_mantissa = 2.0 * t * series
    return exponent * _LN2 + ln_mantissa

# Function words carry no topical signal and would otherwise dominate the
# hashed embedding with their high corpora frequency.
_STOPWORDS = frozenset(
    """
    a an and are as at be by for from has have how i if in into is it its me my
    not of on or our so that the their them then they this to was we what when
    which who will with you your can do get does got did been being about out
    more most some there here where why because but or only just also than each
    other any all both no yes too very per such within without those these
    """.split()
)


def _tokens(text: str) -> list[str]:
    collapsed = " ".join(text.lower().split())
    return [
        token
        for token in _TOKEN_RE.findall(collapsed)
        if token not in _STOPWORDS
    ]


def features(text: str) -> Counter[str]:
    """Word unigrams + adjacent bigrams (post-stopword), counted."""
    words = _tokens(text)
    counts: Counter[str] = Counter(words)
    for left, right in zip(words, words[1:]):
        counts[f"{left} {right}"] += 1
    return counts


class LexicalEmbedder:
    """Corpus-fitted hashed word-n-gram TF-IDF embeddings (eval hermetic mode)."""

    embedding_model = "lexical-hashed-bigrams"

    def __init__(self, dim: int = 4096):
        if dim <= 0:
            raise ValueError("dim must be positive")
        self.dim = dim
        self._idf: dict[str, float] = {}
        self._fallback_weight = 1.0

    def fit(self, texts: list[str]) -> "LexicalEmbedder":
        """Compute IDF over the corpus's document/feature frequencies."""
        df: Counter[str] = Counter()
        for text in texts:
            for feature in set(features(text)):
                df[feature] += 1
        doc_count = len(texts)
        self._idf = {
            feature: _log(1.0 + doc_count / (1.0 + count)) + 1.0
            for feature, count in df.items()
        }
        self._fallback_weight = 1.0
        return self

    def _vector(self, text: str) -> list[float]:
        vec = [0.0] * self.dim
        for feature, count in features(text).items():
            weight = self._idf.get(feature, self._fallback_weight)
            slot = int(hashlib.sha256(feature.encode("utf-8")).hexdigest(), 16) % self.dim
            vec[slot] += weight * count
        norm = math.sqrt(math.fsum(value * value for value in vec))
        if norm > 0:
            vec = [value / norm for value in vec]
        return vec

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Embed texts; order preserved."""
        return [self._vector(text) for text in texts]
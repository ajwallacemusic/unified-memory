"""Okapi BM25, the same scoring as `prototype/memcheck/bm25.py` (copied here because `prototype/` is not a
package of `um`). No stemming; a short stop list."""
from __future__ import annotations

import math
import re
from collections import Counter

STOP = set("a an and are as at be by for from has have in is it its of on or that the to was were with which who he his "
           "him not no so do does".split())
_TOK = re.compile(r"[a-z0-9][a-z0-9_@./$-]*[a-z0-9]|[a-z0-9]")


def tokenize(text: str) -> list[str]:
    return [t for t in _TOK.findall(text.lower()) if t not in STOP]


class BM25:
    def __init__(self, docs: list[str], k1: float = 1.2, b: float = 0.75):
        self.toks = [tokenize(d) for d in docs]
        self.tf = [Counter(t) for t in self.toks]
        self.n = len(docs)
        self.avgdl = sum(len(t) for t in self.toks) / max(self.n, 1) or 1.0
        df = Counter(w for t in self.toks for w in set(t))
        self.idf = {w: math.log(1 + (self.n - c + 0.5) / (c + 0.5)) for w, c in df.items()}
        self.k1, self.b = k1, b

    def scores(self, query: str) -> list[float]:
        q = tokenize(query)
        out = []
        for tf, toks in zip(self.tf, self.toks):
            norm = self.k1 * (1 - self.b + self.b * len(toks) / self.avgdl)
            out.append(sum(self.idf.get(w, 0.0) * tf[w] * (self.k1 + 1) / (tf[w] + norm) for w in q if w in tf))
        return out

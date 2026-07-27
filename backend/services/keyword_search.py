"""Hand-rolled BM25 keyword search — no external dependency.

Standard Okapi BM25 (k1=1.5, b=0.75). Scores every document in the index on
each query, appropriate at the current repo scale (a few hundred chunks);
would need a real inverted index or a search engine for much larger repos.
"""

import math
import re
from collections import Counter
from dataclasses import dataclass

_WORD_RE = re.compile(r"[A-Za-z0-9]+")
_CAMEL_BOUNDARY_RE = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")

K1 = 1.5
B = 0.75


def tokenize(text: str) -> list[str]:
    """Split on non-alphanumerics (so `create_hcp` -> create/hcp) and camelCase
    boundaries (so `createHcp` -> create/hcp) — code identifiers otherwise
    wouldn't be keyword-searchable by their component words at all."""
    tokens = []
    for raw in _WORD_RE.findall(text):
        for part in _CAMEL_BOUNDARY_RE.split(raw):
            if part:
                tokens.append(part.lower())
    return tokens


@dataclass
class _Document:
    doc_id: str
    length: int
    term_counts: Counter


class BM25Index:
    def __init__(self, documents: list[tuple[str, str]]) -> None:
        """documents: list of (id, text) pairs."""
        self._docs: list[_Document] = [
            _Document(doc_id=doc_id, length=len(tokens), term_counts=Counter(tokens))
            for doc_id, tokens in ((doc_id, tokenize(text)) for doc_id, text in documents)
        ]

        self._n = len(self._docs)
        self._avgdl = (sum(d.length for d in self._docs) / self._n) if self._n else 0.0

        document_frequency: Counter = Counter()
        for doc in self._docs:
            document_frequency.update(doc.term_counts.keys())
        self._idf = {
            term: math.log((self._n - freq + 0.5) / (freq + 0.5) + 1)
            for term, freq in document_frequency.items()
        }

    def search(self, query: str, top_k: int) -> list[tuple[str, float]]:
        if self._n == 0:
            return []

        query_terms = tokenize(query)
        scores: list[tuple[str, float]] = []
        for doc in self._docs:
            score = 0.0
            for term in query_terms:
                freq = doc.term_counts.get(term)
                if not freq:
                    continue
                idf = self._idf.get(term, 0.0)
                length_norm = K1 * (1 - B + B * doc.length / self._avgdl) if self._avgdl else K1
                score += idf * (freq * (K1 + 1)) / (freq + length_norm)
            if score > 0:
                scores.append((doc.doc_id, score))

        scores.sort(key=lambda item: item[1], reverse=True)
        return scores[:top_k]

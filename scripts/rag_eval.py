"""RAG evaluation script.

Runs a question/answer dataset against the active RAG backend and reports
Recall@K, Precision@K, MRR, and citation correctness.

Usage:

    uv run python -m scripts.rag_eval --backend chroma --k 3 --k 5

The dataset is intentionally small (30 questions) so it runs quickly in CI,
but large enough to give a signal about retrieval quality.
"""

from __future__ import annotations

import argparse
import sys

from app.core.config import settings
from app.rag.embeddings import EmbeddingService
from app.rag.retriever import Retriever
from app.rag.pgvector_retriever import PgVectorRetriever


# Each entry: (question, expected_source_keywords, min_relevant_sources)
# expected_source_keywords are substrings that should appear in retrieved
# source ids for the answer to be considered correct.
DATASET: list[tuple[str, list[str], int]] = [
    # CPU runbook
    ("cpu high usage investigation steps", ["cpu", "investigation"], 1),
    ("cpu possible causes high load", ["cpu", "possible-causes"], 1),
    ("cpu recommended actions", ["cpu", "recommended-actions"], 1),
    ("cpu overview symptoms", ["cpu", "overview"], 1),
    ("how to investigate cpu saturation", ["cpu", "investigation"], 1),
    # Disk runbook
    ("disk full investigation", ["disk", "investigation"], 1),
    ("disk possible causes full", ["disk", "possible-causes"], 1),
    ("disk recommended actions", ["disk", "recommended-actions"], 1),
    ("how to free disk space", ["disk", "recommended-actions"], 1),
    # Filesystem runbook
    ("filesystem corruption check", ["filesystem", "investigation"], 1),
    ("filesystem recommended actions", ["filesystem", "recommended-actions"], 1),
    # Memory runbook
    ("memory high usage investigation", ["memory", "investigation"], 1),
    ("memory possible causes oom", ["memory", "possible-causes"], 1),
    ("memory recommended actions", ["memory", "recommended-actions"], 1),
    # Network runbook
    ("network latency investigation", ["network", "investigation"], 1),
    ("network possible causes packet loss", ["network", "possible-causes"], 1),
    ("network recommended actions", ["network", "recommended-actions"], 1),
    # Postgres runbook
    ("postgres slow query investigation", ["postgres", "investigation"], 1),
    ("postgres possible causes locks", ["postgres", "possible-causes"], 1),
    ("postgres recommended actions", ["postgres", "recommended-actions"], 1),
    ("postgres connection pool exhausted", ["postgres", "investigation"], 1),
    # Redis runbook
    ("redis high memory investigation", ["redis", "investigation"], 1),
    ("redis possible causes eviction", ["redis", "possible-causes"], 1),
    ("redis recommended actions", ["redis", "recommended-actions"], 1),
    # General / cross-cutting
    ("database is down investigation steps", ["postgres", "investigation"], 1),
    ("server high cpu what to do", ["cpu", "recommended-actions"], 1),
    ("disk is full how to fix", ["disk", "recommended-actions"], 1),
    ("service slow network latency", ["network", "investigation"], 1),
    ("out of memory error investigation", ["memory", "investigation"], 1),
    ("postgres connection refused", ["postgres", "investigation"], 1),
    ("redis not responding", ["redis", "investigation"], 1),
    ("filesystem read only error", ["filesystem", "investigation"], 1),
    ("critical incident cpu memory disk", ["cpu", "memory", "disk"], 2),
]


def get_retriever(backend: str):
    embedding = EmbeddingService()
    if backend == "pgvector":
        return PgVectorRetriever(embedding)
    return Retriever(embedding)


def evaluate(backend: str, ks: list[int]) -> dict:
    retriever = get_retriever(backend)

    results: dict[str, dict] = {}
    for k in ks:
        results[f"recall@{k}"] = 0.0
        results[f"precision@{k}"] = 0.0
    results["mrr"] = 0.0
    results["citation_correct"] = 0
    results["total_questions"] = len(DATASET)

    for question, expected_keywords, min_relevant in DATASET:
        retrieval = retriever.retrieve(
            question,
            k=max(ks),
            threshold=settings.RAG_THRESHOLD,
            where={"tenant_id": 1},
        )
        sources = retrieval.sources or []

        # Citation correctness: at least one retrieved source contains an
        # expected keyword, and we retrieved at least min_relevant sources.
        matched_keywords = [
            kw
            for kw in expected_keywords
            if any(kw.lower() in s.lower() for s in sources)
        ]
        if matched_keywords and len(sources) >= min_relevant:
            results["citation_correct"] += 1

        # For each K, compute recall and precision
        for k in ks:
            top_k = sources[:k]
            relevant_retrieved = sum(
                1 for s in top_k if any(kw.lower() in s.lower() for kw in expected_keywords)
            )
            results[f"recall@{k}"] += relevant_retrieved / max(len(expected_keywords), 1)
            results[f"precision@{k}"] += relevant_retrieved / max(k, 1)

        # MRR: rank of first relevant source
        for rank, s in enumerate(sources, start=1):
            if any(kw.lower() in s.lower() for kw in expected_keywords):
                results["mrr"] += 1.0 / rank
                break

    # Average over questions
    n = results["total_questions"]
    for k in ks:
        results[f"recall@{k}"] /= n
        results[f"precision@{k}"] /= n
    results["mrr"] /= n
    results["citation_accuracy"] = results["citation_correct"] / n

    return results


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate RAG retrieval quality")
    parser.add_argument(
        "--backend",
        default=settings.RAG_BACKEND,
        choices=["chroma", "pgvector"],
        help="RAG backend to evaluate",
    )
    parser.add_argument(
        "--k",
        type=int,
        action="append",
        default=[3, 5],
        help="K values for Recall@K/Precision@K (can repeat)",
    )
    args = parser.parse_args()

    results = evaluate(args.backend, args.k)

    print(f"\nRAG Evaluation — backend={args.backend}")
    print(f"Questions: {results['total_questions']}")
    print(f"MRR: {results['mrr']:.3f}")
    print(f"Citation accuracy: {results['citation_accuracy']:.3f} "
          f"({results['citation_correct']}/{results['total_questions']})")
    for k in args.k:
        print(f"  Recall@{k}:  {results[f'recall@{k}']:.3f}")
        print(f"  Precision@{k}: {results[f'precision@{k}']:.3f}")
    print()

    # Fail CI if citation accuracy is below 0.7
    if results["citation_accuracy"] < 0.7:
        print("FAIL: citation accuracy below 0.7 threshold", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()

"""Binary chunk relevance metrics; unanswerable queries have separate denominators."""

import math
import statistics


def ranking_metrics(retrieved, relevant, k):
    if not isinstance(k, int) or isinstance(k, bool) or k < 1:
        raise ValueError("k must be a positive integer")
    gold = set(relevant)
    if not gold:
        return dict(recall=None, mrr=None, ndcg=None)
    ranked = list(dict.fromkeys(retrieved))[:k]
    hits = [index for index, item in enumerate(ranked, 1) if item in gold]
    dcg = sum(1 / math.log2(rank + 1) for rank in hits)
    ideal = sum(1 / math.log2(rank + 1) for rank in range(1, min(k, len(gold)) + 1))
    return dict(recall=len(hits) / len(gold), mrr=1 / hits[0] if hits else 0, ndcg=dcg / ideal)


def summarize(rows, k):
    metrics = [ranking_metrics(row["retrieved_ids"], row["gold_ids"], k) for row in rows]
    answerable = [m for m in metrics if m["recall"] is not None]
    negatives = [row for row in rows if not row["gold_ids"]]
    positive_rows = [row for row in rows if row["gold_ids"]]
    latencies = sorted(row["latency_ms"] for row in rows)
    return {
        "count": len(rows), "answerable_count": len(answerable),
        "unanswerable_count": len(negatives),
        **{key: statistics.mean(m[key] for m in answerable) if answerable else None
           for key in ("recall", "mrr", "ndcg")},
        "answerable_empty_rate": (
            sum(not row["retrieved_ids"] for row in positive_rows) / len(positive_rows)
            if positive_rows else None
        ),
        "unanswerable_empty_rate": (
            sum(not row["retrieved_ids"] for row in negatives) / len(negatives)
            if negatives else None
        ),
        "latency_p50_ms": statistics.median(latencies) if latencies else None,
        "latency_p95_ms": latencies[math.ceil(len(latencies) * 0.95) - 1] if latencies else None,
    }

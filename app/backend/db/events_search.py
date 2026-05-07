"""Per-tenant lexical search over the multiparty event ledger using bm25s.

The agent calls `find_customer_clusters(business_id, query)` to retrieve
the top-K customers whose recent events match a free-form query. Results
are pre-clustered by customer_id (one row per candidate customer) so the
agent doesn't have to group ranked hits in its head.

Events with `customer_id IS NULL` (e.g. unprompted vendor messages) form
a synthetic `unattributed` cluster. The agent reads them as candidates
to attribute by content + asking the vendor for confirmation.

Ranker: the `bm25s` package (https://bm25s.github.io). Per-tenant index is
rebuilt lazily on first search after each `bump_tenant`. bm25s' tokenizer
runs over the doc text (actor + direction + content) and returns numpy
arrays of doc indices + scores from `retriever.retrieve(...)`.
"""

from __future__ import annotations

import math
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

import bm25s

from backend.db import events as events_db


@dataclass
class CustomerCluster:
    """Top-K cluster row returned by `find_customer_clusters`.

    Fields are kept narrow so the agent prompt cost stays predictable.
    `recent_events` is the customer's last few turns ordered newest-first;
    `open_task_summaries` lifts running outbound tasks from the cluster's
    most recent activity so the agent can decide whether to amend an
    existing task vs dispatch a new one.
    """

    customer_id: UUID | None
    customer_name: str | None
    score: float
    recent_events: list[dict[str, Any]] = field(default_factory=list)
    open_task_summaries: list[dict[str, Any]] = field(default_factory=list)


_RECENCY_HALFLIFE_DAYS = 14.0
_INDEX_DOC_LIMIT = 5000


@dataclass
class _TenantIndex:
    """In-memory bm25s index for one business.

    The retriever holds the inverted index; `docs[i]` maps bm25s' integer
    hit ids back to the original event row. Versioning is bumped by
    `bump_tenant(business_id)` on every insert; the next search rebuilds.
    """

    version: int
    docs: list[events_db.EventRow]
    retriever: Any  # bm25s.BM25


_versions: dict[UUID, int] = {}
_indexes: dict[UUID, _TenantIndex] = {}
_lock = threading.Lock()


def bump_tenant(business_id: UUID) -> None:
    """Mark this tenant's bm25s cache stale. Called after every event insert."""
    with _lock:
        _versions[business_id] = _versions.get(business_id, 0) + 1


def _doc_text(row: events_db.EventRow) -> str:
    """The text bm25s indexes for one event row.

    Includes structural hints (actor, direction) so queries like 'vendor
    address' rank vendor-side events higher even when the body alone
    doesn't carry the word.
    """
    return f"{row.actor} {row.direction} {row.content}"


def _recency_weight(created_at: datetime) -> float:
    age = (datetime.now(timezone.utc) - created_at).total_seconds()
    days = max(age / 86400.0, 0.0)
    return math.exp(-days * math.log(2) / _RECENCY_HALFLIFE_DAYS)


async def _load_or_build_index(business_id: UUID) -> _TenantIndex | None:
    """Return a fresh-enough index for this tenant or rebuild it.

    Returns None when the tenant has zero events — callers treat that as
    'no clusters'.
    """
    with _lock:
        cached = _indexes.get(business_id)
        version = _versions.get(business_id, 0)
        if cached is not None and cached.version == version:
            return cached

    docs = await events_db.list_recent_for_business(
        business_id, limit=_INDEX_DOC_LIMIT
    )
    if not docs:
        return None

    # No corpus= kwarg: bm25s.retrieve then returns integer doc indices,
    # which we map back to event rows ourselves via `index.docs[i]`.
    corpus_tokens = bm25s.tokenize(
        [_doc_text(d) for d in docs], show_progress=False
    )
    retriever = bm25s.BM25()
    retriever.index(corpus_tokens, show_progress=False)

    index = _TenantIndex(version=version, docs=docs, retriever=retriever)
    with _lock:
        _indexes[business_id] = index
    return index


async def find_customer_clusters(
    business_id: UUID,
    query: str,
    *,
    limit: int = 5,
    per_cluster_events: int = 6,
) -> list[CustomerCluster]:
    """Retrieve top-K customer clusters matching `query`.

    Algorithm:
    1. bm25s scores every recent event in the tenant against the query.
    2. Each event's score is weighted by exponential recency decay.
    3. Hits group by customer_id; each customer's score is the max of its
       hits (max-pool, not sum, so a single great match beats many weak ones).
    4. Top-`limit` customers are expanded with their last `per_cluster_events`
       turns and any open outbound task summaries. Hits with no customer_id
       form a synthetic 'unattributed' cluster (customer_id=None).
    """
    if not query.strip():
        return []

    index = await _load_or_build_index(business_id)
    if index is None:
        return []

    query_tokens = bm25s.tokenize(query, show_progress=False)
    # Pull more candidates than `limit` so post-grouping doesn't starve.
    k = min(len(index.docs), max(limit * 8, 24))
    hit_ids, hit_scores = index.retriever.retrieve(
        query_tokens, k=k, show_progress=False
    )
    # Single-query result is shape (1, k). Flatten.
    if hasattr(hit_ids, "shape") and len(hit_ids.shape) == 2:
        hit_ids = hit_ids[0]
        hit_scores = hit_scores[0]

    by_customer: dict[UUID | None, dict[str, Any]] = {}
    for doc_idx, raw_score in zip(hit_ids, hit_scores):
        idx = int(doc_idx)
        if idx < 0 or idx >= len(index.docs):
            continue
        if float(raw_score) <= 0:
            continue
        row = index.docs[idx]
        weighted = float(raw_score) * _recency_weight(row.created_at)
        bucket = by_customer.setdefault(
            row.customer_id, {"score": 0.0, "top_event": row}
        )
        if weighted > bucket["score"]:
            bucket["score"] = weighted
            bucket["top_event"] = row

    ranked = sorted(by_customer.items(), key=lambda kv: kv[1]["score"], reverse=True)
    clusters = await _expand_clusters(
        business_id, ranked[:limit], per_cluster_events=per_cluster_events
    )
    return clusters


async def _expand_clusters(
    business_id: UUID,
    ranked: list[tuple[UUID | None, dict[str, Any]]],
    *,
    per_cluster_events: int,
) -> list[CustomerCluster]:
    """Pull recent events + open task summaries for each candidate customer.

    Lazy-imports the contacts/outbound_ledger/users helpers so the search
    module stays a leaf — events.py is allowed to depend on connection,
    but pulling in user/contact lookups creates a wider blast radius if
    we tighten import boundaries later.
    """
    from backend.db import db_utils, outbound_ledger  # noqa: PLC0415

    clusters: list[CustomerCluster] = []
    for customer_id, bucket in ranked:
        if customer_id is None:
            top: events_db.EventRow = bucket["top_event"]
            clusters.append(
                CustomerCluster(
                    customer_id=None,
                    customer_name=None,
                    score=bucket["score"],
                    recent_events=[_event_dict(top)],
                    open_task_summaries=[],
                )
            )
            continue

        events = await events_db.list_recent_for_customer(
            business_id, customer_id, limit=per_cluster_events
        )
        user = await db_utils.get_user_by_id(str(customer_id))
        name = (user or {}).get("name") if user else None

        open_tasks = await outbound_ledger.get_pending_for_customer(
            business_id, customer_id
        )
        clusters.append(
            CustomerCluster(
                customer_id=customer_id,
                customer_name=name,
                score=bucket["score"],
                recent_events=[_event_dict(e) for e in events],
                open_task_summaries=[
                    {
                        "task_key": t.task_key,
                        "summary": t.summary,
                        "state": t.state,
                        "contact_role": t.contact_role,
                    }
                    for t in open_tasks
                ],
            )
        )
    return clusters


def _event_dict(row: events_db.EventRow) -> dict[str, Any]:
    return {
        "actor": row.actor,
        "direction": row.direction,
        "content": row.content,
        "task_key": row.task_key,
        "created_at": row.created_at.isoformat(),
    }

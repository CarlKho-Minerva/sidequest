"""Elasticsearch is Sidequest's only datastore: talks, side events and the hybrid search over them.

One index, ``sidequest-items``, holds both kinds of thing (``kind`` is ``talk`` or ``side_event``).
Each document carries a BM25-searchable ``text`` field and a 384-dimensional sentence embedding, so a
query can run as a hybrid: keyword search (title, speakers, tags, abstract) and vector search over the
abstract, fused with reciprocal rank fusion. In words: a talk ranks high when either its words or its
meaning match what the attendee asked for, and highest when both do.

Configuration comes from the environment only:
  ES_URL        default http://localhost:9200
  ES_API_KEY    or ES_USER + ES_PASSWORD (default user "elastic")
  SIDEQUEST_EMBED_MODEL  default sentence-transformers/all-MiniLM-L6-v2

Run ``python -m sidequest.search index`` to (re)build the index from data/*.json, and
``python -m sidequest.search query "edge inference"`` to try a search.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from elasticsearch import Elasticsearch, helpers
from opentelemetry import trace

tracer = trace.get_tracer(__name__)

INDEX = "sidequest-items"
VENUE_TZ = ZoneInfo("America/Denver")
EMBED_DIM = 384
DATA_DIR = Path(__file__).resolve().parent.parent / "data"


def es_client() -> Elasticsearch:
    url = os.environ.get("ES_URL", "http://localhost:9200")
    api_key = os.environ.get("ES_API_KEY")
    if api_key:
        return Elasticsearch(url, api_key=api_key, request_timeout=30)
    user = os.environ.get("ES_USER", "elastic")
    password = os.environ.get("ES_PASSWORD")
    if not password:
        raise RuntimeError("set ES_API_KEY or ES_PASSWORD for Elasticsearch")
    return Elasticsearch(url, basic_auth=(user, password), request_timeout=30)


@lru_cache(maxsize=1)
def embedder():
    """Load the sentence-embedding model once. Small (about 80 MB), runs on CPU."""
    from sentence_transformers import SentenceTransformer

    name = os.environ.get("SIDEQUEST_EMBED_MODEL", "sentence-transformers/all-MiniLM-L6-v2")
    return SentenceTransformer(name, cache_folder=str(Path(__file__).resolve().parent.parent / "models"))


def embed(texts: list[str]) -> list[list[float]]:
    vectors = embedder().encode(texts, normalize_embeddings=True, batch_size=64, show_progress_bar=False)
    return [v.tolist() for v in vectors]


MAPPING: dict[str, Any] = {
    "mappings": {
        "properties": {
            "kind": {"type": "keyword"},
            "title": {"type": "text", "fields": {"raw": {"type": "keyword"}}},
            "text": {"type": "text"},
            "speakers": {"type": "text", "fields": {"raw": {"type": "keyword"}}},
            "track": {"type": "keyword"},
            "tags": {"type": "keyword"},
            "day": {"type": "keyword"},
            "start": {"type": "date"},
            "end": {"type": "date"},
            "room": {"type": "keyword"},
            "venue": {"type": "keyword"},
            "location": {"type": "text"},
            "url": {"type": "keyword"},
            "sold_out": {"type": "boolean"},
            "embedding": {"type": "dense_vector", "dims": EMBED_DIM, "index": True, "similarity": "cosine"},
        }
    }
}


def _talk_doc(t: dict) -> dict:
    return {
        "_id": f"talk-{t['id']}",
        "kind": "talk",
        "title": t["title"],
        "text": t.get("abstract") or "",
        "speakers": t.get("speakers") or [],
        "track": t.get("track") or "",
        "tags": t.get("tags") or [],
        "day": t.get("day") or "",
        "start": t["start"],
        "end": t.get("end") or None,
        "room": t.get("room") or "",
        "venue": t.get("venue") or "",
        "url": t.get("url") or "",
        "sold_out": "SOLD OUT" in t["title"].upper(),
    }


def side_event_day(start_iso: str) -> str:
    """Luma sends UTC; the day name is the venue's local day, in the same form as the talks ("Tuesday November 10")."""
    try:
        dt = datetime.fromisoformat(start_iso.replace("Z", "+00:00"))
    except ValueError:
        return ""
    local = dt.astimezone(VENUE_TZ) if dt.tzinfo else dt
    return f"{local:%A} {local:%B} {local.day}"


def _side_event_doc(e: dict) -> dict:
    location = e.get("location") or ""
    return {
        "_id": f"side-{e['id']}",
        "kind": "side_event",
        "title": e["name"],
        "text": e.get("description") or "",
        "speakers": e.get("hosts") or [],
        "track": "Side event",
        "tags": ["Side event"],
        "day": side_event_day(e["start"]),
        "start": e["start"],
        "end": e.get("end") or None,
        # Side events are off-site by definition, so the planner's travel buffer treats them as a trip.
        "room": f"Off-Site Location | {location}" if location else "Off-Site Location",
        "venue": "Off-Site Location",
        "location": location,
        "url": e.get("url") or "",
        "sold_out": bool(e.get("sold_out")),
    }


def embedding_text(doc: dict) -> str:
    """What the vector represents: title, track and the first part of the abstract."""
    return f"{doc['title']}. {doc.get('track', '')}. {(doc.get('text') or '')[:1200]}"


def build_index(client: Elasticsearch, data_dir: Path = DATA_DIR) -> int:
    talks = json.loads((data_dir / "talks.json").read_text())
    events_path = data_dir / "side_events.json"
    events = json.loads(events_path.read_text()) if events_path.exists() else []
    docs = [_talk_doc(t) for t in talks] + [_side_event_doc(e) for e in events]
    vectors = embed([embedding_text(d) for d in docs])
    for d, v in zip(docs, vectors, strict=True):
        d["embedding"] = v
    with tracer.start_as_current_span("search.index_rebuild") as span:
        span.set_attribute("sidequest.documents", len(docs))
        if client.indices.exists(index=INDEX):
            client.indices.delete(index=INDEX)
        client.indices.create(index=INDEX, **MAPPING)
        actions = ({"_index": INDEX, **d} for d in docs)
        with tracer.start_as_current_span("search.bulk_index") as bulk_span:
            ok, _ = helpers.bulk(client, actions, refresh="wait_for")
            bulk_span.set_attribute("sidequest.documents_indexed", ok)
    return ok


def hybrid_search(
    client: Elasticsearch,
    query: str,
    *,
    k: int = 20,
    kinds: tuple[str, ...] = ("talk", "side_event"),
    day: str | None = None,
    exclude_sold_out: bool = True,
) -> list[dict]:
    """Keyword + vector search fused with reciprocal rank fusion. Returns hits with a ``score`` field."""
    filters: list[dict] = [{"terms": {"kind": list(kinds)}}]
    if day:
        filters.append(
            {
                "bool": {
                    "should": [{"term": {"day": day}}, {"term": {"kind": "side_event"}}],
                    "minimum_should_match": 1,
                }
            }
        )
    if exclude_sold_out:
        filters.append({"term": {"sold_out": False}})
    vector = embed([query])[0]
    keyword = {
        "standard": {
            "query": {
                "bool": {
                    "must": {
                        "multi_match": {
                            "query": query,
                            "fields": ["title^3", "speakers^2", "tags^2", "text"],
                            "type": "best_fields",
                            "fuzziness": "AUTO",
                        }
                    },
                    "filter": filters,
                }
            }
        }
    }
    knn = {
        "knn": {
            "field": "embedding",
            "query_vector": vector,
            "k": k * 2,
            "num_candidates": max(100, k * 10),
            "filter": filters,
        }
    }
    body = {
        "retriever": {"rrf": {"retrievers": [keyword, knn], "rank_window_size": k * 3, "rank_constant": 60}},
        "size": k,
        "_source": {"excludes": ["embedding"]},
    }
    with tracer.start_as_current_span("search.hybrid_search") as span:
        span.set_attribute("sidequest.k", k)
        res = client.search(index=INDEX, **body)
    hits = []
    for h in res["hits"]["hits"]:
        src = h["_source"]
        src["id"] = h["_id"]
        src["score"] = h.get("_score") or 0.0
        hits.append(src)
    return hits


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    client = es_client()
    if argv[:1] == ["index"]:
        n = build_index(client)
        print(f"indexed {n} documents into {INDEX}", file=sys.stderr)
        return 0
    if argv[:1] == ["query"] and len(argv) > 1:
        for h in hybrid_search(client, " ".join(argv[1:]), k=10):
            print(f"{h['kind']:10} {h['start'][:16]} {h['title'][:70]}  [{h['track']}]")
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())

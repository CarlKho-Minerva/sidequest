import json
from types import SimpleNamespace

from sidequest import search


class RecordingSpan:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False

    def set_attribute(self, name, value):
        pass


class RecordingTracer:
    def __init__(self):
        self.span_names = []

    def start_as_current_span(self, name):
        self.span_names.append(name)
        return RecordingSpan()


class SearchClient:
    def __init__(self):
        self.body = None
        self.indices = SimpleNamespace(
            exists=lambda **kwargs: False,
            delete=lambda **kwargs: None,
            create=lambda **kwargs: None,
        )

    def search(self, *, index, **body):
        self.body = body
        return {"hits": {"hits": []}}


def test_day_filter_includes_side_events_and_search_is_traced(monkeypatch):
    client = SearchClient()
    tracer = RecordingTracer()
    monkeypatch.setattr(search, "embed", lambda texts: [[0.0] * search.EMBED_DIM])
    monkeypatch.setattr(search, "tracer", tracer)

    search.hybrid_search(client, "query", day="Tuesday", k=5)

    filters = client.body["retriever"]["rrf"]["retrievers"][0]["standard"]["query"]["bool"]["filter"]
    expected_day_filter = {
        "bool": {
            "should": [{"term": {"day": "Tuesday"}}, {"term": {"kind": "side_event"}}],
            "minimum_should_match": 1,
        }
    }
    assert expected_day_filter in filters
    assert expected_day_filter in client.body["retriever"]["rrf"]["retrievers"][1]["knn"]["filter"]
    assert tracer.span_names == ["search.hybrid_search"]


def test_index_rebuild_and_bulk_index_are_traced(tmp_path, monkeypatch):
    (tmp_path / "talks.json").write_text(
        json.dumps([{"id": "talk-1", "title": "Talk", "start": "2026-11-10T09:00:00"}])
    )
    tracer = RecordingTracer()
    monkeypatch.setattr(search, "tracer", tracer)
    monkeypatch.setattr(search, "embed", lambda texts: [[0.0] * search.EMBED_DIM for _ in texts])
    monkeypatch.setattr(search.helpers, "bulk", lambda client, actions, refresh: (len(list(actions)), []))

    indexed = search.build_index(SearchClient(), data_dir=tmp_path)

    assert indexed == 1
    assert tracer.span_names == ["search.index_rebuild", "search.bulk_index"]

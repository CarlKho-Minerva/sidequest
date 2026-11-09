from sidequest.api import _avoid_terms, _interest_lines, _why

PROFILE = """topics:
- LLM inference on GPUs
- edge AI and wearables
people:
- founders building devtools
avoid:
- service mesh
energy: low
needs:
- breaks between talks
"""


def test_profile_yaml_yields_search_phrases_without_avoid_or_needs():
    assert _interest_lines(PROFILE) == [
        "LLM inference on GPUs",
        "edge AI and wearables",
        "founders building devtools",
    ]
    assert _avoid_terms(PROFILE) == ["service mesh"]


def test_free_text_is_one_phrase():
    assert _interest_lines("Kueue and batch scheduling") == ["Kueue and batch scheduling"]
    assert _avoid_terms("Kueue and batch scheduling") == []


def test_why_names_the_matching_interest_or_falls_back_to_the_track():
    hit = {"title": "GPU sharing for inference", "track": "AI Inference + Agentic", "tags": [], "text": ""}
    assert _why(hit, ["LLM inference on GPUs", "wasm"]) == "Matches your interest in LLM inference on GPUs."
    assert _why({"title": "x", "track": "Observability", "tags": [], "text": ""}, ["wasm"]).startswith(
        "Close in meaning"
    )

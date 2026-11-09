# Sidequest, for every Gitar agent

Sidequest is a conference copilot built solo in one day at the Cloud Native Hackathon (KubeCon NA 2026).
It turns an attendee's interests into one low-overwhelm day plan over the official KubeCon schedule and the
Luma side events. The user it is designed for has ADHD; "fewer things on screen" beats "more features".

Layout: `sidequest/ingest.py` (data), `sidequest/search.py` (Elasticsearch index + hybrid search),
`sidequest/planner.py` (deterministic planner), `sidequest/api.py` (FastAPI), `ui/` (one static page),
`deploy/` (container + Kubernetes), `tests/` (pytest).

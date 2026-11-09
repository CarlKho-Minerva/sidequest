# Sidequest

A conference copilot for brains that cannot hold the whole schedule in their head.

Built solo at the Cloud Native Hackathon, KubeCon + CloudNativeCon North America 2026, Salt Lake City, Monday 9 November 2026. Challenge: make conferences easier.

You tell Sidequest what you care about, in plain words or as the short profile your own AI writes about you. It reads the official KubeCon schedule (600 sessions) and every Luma side event (39), finds your talks with Elasticsearch hybrid search, and returns one low-overwhelm plan for the day: fifteen-minute buffers that stretch when the rooms are far apart, one quiet break per half day, every clash shown with the talk it beat, and a "too much, simplify" button that drops the day to three items. For a side event it can hand the registration to an agent on your own phone, which opens Luma, fills the form and stops with the final button on screen for you to press.

The planner is deliberately deterministic. Same interests, same plan, every time. A plan that changes every time you look at it is itself a cognitive load.

## How it is put together

| Part | File | What it does |
|---|---|---|
| Ingest | `sidequest/ingest.py` | Parses the Linux Foundation schedule page and pages through the Luma calendar feed into `data/*.json`. |
| Search | `sidequest/search.py` | Elasticsearch is the only datastore. One index, BM25 fields plus a 384-dimensional sentence embedding, keyword and vector retrievers fused with reciprocal rank fusion. |
| Planner | `sidequest/planner.py` | Greedy by relevance under a travel-aware buffer, alternatives for every clash, one quiet break per half day, energy cap, simplify to three. No model, randomness or clock chooses a talk or a time. |
| API | `sidequest/api.py` | FastAPI. `/api/plan`, `/api/search`, `/api/prompt`, `/api/phone/*`, `/healthz`. Every request and outbound call is an OpenTelemetry span; the plan carries its own build time. |
| Phone | `sidequest/phone.py` | Client for ARTEMIS (an open-source Android UI agent) over MCP: start the Luma registration on the attendee's own phone, stop before the final button, report status. |
| UI | `ui/index.html` | One phone-first page: Now and Next card, the plan, the simplify button, side events with "Register from my phone". Real-user monitoring through the Dash0 web SDK when configured. |
| Deploy | `Dockerfile`, `deploy/` | Container, kind config, Kubernetes manifests (Elasticsearch + API), Radar connected to the cluster. |

## Run it

```bash
uv venv && uv pip install -e ".[dev]"
python -m sidequest.ingest                 # data/talks.json, data/side_events.json
export ES_URL=http://localhost:9200 ES_PASSWORD=...   # or ES_API_KEY
python -m sidequest.search index           # 639 documents, about 7 seconds
uvicorn sidequest.api:app --port 8080      # then open http://localhost:8080
```

Elasticsearch locally: `curl -fsSL https://elastic.co/start-local | sh -s -- --esonly` (needs Docker).

## Configuration

All credentials come from the environment, never from files in this repository.

| Variable | Purpose |
|---|---|
| `ES_URL`, `ES_API_KEY` or `ES_USER` + `ES_PASSWORD` | Elasticsearch |
| `OTEL_EXPORTER_OTLP_ENDPOINT`, `OTEL_EXPORTER_OTLP_HEADERS` | OpenTelemetry export (Dash0: `https://ingress.<region>.aws.dash0.com`, `Authorization=Bearer <token>,Dash0-Dataset=default`) |
| `DASH0_WEB_TOKEN` | Ingest-only token handed to the browser for real-user monitoring |
| `ARTEMIS_MCP_URL`, `ARTEMIS_DEVICE` | The phone agent's MCP endpoint (default `http://127.0.0.1:8012/mcp`) and an optional ADB serial |
| `SIDEQUEST_DEFAULT_DAY` | Default day to plan (`2026-11-10`) |

## Deploy to Kubernetes

See `deploy/README.md`: a kind cluster, the image loaded into it, one secret, `kubectl apply -k deploy/`, Radar's install command against the same context.

## Tracks

- Elasticsearch, Find the Right Talk: the index is the data layer; hybrid keyword and vector search.
- Sonar, Never Merge Broken: every feature landed through a Gitar-reviewed pull request; review instructions and rules in `.gitar/`; CI failures diagnosed and fixed by Gitar.
- Dash0, Stop Flying Blind: traces, metrics and logs from the API, real-user monitoring from the page, Agent0 used on a real slow query, an SLO on plan latency.
- Radar, AI SRE: runs on Kubernetes with Radar connected; investigations on real issues.
- Merge Forward, Conferences for Everyone: designed around ADHD, from the one-thing-at-a-time card to the simplify button and the phone that fills forms for you.

## Use of AI assistance

I used AI tools to help draft and edit from my own notes; the work and results are my own.

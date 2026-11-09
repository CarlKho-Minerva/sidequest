# Review instructions for Sidequest

- The planner (`sidequest/planner.py`) must stay deterministic: same inputs, same plan. Flag any change that
  lets a language model, randomness or wall-clock time choose a talk or a time. A model may only write the
  one-line "why" text.
- Elasticsearch is the only datastore at runtime. Flag any new file-based or in-memory store that replaces it.
- Every HTTP endpoint and every outbound call (Elasticsearch, the phone agent) must be inside an OpenTelemetry
  span; flag endpoints added without instrumentation.
- Buffer logic (15 minutes, stretched by room distance) and the "simplify to 3" rule need a test in `tests/`
  whenever they change.
- Never log or commit credentials: Elasticsearch password, Dash0 token, Radar token, Gemini key. They come from
  the environment only.
- Prefer plain words in user-facing strings; the user may be overwhelmed. No exclamation marks in the UI.

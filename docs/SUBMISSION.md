# Submission text (Cloud Native Hackathon, KubeCon NA 2026)

Project title: **Sidequest**

Repository: https://github.com/CarlKho-Minerva/sidequest

## Short description

A conference copilot for brains that cannot hold the whole schedule in their head. You tell Sidequest what you care about, in plain words or as the short profile your own AI writes about you. It reads the official KubeCon schedule (600 sessions) and every Luma side event (39), finds your talks with Elasticsearch hybrid search, and returns one low-overwhelm plan for the day: fifteen-minute buffers that stretch when rooms are far apart, one quiet break per half day, every clash shown with the talk it beat, and a "too much, simplify" button that drops the day to three items. For a side event it hands the registration to an agent on your own phone, which opens Luma, fills the form and stops with the final button on screen for you to press. The planner is deliberately deterministic: the same interests give the same plan every time, because a plan that changes every time you look at it is itself a cognitive load.

## Why

Last night I applied to 37 side events and planned my week at 1 AM, with my own agents doing most of the work. I have ADHD. The planning is the part my brain refuses to do, and conferences are built for people who can hold the whole schedule in their head.

## Tracks

**Elasticsearch, Find the Right Talk.** Elasticsearch is the only datastore: talks, side events and the attendee's interests all go through one index with BM25 fields and a 384-dimensional sentence embedding. Each interest phrase runs as a hybrid query (keyword plus vector) fused with reciprocal rank fusion, on the server where the licence allows it and in code where it does not. Day, kind and sold-out filters are applied inside both retrievers.

**Sonar, Never Merge Broken.** Every feature landed through a pull request Gitar reviewed (ingest; search and planner; API, UI, telemetry, phone and deploy; follow-ups). `.gitar/review/sidequest.md` holds the project's review instructions, `.gitar/rules/` two checks (planner changes need tests; no credential literals). Gitar's findings were taken on every PR, it diagnosed a real CI lint failure, and on PR 2 it pushed its own fix commit for three regressions it found.

**Dash0, Stop Flying Blind.** The API emits traces for every request and outbound call, logs correlated to spans, and three product metrics (plan build time, plan size, search hits). The page sends real-user monitoring through the Dash0 web SDK with an ingest-only token. Agent0 caught a real gap during the day: the plan route had exported nothing because the first runs used a wrong token. The plan response itself shows its build time, so observability is in the product, not bolted on.

**Radar, AI SRE.** Sidequest runs on a kind cluster with Radar connected. Radar surfaced that the metrics API was missing (fixed by installing metrics-server), and its AI investigation on the API pod found the real root cause of failing plans: Elasticsearch's Basic licence refusing reciprocal rank fusion, plus the init container's retries while Elasticsearch started. Both were fixed the same hour.

**Merge Forward, Conferences for Everyone.** Designed around ADHD from the first screen: one "next thing" card, buffers and breaks as first-class items, a simplify button, and a phone that fills the registration form so the attendee only has to press one button. No exclamation marks anywhere in the UI.

## Demo

Live on a phone: interests in, plan out, simplify, then the phone registers itself for a side event and stops before the final button.

## Use of AI assistance

I used AI tools to help draft and edit from my own notes; the work and results are my own.

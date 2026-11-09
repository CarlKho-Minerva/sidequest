"""Fetch the two schedules Sidequest plans over and write them as plain JSON.

Two sources, no login needed for either:

1. The official KubeCon + CloudNativeCon North America 2026 schedule. The Linux Foundation renders
   it (from Sessionize) into one HTML page: a ``section.slot`` per start time, a ``.sess-wrap`` per
   session with the title, room, speakers and tags visible, and a hidden ``.sess__seo`` block with
   the exact start and end time and the abstract.
2. The KubeCon side-event calendar on Luma, a JSON feed.

Run: ``python -m sidequest.ingest`` writes ``data/talks.json`` and ``data/side_events.json``.
``--schedule-html <file>`` parses a saved copy instead of fetching (the page is 3.6 MB).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

import httpx
from bs4 import BeautifulSoup

SCHEDULE_URL = (
    "https://events.linuxfoundation.org/kubecon-cloudnativecon-north-america/program/schedule/"
)
LUMA_FEED_URL = (
    "https://api.lu.ma/calendar/get-items?calendar_api_id=cal-trgXrvZoNlgsdyT"
    "&period=future&pagination_limit=100"
)
DATA_DIR = Path(__file__).resolve().parent.parent / "data"
USER_AGENT = "Sidequest/0.1 (KubeCon NA 2026 hackathon; +https://github.com/CarlKho-Minerva/sidequest)"


@dataclass
class Talk:
    id: str
    title: str
    start: str  # ISO 8601, venue local time (America/Denver), no offset in the source
    end: str
    day: str  # "Tuesday November 10"
    room: str
    venue: str  # "Salt Palace" / "Hyatt Regency" / "Off-Site Location" / ""
    speakers: list[str]
    track: str  # the primary tag, e.g. "AI + ML"
    tags: list[str]
    abstract: str
    url: str
    kind: str = "talk"


@dataclass
class SideEvent:
    id: str
    name: str
    start: str  # ISO 8601 with offset, from Luma
    end: str | None
    url: str
    description: str
    location: str
    hosts: list[str] = field(default_factory=list)
    sold_out: bool = False
    cover_url: str | None = None
    kind: str = "side_event"


def _text(node) -> str:
    return re.sub(r"\s+", " ", node.get_text(" ", strip=True)) if node else ""


def parse_schedule(html: str) -> list[Talk]:
    """Walk the page in document order so every session knows its day."""
    soup = BeautifulSoup(html, "html.parser")
    talks: list[Talk] = []
    day = ""
    for node in soup.find_all(["div", "section"]):
        classes = node.get("class") or []
        if "day-divider__title" in classes:
            day = _text(node)
            continue
        if "sess-wrap" not in classes:
            continue
        link = node.find("a", class_="sess-link")
        if link is None:
            continue
        sid = link.get("data-session-id") or ""
        title = _text(node.find(class_="sess__title"))
        room = _text(node.find(class_="sess__room"))
        speakers_text = _text(node.find(class_="sess__speakers"))
        speakers = [s.strip() for s in re.split(r",|\band\b", speakers_text) if s.strip()]
        tags = [_text(t) for t in node.select(".sess__tags .tag")]
        primary = node.select_one(".sess__tags .tag--primary")
        times = node.select(".sess__seotime time")
        start = times[0].get("datetime", "") if times else ""
        end = times[1].get("datetime", "") if len(times) > 1 else ""
        desc = node.select_one(".sess__seodesc")
        abstract = _text(desc)
        venue = room.split("|")[0].strip() if "|" in room else ("Off-Site Location" if "Off-Site" in room else "")
        if not title or not start:
            continue
        talks.append(
            Talk(
                id=sid or f"t{len(talks)}",
                title=title,
                start=start,
                end=end,
                day=day,
                room=room,
                venue=venue,
                speakers=speakers,
                track=_text(primary),
                tags=tags,
                abstract=abstract,
                url=link.get("href", ""),
            )
        )
    return talks


def fetch_schedule(client: httpx.Client) -> str:
    r = client.get(SCHEDULE_URL, headers={"User-Agent": USER_AGENT}, timeout=60, follow_redirects=True)
    r.raise_for_status()
    return r.text


def fetch_side_events(client: httpx.Client) -> list[SideEvent]:
    r = client.get(LUMA_FEED_URL, headers={"User-Agent": USER_AGENT}, timeout=30)
    r.raise_for_status()
    payload = r.json()
    if "entries" not in payload:
        # Luma answers {"message": "You've exceeded our rate limit..."} when polled too often.
        raise RuntimeError(f"Luma feed had no entries: {str(payload)[:200]}")
    events: list[SideEvent] = []
    for entry in payload["entries"]:
        e = entry["event"]
        geo = e.get("geo_address_info") or {}
        location = ", ".join(
            x for x in [geo.get("address"), geo.get("city_state")] if x
        ) or (geo.get("full_address") or "")
        ticket = entry.get("ticket_info") or {}
        hosts = [h.get("name", "") for h in (entry.get("hosts") or []) if h.get("name")]
        events.append(
            SideEvent(
                id=e.get("api_id", ""),
                name=e.get("name", ""),
                start=e.get("start_at", ""),
                end=e.get("end_at"),
                url=f"https://lu.ma/{e.get('url', '')}",
                description=(entry.get("description_mirror") or {}).get("text", "")
                or e.get("description", "")
                or "",
                location=location,
                hosts=hosts,
                sold_out=bool(ticket.get("is_sold_out")),
                cover_url=e.get("cover_url"),
            )
        )
    return events


def write_json(path: Path, rows: list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps([asdict(r) for r in rows], indent=1, ensure_ascii=False))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--schedule-html", type=Path, help="parse a saved copy of the schedule page")
    ap.add_argument("--skip-luma", action="store_true")
    ap.add_argument("--out", type=Path, default=DATA_DIR)
    args = ap.parse_args(argv)

    with httpx.Client() as client:
        html = args.schedule_html.read_text(encoding="utf-8", errors="ignore") if args.schedule_html else fetch_schedule(client)
        talks = parse_schedule(html)
        write_json(args.out / "talks.json", talks)
        days = sorted({t.day for t in talks})
        print(f"talks: {len(talks)} across {len(days)} days ({', '.join(days)})", file=sys.stderr)
        if not args.skip_luma:
            events = fetch_side_events(client)
            write_json(args.out / "side_events.json", events)
            print(f"side events: {len(events)}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

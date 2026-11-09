"""The deterministic planner: candidates in, one low-overwhelm day out.

Why deterministic: a plan that changes every time you look at it is itself a cognitive load. Given the same
ranked candidates and the same settings, this module returns the same plan, byte for byte. No model, no
randomness and no wall clock take part in choosing a talk or a time. Ties break on start time, then id.

Rules (each one has a test in tests/test_planner.py):
1. Greedy by relevance: walk candidates from best to worst score, keep a talk when it fits.
2. A talk fits when it does not overlap any kept talk once a buffer is added between them. The buffer is
   15 minutes, stretched by how far apart the two rooms are: same building and level adds nothing, a
   different level adds 5, a different building adds 10, anything off-site adds 20, and side events add 10.
3. A rejected talk that overlapped a kept one is remembered as that talk's alternative, so a clash is
   shown with its other option instead of silently disappearing.
4. One quiet break per half day (before and after 12:30): the longest free gap of at least 30 minutes
   is marked as a break; if no such gap exists, the lowest-scored talk in that half is dropped to make one.
5. Simplify: keep only the three highest-scored talks, in time order. Everything else above still holds.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

BASE_BUFFER_MIN = 15
VENUE_TZ = ZoneInfo("America/Denver")
MIN_BREAK_MIN = 30
MIDDAY = (12, 30)


@dataclass(frozen=True)
class Candidate:
    id: str
    title: str
    start: datetime
    end: datetime
    room: str
    score: float
    kind: str = "talk"
    track: str = ""
    url: str = ""
    speakers: tuple[str, ...] = ()

    @property
    def venue(self) -> str:
        return (
            self.room.split("|")[0].strip()
            if "|" in self.room
            else ("Off-Site" if "Off-Site" in self.room else self.room)
        )

    @property
    def level(self) -> str:
        parts = [p.strip() for p in self.room.split("|")]
        return parts[1] if len(parts) > 1 else ""


@dataclass
class PlanItem:
    type: str  # "talk" | "break"
    start: datetime
    end: datetime
    title: str
    id: str = ""
    room: str = ""
    track: str = ""
    url: str = ""
    score: float = 0.0
    speakers: tuple[str, ...] = ()
    alternatives: list[dict] = field(default_factory=list)
    why: str = ""

    def as_dict(self) -> dict:
        d = {
            "type": self.type,
            "start": self.start.isoformat(),
            "end": self.end.isoformat(),
            "title": self.title,
            "id": self.id,
            "room": self.room,
            "track": self.track,
            "url": self.url,
            "score": round(self.score, 4),
            "speakers": list(self.speakers),
            "alternatives": self.alternatives,
            "why": self.why,
        }
        return d


@dataclass
class Plan:
    items: list[PlanItem]
    considered: int
    dropped_for_break: list[str]

    @property
    def talks(self) -> list[PlanItem]:
        return [i for i in self.items if i.type == "talk"]

    def as_dict(self) -> dict:
        return {
            "items": [i.as_dict() for i in self.items],
            "stats": {
                "considered": self.considered,
                "chosen": len(self.talks),
                "clashes": sum(len(i.alternatives) for i in self.talks),
                "dropped_for_break": self.dropped_for_break,
            },
        }


def travel_minutes(a: Candidate, b: Candidate) -> int:
    """Extra minutes needed to travel between items. Side events add 10; off-site talks add 20."""
    if a.kind == "side_event" or b.kind == "side_event":
        return 10
    if "Off-Site" in a.venue or "Off-Site" in b.venue:
        return 20
    if a.venue != b.venue:
        return 10
    if a.level != b.level:
        return 5
    return 0


def required_gap(a: Candidate, b: Candidate) -> timedelta:
    return timedelta(minutes=BASE_BUFFER_MIN + travel_minutes(a, b))


def fits(new: Candidate, kept: list[Candidate]) -> Candidate | None:
    """Return the kept candidate that blocks ``new``, or None when it fits."""
    for k in kept:
        first, second = (k, new) if k.start <= new.start else (new, k)
        if second.start < first.end + required_gap(first, second):
            return k
    return None


def _sort_key(c: Candidate):
    return (-c.score, c.start, c.id)


def choose(
    candidates: list[Candidate], *, max_items: int | None = None
) -> tuple[list[Candidate], dict[str, list[Candidate]]]:
    kept: list[Candidate] = []
    alternatives: dict[str, list[Candidate]] = {}
    for c in sorted(candidates, key=_sort_key):
        if max_items is not None and len(kept) >= max_items:
            blocker = fits(c, kept)
            if blocker is not None:
                alternatives.setdefault(blocker.id, []).append(c)
            continue
        blocker = fits(c, kept)
        if blocker is None:
            kept.append(c)
        else:
            alternatives.setdefault(blocker.id, []).append(c)
    kept.sort(key=lambda c: (c.start, c.id))
    return kept, alternatives


def _longest_gap(
    kept: list[Candidate], window: tuple[datetime, datetime]
) -> tuple[datetime, datetime] | None:
    """Longest free stretch inside the window, at least MIN_BREAK_MIN long, else None."""
    points = (
        [window[0]] + [t for c in kept for t in (c.start, c.end) if window[0] <= t <= window[1]] + [window[1]]
    )
    busy = [(c.start, c.end) for c in kept]
    best: tuple[datetime, datetime] | None = None
    points = sorted(set(points))
    for a, b in itertools.pairwise(points):
        mid = a + (b - a) / 2
        if any(s <= mid < e for s, e in busy):
            continue
        if b - a >= timedelta(minutes=MIN_BREAK_MIN) and (best is None or (b - a) > (best[1] - best[0])):
            best = (a, b)
    return best


ENERGY_CAP = {"low": 5, "normal": 8, "high": None}


def plan_day(
    candidates: list[Candidate],
    *,
    day: datetime,
    quiet_break: bool = True,
    simplify: bool = False,
    energy: str = "normal",
    day_start: tuple[int, int] = (9, 0),
    day_end: tuple[int, int] = (18, 0),
) -> Plan:
    """Build the plan for one day. ``day`` is any datetime on that day; only its date is used.

    ``energy`` caps how many talks a day may hold (low 5, normal 8, high unlimited); simplify caps at 3."""
    day0 = day.replace(hour=0, minute=0, second=0, microsecond=0)
    todays = [c for c in candidates if c.start.date() == day0.date()]
    cap = 3 if simplify else ENERGY_CAP.get(energy, ENERGY_CAP["normal"])
    kept, alternatives = choose(todays, max_items=cap)
    dropped: list[str] = []

    items: list[PlanItem] = []
    if quiet_break and not simplify:
        start = day0.replace(hour=day_start[0], minute=day_start[1])
        midday = day0.replace(hour=MIDDAY[0], minute=MIDDAY[1])
        end = day0.replace(hour=day_end[0], minute=day_end[1])
        for window in [(start, midday), (midday, end)]:
            gap = _longest_gap(kept, window)
            if gap is None:
                in_half = [c for c in kept if c.start < window[1] and c.end > window[0]]
                if in_half:
                    victim = min(in_half, key=lambda c: (c.score, c.start, c.id))
                    kept.remove(victim)
                    dropped.append(victim.id)
                    gap = _longest_gap(kept, window)
            if gap is not None:
                b_start = gap[0] + timedelta(minutes=5) if gap[0] != window[0] else gap[0]
                b_end = min(gap[1], b_start + timedelta(minutes=30))
                items.append(
                    PlanItem(
                        type="break",
                        start=b_start,
                        end=b_end,
                        title="Quiet break",
                        why="A gap kept on purpose.",
                    )
                )

    for c in kept:
        alts = sorted(alternatives.get(c.id, []), key=_sort_key)[:2]
        items.append(
            PlanItem(
                type="talk",
                start=c.start,
                end=c.end,
                title=c.title,
                id=c.id,
                room=c.room,
                track=c.track,
                url=c.url,
                score=c.score,
                speakers=c.speakers,
                alternatives=[
                    {
                        "id": a.id,
                        "title": a.title,
                        "start": a.start.isoformat(),
                        "end": a.end.isoformat(),
                        "room": a.room,
                    }
                    for a in alts
                ],
            )
        )
    items.sort(key=lambda i: (i.start, i.type, i.id))
    return Plan(items=items, considered=len(todays), dropped_for_break=dropped)


def _local(value: str) -> datetime:
    dt = datetime.fromisoformat(value)
    return dt.astimezone(VENUE_TZ).replace(tzinfo=None) if dt.tzinfo else dt


def candidate_from_hit(hit: dict) -> Candidate | None:
    """Turn an Elasticsearch hit (see search.py) into a Candidate. Items without an end get 30 minutes."""
    if not hit.get("start"):
        return None
    start = _local(hit["start"])
    end = _local(hit["end"]) if hit.get("end") else start + timedelta(minutes=30)
    return Candidate(
        id=hit["id"],
        title=hit["title"],
        start=start,
        end=end,
        room=hit.get("room") or hit.get("location") or "",
        score=float(hit.get("score") or 0.0),
        kind=hit.get("kind", "talk"),
        track=hit.get("track") or "",
        url=hit.get("url") or "",
        speakers=tuple(hit.get("speakers") or []),
    )

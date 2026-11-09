from datetime import datetime

from sidequest.planner import (
    Candidate,
    candidate_from_hit,
    choose,
    fits,
    plan_day,
    required_gap,
    travel_minutes,
)

DAY = datetime(2026, 11, 10)


def talk(id, h, m, dur, room="Salt Palace | Level 2 | 250", score=1.0, title=None):
    start = DAY.replace(hour=h, minute=m)
    return Candidate(id=id, title=title or f"Talk {id}", start=start, end=start.replace(minute=0) + (start - start.replace(minute=0)) + __import__("datetime").timedelta(minutes=dur), room=room, score=score)


def test_buffer_stretches_with_distance():
    a = talk("a", 9, 0, 30)
    assert travel_minutes(a, talk("b", 10, 0, 30)) == 0
    assert travel_minutes(a, talk("c", 10, 0, 30, room="Salt Palace | Level 1 | Hall D")) == 5
    assert travel_minutes(a, talk("d", 10, 0, 30, room="Hyatt Regency | Level 4 | Regency Ballroom")) == 10
    assert travel_minutes(a, talk("e", 10, 0, 30, room="Off-Site Location")) == 20
    side_event = Candidate(
        id="side-event",
        title="Side event",
        start=DAY.replace(hour=10),
        end=DAY.replace(hour=10, minute=30),
        room="Off-Site Location",
        score=1.0,
        kind="side_event",
    )
    assert travel_minutes(a, side_event) == 10
    assert required_gap(a, side_event).seconds == 25 * 60
    assert required_gap(a, talk("d", 10, 0, 30, room="Hyatt Regency | Level 4 | X")).seconds == 25 * 60


def test_candidate_from_hit_converts_aware_times_to_venue_timezone():
    candidate = candidate_from_hit(
        {
            "id": "side-event",
            "title": "Side event",
            "start": "2026-11-10T16:00:00Z",
            "end": "2026-11-10T17:30:00+00:00",
        }
    )

    assert candidate is not None
    assert candidate.start == datetime(2026, 11, 10, 9, 0)
    assert candidate.end == datetime(2026, 11, 10, 10, 30)


def test_fits_respects_the_buffer():
    a = talk("a", 9, 0, 30)  # ends 9:30, needs 15 min before the next one in the same room
    assert fits(talk("b", 9, 44, 30), [a]) is a
    assert fits(talk("c", 9, 45, 30), [a]) is None


def test_choose_is_greedy_by_score_and_records_alternatives():
    best = talk("best", 10, 0, 30, score=0.9)
    clash = talk("clash", 10, 10, 30, score=0.5)
    later = talk("later", 11, 0, 30, score=0.7)
    kept, alts = choose([clash, later, best])
    assert [c.id for c in kept] == ["best", "later"]
    assert [c.id for c in alts["best"]] == ["clash"]


def test_choose_is_deterministic_on_ties():
    a = talk("a", 10, 0, 30, score=0.5)
    b = talk("b", 10, 0, 30, score=0.5)
    kept1, _ = choose([a, b])
    kept2, _ = choose([b, a])
    assert [c.id for c in kept1] == [c.id for c in kept2] == ["a"]


def test_plan_day_adds_one_break_per_half_day():
    cands = [talk("a", 9, 0, 30, score=0.9), talk("b", 10, 30, 30, score=0.8), talk("c", 14, 0, 30, score=0.7), talk("d", 16, 0, 30, score=0.6)]
    plan = plan_day(cands, day=DAY)
    breaks = [i for i in plan.items if i.type == "break"]
    assert len(breaks) == 2
    assert breaks[0].start < DAY.replace(hour=12, minute=30) <= breaks[1].start
    assert [i.id for i in plan.talks] == ["a", "b", "c", "d"]
    assert plan.dropped_for_break == []


def test_plan_day_drops_the_weakest_talk_when_a_half_has_no_gap():
    # Back to back from 9:00 to 12:30 in the same room with exactly 15-minute gaps: no 30-minute gap exists.
    cands = [talk("before", 8, 0, 30, score=0.01)] + [
        talk(f"m{i}", 9 + (i * 45) // 60, (i * 45) % 60, 30, score=1.0 - i * 0.1) for i in range(5)
    ]
    plan = plan_day(cands, day=DAY)
    assert plan.dropped_for_break == ["m4"]
    assert "before" in [item.id for item in plan.talks]
    assert any(i.type == "break" and i.start < DAY.replace(hour=12, minute=30) for i in plan.items)


def test_simplify_keeps_three_in_time_order():
    cands = [talk(str(i), 9 + i, 0, 30, score=i / 10) for i in range(1, 8)]
    plan = plan_day(cands, day=DAY, simplify=True)
    assert [i.id for i in plan.talks] == ["5", "6", "7"]
    assert all(i.type == "talk" for i in plan.items)


def test_plan_day_ignores_other_days():
    other = Candidate(id="x", title="x", start=datetime(2026, 11, 11, 9), end=datetime(2026, 11, 11, 9, 30), room="", score=1.0)
    plan = plan_day([other, talk("a", 9, 0, 30)], day=DAY)
    assert [i.id for i in plan.talks] == ["a"]
    assert plan.considered == 1


def test_energy_caps_the_day():
    cands = [talk(str(i), 9 + i, 0, 30, score=i / 10) for i in range(1, 10)]
    assert len(plan_day(cands, day=DAY, energy="low").talks) == 5
    assert len(plan_day(cands, day=DAY, energy="normal").talks) == 8
    assert len(plan_day(cands, day=DAY, energy="high").talks) == 9

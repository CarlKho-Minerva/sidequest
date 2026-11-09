from sidequest.ingest import parse_schedule

SAMPLE = """
<div class="day-divider"><div class="day-divider__title">Tuesday November 10</div></div>
<section class="slot"><div class="slot__time"><strong>9:30 AM</strong></div>
<div class="sess-wrap"><a class="sess-link" href="https://x/?id=42" data-session-id="42">
<div class="sess"><div class="sess__title">Kueue in Practice</div>
<div class="sess__meta"><span class="sess__room">Salt Palace | Level 2 | 250</span>
<span class="sess__speakers">Ada Lovelace, Grace Hopper</span></div>
<div class="sess__tags"><span class="tag tag--primary">AI Inference + Agentic</span><span class="tag">Intermediate</span></div>
</div></a>
<div class="sess__seo" hidden><div class="sess__seotime"><time datetime="2026-11-10T09:30:00">9:30 AM</time> -
<time datetime="2026-11-10T10:05:00">10:05 AM</time></div><div class="sess__seodesc"><p>Batch scheduling.</p></div></div>
</div></section>
"""


def test_parse_schedule_reads_one_session_with_day_times_and_people():
    talks = parse_schedule(SAMPLE)
    assert len(talks) == 1
    t = talks[0]
    assert t.id == "42"
    assert t.title == "Kueue in Practice"
    assert t.day == "Tuesday November 10"
    assert (t.start, t.end) == ("2026-11-10T09:30:00", "2026-11-10T10:05:00")
    assert t.room == "Salt Palace | Level 2 | 250"
    assert t.venue == "Salt Palace"
    assert t.speakers == ["Ada Lovelace", "Grace Hopper"]
    assert t.track == "AI Inference + Agentic"
    assert t.tags == ["AI Inference + Agentic", "Intermediate"]
    assert t.abstract == "Batch scheduling."


def test_parse_schedule_skips_cards_without_a_time():
    assert parse_schedule('<div class="sess-wrap"><a class="sess-link"></a><div class="sess__title">x</div></div>') == []

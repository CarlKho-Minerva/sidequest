---
title: Planner changes need tests
description: Any change to the deterministic planner must come with a test change.
slug: planner-tests
type: check
when: "PRs that modify sidequest/planner.py"
actions: "Fail the check if tests/test_planner.py is not also modified, and say which rule changed without a test."
---

The planner is the product. Its rules (15-minute buffers stretched by room distance, one quiet break per half day,
clash flags with an alternative, simplify to the top three) are promises made to an overwhelmed user, so a change
to any of them lands with a test that pins the new behaviour.

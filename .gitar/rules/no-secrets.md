---
title: No credentials in the repository
description: Block any PR that adds a token, password or API key literal.
slug: no-secrets
type: check
when: "PRs adding strings that look like credentials (auth_, rhc_, rhp_, AIza, ApiKey, password=)"
actions: "Fail the check and name the file and line."
---

All credentials come from environment variables; see README.md "Configuration".

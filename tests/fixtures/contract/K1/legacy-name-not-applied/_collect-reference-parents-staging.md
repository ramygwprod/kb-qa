---
batch: reference-parents
source_capture: _capture-reference-parents.raw.txt
source_capture_sha256: 5d16172d09e1dba87b919bf70d3a5c70465fe79959b7f045408132c02dd41eea
fetched_by_this_agent: false
pages:
  - https://example.test/docs/api
  - https://example.test/docs/inbox
  - https://example.test/docs/reports
  - https://example.test/docs/roles
---

# Staging — reference-parents

```json
[
{"vendor_term": "Inbox", "id": "example.docs.inbox", "what_it_does": "The shared inbox lets agents reply to every customer message in one place.", "parent_path": "", "source_url": "https://example.test/docs/inbox", "source_quote": "The shared inbox lets agents reply to every customer message in one place.", "access_date": "2026-01-31", "evidence_grade": "verify", "confidence": "high", "mechanism": "Native", "outcome": "yes", "depth_level": "feature", "canonical": "NOVEL", "broken_source": false},
{"id": "example.docs.reports", "vendor_term": "Reports", "what_it_does": "Reports show how many conversations each team closed this week.", "parent_path": "Docs > Reports", "source_url": "https://example.test/docs/reports", "source_quote": "Reports show how many conversations each team closed this week.", "access_date": "2026-01-31", "evidence_grade": "official-doc", "confidence": "high", "mechanism": "Native", "outcome": "yes", "depth_level": "feature", "canonical": "NOVEL", "broken_source": false},
{"id": "example.docs.roles", "vendor_term": "Roles", "what_it_does": "Admins create custom roles so only the right people can change settings.", "parent_path": "Docs > Settings > Roles", "source_url": "https://example.test/docs/roles", "source_quote": "Admins create custom roles so only the right people can change settings.", "access_date": "2026-01-31", "evidence_grade": "official-doc", "confidence": "high", "mechanism": "Native", "outcome": "yes", "depth_level": "feature", "canonical": "NOVEL", "broken_source": false},
{"id": "example.docs.api", "vendor_term": "Messages API", "what_it_does": "Developers send messages from their own systems with the Messages API.", "parent_path": "Docs > Developers > API", "source_url": "https://example.test/docs/api", "source_quote": "Developers send messages from their own systems with the Messages API.", "access_date": "2026-01-31", "evidence_grade": "official-doc", "confidence": "high", "mechanism": "Native", "outcome": "yes", "depth_level": "feature", "canonical": "NOVEL", "broken_source": false}
]
```

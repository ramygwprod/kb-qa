---
batch: widgets
vendor: Acme
source_capture: _capture-widgets.raw.txt
source_capture_sha256: 0000000000000000000000000000000000000000000000000000000000000000
pages:
  - https://docs.acme.test/widgets/overview
  - https://docs.acme.test/widgets/syntax-reference
fetched_by_this_agent: false
---

# Staging — Acme widgets batch

{"id": "widgets", "schema_version": 5, "vendor_term": "Widgets", "what_it_does": "Compose reusable UI blocks scoped to a workspace.", "source_url": "https://docs.acme.test/widgets/overview", "source_quote": "Acme Widgets let you compose reusable UI blocks.", "access_date": "2026-08-23", "evidence_grade": "official-doc", "confidence": "high", "mechanism": "Native", "outcome": "yes", "depth_level": "module"}
{"id": "widgets.syntax", "schema_version": 5, "vendor_term": "Widget Syntax", "what_it_does": "Every widget declares a type field.", "source_url": "https://docs.acme.test/widgets/syntax-reference", "source_quote": "A widget definiton must declare a `type` field.", "access_date": "2026-08-23", "evidence_grade": "official-doc", "confidence": "high", "mechanism": "Native", "outcome": "yes", "depth_level": "feature", "parent_path": "Widgets"}

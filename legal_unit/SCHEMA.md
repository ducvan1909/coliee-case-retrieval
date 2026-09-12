# Schema LegalUnit code-provisional

Output chính là `legal_unit_candidates.jsonl`. Mỗi legal unit có cấu trúc:

```json
{
  "id": "024310.txt:lu:1",
  "case_id": "024310.txt",
  "text": "Verbatim source slice",
  "source_span": {
    "source_ref": "legal_unit/samples/cases/024310.txt",
    "start_char": 0,
    "end_char": 22
  },
  "order": 0,
  "functions": ["unknown"],
  "attributed_to": {
    "kind": "unknown",
    "party_role": null
  },
  "reporting_voice": null,
  "language": "unknown",
  "confidence": 0.0,
  "unknowns": [
    "semantic function, speaker, language, and boundary adequacy require later review"
  ],
  "status": "code_provisional",
  "boundary_basis": ["document_start"],
  "segmenter_version": "structural-boundaries-v5.1"
}
```

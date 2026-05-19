# Google Sheets schema — P3_bot

> Source of truth is `project_specs.md` §7 — this file is a published
> copy for portfolio viewers who want the data model at a glance.

The bot's Google Sheet has **5 tabs**: `template` (golden reference),
`sessions`, `documents`, `_report` (formula-driven pivot), and `_errors`
(append-only log).

---

## Tab: `template` (golden reference for document types)

| Col | Name | Type | Notes |
|---|---|---|---|
| A | `id` | int | Auto-incremented row ID. |
| B | `document_type` | string | Canonical type: `invoice`, `contract`, `passport`, `certificate`, `payment_proof`, `photo`, `unknown`. |
| C | `required_fields` | JSON string | `{"date":true,"number":true,"amount":true,"contractor":true}` — which extraction fields are mandatory for this type. |
| D | `is_required` | bool | `TRUE` if missing this type fails the session's required-completeness check. |
| E | `synonyms` | comma string | Aliases Claude might output: `"счёт-фактура,инвойс"` for invoice. Used for normalization in WF02. |

Seeded with 5–8 rows during operator setup (Step 0.9 in `prompts.md`).

---

## Tab: `sessions`

| Col | Name | Type | Notes |
|---|---|---|---|
| A | `session_id` | string | `<chat_id>_<media_group_id or message_id>`. Unique. |
| B | `user_id` | int | Telegram user ID. |
| C | `username` | string | `@username` (nullable). |
| D | `started_at` | ISO datetime | First file received. |
| E | `files_count` | int | Total files in this session. |
| F | `status` | enum | `pending` → `extracting` → `classifying` → `archiving` → `done` / `failed`. |
| G | `completed_at` | ISO datetime | Set when status → `done`. |
| H | `archive_url` | string | Drive ZIP URL (set in WF04). |
| I | `error_count` | int | Count of files that failed during this session. |

---

## Tab: `documents`

| Col | Name | Type | Notes |
|---|---|---|---|
| A | `session_id` | string | FK to `sessions.session_id`. |
| B | `file_id` | string | Telegram `file_unique_id`. |
| C | `file_name` | string | Original filename or `photo_<timestamp>.jpg`. |
| D | `file_md5` | string | hex md5 (32 chars). Computed from `file_unique_id + "_" + file_size`. Powers WOW 2 dedup. |
| E | `detected_type` | string | From `template.document_type` or `unknown`. |
| F | `date` | date | Extracted. Nullable. |
| G | `number` | string | Document number. Nullable. |
| H | `amount` | numeric | Amount in base currency. Nullable. |
| I | `contractor` | string | Counterparty name. Nullable. |
| J | `confidence` | float | 0.0–1.0 from Claude. |
| K | `model_used` | string | `haiku-4.5` or `sonnet-4.6` (WOW 1 retry escalation). |
| L | `drive_url` | string | Drive file URL. |
| M | `processed_at` | ISO datetime | |

Compound unique index: `(session_id, file_id)`. `Append or Update`
operations key on this pair for write-after-success idempotency.

---

## Tab: `_report` (formula-driven pivot)

Built via Sheets formulas (no n8n writes here). Sample structure:

| `session_id` | `invoice` | `contract` | `passport` | `certificate` | `payment_proof` | `photo` |
|---|---|---|---|---|---|---|
| `-1001234_8901` | ✅ | ✅ | ✅ | ❌ | ✅ | (n/a) |
| `-1001234_8902` | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |

Formula in each cell (column B onwards):

```
=IF(COUNTIFS(documents!A:A, $A2, documents!E:E, B$1) > 0,
    "✅",
    IF(VLOOKUP(B$1, template!B:D, 3, FALSE) = TRUE, "❌", ""))
```

- ✅ = at least one file in this session matched this type.
- ❌ = required type missing (per template).
- empty cell = optional type not present (no concern).

---

## Tab: `_errors` (append-only log)

| Col | Name | Type | Notes |
|---|---|---|---|
| A | `timestamp` | ISO datetime | When the error was logged. |
| B | `session_id` | string | Nullable — workflow-level errors have no session. |
| C | `file_id` | string | Nullable — only set for file-level failures. |
| D | `workflow_id` | string | n8n workflow ID that errored. |
| E | `node` | string | Failing node name. |
| F | `error_text` | string | Sanitized error message (no secrets). |
| G | `payload_redacted` | string | First 500 chars of payload with base64 + tokens stripped. |
| H | `retry_count` | int | How many times this row was reprocessed manually by an operator. |

The `_errors` tab doubles as a DLQ (dead-letter queue) — operators can
filter for unresolved rows and manually re-run sessions via n8n UI.

---

## Indexes & performance

Google Sheets is not a database — there are no real indexes. Effective
patterns we rely on:

- **Append-only growth** for `sessions`, `documents`, `_errors`. Never
  delete; archive via column flag if needed.
- **Compound key lookups** via `COUNTIFS` and `VLOOKUP`. Both are O(N)
  on the sheet, but at <10,000 rows total this is sub-100ms.
- **Read patterns** prefer `Read Rows` with column filters over fetching
  full sheets. n8n Sheets node supports this natively.

Beyond ~50,000 rows total, this design needs to migrate to BigQuery or
Postgres. Out of scope for v1.

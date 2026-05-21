# test-data/golden — M7 golden dataset

15 PDF bank statements (3 per bank × 5 banks) for the precision /
recall / cost / latency measurement run defined in `project_specs.md`
§19. Used by `test-data/run-golden.ps1` (drafted at M7).

> **Status (2026-05-21):** directory created at M6 cutover; **operator
> sources files at M7**. The script + measurement code are drafted by
> Claude when the dataset is in place.

---

## Sourcing checklist

Filename convention: `<bank>_<period_start>_<filename_hint>.pdf`. Example:
`privat24_2024-01_personal.pdf`.

Each PDF has a sibling `.expected.json` with ground-truth values you can
write by manually inspecting the PDF after sourcing.

### Per-bank breakdown (3 each)

| # | Bank | Statement type | Notes for sourcing |
|---|---|---|---|
| 1–3 | **Privat24** | Personal card statement, 1 month | Either export from Privat24 web/app (PDF, не виписка для податкової — звичайна виписка) or use a sample from a previous test (sanitize first). |
| 4–6 | **Mono (monobank)** | Личный счёт, 1 месяц | Export from monobank app (Statements → period → Export as PDF). |
| 7–9 | **Raiffeisen Bank Aval** | Картковий рахунок | Export from Райффайзен Online (web). |
| 10–12 | **ПУМБ** | Особовий рахунок | Export from PUMB Online / iPUMB. |
| 13–15 | **А-Банк** | Особовий рахунок | Export from А-Банк web cabinet. |

### Coverage to aim for across the 15

- At least 1 PDF that's text-only (clean digital export).
- At least 1 PDF that's a scanned image (test the Anthropic auto-OCR
  path — Anthropic processes each page as both extracted text AND a
  page image, so scans should still work).
- At least 1 multi-currency statement (UAH + USD/EUR same account).
- At least 1 statement with > 100 transactions in one period (stress
  the per-statement transaction count and Excel rendering).
- At least 1 statement with non-standard descriptions (P2P transfers,
  international SWIFT, fees, recurring subscriptions).

### Sanitization (must do before commit)

- **Account number / IBAN:** mask to last 4 digits (e.g., `UA...3456`).
- **Counterparty PII:** redact full names where it's a personal
  contact (`ПЕТРО І.` instead of `ПЕТРОВ ІВАН СЕРГІЙОВИЧ`). Public
  counterparties (АТБ, Київстар, Нова Пошта) stay as-is.
- **Card numbers in descriptions:** mask to last 4 digits.
- **Cross-reference the .expected.json** — sanitized values there
  must match what's actually visible in the sanitized PDF.

### Don't commit PDFs to git

`test-data/golden/*.pdf` is gitignored (large binaries). The
`.expected.json` files **are** committed — they're the ground truth.

Make sure `.gitignore` has:

```
test-data/golden/*.pdf
test-data/golden/*.PDF
!test-data/golden/*.expected.json
```

(If the entry isn't already there, add it. The PDFs live on your local
disk + a backup; the JSON sidecars are version-controlled.)

---

## `.expected.json` schema

One JSON file per PDF, named `<pdf-filename>.expected.json`.

```json
{
  "bank": "Privat24",
  "period_start": "2024-01-01",
  "period_end": "2024-01-31",
  "currency": "UAH",
  "opening_balance": 12345.67,
  "closing_balance": 8765.43,
  "expected_transaction_count": 87,
  "expected_categories_present": ["products", "transport", "comms", "utilities"],
  "sample_transactions": [
    {
      "date": "2024-01-15",
      "amount": 245.50,
      "debit_credit": "debit",
      "description_contains": "АТБ",
      "category": "products"
    }
  ],
  "notes": "Multi-page scan; tests the auto-OCR path."
}
```

Field meanings:

- `bank` — expected detected bank ID (must match WF02b's `bank` enum).
- `period_start` / `period_end` — ISO dates Claude must extract.
- `currency` — statement-level currency.
- `opening_balance` / `closing_balance` — exact numeric values from
  the PDF header/footer (used to verify balance extraction).
- `expected_transaction_count` — total rows (±1 row tolerance per
  §18.2 quality gate).
- `expected_categories_present` — categories that MUST appear at least
  once (sanity check: a personal statement should have `products`).
- `sample_transactions` — 3–5 spot-checks per statement. The run
  script verifies each: same date, same amount (±0.01), same
  debit_credit, description contains the substring, category matches.
- `notes` — free-text gotchas for the manual reviewer.

---

## The run script (M7 deliverable)

`test-data/run-golden.ps1` will:

1. Read every PDF in `test-data/golden/`.
2. For each PDF: upload to Telegram via Bot API `sendDocument` (uses
   `TELEGRAM_BOT_TOKEN` from `.env`, sends to `MANAGER_CHAT_ID` chat).
3. Wait for the bot's reply (poll `getUpdates` or the resulting
   `transactions` Sheets rows).
4. Compare each statement's parsed rows to its `.expected.json`:
   - Bank detection accuracy (target ≥ 95% on this set).
   - Transaction count (±1 row tolerance).
   - Sample-transaction match (date/amount/debit_credit/description/category).
5. Aggregate per-bank precision tables.
6. Sum Anthropic cost from execution `usage` fields.
7. Output a markdown report in `test-data/golden/RESULTS.md` with:
   - Precision per bank
   - Category precision matrix
   - p50 / p95 latency
   - Total cost + cost per statement
   - Number of Sonnet retries triggered

---

## When you're ready

Stage **3 PDFs per bank + their .expected.json files** in this folder,
type `golden ready` to Claude, and I'll draft `run-golden.ps1` + run it.

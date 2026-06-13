# Statement-to-Excel Bot

> A Telegram bot that turns a Ukrainian-bank PDF statement (Privat24, Mono, Raiffeisen, ПУМБ, А-Банк — together ≈ 90–98% of Ukrainian retail banking by user count) into a categorized Excel within 60 seconds.

## Demo

<!-- Loom walkthrough: link added after recording -->

## Overview

Outsource accountants serving 10–30 ФОПів each spend one to three hours per client every month retyping bank-statement PDFs into spreadsheets and tagging every row by category (Продукти / Транспорт / Зв'язок / ...). This bot does that data entry. A client forwards a monthly statement to Telegram; the bot detects the bank, extracts every transaction, categorizes it, flags anything it is unsure about, and replies with a ready Excel — for a typical monthly statement, in well under a minute.

Example reply:

```
✅ Обработано 142 транзакции за период 01.01.2026–31.01.2026 (Privat24).

💸 Расходы: 47 320 UAH
💰 Доходы: 65 000 UAH

📊 Топ-3 категории:
• Продукти: 12 450 UAH
• Транспорт: 6 200 UAH
• Зв'язок: 1 800 UAH

⚠ 3 транзакции требуют проверки (отмечены жёлтым в Excel).

📥 Excel: https://drive.google.com/.../session_a3f7.xlsx
```

The Excel has three sheets: `Transactions` (every row, categorized, low-confidence rows highlighted), `Summary` (totals, top categories, period, bank), and `Suspicious` (the low-confidence rows on their own for review).

## Key features

- **Bank auto-detection.** Page 1 of the statement identifies the bank (Privat24 / Mono / Raiffeisen / ПУМБ / А-Банк, generic fallback otherwise) — no manual bank picker.
- **Signed-PDF unwrapping.** Privat24 and other banks deliver statements as КЕП-signed PKCS#7 containers, not plain PDFs — the bytes start with an ASN.1 header, not `%PDF`, so an ordinary reader rejects them. The bot unwraps the embedded document first, so a signed export is parsed exactly like an unsigned one.
- **Contextual categorization.** "АТБ-МАРКЕТ" -> Продукти, "Uklon" -> Транспорт, "Київстар" -> Зв'язок, person-to-person transfers -> Особисті перекази. Synonyms, typos, and mixed uk/ru/en descriptions are handled without regex tables.
- **Honest uncertainty.** Rows the model is not confident about (confidence < 0.8) are highlighted in the Excel and counted in the Telegram reply, instead of being passed off as certain.
- **Weight-based model routing.** Page count picks the model, so a dense statement is never sent to one that would run out of output budget halfway through the JSON.
- **MD5 deduplication.** Re-sending the same file returns the cached result in a few seconds instead of paying for the extraction again.

## How it works

A statement arrives in Telegram. The receiver (Python / aiogram) unwraps any КЕП signature, counts pages, and picks the model tier. n8n downloads the PDF, sends it to Claude as a document block with a per-bank prompt and the seeded category taxonomy, and gets back strict JSON of `{bank, period, balances, transactions[]}`. The rows are written to Google Sheets, an Excel is built (Apps Script — n8n Cloud has no native spreadsheet-writer node), and the Drive link is sent back to Telegram. Five n8n workflows cover the stages: receive -> extract -> persist -> build Excel -> error alerts.

## Model routing

Extraction is bound by **output** tokens, not input context — every transaction has to come back as JSON, and each model caps how much it can emit in one response (64K for Haiku and Sonnet, 128K for Opus). Page count is the proxy for how much output a statement will produce:

| Pages | Model | Why |
| --- | --- | --- |
| ≤ 15 | Haiku 4.5 | Cheapest; a monthly statement fits one pass |
| 16–120 | Sonnet 4.6 | Dense / long statements complete in one clean pass |
| 121–200 | Opus 4.x | Largest accepted statements |
| > 200 | rejected | Bot asks the user to split and resend |

Measured example: a 25-page Privat24 export routes straight to Sonnet and finishes in a single pass (27K output tokens, no truncation) — instead of burning a doomed attempt on a smaller model first. Low-confidence results can still escalate one tier as a quality retry.

## Performance

- A typical monthly statement (a few pages) returns in well under a minute.
- A large full-history export takes proportionally longer: speed is bounded by how fast the model emits the transaction JSON — a 25-page statement is roughly 27K output tokens, a few minutes on a single pass — not by the bot.
- Roadmap for large statements: split into page-range chunks processed in parallel, so wall-clock becomes the slowest chunk rather than the sum — turning those few minutes into about one.
- Target cost is about $0.05 per monthly statement; caching the system prompt makes repeat sessions cheaper.

## Tech stack

- **Orchestration:** n8n Cloud Pro — stable webhook URL, native Anthropic and Google nodes, managed Postgres.
- **AI:** Anthropic Claude — Haiku 4.5 / Sonnet 4.6 / Opus 4.x, routed by statement size; PDFs sent as document blocks (text plus per-page image in one call), strict-JSON output, system-prompt caching.
- **Receiver:** Python `aiogram` 3 and FastAPI — owns the Telegram side and the КЕП unwrap / page-count / tier decision.
- **Data and output:** Google Sheets API v4 (transactions, statements, categories, sessions, errors), Google Drive API v3 (the Excel files), Google Apps Script web app (XLSX builder).

## Status

Case study / portfolio project. Runs behind a webhook secret; error logs are sanitized (base64, tokens, and query strings stripped) and no secrets live in the workflow JSON exports under `workflows/`.

/**
 * build-zip.gs — Google Apps Script Web App for P3_bot.
 *
 * After the 2026-05-21 pivot, primary action is `build_xlsx`. The legacy
 * `zip` and `extract_docx` actions remain wired but unused (slated for
 * deletion at M8 of the bank-statement-parser rebuild).
 *
 * Actions:
 *
 *   action = "build_xlsx" (called from WF04b — bank-statement product)
 *     Creates a new Google Spreadsheet with three sheets:
 *       - Transactions: every parsed transaction row + confidence column,
 *         with conditional formatting (yellow background when confidence < 0.8).
 *       - Summary: period, bank(s), totals (debit/credit), top categories,
 *         low_confidence_count.
 *       - Suspicious: filtered subset of Transactions where confidence < 0.8.
 *     Exports the spreadsheet as .xlsx into the archive folder, shares
 *     anyone-with-link, trashes the intermediate Google Sheet, returns URL.
 *     Body: {
 *       "session_id": "...",
 *       "chat_id": ...,
 *       "drive_folder_id": "...",      // where the .xlsx is written
 *       "statements": [{statement_id, bank, period_start, period_end, currency,
 *                       opening_balance, closing_balance, drive_url}],
 *       "transactions": [{statement_id, date, description, counterparty,
 *                         amount, currency, debit_credit, balance_after,
 *                         category, confidence, model_used}],
 *       "categories": [{id, name_ua}]
 *     }
 *     Response: { "xlsx_url": "...", "sheets_count": 3, "transactions_count": N }
 *
 *   action = "zip" (legacy — v1 classifier product, retained until M8)
 *   action = "extract_docx" (legacy — v1 DOCX text extraction)
 *
 * Deploy: Extensions → Apps Script → paste this file → Services →
 *   Add → "Drive API" (legacy extract_docx still needs it). Then Deploy
 *   as Web App: Execute as: Me, Who has access: Anyone (anonymous OK).
 * Copy URL into .env as APPS_SCRIPT_WEBHOOK_URL.
 *
 * Script Properties → set EXPECTED_TOKEN to a random 32-char string,
 * same value as APPS_SCRIPT_TOKEN in .env. Query string MUST include
 * ?token=<APPS_SCRIPT_TOKEN>.
 *
 * Response shape (HTTP 200 always — Apps Script quirk):
 *   Errors: { "error": "<message>" }
 */

function doPost(e) {
  try {
    // 1. Auth: shared token in query param.
    const provided = e.parameter && e.parameter.token;
    const expected = PropertiesService.getScriptProperties()
      .getProperty('EXPECTED_TOKEN');
    if (!expected || provided !== expected) {
      return jsonResponse({ error: 'unauthorized' });
    }

    // 2. Parse body.
    const body = JSON.parse(e.postData.contents);
    const action = body.action || 'zip';

    if (action === 'build_xlsx') {
      return handleBuildXlsx(body);
    } else if (action === 'zip') {
      return handleZip(body);
    } else if (action === 'extract_docx') {
      return handleExtractDocx(body);
    } else {
      return jsonResponse({ error: 'unknown action: ' + action });
    }
  } catch (err) {
    return jsonResponse({ error: String(err && err.message || err) });
  }
}

/**
 * handleBuildXlsx — primary action after the pivot.
 *
 * Builds a categorised-transactions Excel workbook (.xlsx) for the
 * accountant, with conditional formatting on low-confidence rows.
 */
function handleBuildXlsx(body) {
  const sessionId = body.session_id;
  const folderId = body.drive_folder_id;
  const statements = Array.isArray(body.statements) ? body.statements : [];
  const transactions = Array.isArray(body.transactions) ? body.transactions : [];
  const categories = Array.isArray(body.categories) ? body.categories : [];

  if (!sessionId || !folderId) {
    return jsonResponse({ error: 'missing session_id or drive_folder_id' });
  }
  if (statements.length === 0) {
    return jsonResponse({ error: 'no statements provided' });
  }

  // Category id → name_ua lookup, for human-readable Excel labels.
  const catNameById = {};
  categories.forEach(function (c) {
    if (c && c.id) catNameById[c.id] = c.name_ua || c.id;
  });

  // 1. Create new Spreadsheet (auto-named with session_id).
  const ss = SpreadsheetApp.create('p3bot_' + sessionId);
  const ssId = ss.getId();

  // 2. Transactions sheet (rename default).
  const txSheet = ss.getActiveSheet();
  txSheet.setName('Transactions');
  const txHeaders = [
    'Date', 'Bank', 'Period', 'Description', 'Counterparty',
    'Amount', 'Currency', 'Debit/Credit', 'Balance After',
    'Category', 'Category (UA)', 'Confidence', 'Model'
  ];
  txSheet.getRange(1, 1, 1, txHeaders.length).setValues([txHeaders]).setFontWeight('bold');

  // Build statement_id → {bank, period} lookup so each transaction row
  // can show which statement it came from without a JOIN.
  const stmtById = {};
  statements.forEach(function (s) {
    if (s && s.statement_id) {
      stmtById[s.statement_id] = {
        bank: s.bank || '',
        period: (s.period_start || '') + ' – ' + (s.period_end || ''),
      };
    }
  });

  const txRows = transactions.map(function (t) {
    const meta = stmtById[t.statement_id] || { bank: '', period: '' };
    return [
      t.date || '',
      meta.bank,
      meta.period,
      t.description || '',
      t.counterparty || '',
      typeof t.amount === 'number' ? t.amount : '',
      t.currency || '',
      t.debit_credit || '',
      typeof t.balance_after === 'number' ? t.balance_after : '',
      t.category || 'other',
      catNameById[t.category] || t.category || 'Інше',
      typeof t.confidence === 'number' ? t.confidence : 0,
      t.model_used || ''
    ];
  });

  if (txRows.length > 0) {
    txSheet.getRange(2, 1, txRows.length, txHeaders.length).setValues(txRows);
  }
  txSheet.setFrozenRows(1);
  txSheet.autoResizeColumns(1, txHeaders.length);

  // 3. Conditional formatting: yellow background when Confidence < 0.8.
  // Column L (index 12) holds Confidence.
  if (txRows.length > 0) {
    const confRange = txSheet.getRange(2, 12, txRows.length, 1);
    const yellowRule = SpreadsheetApp.newConditionalFormatRule()
      .whenNumberLessThan(0.8)
      .setBackground('#FFEB3B')
      .setRanges([confRange])
      .build();
    txSheet.setConditionalFormatRules([yellowRule]);
  }

  // 4. Summary sheet.
  const summarySheet = ss.insertSheet('Summary');
  summarySheet.getRange('A1').setValue('P3_bot — bank statement summary').setFontWeight('bold').setFontSize(14);

  let row = 3;
  summarySheet.getRange(row, 1).setValue('Session ID:').setFontWeight('bold');
  summarySheet.getRange(row, 2).setValue(sessionId);
  row++;

  // Period range across all statements.
  const periodStarts = statements.map(function (s) { return s.period_start || ''; }).filter(Boolean).sort();
  const periodEnds = statements.map(function (s) { return s.period_end || ''; }).filter(Boolean).sort();
  summarySheet.getRange(row, 1).setValue('Period:').setFontWeight('bold');
  summarySheet.getRange(row, 2).setValue((periodStarts[0] || '?') + ' – ' + (periodEnds[periodEnds.length - 1] || '?'));
  row++;

  // Bank list.
  const banks = Array.from(new Set(statements.map(function (s) { return s.bank; }).filter(Boolean)));
  summarySheet.getRange(row, 1).setValue('Banks:').setFontWeight('bold');
  summarySheet.getRange(row, 2).setValue(banks.join(', '));
  row += 2;

  // Totals.
  let totalDebit = 0;
  let totalCredit = 0;
  let lowConfCount = 0;
  const byCategory = {};
  transactions.forEach(function (t) {
    const amt = typeof t.amount === 'number' ? t.amount : 0;
    if (t.debit_credit === 'debit') totalDebit += amt;
    else if (t.debit_credit === 'credit') totalCredit += amt;
    if (typeof t.confidence === 'number' && t.confidence < 0.8) lowConfCount++;
    const cat = t.category || 'other';
    if (!byCategory[cat]) byCategory[cat] = { count: 0, debit: 0, credit: 0 };
    byCategory[cat].count++;
    if (t.debit_credit === 'debit') byCategory[cat].debit += amt;
    else if (t.debit_credit === 'credit') byCategory[cat].credit += amt;
  });

  summarySheet.getRange(row, 1).setValue('Total debit:').setFontWeight('bold');
  summarySheet.getRange(row, 2).setValue(totalDebit);
  row++;
  summarySheet.getRange(row, 1).setValue('Total credit:').setFontWeight('bold');
  summarySheet.getRange(row, 2).setValue(totalCredit);
  row++;
  summarySheet.getRange(row, 1).setValue('Transactions:').setFontWeight('bold');
  summarySheet.getRange(row, 2).setValue(transactions.length);
  row++;
  summarySheet.getRange(row, 1).setValue('Low confidence (<0.8):').setFontWeight('bold');
  summarySheet.getRange(row, 2).setValue(lowConfCount);
  row += 2;

  // By-category breakdown (sorted by total debit descending).
  summarySheet.getRange(row, 1).setValue('Categories (debit/credit/count):').setFontWeight('bold');
  row++;
  summarySheet.getRange(row, 1, 1, 4).setValues([['Category', 'Debit', 'Credit', 'Count']]).setFontWeight('bold');
  row++;
  const sortedCats = Object.keys(byCategory).sort(function (a, b) {
    return byCategory[b].debit - byCategory[a].debit;
  });
  sortedCats.forEach(function (cat) {
    const c = byCategory[cat];
    summarySheet.getRange(row, 1, 1, 4).setValues([[catNameById[cat] || cat, c.debit, c.credit, c.count]]);
    row++;
  });
  summarySheet.autoResizeColumns(1, 4);

  // 5. Suspicious sheet — filtered Transactions where confidence < 0.8.
  const suspSheet = ss.insertSheet('Suspicious');
  suspSheet.getRange(1, 1, 1, txHeaders.length).setValues([txHeaders]).setFontWeight('bold');
  const suspRows = txRows.filter(function (r) {
    return typeof r[11] === 'number' && r[11] < 0.8;
  });
  if (suspRows.length > 0) {
    suspSheet.getRange(2, 1, suspRows.length, txHeaders.length).setValues(suspRows);
  }
  suspSheet.setFrozenRows(1);
  suspSheet.autoResizeColumns(1, txHeaders.length);
  // Same yellow background on the confidence column for visual consistency.
  if (suspRows.length > 0) {
    const suspConfRange = suspSheet.getRange(2, 12, suspRows.length, 1);
    suspSheet.setConditionalFormatRules([
      SpreadsheetApp.newConditionalFormatRule()
        .whenNumberLessThan(0.8)
        .setBackground('#FFEB3B')
        .setRanges([suspConfRange])
        .build()
    ]);
  }

  // 6. Export as XLSX → Drive archive folder.
  SpreadsheetApp.flush();
  const xlsxBlob = DriveApp.getFileById(ssId)
    .getBlob()
    .getAs('application/vnd.openxmlformats-officedocument.spreadsheetml.sheet');
  xlsxBlob.setName(sessionId + '.xlsx');
  const folder = DriveApp.getFolderById(folderId);
  // Overwrite previous attempts with same session_id.
  const existing = folder.getFilesByName(sessionId + '.xlsx');
  while (existing.hasNext()) {
    existing.next().setTrashed(true);
  }
  const xlsxFile = folder.createFile(xlsxBlob);
  xlsxFile.setSharing(DriveApp.Access.ANYONE_WITH_LINK, DriveApp.Permission.VIEW);

  // 7. Trash the intermediate Google Sheet (keeps the archive folder clean).
  try {
    DriveApp.getFileById(ssId).setTrashed(true);
  } catch (cleanupErr) {
    // Non-fatal — the .xlsx is already written.
  }

  return jsonResponse({
    xlsx_url: xlsxFile.getUrl(),
    sheets_count: 3,
    transactions_count: transactions.length,
    low_confidence_count: lowConfCount,
  });
}

function handleZip(body) {
  const sessionId = body.session_id;
  const folderId = body.drive_folder_id;
  const driveIds = body.drive_ids || [];
  const fileNames = body.file_names || [];

  if (!sessionId || !folderId) {
    return jsonResponse({ error: 'missing session_id or drive_folder_id' });
  }
  if (driveIds.length === 0 && fileNames.length === 0) {
    return jsonResponse({ error: 'no drive_ids or file_names provided' });
  }

  const blobs = [];
  const missing = [];

  // Primary path: file IDs (exact Drive lookup, immune to renames).
  // Google Docs / Sheets / Slides exported as PDF; raw uploads kept as-is.
  driveIds.forEach(function (id) {
    try {
      const file = DriveApp.getFileById(id);
      const mime = file.getMimeType();
      let blob;
      if (mime === 'application/vnd.google-apps.document') {
        blob = file.getAs('application/pdf').setName(file.getName() + '.pdf');
      } else if (mime === 'application/vnd.google-apps.spreadsheet') {
        blob = file.getAs('application/pdf').setName(file.getName() + '.pdf');
      } else if (mime === 'application/vnd.google-apps.presentation') {
        blob = file.getAs('application/pdf').setName(file.getName() + '.pdf');
      } else {
        blob = file.getBlob();
      }
      blobs.push(blob);
    } catch (e) {
      missing.push(id);
    }
  });

  // Fallback path: file names (folder lookup) — only if no IDs were given.
  if (driveIds.length === 0 && fileNames.length > 0) {
    const folder = DriveApp.getFolderById(folderId);
    fileNames.forEach(function (name) {
      const iter = folder.getFilesByName(name);
      if (iter.hasNext()) {
        blobs.push(iter.next().getBlob());
      } else {
        missing.push(name);
      }
    });
  }

  if (blobs.length === 0) {
    return jsonResponse({ error: 'no files found', missing: missing });
  }

  const folder = DriveApp.getFolderById(folderId);
  // User-facing ZIP name: timestamped in the script's locale.
  // Drive supports Unicode in filenames; modern browsers preserve it
  // through Content-Disposition on download.
  const tz = Session.getScriptTimeZone();
  const ts = Utilities.formatDate(new Date(), tz, 'yyyy-MM-dd_HH-mm');
  const zipName = 'Архив_' + ts + '.zip';
  const zipBlob = Utilities.zip(blobs, zipName);

  // Overwrite any previous attempt with same name.
  const existing = folder.getFilesByName(zipName);
  while (existing.hasNext()) {
    existing.next().setTrashed(true);
  }
  const zipFile = folder.createFile(zipBlob);

  zipFile.setSharing(
    DriveApp.Access.ANYONE_WITH_LINK,
    DriveApp.Permission.VIEW
  );

  return jsonResponse({
    zip_url: zipFile.getUrl(),
    files_count: blobs.length,
    missing_files: missing,
  });
}

function handleExtractDocx(body) {
  const fileName = body.file_name || ('p3-temp-' + Date.now() + '.docx');
  const docxBase64 = body.docx_base64;

  if (!docxBase64) {
    return jsonResponse({ error: 'missing docx_base64' });
  }

  const bytes = Utilities.base64Decode(docxBase64);
  const blob = Utilities.newBlob(
    bytes,
    'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    fileName
  );

  // Use Drive Advanced Service to insert with auto-conversion to Google Doc.
  // Requires "Drive API" enabled under Services in the Apps Script project.
  let convertedFileId = null;
  try {
    const created = Drive.Files.insert(
      {
        title: 'p3-extract-' + Date.now(),
        mimeType: 'application/vnd.google-apps.document',
      },
      blob,
      { convert: true }
    );
    convertedFileId = created.id;

    // Export the converted Google Doc as plain text via Drive REST API v3,
    // using the script's OAuth token (Drive scope already granted by the
    // Advanced Service enable step). Avoids the separate Documents API
    // scope that DocumentApp.openById would require.
    const exportResponse = UrlFetchApp.fetch(
      'https://www.googleapis.com/drive/v3/files/' + convertedFileId + '/export?mimeType=text%2Fplain',
      {
        method: 'get',
        headers: { Authorization: 'Bearer ' + ScriptApp.getOAuthToken() },
        muteHttpExceptions: true,
      }
    );

    if (exportResponse.getResponseCode() !== 200) {
      return jsonResponse({
        error: 'drive_export_failed',
        status: exportResponse.getResponseCode(),
        body: exportResponse.getContentText().slice(0, 300),
      });
    }

    const text = exportResponse.getContentText();
    return jsonResponse({
      text: text,
      char_count: text.length,
    });
  } finally {
    // Always trash the temp file, even on error.
    if (convertedFileId) {
      try {
        DriveApp.getFileById(convertedFileId).setTrashed(true);
      } catch (cleanupErr) {
        // Swallow cleanup errors; the response already left.
      }
    }
  }
}

function doGet(e) {
  return jsonResponse({
    status: 'ok',
    message: 'P3_bot Apps Script — actions: zip, extract_docx (POST + ?token=...).',
  });
}

/**
 * One-time helper. Run this from the Apps Script editor
 * (function dropdown → setupAuth → ▶ Run) to trigger the
 * scope-grant dialog for every external API the script needs.
 * Accept all permissions when prompted. No redeploy required.
 *
 * MUST be re-run whenever a new API is added to the script
 * (e.g., adding SpreadsheetApp.create triggered the scope
 * "https://www.googleapis.com/auth/spreadsheets" which the
 * previous setupAuth didn't cover — see learnings 2026-05-21).
 */
function setupAuth() {
  // Touch UrlFetchApp so the script.external_request scope is granted.
  UrlFetchApp.fetch('https://www.google.com/generate_204', { muteHttpExceptions: true });
  // Touch Drive Advanced Service (scope already granted by enable, but harmless).
  Drive.About.get();
  // Touch SpreadsheetApp to grant https://www.googleapis.com/auth/spreadsheets.
  // Required for handleBuildXlsx — create + immediately trash a probe Sheet.
  const probe = SpreadsheetApp.create('p3bot_setup_probe_' + Date.now());
  DriveApp.getFileById(probe.getId()).setTrashed(true);
  Logger.log('setupAuth: all scopes granted (UrlFetchApp + Drive + Spreadsheets).');
}

function jsonResponse(obj) {
  return ContentService
    .createTextOutput(JSON.stringify(obj))
    .setMimeType(ContentService.MimeType.JSON);
}

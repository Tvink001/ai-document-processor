/**
 * build-zip.gs — Google Apps Script Web App for P3_bot.
 *
 * Routes POST requests to one of two actions:
 *
 *   action = "zip" (default, backwards-compatible with WF04)
 *     Locates files in Drive by name, builds a ZIP, stores it in the
 *     same folder, returns the public URL.
 *     Body: { "session_id": "...", "drive_folder_id": "...", "file_names": ["..."] }
 *     Response: { "zip_url": "...", "files_count": N, "missing_files": [...] }
 *
 *   action = "extract_docx" (called from WF02 — see project_specs.md §11.A)
 *     Receives a DOCX file as base64, uploads it to Drive with
 *     mimeType=application/vnd.google-apps.document so Drive auto-
 *     converts it to a Google Doc, reads the body text via
 *     DocumentApp, trashes the temp file, returns plain text.
 *     Body: { "file_name": "...", "docx_base64": "..." }
 *     Response: { "text": "...", "char_count": N }
 *
 * Deploy: Extensions → Apps Script → paste this file → Services →
 *   Add → "Drive API" (required for extract_docx). Then Deploy as
 *   Web App: Execute as: Me, Who has access: Anyone.
 * Copy URL into .env as APPS_SCRIPT_WEBHOOK_URL (or use the hardcoded
 * value directly in n8n nodes — n8n Cloud blocks $env access in
 * expressions; see learnings 2026-05-20).
 *
 * Script Properties → set EXPECTED_TOKEN to a random 32-char string,
 * same value as APPS_SCRIPT_TOKEN in .env.
 * Query string MUST include ?token=<APPS_SCRIPT_TOKEN>.
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

    if (action === 'zip') {
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

function handleZip(body) {
  const sessionId = body.session_id;
  const folderId = body.drive_folder_id;
  const fileNames = body.file_names || [];

  if (!sessionId || !folderId || fileNames.length === 0) {
    return jsonResponse({ error: 'missing required fields for zip' });
  }

  const folder = DriveApp.getFolderById(folderId);
  const blobs = [];
  const missing = [];

  fileNames.forEach(function (name) {
    const iter = folder.getFilesByName(name);
    if (iter.hasNext()) {
      blobs.push(iter.next().getBlob());
    } else {
      missing.push(name);
    }
  });

  if (blobs.length === 0) {
    return jsonResponse({ error: 'no files found', missing: missing });
  }

  const zipName = 'session_' + sessionId + '.zip';
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
 */
function setupAuth() {
  // Touch UrlFetchApp so the script.external_request scope is granted.
  UrlFetchApp.fetch('https://www.google.com/generate_204', { muteHttpExceptions: true });
  // Touch Drive Advanced Service (scope already granted by enable, but harmless).
  Drive.About.get();
  Logger.log('setupAuth: all scopes granted.');
}

function jsonResponse(obj) {
  return ContentService
    .createTextOutput(JSON.stringify(obj))
    .setMimeType(ContentService.MimeType.JSON);
}

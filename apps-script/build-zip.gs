/**
 * build-zip.gs — Google Apps Script Web App for P3_bot.
 *
 * Receives a session_id + drive_folder_id + file_names[] from n8n WF04,
 * locates the matching files in Drive, zips them via Utilities.zip(),
 * stores the ZIP in the same folder, and returns the public URL.
 *
 * Deploy: Extensions → Apps Script → paste this file → Deploy as Web App
 *   Execute as: Me
 *   Who has access: Anyone
 * Copy the URL into .env as APPS_SCRIPT_WEBHOOK_URL.
 * Script Properties → set EXPECTED_TOKEN to a random 32-char string,
 *   same value as APPS_SCRIPT_TOKEN in .env.
 *
 * Request shape (POST body, JSON):
 *   { "session_id": "...", "drive_folder_id": "...", "file_names": ["..."] }
 *
 * Query string MUST include ?token=<APPS_SCRIPT_TOKEN>.
 *
 * Response shape (JSON, HTTP 200 always — Apps Script quirk):
 *   Success: { "zip_url": "...", "files_count": N }
 *   Error:   { "error": "<message>" }
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
    const sessionId = body.session_id;
    const folderId = body.drive_folder_id;
    const fileNames = body.file_names || [];

    if (!sessionId || !folderId || fileNames.length === 0) {
      return jsonResponse({ error: 'missing required fields' });
    }

    // 3. Locate files in Drive.
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
      return jsonResponse({
        error: 'no files found',
        missing: missing,
      });
    }

    // 4. Build ZIP.
    const zipName = 'session_' + sessionId + '.zip';
    const zipBlob = Utilities.zip(blobs, zipName);

    // 5. Save ZIP into the same folder (overwrite if previous attempt exists).
    const existing = folder.getFilesByName(zipName);
    while (existing.hasNext()) {
      existing.next().setTrashed(true);
    }
    const zipFile = folder.createFile(zipBlob);

    // 6. Make ZIP shareable (anyone with the link can view).
    zipFile.setSharing(
      DriveApp.Access.ANYONE_WITH_LINK,
      DriveApp.Permission.VIEW
    );

    return jsonResponse({
      zip_url: zipFile.getUrl(),
      files_count: blobs.length,
      missing_files: missing,
    });
  } catch (err) {
    return jsonResponse({ error: String(err && err.message || err) });
  }
}

function doGet(e) {
  return jsonResponse({
    status: 'ok',
    message: 'P3_bot ZIP builder. Use POST with token + session_id + drive_folder_id + file_names.',
  });
}

function jsonResponse(obj) {
  return ContentService
    .createTextOutput(JSON.stringify(obj))
    .setMimeType(ContentService.MimeType.JSON);
}

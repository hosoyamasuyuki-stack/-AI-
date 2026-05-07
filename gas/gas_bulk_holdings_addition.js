/**
 * 保有ポートフォリオ一括更新 GAS 追加スニペット
 *
 * 用途: ダッシュボードor LISA admin の「一括更新」ボタンから CSV を投げ、
 *       GitHub Actions の bulk_update_holdings.yml を起動する。
 *
 * 既存スクリプトプロパティを再利用:
 *   - GITHUB_TOKEN  : GitHub Actions workflow_dispatch 用
 *   - ADMIN_SECRET  : LISA Vercel の KAIZEN_ADMIN_SECRET と同値
 *
 * 配置: 既存の manage_stock 用 GAS（GAS_URL_FULL_UPDATE と同じプロジェクト）
 *       https://script.google.com/u/0/home/projects/...
 *       の doPost 関数内に下記の if 分岐を追加する。
 *
 * 既存の manage_stock 分岐とは独立・干渉しない。
 * デプロイ後は新バージョンとして公開（既存バージョンとの互換性は維持される）。
 */

// ── 既存 doPost(e) 関数内に追加する分岐 ─────────────────────────
//
//   var params = {};
//   try {
//     if (e.postData && e.postData.contents) {
//       params = JSON.parse(e.postData.contents);
//     }
//   } catch (err) {}
//
//   var action = (params && params.action) || e.parameter.action || '';
//
//   // ↓ ここから追加
//   if (action === 'bulk_update_holdings') {
//     return handleBulkUpdateHoldings(e, params);
//   }
//   // ↑ ここまで
//
//   // 既存の manage_stock 分岐などは下に続く
//
// ─────────────────────────────────────────────────────────────

/**
 * 保有ポートフォリオ一括更新ハンドラ
 *
 * 期待入力:
 *   - admin_secret : LISA Vercel の KAIZEN_ADMIN_SECRET と同値
 *   - csv          : CSV 本文（market,code,shares 形式・改行区切り）
 *   - dry_run      : 'true' / 'false'（任意・既定は 'false'）
 *
 * 処理:
 *   1. ADMIN_SECRET 検証
 *   2. CSV 必須検証
 *   3. GitHub Actions の bulk_update_holdings.yml を workflow_dispatch
 *
 * 戻り値:
 *   { status: 'ok' | 'error', message?: string, code?: number }
 */
function handleBulkUpdateHoldings(e, params) {
  // 1. ADMIN_SECRET 検証
  var adminSecret = (params && params.admin_secret) || e.parameter.admin_secret || '';
  var expected = PropertiesService.getScriptProperties().getProperty('ADMIN_SECRET');
  if (!expected) {
    return jsonResponse({ status: 'error', message: 'ADMIN_SECRET not configured in Script Properties' });
  }
  if (adminSecret !== expected) {
    return jsonResponse({ status: 'error', message: 'unauthorized' });
  }

  // 2. CSV 必須検証
  var csv = (params && params.csv) || e.parameter.csv || '';
  if (!csv || csv.length < 10) {
    return jsonResponse({ status: 'error', message: 'csv body is required (header + at least one row)' });
  }
  // CSV 改行が \\n 形式で来た場合のために正規化
  csv = String(csv).replace(/\\n/g, '\n').replace(/\\r/g, '\r');

  var dryRun = String((params && params.dry_run) || e.parameter.dry_run || 'false').toLowerCase();

  // 3. GitHub Actions workflow_dispatch
  var token = PropertiesService.getScriptProperties().getProperty('GITHUB_TOKEN');
  if (!token) {
    return jsonResponse({ status: 'error', message: 'GITHUB_TOKEN not configured in Script Properties' });
  }

  var url = 'https://api.github.com/repos/hosoyamasuyuki-stack/-AI-/actions/workflows/bulk_update_holdings.yml/dispatches';
  var payload = {
    ref: 'main',
    inputs: {
      csv: csv,
      dry_run: dryRun
    }
  };

  var response;
  try {
    response = UrlFetchApp.fetch(url, {
      method: 'post',
      contentType: 'application/json',
      headers: {
        'Authorization': 'token ' + token,
        'Accept': 'application/vnd.github.v3+json'
      },
      payload: JSON.stringify(payload),
      muteHttpExceptions: true
    });
  } catch (err) {
    return jsonResponse({ status: 'error', message: 'fetch failed: ' + err.message });
  }

  var responseCode = response.getResponseCode();
  if (responseCode === 204) {
    return jsonResponse({
      status: 'ok',
      message: 'bulk_update_holdings workflow dispatched (dry_run=' + dryRun + ')',
      rows_in_csv: csv.split('\n').length - 1  // ヘッダ除く想定行数
    });
  }
  return jsonResponse({
    status: 'error',
    code: responseCode,
    body: response.getContentText()
  });
}

/**
 * JSON レスポンスのヘルパー（既存にあれば不要）
 */
function jsonResponse(obj) {
  return ContentService
    .createTextOutput(JSON.stringify(obj))
    .setMimeType(ContentService.MimeType.JSON);
}

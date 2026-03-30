// ============================================================
// GASプロキシに追加するコード（manage_stock対応）
//
// 既存のdoGet関数内に以下の分岐を追加してください：
// https://script.google.com/u/0/home/projects/10AJhsVjzs6dUsSu9f-NCIE0F9Dbt1ECykKPSaRkppCtRz_XQpu7EQ6lo/edit
//
// デプロイ後のURL:
// https://script.google.com/macros/s/AKfycbwVDZ9IhuGEz7onU9uCvhSFd7N84cGQouIcnBMQO5iIlFwbNbVP4J8_tPtOj8X7yxAw/exec
// ============================================================

// doGet または doPost 関数内に追加する分岐：
// -----------------------------------------------
// if (action === 'manage_stock') {
//   var code      = e.parameter.code      || '';
//   var operation = e.parameter.operation  || '';  // add, remove, move, swap
//   var target    = e.parameter.target     || '';  // 保有, 監視
//   var add_code  = e.parameter.add_code   || '';  // swap時のみ: 追加する銘柄コード
//
//   if (!code || !operation || !target) {
//     return ContentService.createTextOutput(
//       JSON.stringify({status: 'error', message: 'code, operation, target are required'})
//     ).setMimeType(ContentService.MimeType.JSON);
//   }
//
//   // GitHub Actions workflow_dispatch を発火
//   var url = 'https://api.github.com/repos/hosoyamasuyuki-stack/-AI-/actions/workflows/manage_stock.yml/dispatches';
//   var token = PropertiesService.getScriptProperties().getProperty('GITHUB_TOKEN');
//
//   var inputs = {
//     code: code,
//     action: operation,
//     target: target,
//     add_code: add_code   // swap時のみ使用（それ以外は空文字列）
//   };
//
//   var payload = {
//     ref: 'main',
//     inputs: inputs
//   };
//
//   var options = {
//     method: 'post',
//     contentType: 'application/json',
//     headers: {
//       'Authorization': 'token ' + token,
//       'Accept': 'application/vnd.github.v3+json'
//     },
//     payload: JSON.stringify(payload),
//     muteHttpExceptions: true
//   };
//
//   var response = UrlFetchApp.fetch(url, options);
//   var responseCode = response.getResponseCode();
//
//   if (responseCode === 204) {
//     return ContentService.createTextOutput(
//       JSON.stringify({status: 'ok', message: 'manage_stock workflow dispatched: ' + operation + ' ' + code + ' -> ' + target})
//     ).setMimeType(ContentService.MimeType.JSON);
//   } else {
//     return ContentService.createTextOutput(
//       JSON.stringify({status: 'error', code: responseCode, body: response.getContentText()})
//     ).setMimeType(ContentService.MimeType.JSON);
//   }
// }
// -----------------------------------------------

// 注意：
// 1. GITHUB_TOKENはスクリプトプロパティに既に設定済み
// 2. manage_stock.ymlのworkflow名は 'manage_stock.yml'
// 3. inputsのキー名はYAMLのinputs定義と一致させること
// 4. デプロイ後は新バージョンとして公開が必要（バージョン13以降）

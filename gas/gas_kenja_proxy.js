/**
 * 賢者の審判 GASプロキシ v2（EDINET全文分析版）
 *
 * スクリプトプロパティに以下を設定:
 *   EDINET_API_KEY  : EDINET APIキー
 *   kenja-rich-api  : OpenAI APIキー（GPT-4o使用）
 *
 * v1からの変更点:
 *   - EDINET書類のXBRL ZIPを取得→解凍→HTML本文テキスト化
 *   - GPT-4oの128Kコンテキストに全文を投入（正規表現抽出なし）
 *   - 段階的フォールバック（どの段階で失敗してもサービスは継続）
 *   - タイムアウト管理（GAS 6分制限対策）
 *   - max_tokens 4000→8000（詳細分析出力）
 *
 * デプロイ: ウェブアプリ → 誰でもアクセス可 → 新バージョン
 */

// ── グローバル: タイムアウト管理 ────────────────────────────
var SCRIPT_START = new Date().getTime();
var TIMEOUT_FETCH = 240000;  // fetchDocText打ち切り: 4分
var TIMEOUT_TOTAL = 330000;  // 全体打ち切り: 5.5分（6分制限にマージン）

// ── 決算短信キャッシュ Sheets ────────────────────────────
// fetch_tanshin.py が毎週月曜 11:30 JST に「決算短信_キャッシュ」シートに書き込む
var SPREADSHEET_ID = '1GtlVhGcPjMU0pJWsijwnmTe1rFJXAGvkaJFjav9gGcE';
var TANSHIN_CACHE_SHEET = '決算短信_キャッシュ';

function elapsed() { return new Date().getTime() - SCRIPT_START; }
function isTimeout(limit) { return elapsed() > limit; }

// ══════════════════════════════════════════════════════════════
// メインエントリポイント
// ══════════════════════════════════════════════════════════════

function doPost(e) {
  try {
    var params = JSON.parse(e.postData.contents);
    var secCode = params.secCode;
    var name = params.name || '';
    var scores = params.scores || {};

    Logger.log('START: ' + secCode + ' ' + name);

    // 1. EDINET検索 + 書類本文取得
    var edinetData = searchEdinet(secCode);
    Logger.log('EDINET: ' + elapsed() + 'ms, found=' + edinetData.found +
               ', hasText=' + (edinetData.docText ? edinetData.docText.length + 'chars' : 'none'));

    // 1b. 決算短信キャッシュ取得（経営者の生のトーン分析用）
    var tanshinData = fetchTanshinFromCache(secCode);
    Logger.log('TANSHIN: ' + elapsed() + 'ms, found=' + (tanshinData ? 'yes ' + (tanshinData.text || '').length + 'chars' : 'no'));

    // 2. データソース判定
    var dataSource = 'no_edinet';
    if (edinetData.found && edinetData.docText) {
      dataSource = 'full_text';
    } else if (edinetData.found) {
      dataSource = 'metadata_only';
    }
    if (tanshinData && tanshinData.text) {
      dataSource += '+tanshin';
    }

    // 3. 2段階API呼び出し（TPM制限30K回避）
    // Step A: Part A（スコア+短要約）
    var promptA = buildPrompt(secCode, name, scores, edinetData, dataSource, 'A', tanshinData);
    if (isTimeout(TIMEOUT_TOTAL)) {
      return jsonResponse({ ok: false, error: 'Timeout (' + elapsed() + 'ms)' });
    }
    var partA = callAI(promptA, 4000);
    Logger.log('PART_A DONE: ' + elapsed() + 'ms');

    // TPMリセット待機（61秒）
    Utilities.sleep(61000);

    // Step B: Part B（詳細レポート）
    var promptB = buildPrompt(secCode, name, scores, edinetData, dataSource, 'B', tanshinData);
    var partB = callAI(promptB, 8000);
    Logger.log('PART_B DONE: ' + elapsed() + 'ms');

    // 結合
    var analysis = partA;
    if (partB && partB.partB) analysis.partB = partB.partB;
    if (partB && partB.beginnerAdvice) analysis.beginnerAdvice = partB.beginnerAdvice;

    // 6. レスポンス
    return jsonResponse({
      ok: true,
      edinet: {
        found: edinetData.found,
        docType: edinetData.docType || '',
        docDescription: edinetData.docDescription || '',
        submitDate: edinetData.submitDate || '',
        filerName: edinetData.filerName || ''
      },
      tanshin: tanshinData ? {
        submitDate: tanshinData.submitDate,
        title: tanshinData.title,
        chars: (tanshinData.text || '').length
      } : null,
      analysis: analysis,
      dataSource: dataSource
    });

  } catch (err) {
    Logger.log('ERROR: ' + err.message);
    return jsonResponse({ ok: false, error: err.message });
  }
}

function doGet(e) {
  return jsonResponse({ status: 'kenja-proxy-v2', usage: 'POST with {secCode, name, scores}' });
}

function jsonResponse(obj) {
  return ContentService.createTextOutput(JSON.stringify(obj))
    .setMimeType(ContentService.MimeType.JSON);
}

// ══════════════════════════════════════════════════════════════
// 決算短信キャッシュ取得（fetch_tanshin.py が定期更新）
// ══════════════════════════════════════════════════════════════

/**
 * 決算短信_キャッシュ シートから銘柄コードに対応する決算短信を取得
 * 返却: { submitDate, title, text } または null
 */
function fetchTanshinFromCache(secCode) {
  try {
    var sec4 = String(secCode).substring(0, 4);
    var ss = SpreadsheetApp.openById(SPREADSHEET_ID);
    var sh = ss.getSheetByName(TANSHIN_CACHE_SHEET);
    if (!sh) {
      Logger.log('TANSHIN: cache sheet not found (run fetch_tanshin.yml first)');
      return null;
    }
    var data = sh.getDataRange().getValues();
    if (data.length < 2) return null;
    // ヘッダ: [銘柄コード, 提出日, 表題, 本文, 取得日]
    var latest = null;
    for (var i = 1; i < data.length; i++) {
      if (String(data[i][0]).substring(0, 4) === sec4) {
        var entry = {
          submitDate: String(data[i][1] || ''),
          title: String(data[i][2] || ''),
          text: String(data[i][3] || ''),
          fetchedAt: String(data[i][4] || ''),
        };
        if (!latest || entry.submitDate > latest.submitDate) {
          latest = entry;
        }
      }
    }
    return latest;
  } catch (e) {
    Logger.log('fetchTanshinFromCache error: ' + e.message);
    return null;
  }
}

// ══════════════════════════════════════════════════════════════
// EDINET API: 書類検索 + 本文取得
// ══════════════════════════════════════════════════════════════

/**
 * EDINET API: 直近90日の書類を検索し、最新の決算書類本文を取得
 * 返却: { found, docID, docType, docDescription, submitDate, filerName, docText }
 */
function searchEdinet(secCode) {
  var props = PropertiesService.getScriptProperties();
  var apiKey = props.getProperty('EDINET_API_KEY');
  if (!apiKey) return { found: false, reason: 'no_api_key' };

  // 5桁コード（末尾0付き）
  var sec5 = String(secCode);
  if (sec5.length === 4) sec5 = sec5 + '0';

  var today = new Date();
  var allDocs = [];

  // 直近90日を1日刻みで検索（EDINET APIは指定日の提出書類のみ返すため）
  // 見つかり次第終了するので、通常は数日分のAPI呼び出しで済む
  for (var d = 0; d < 90; d++) {
    if (isTimeout(120000)) break;  // 2分超で検索打ち切り

    var dt = new Date(today);
    dt.setDate(dt.getDate() - d);
    var dateStr = Utilities.formatDate(dt, 'Asia/Tokyo', 'yyyy-MM-dd');

    var url = 'https://api.edinet-fsa.go.jp/api/v2/documents.json?date=' + dateStr +
              '&type=2&Subscription-Key=' + apiKey;
    try {
      var resp = UrlFetchApp.fetch(url, { muteHttpExceptions: true });
      if (resp.getResponseCode() !== 200) continue;
      var json = JSON.parse(resp.getContentText());
      if (!json.results) continue;

      // メイン書類のみ収集（有価証券報告書/四半期報告書/半期報告書）
      // 自己株券買付報告書・臨時報告書等は分析に不向きなので無視
      var MAIN_FORMS = { '030000': true, '030001': true, '043000': true, '043001': true, '050000': true };
      for (var i = 0; i < json.results.length; i++) {
        var doc = json.results[i];
        if (doc.secCode === sec5 && MAIN_FORMS[doc.formCode]) {
          allDocs.push({
            docID: doc.docID,
            filerName: doc.filerName,
            docDescription: doc.docDescription,
            submitDateTime: doc.submitDateTime,
            ordinanceCode: doc.ordinanceCode,
            formCode: doc.formCode,
            periodStart: doc.periodStart,
            periodEnd: doc.periodEnd
          });
        }
      }
    } catch (e) {
      continue;
    }

    // メイン書類が見つかったら検索終了
    if (allDocs.length > 0) break;
    Utilities.sleep(300);  // APIレート制限対策
  }

  if (allDocs.length === 0) {
    return { found: false, reason: 'no_documents' };
  }

  // 書類の優先順位で選択（決算短信 > 有価証券報告書 > 四半期報告書 > その他）
  var selected = selectBestDoc(allDocs);
  var docType = getDocTypeName(selected.ordinanceCode, selected.formCode);

  // 書類本文の取得を試みる
  var docText = null;
  if (!isTimeout(TIMEOUT_FETCH)) {
    Utilities.sleep(3000);  // EDINETレート制限（3秒間隔推奨）
    docText = fetchDocText(selected.docID, apiKey);
  } else {
    Logger.log('TIMEOUT: fetchDocText skipped at ' + elapsed() + 'ms');
  }

  return {
    found: true,
    docID: selected.docID,
    filerName: selected.filerName,
    docDescription: selected.docDescription,
    submitDate: selected.submitDateTime,
    docType: docType,
    periodStart: selected.periodStart,
    periodEnd: selected.periodEnd,
    totalDocs: allDocs.length,
    docText: docText
  };
}

/**
 * 書類の優先順位で最適な書類を選択
 * 優先: 有価証券報告書(030000) > 四半期報告書(043000) > 半期報告書(050000) > その他
 */
function selectBestDoc(docs) {
  var priority = { '030000': 1, '043000': 2, '050000': 3 };
  docs.sort(function(a, b) {
    var pa = priority[a.formCode] || 99;
    var pb = priority[b.formCode] || 99;
    return pa - pb;
  });
  return docs[0];
}

function getDocTypeName(ordCode, formCode) {
  if (ordCode === '010' && formCode === '030000') return '有価証券報告書';
  if (ordCode === '010' && formCode === '043000') return '四半期報告書';
  if (ordCode === '010' && formCode === '030001') return '有価証券報告書(訂正)';
  if (ordCode === '010' && formCode === '043001') return '四半期報告書(訂正)';
  if (ordCode === '010' && formCode === '050000') return '半期報告書';
  if (ordCode === '030' && formCode === '030000') return '臨時報告書';
  return ordCode + '/' + formCode;
}

// ══════════════════════════════════════════════════════════════
// EDINET書類本文取得（XBRL ZIP → 解凍 → テキスト化）
// ══════════════════════════════════════════════════════════════

/**
 * EDINET API v2から書類ZIPを取得し、HTML本文をプレーンテキスト化して返す
 * 失敗時はnullを返す（フォールバック用）
 */
function fetchDocText(docID, apiKey) {
  try {
    // type=1: XBRL ZIP
    var url = 'https://api.edinet-fsa.go.jp/api/v2/documents/' + docID +
              '?type=1&Subscription-Key=' + apiKey;
    var resp = UrlFetchApp.fetch(url, { muteHttpExceptions: true });

    if (resp.getResponseCode() !== 200) {
      Logger.log('fetchDocText: HTTP ' + resp.getResponseCode());
      return null;
    }

    // ZIP解凍
    var blob = resp.getBlob();
    blob.setContentType('application/zip');
    var files;
    try {
      files = Utilities.unzip(blob);
    } catch (e) {
      Logger.log('fetchDocText: unzip failed: ' + e.message);
      return null;
    }

    if (!files || files.length === 0) {
      Logger.log('fetchDocText: ZIP empty');
      return null;
    }

    // 全HTMLファイルをファイル名順に結合（企業概況→事業→設備→会社→経理の順）
    var htmlFiles = [];
    for (var i = 0; i < files.length; i++) {
      var fname = files[i].getName().toLowerCase();
      if (fname.match(/\.htm[l]?$/) && !fname.match(/manifest|viewer/i)) {
        htmlFiles.push({ name: files[i].getName(), blob: files[i] });
      }
    }

    if (htmlFiles.length === 0) {
      Logger.log('fetchDocText: no HTML found in ZIP (' + files.length + ' files)');
      return null;
    }

    // ファイル名順にソート（0101010→0102010→...→0105020の順になる）
    htmlFiles.sort(function(a, b) { return a.name.localeCompare(b.name); });
    Logger.log('fetchDocText: ' + htmlFiles.length + ' HTML files found, concatenating...');

    // 全HTMLを結合してテキスト化
    var allText = '';
    for (var k = 0; k < htmlFiles.length; k++) {
      if (isTimeout(TIMEOUT_FETCH)) {
        Logger.log('fetchDocText: timeout at file ' + k + '/' + htmlFiles.length);
        break;
      }
      var htmlContent = htmlFiles[k].blob.getDataAsString('UTF-8');
      var sectionText = htmlToText(htmlContent);
      if (sectionText.length > 100) {  // 空ファイルをスキップ
        allText += '\n\n=== ' + htmlFiles[k].name + ' ===\n' + sectionText;
      }
    }

    var text = allText.trim();
    Logger.log('fetchDocText: total text ' + text.length + ' chars from ' + htmlFiles.length + ' files');

    // 30,000文字にトリム（OpenAI TPM 30K + 決算短信 5-15K の合算余裕を確保）
    // 有報の MD&A・事業等のリスクは先頭側に多い構造のため、ここでは単純先頭優先で十分
    if (text.length > 30000) {
      text = text.substring(0, 30000) + '\n\n[... 以降省略 ...]';
    }

    Logger.log('fetchDocText: text extracted, ' + text.length + ' chars');
    return text;

  } catch (e) {
    Logger.log('fetchDocText: error: ' + e.message);
    return null;
  }
}

/**
 * HTMLをプレーンテキストに変換
 * テーブル構造を維持しつつ、タグを除去
 */
function htmlToText(html) {
  // scriptとstyleを除去
  var text = html.replace(/<script[^>]*>[\s\S]*?<\/script>/gi, '');
  text = text.replace(/<style[^>]*>[\s\S]*?<\/style>/gi, '');

  // テーブル構造を維持するための変換
  text = text.replace(/<\/th>/gi, '\t');
  text = text.replace(/<\/td>/gi, '\t');
  text = text.replace(/<\/tr>/gi, '\n');
  text = text.replace(/<br\s*\/?>/gi, '\n');
  text = text.replace(/<\/p>/gi, '\n\n');
  text = text.replace(/<\/div>/gi, '\n');
  text = text.replace(/<\/h[1-6]>/gi, '\n\n');

  // 全タグ除去
  text = text.replace(/<[^>]+>/g, '');

  // HTMLエンティティ変換
  text = text.replace(/&nbsp;/g, ' ');
  text = text.replace(/&amp;/g, '&');
  text = text.replace(/&lt;/g, '<');
  text = text.replace(/&gt;/g, '>');
  text = text.replace(/&quot;/g, '"');
  text = text.replace(/&#\d+;/g, '');

  // 連続空白・空行を整理
  text = text.replace(/[ \t]+/g, ' ');
  text = text.replace(/\n\s*\n\s*\n/g, '\n\n');
  text = text.trim();

  return text;
}

// ══════════════════════════════════════════════════════════════
// プロンプト構築（Deep Insight v3）
// ══════════════════════════════════════════════════════════════

function buildPrompt(secCode, name, scores, edinetData, dataSource, part, tanshinData) {
  part = part || 'A';
  // ── スコア情報 ──
  var scoreInfo = '';
  if (scores.v42) {
    scoreInfo = '\n\n## Dashboard Score Data\n'
      + '- v4.3 Total: ' + scores.v42 + ' (Rank ' + (scores.rank || '?') + ')\n'
      + '- Variable1 Real ROIC: ' + (scores.s1 || '?') + 'pt\n'
      + '- Variable2 Trend: ' + (scores.s2 || '?') + 'pt\n'
      + '- Variable3 Price: ' + (scores.s3 || '?') + 'pt\n'
      + '- Short-term score: ' + (scores.shortScore || '?') + '\n'
      + '- Mid-term score: ' + (scores.midScore || '?') + '\n';
  }

  // ── 決算短信（経営者の生のトーン）──
  var tanshinSection = '';
  if (tanshinData && tanshinData.text) {
    var tText = String(tanshinData.text);
    if (tText.length > 15000) tText = tText.substring(0, 15000) + '\n\n[... 以降省略 ...]';
    tanshinSection = '\n\n## 直近の決算短信（経営者の生の言葉・最重要トーン分析資料）\n'
      + '提出日: ' + (tanshinData.submitDate || '') + '\n'
      + '表題: ' + (tanshinData.title || '') + '\n\n'
      + '--- 決算短信本文ここから ---\n'
      + tText + '\n'
      + '--- 決算短信本文ここまで ---\n'
      + '【決算短信の使い方】業績概要・業績予想の文言から「経営者の強気度」を判定せよ。'
      + '「順調に推移」「力強く拡大」=強気、「慎重に見守る」「不透明感」=弱気。'
      + '通期予想の据え置き/上方修正/下方修正は決定的シグナル。'
      + '有報のリスク開示は形式的に網羅的だが、決算短信はその時点の生のトーン。両者を比較せよ。\n';
  }

  // ── EDINET情報 ──
  var edinetSection = '';
  if (dataSource === 'full_text') {
    edinetSection = '\n\n## EDINET提出書類の全文（以下は実データです）\n'
      + '書類種別: ' + edinetData.docType + '\n'
      + '提出者: ' + edinetData.filerName + '\n'
      + '対象期間: ' + (edinetData.periodStart || '') + ' ~ ' + (edinetData.periodEnd || '') + '\n'
      + '提出日: ' + edinetData.submitDate + '\n\n'
      + '--- 書類本文ここから ---\n'
      + edinetData.docText + '\n'
      + '--- 書類本文ここまで ---\n';
  } else if (dataSource === 'metadata_only') {
    edinetSection = '\n\n## EDINET Filing (metadata only - full text unavailable)\n'
      + '- Document: ' + edinetData.docType + '\n'
      + '- Filed: ' + edinetData.submitDate + '\n'
      + '- Filer: ' + edinetData.filerName + '\n'
      + '⚠ Full text could not be retrieved. Use your knowledge of this company.\n';
  } else {
    edinetSection = '\n\n## EDINET: No filing found in last 90 days.\n'
      + '⚠ Use publicly available information. Note lower confidence.\n';
  }

  // ── メインプロンプト ──
  var dataInstruction = '';
  if (dataSource === 'full_text') {
    dataInstruction = '【最重要ルール】上記のEDINET書類の実データのみに基づいて分析してください。\n'
      + '- 書類に記載された具体的な数値（売上高、営業利益、営業利益率、前年比%等）を必ず引用すること\n'
      + '- セグメント別の売上・利益がある場合、絶好調のセグメントと不調のセグメントを特定すること\n'
      + '- キャッシュフロー（営業CF、投資CF、フリーCF）の具体的金額を記載すること\n'
      + '- 経営陣の業績予想（次期の売上・利益予想と前年比）を記載すること\n'
      + '- リスク要因を書類から具体的に抽出すること（「為替リスク」のような一般論ではなく、この会社固有のリスク）\n'
      + '- 推測は「推測ですが」と必ず明記すること\n'
      + '- 一般論・定型文は厳禁。この書類に書いてある事実だけを使うこと\n';
  } else {
    dataInstruction = '公開情報に基づいて分析してください。EDINET書類が取得できなかったため、'
      + '信頼度は下がります。可能な範囲で具体的な数値を使用してください。\n';
  }

  return 'あなたは「賢者」です。プロの証券アナリストであり、投資教育者です。\n'
    + name + '（証券コード: ' + secCode + '）を分析してください。\n'
    + '対象: 日本の個人投資家（50代以上の投資初心者）\n'
    + scoreInfo
    + tanshinSection
    + edinetSection
    + '\n' + dataInstruction
    + '\n## 【賢者の審判：AI 独自分析】\n'
    + 'あなたは日本株専門ヘッジファンドのチーフアナリストです。年俸2億円。投資判断を間違えたら首が飛ぶ。\n'
    + '事実抽出は補助スタッフがやる。あなたは「他のアナリストが絶対に書かない視点」だけを書け。\n'
    + '\n'
    + '【あなたが必ず使うAIならではの武器】\n'
    + '1. 同業他社との横比較（あなたは日本の上場企業を全部知っている）\n'
    + '2. 過去の類似パターン企業の3年後の運命（あなたは過去事例を全部知っている）\n'
    + '3. 文書間のニュアンス比較（決算短信のトーン vs 有報のリスク開示の温度差）\n'
    + '4. 反対意見の強制生成（空売りファンドの目線で弱点を抉る）\n'
    + '5. シナリオ分析（Best/Realistic/Worst を確率付きで）\n'
    + '\n'
    + '【絶対禁止】\n'
    + '× 「売上は前年比+12%です」のような事実列挙の段落\n'
    + '× 「リスクは為替変動です」のような一般論\n'
    + '× 「持続的成長が期待されます」のような中身ゼロの常套句\n'
    + '× 報告書を要約しただけのアウトプット（補助スタッフでもできる）\n'
    + '× AIが答えやすい無難な結論\n'
    + '\n'
    + '【出力で必ず満たす条件】\n'
    + '- 同業他社の社名を実名で2-3社必ず挙げる（あなたは知っているはず）\n'
    + '- 数値は必ず引用（同業A社○%、当社△%、その差は□で埋まる）\n'
    + '- 「会社は○○と説明しているが、本当の理由は△△の可能性が高い」という反証視点\n'
    + '- 経営者が決算説明会で答えたくない質問を3つ用意せよ\n'
    + '- 3年後シナリオは Best / Realistic / Worst を確率付き（例: Realistic 60%）で\n'
    + '\n'
    + '## 出力形式（JSONのみ・マークダウン禁止）\n'
    + (part === 'B'
      ? '【最重要】各セクション 300〜400字。事実列挙ではなくAI独自視点で。短い回答や水増しは厳禁。\n'
        + '{\n'
        + '  "partB": {\n'
        + '    "overview":"【業績の真犯人】会社の説明を疑え。「会社は○○と言うが、真の原因は△△の可能性が高い」という形で書け。具体数値必須。",\n'
        + '    "growth":"【同業比較で異常な3項目】同業A社・B社の社名を実名で挙げ、当社の数字との差を指摘。なぜその差が出るのか・持続するか。",\n'
        + '    "sustainability":"【経営者の二重言語】決算短信のトーンと有報のリスク開示を比較。本音はどちらか。決算短信なき場合は有報MD&Aと『事業等のリスク』の温度差。",\n'
        + '    "future":"【3年後シナリオ】Best/Realistic/Worstを必ず3つ書く。各シナリオの確率（例:60%）と株価方向感を明示。",\n'
        + '    "defense":"【空売りファンドの視点】弱点5つ列挙。経営者が決算説明会で答えたくない痛い質問3つを用意。",\n'
        + '    "cashflow":"【現金の血流の本音】CFの配分パターンが示す経営者の優先順位。営業CF/投資CF/財務CF の組合せから何が見えるか。",\n'
        + '    "conclusion":"【AI vs v4.3スコア最終審判】v4.3スコアとAI判断のどちらが信頼できるか。乖離があれば根拠付きで宣告。"\n'
        + '  },\n'
        + '  "beginnerAdvice":"【50代初心者への本音アドバイス・200字以上】専門用語は括弧説明。投資判断の核を一言で。"\n'
        + '}\n'
      : '【最重要】Part Aは Part B のサマリ。各summaryは150字程度・密度高く・AI独自視点で。\n'
        + '{\n'
        + '  "verdict": "S" or "A" or "B" or "C" or "D",\n'
        + '  "partA": {\n'
        + '    "businessResults": {"score":1-5,"title":"業績の真犯人","summary":"会社の説明を疑え。真の原因は何か。具体数値必須。"},\n'
        + '    "growthQuality": {"score":1-5,"title":"同業比較の異常値","summary":"同業A社・B社（実名）と比較した異常項目3つ。"},\n'
        + '    "sustainability": {"score":1-5,"title":"経営者の二重言語","summary":"決算短信vs有報のトーン乖離。本音は強気か慎重か。"},\n'
        + '    "outlook": {"score":1-5,"title":"3年後シナリオ","summary":"Best/Realistic/Worstと各確率。株価方向感。"},\n'
        + '    "defense": {"score":1-5,"title":"空売り視点の弱点5つ","summary":"経営者が答えたくない質問3つを含む。"},\n'
        + '    "cashFlow": {"score":1-5,"title":"現金の血流の本音","summary":"CF配分が示す経営優先順位。具体数値。"},\n'
        + '    "finalVerdict": {"credibility":"high"or"medium"or"low","reasons":["AIが信頼できる根拠1","2","3"]}\n'
        + '  },\n'
        + '  "alert": "v4.3スコアと実態の乖離警告。乖離があれば「Sランクなのに○○の懸念」のような形で。乖離無しならnull。"\n'
        + '}\n'
    )
    + '\n語り口:\n'
    + '- 自然な「です・ます」調・プロのアナリストが顧客に語る口調\n'
    + '- 専門用語は括弧で説明\n'
    + '- AIっぽい「〜と考えられます」「〜が期待されます」を避けよ。「〜です」「〜と判断します」と言い切れ\n'
    + '- 報告書のコピーではなく、あなたの頭で再構築した洞察を書け\n';
}

// ══════════════════════════════════════════════════════════════
// AI API呼び出し（OpenAI GPT-4o）
// ══════════════════════════════════════════════════════════════

function callAI(prompt, maxTokens) {
  maxTokens = maxTokens || 8000;
  var props = PropertiesService.getScriptProperties();
  var apiKey = props.getProperty('kenja-rich-api');
  if (!apiKey) throw new Error('kenja-rich-api not set in Script Properties');

  var systemPrompt = 'あなたは「賢者」です。温かみのある、経験豊富な証券アナリストです。'
    + '複雑な話題を初心者にもわかるように説明します。'
    + '全ての日本語は自然な「です・ます」調で、信頼できる友人に話すように書いてください。'
    + '具体的な数値を必ず使ってください。'
    + 'EDINET書類の実データが提供されている場合、一般論ではなく、その書類に書かれた具体的な数値・事実のみに基づいて分析してください。'
    + '書類にない情報を推測する場合は「推測ですが」と必ず明記してください。'
    + '常にJSON形式のみで回答してください。マークダウンやコードフェンスは使わないでください。';

  var resp = UrlFetchApp.fetch('https://api.openai.com/v1/chat/completions', {
    method: 'post',
    headers: {
      'Content-Type': 'application/json',
      'Authorization': 'Bearer ' + apiKey
    },
    payload: JSON.stringify({
      model: 'gpt-4o',
      max_tokens: maxTokens,
      temperature: 0.3,
      messages: [
        { role: 'system', content: systemPrompt },
        { role: 'user', content: prompt }
      ]
    }),
    muteHttpExceptions: true
  });

  var code = resp.getResponseCode();
  var body = JSON.parse(resp.getContentText());

  if (code !== 200) {
    throw new Error('OpenAI API error ' + code + ': ' + (body.error ? body.error.message : 'unknown'));
  }

  var text = body.choices && body.choices[0] ? body.choices[0].message.content : '';

  // JSON部分を抽出（前後の余分なテキストを除去）
  var jsonMatch = text.match(/\{[\s\S]*\}/);
  if (!jsonMatch) throw new Error('AI response is not valid JSON');

  try {
    return JSON.parse(jsonMatch[0]);
  } catch (e) {
    throw new Error('Failed to parse AI JSON: ' + e.message);
  }
}

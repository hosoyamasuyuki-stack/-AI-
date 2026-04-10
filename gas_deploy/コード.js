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

    // 2. データソース判定
    var dataSource = 'no_edinet';
    if (edinetData.found && edinetData.docText) {
      dataSource = 'full_text';
    } else if (edinetData.found) {
      dataSource = 'metadata_only';
    }

    // 3. 2段階API呼び出し（TPM制限30K回避）
    // Step A: Part A（スコア+短要約）
    var promptA = buildPrompt(secCode, name, scores, edinetData, dataSource, 'A');
    if (isTimeout(TIMEOUT_TOTAL)) {
      return jsonResponse({ ok: false, error: 'Timeout (' + elapsed() + 'ms)' });
    }
    var partA = callAI(promptA, 4000);
    Logger.log('PART_A DONE: ' + elapsed() + 'ms');

    // TPMリセット待機（61秒）
    Utilities.sleep(61000);

    // Step B: Part B（詳細レポート）
    var promptB = buildPrompt(secCode, name, scores, edinetData, dataSource, 'B');
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

    // 20,000文字にトリム（OpenAI TPM制限30,000トークン対策）
    if (text.length > 20000) {
      text = text.substring(0, 20000) + '\n\n[... 以降省略 ...]';
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

function buildPrompt(secCode, name, scores, edinetData, dataSource, part) {
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
    + edinetSection
    + '\n' + dataInstruction
    + '\n## 分析フレームワーク（7セクション「ディープ・インサイト」）\n'
    + '\n'
    + '1. 業績の正体 — 売上・利益の増減とその真因。最も業績を牽引しているセグメントと最も弱いセグメントを特定。\n'
    + '   前年比の数値を必ず含める。「増収増益」のような曖昧表現ではなく、具体的%変化を記載。\n'
    + '\n'
    + '2. 成長の質 — 何で伸びているか（新製品/値上げ/数量増/M&A/為替/その他）を特定。\n'
    + '   営業利益率の変化とその理由。この会社だけの独自の強み・弱みは何か。\n'
    + '\n'
    + '3. 持続力 — 構造的成長か一過性か。外部依存度（為替・特定顧客・政策等）。\n'
    + '   同業他社と比較した場合のポジション。\n'
    + '\n'
    + '4. 未来への展望 — 会社発表の業績予想（売上・利益の前年比%）。\n'
    + '   経営陣の温度感（慎重/中立/強気）を具体的な根拠とともに。予想の透明度（1-5星）。\n'
    + '\n'
    + '5. リスクの特定（防御度）— 上位2-3リスクを具体的に特定。\n'
    + '   会社の対策の有無と十分性。投資家として最も気を付けるべき点。\n'
    + '   Score 1-5（5=防御万全, 1=重大リスクあり）。\n'
    + '\n'
    + '6. 資金の血流 — 営業CF・投資CF・フリーCFの具体的な金額。\n'
    + '   現金創出力の実態。設備投資の過大/過小。財務健全性。\n'
    + '\n'
    + '7. 最終審判 — この会社の「勝ち筋」は信頼できるか。\n'
    + '   ダッシュボードのv4.3スコアとの乖離がないか確認。\n'
    + '   直近で何か変わったことはないか（スコアがまだ反映していない変化）。\n'
    + '\n'
    + '## 出力形式\n'
    + 'JSON形式のみ出力してください（マークダウンやコードフェンス不要）。\n'
    + (part === 'B'
      ? '【最重要】これは詳細レポートです。各セクション最低400文字以上で丁寧に書いてください。短い回答は厳禁。\n'
        + '{\n'
        + '  "partB": {\n'
        + '    "overview":"【400字以上】売上・利益の増減額と前年比%。セグメント別の好調・不調を名指し。会社の意気込みと経営方針。業界ポジション。",\n'
        + '    "growth":"【400字以上】成長エンジン解剖。営業利益率変化と理由。独自の強みと競争優位性。業界トレンド。",\n'
        + '    "sustainability":"【400字以上】構造的か一過性か。外部依存度。同業他社比較。3-5年見通し。",\n'
        + '    "future":"【400字以上】業績予想数値。経営陣の温度感。投資戦略。予想透明度。",\n'
        + '    "defense":"【400字以上】上位2-3リスク名指し。対策の有無。最も気を付けるべき1点。",\n'
        + '    "cashflow":"【400字以上】営業CF・投資CF・FCF金額。株主還元。財務安全性。",\n'
        + '    "conclusion":"【400字以上】初心者への本音。勝ち筋の信頼性。買い時判断。見落としポイント。"\n'
        + '  },\n'
        + '  "beginnerAdvice":"【200字以上】50代初心者への丁寧なアドバイス。専門用語に括弧説明。"\n'
        + '}\n'
      : '{\n'
        + '  "verdict": "S" or "A" or "B" or "C" or "D",\n'
        + '  "partA": {\n'
        + '    "businessResults": {"score":1-5,"title":"鋭いタイトル","summary":"8-12文。売上・利益の増減と好調・不調事業。"},\n'
        + '    "growthQuality": {"score":1-5,"title":"...","summary":"8-12文。成長エンジン。営業利益率変化。"},\n'
        + '    "sustainability": {"score":1-5,"title":"...","summary":"8-12文。構造的か一過性か。"},\n'
        + '    "outlook": {"score":1-5,"title":"...","summary":"8-12文。公式予想と温度感。"},\n'
        + '    "defense": {"score":1-5,"title":"...","summary":"8-12文。上位リスク名指し。"},\n'
        + '    "cashFlow": {"score":1-5,"title":"...","summary":"8-12文。CF具体金額。"},\n'
        + '    "finalVerdict": {"credibility":"high"or"medium"or"low","reasons":["r1","r2","r3"]}\n'
        + '  },\n'
        + '  "alert": "スコアと実態の乖離警告。なければnull。"\n'
        + '}\n'
    )
    + '\n重要ルール:\n'
    + '- 全て自然な日本語「です・ます」調。機械的な箇条書きではなく、信頼できる友人に説明する口調。\n'
    + '- 数値は必ず書類から引用（売上+12.3%, 営業利益率8.2%→9.1%）。曖昧な表現禁止。\n'
    + '- 専門用語には必ず簡単な説明を括弧内に添える。\n'
    + '- リスクは美化しない。正直に。\n'
    + '- Part Bは雑誌記事のように読みやすく。AIの出力ではなくプロのアナリストの語り口。\n'
    + '- "alert"フィールドが最重要: v4.3スコアと直近実態の乖離を検出せよ。\n';
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

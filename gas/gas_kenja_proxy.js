/**
 * 賢者の審判 GASプロキシ
 *
 * スクリプトプロパティに以下を設定:
 *   EDINET_API_KEY  : EDINET APIキー
 *   kenja-rich-api  : OpenAI APIキー（GPT-4o使用）
 *
 * デプロイ: ウェブアプリ → 誰でもアクセス可 → 新バージョン
 */

function doPost(e) {
  try {
    var params = JSON.parse(e.postData.contents);
    var secCode = params.secCode;
    var name = params.name || '';
    var scores = params.scores || {};

    // 1. EDINET検索
    var edinetData = searchEdinet(secCode);

    // 2. プロンプト構築
    var prompt = buildPrompt(secCode, name, scores, edinetData);

    // 3. AI API呼び出し（OpenAI GPT-4o）
    var analysis = callAI(prompt);

    // 4. レスポンス
    return ContentService.createTextOutput(JSON.stringify({
      ok: true,
      edinet: edinetData,
      analysis: analysis
    })).setMimeType(ContentService.MimeType.JSON);

  } catch (err) {
    return ContentService.createTextOutput(JSON.stringify({
      ok: false,
      error: err.message
    })).setMimeType(ContentService.MimeType.JSON);
  }
}

function doGet(e) {
  return ContentService.createTextOutput(JSON.stringify({
    status: 'kenja-proxy-v1',
    usage: 'POST with {secCode, name, scores}'
  })).setMimeType(ContentService.MimeType.JSON);
}

/**
 * EDINET API: 直近90日の書類を検索し、指定銘柄の最新決算書類を返す
 */
function searchEdinet(secCode) {
  var props = PropertiesService.getScriptProperties();
  var apiKey = props.getProperty('EDINET_API_KEY');
  if (!apiKey) return { found: false, reason: 'no_api_key' };

  // 5桁コード（末尾0付き）
  var sec5 = String(secCode);
  if (sec5.length === 4) sec5 = sec5 + '0';

  var today = new Date();
  var docs = [];

  // 直近90日を検索（1日ずつAPIを叩く）
  // 効率化：7日刻みで検索し、ヒットしたら詳細検索
  for (var d = 0; d < 90; d += 7) {
    var dt = new Date(today);
    dt.setDate(dt.getDate() - d);
    var dateStr = Utilities.formatDate(dt, 'Asia/Tokyo', 'yyyy-MM-dd');

    var url = 'https://api.edinet-fsa.go.jp/api/v2/documents.json?date=' + dateStr + '&type=2&Subscription-Key=' + apiKey;

    try {
      var resp = UrlFetchApp.fetch(url, { muteHttpExceptions: true });
      if (resp.getResponseCode() !== 200) continue;

      var json = JSON.parse(resp.getContentText());
      if (!json.results) continue;

      for (var i = 0; i < json.results.length; i++) {
        var doc = json.results[i];
        if (doc.secCode === sec5) {
          docs.push({
            docID: doc.docID,
            edinetCode: doc.edinetCode,
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
      // API呼び出しエラーは無視して次の日付へ
      continue;
    }

    // 書類が見つかったら終了
    if (docs.length > 0) break;
  }

  if (docs.length === 0) {
    return { found: false, reason: 'no_documents' };
  }

  // 最新の書類を返す
  var latest = docs[0];

  // 書類種別の日本語名
  var docType = getDocTypeName(latest.ordinanceCode, latest.formCode);

  return {
    found: true,
    docID: latest.docID,
    filerName: latest.filerName,
    docDescription: latest.docDescription,
    submitDate: latest.submitDateTime,
    docType: docType,
    periodStart: latest.periodStart,
    periodEnd: latest.periodEnd,
    totalDocs: docs.length
  };
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

/**
 * Deep Insight v2プロンプト構築
 */
function buildPrompt(secCode, name, scores, edinetData) {
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

  var edinetInfo = '';
  if (edinetData.found) {
    edinetInfo = '\n\n## Latest EDINET Filing\n'
      + '- Document: ' + edinetData.docType + '\n'
      + '- Description: ' + edinetData.docDescription + '\n'
      + '- Filed: ' + edinetData.submitDate + '\n'
      + '- Period: ' + (edinetData.periodStart || '') + ' to ' + (edinetData.periodEnd || '') + '\n'
      + '- Filer: ' + edinetData.filerName + '\n';
  } else {
    edinetInfo = '\n\n## EDINET Filing: Not found in last 90 days. Use public information.\n';
  }

  return 'You are "The Sage" - a professional securities analyst and investment educator.\n'
    + 'Analyze ' + name + ' (code: ' + secCode + ') for a Japanese individual investor (beginner, age 50+).\n'
    + 'Use the latest publicly available financial data (earnings reports, financial statements) for this company.\n'
    + scoreInfo
    + edinetInfo
    + '\n## Analysis Framework (7 Sections - "Deep Insight")\n'
    + 'Analyze this company through these 7 lenses:\n'
    + '\n'
    + '1. BUSINESS RESULTS - Sales trend (increase/decrease/flat, % change, main driver).\n'
    + '   Profit trend (increase/decrease/flat, % change, root cause).\n'
    + '   Best performing segment vs worst performing segment.\n'
    + '\n'
    + '2. GROWTH QUALITY - What is driving revenue? (new products, pricing, volume, M&A, FX, other)\n'
    + '   Operating margin change and why.\n'
    + '\n'
    + '3. SUSTAINABILITY - Is the growth structural (real capability) or temporary (one-time)?\n'
    + '   External dependency level (low/medium/high).\n'
    + '\n'
    + '4. OUTLOOK - Official guidance (revenue/profit forecast, YoY %).\n'
    + '   Management tone (cautious/neutral/bullish) with evidence.\n'
    + '   Transparency of forecast basis (1-5 stars).\n'
    + '\n'
    + '5. DEFENSE (防御度) - Identify top 2-3 risks.\n'
    + '   Does the company have countermeasures? Score 1-5 (5=very well defended, few risks; 1=many severe risks, no countermeasures).\n'
    + '\n'
    + '6. CASH FLOW - Operating CF, Investing CF, Free CF.\n'
    + '   Is the company generating cash after investment? Healthy or concerning?\n'
    + '\n'
    + '7. FINAL VERDICT - Is this company\'s "winning formula" trustworthy?\n'
    + '   Compare with dashboard v4.3 score. Flag any discrepancy.\n'
    + '   Key question: Has anything changed recently that the score hasn\'t caught yet?\n'
    + '\n'
    + '## Output Requirements\n'
    + 'Output ONLY valid JSON (no markdown, no code fences). Use this exact structure:\n'
    + '{\n'
    + '  "verdict": "S" or "A" or "B" or "C" or "D",\n'
    + '  "partA": {\n'
    + '    "businessResults": {"score":1-5,"title":"short title in Japanese","summary":"2-3 sentences in Japanese. Include sales/profit % change."},\n'
    + '    "growthQuality": {"score":1-5,"title":"...","summary":"2-3 sentences. What is the growth engine?"},\n'
    + '    "sustainability": {"score":1-5,"title":"...","summary":"2-3 sentences. Structural or temporary?"},\n'
    + '    "outlook": {"score":1-5,"title":"...","summary":"2-3 sentences. Management tone and forecast."},\n'
    + '    "defense": {"score":1-5,"title":"...","summary":"2-3 sentences. Top risk and countermeasure. 5=well defended, 1=vulnerable."},\n'
    + '    "cashFlow": {"score":1-5,"title":"...","summary":"2-3 sentences. FCF status."},\n'
    + '    "finalVerdict": {"credibility":"high" or "medium" or "low","reasons":["reason1","reason2","reason3"]}\n'
    + '  },\n'
    + '  "partB": {\n'
    + '    "overview":"3-5 sentences in Japanese. Overall picture of business results.",\n'
    + '    "growth":"3-5 sentences. Dissect the growth drivers.",\n'
    + '    "sustainability":"3-5 sentences. Will this momentum continue?",\n'
    + '    "future":"3-5 sentences. Management outlook and its credibility.",\n'
    + '    "defense":"3-5 sentences. What could go wrong and how well is the company prepared?",\n'
    + '    "cashflow":"3-5 sentences. Cash flow health assessment.",\n'
    + '    "conclusion":"3-5 sentences. Bottom line for a beginner investor."\n'
    + '  },\n'
    + '  "alert": "If something has recently changed that contradicts the dashboard score, describe it here in 1-2 sentences Japanese. Otherwise null.",\n'
    + '  "beginnerAdvice": "2-3 sentences simple advice in Japanese for a 50-year-old beginner investor"\n'
    + '}\n'
    + '\nCritical rules:\n'
    + '- ALL Japanese text in natural, warm "です・ます" style. NOT mechanical bullet points.\n'
    + '- Write as if explaining to a trusted friend over coffee, not writing a report.\n'
    + '- Use concrete numbers (売上+12%, 営業利益率8.2%→9.1%) instead of vague descriptions.\n'
    + '- If you use a financial term, add a simple explanation in parentheses.\n'
    + '- Score 1-5: 1=very poor, 2=poor, 3=average, 4=good, 5=excellent\n'
    + '- Be honest about risks, do not sugarcoat.\n'
    + '- The "alert" field is the MOST IMPORTANT output: flag if recent data contradicts the v4.3 score.\n'
    + '- Part B must read like a magazine article, not an AI output. Use storytelling.\n';
}

/**
 * AI API呼び出し（OpenAI GPT-4o）
 *
 * スクリプトプロパティ kenja-rich-api が必要。
 * レスポンスからJSON部分を抽出してパースする。
 */
function callAI(prompt) {
  var props = PropertiesService.getScriptProperties();
  var apiKey = props.getProperty('kenja-rich-api');
  if (!apiKey) throw new Error('kenja-rich-api not set');

  var resp = UrlFetchApp.fetch('https://api.openai.com/v1/chat/completions', {
    method: 'post',
    headers: {
      'Content-Type': 'application/json',
      'Authorization': 'Bearer ' + apiKey
    },
    payload: JSON.stringify({
      model: 'gpt-4o',
      max_tokens: 4000,
      temperature: 0.3,
      messages: [
        { role: 'system', content: 'You are "The Sage" - a warm, experienced securities analyst who explains complex topics simply. Write all Japanese in natural です・ます style, as if talking to a trusted friend. Be specific with numbers. Always respond with valid JSON only, no markdown.' },
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

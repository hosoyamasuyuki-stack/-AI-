#!/usr/bin/env python3
"""
fetch_tanshin.py
TDnet（東証適時開示）から保有・監視銘柄の決算短信PDFを取得し、
テキスト化してGoogle Sheetsの「決算短信_キャッシュ」シートに格納する。

GitHub Actions: 毎日 11:30 JST 自動実行（cron '30 2 * * *' UTC・案 X' 2026-05-20）

機能:
  1. 直近31日のTDnet日次インデックスをスクレイプ（TDnet 31 日上限）
     ＋ EDINET（過去90日・日付インデックス走査）で全銘柄の最新の有報/半期/四半期を取得（System B・2026-06-09）
  2. 保有銘柄+監視銘柄の決算短信PDFを特定（訂正・補足は除外）
  3. PDFをダウンロード→pdfplumberでテキスト化（先頭20ページ）
  4. Sheetsに [銘柄コード, 提出日, 表題, 本文, 取得日] でupsert

GAS『賢者の審判』はこのキャッシュを SpreadsheetApp.openById で読む。
"""

import io
import os
import re
import sys
import time
import zipfile  # CEO 通達 2026-06-04: EDINET 書類 ZIP 解凍用
from datetime import datetime, timedelta, timezone

import gspread
import pdfplumber
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from bs4 import BeautifulSoup

from core.config import SPREADSHEET_ID
from core.auth import get_spreadsheet

JST = timezone(timedelta(hours=9))
TDNET_BASE = 'https://www.release.tdnet.info/inbs'
LOOKBACK_DAYS = 31  # C-3: 35 → 31（TDnet 31 日上限制約・KB §2.2 整合）
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (compatible; RICH-KAIZEN/1.0; '
                  '+https://github.com/hosoyamasuyuki-stack/-AI-)'
}


def _make_session():
    """3者協議採用（SPEC v1.0 §3.2/§7/§13）: 指数バックオフ付きリトライ Session。

    TDnet の一時的 5xx/429/接続断でページ走査が中断し被覆率が落ちるのを防ぐ。
    全ページ走査（被覆率根治）と一体で入れるべき対策（HTTP リクエスト数が増えるため）。
    リトライ全敗時は通常レスポンス/例外を返すので、最悪でも従来挙動と同等。
    """
    s = requests.Session()
    retry = Retry(
        total=3, connect=3, read=3,
        backoff_factor=1.5,  # 待機 0 / 1.5 / 3.0 ... 秒
        status_forcelist=(429, 500, 502, 503, 504),
    )
    adapter = HTTPAdapter(max_retries=retry)
    s.mount('https://', adapter)
    s.mount('http://', adapter)
    return s


SESSION = _make_session()

CACHE_SHEET = '決算短信_キャッシュ'
HOLDINGS_SHEET = '保有銘柄_v4.3スコア'
WATCHLIST_SHEET = '監視銘柄_v4.3スコア'
# CEO 通達 2026-06-04: Top75 も cron 対象に追加（顧客スキャン時のエラー/遅延防止）
# スクリーニング_Top50 は実体 150 社保存・表示は上位 75 社（generate_dashboard.py L953）。
# 全件キャッシュ対象とし、月次変動で Top75 入れ替わっても顧客側で未キャッシュ事故を防ぐ。
SCREENING_SHEET = 'スクリーニング_Top50'
MAX_TEXT_CHARS = 50000   # Sheets セル上限 50,000 文字
MIN_TEXT_CHARS = 500     # これ未満は画像PDF/抽出失敗とみなし取得失敗扱い（QA レビュー指摘）
MAX_PDF_PAGES = 25

# System B (2026-06-09): dry-run（Sheet 書込・Storage put をスキップし取得/判定のみ）。
# 環境変数 DRY_RUN=1 または引数 --dry-run。CI の workflow_dispatch から安全に実データ検証する用途。
DRY_RUN = ('--dry-run' in sys.argv) or (os.environ.get('DRY_RUN', '').strip().lower() in ('1', 'true', 'yes'))

# CEO 通達 2026-06-04: EDINET 補完設定（TDnet 35 日制約の構造的解決）
# 賢者 GAS の searchEdinet を Python 移植。決算短信が取れない過去分を有価証券
# 報告書・四半期報告書・半期報告書で代替する。
EDINET_API_KEY = os.environ.get('EDINET_API_KEY', '')
EDINET_API_BASE = 'https://api.edinet-fsa.go.jp/api/v2'
EDINET_LOOKBACK_DAYS = 90
EDINET_MAIN_FORMS = {'030000', '030001', '043000', '043001', '050000'}
EDINET_FORM_PRIORITY = {'030000': 1, '030001': 2, '043000': 3, '043001': 4, '050000': 5}
# System B (2026-06-09): 旧 EDINET_STALE_DAYS(31日ゲート)は廃止。全銘柄を日付インデックス
# 走査で常時チェックし、短信の鮮度に関係なく最新の有報/半期を取り込む（B-1）。

# P-1: Supabase Storage 設定（E-2 secret 経由・販売前バックエンドのみ）
SUPABASE_URL = os.environ.get('SUPABASE_URL', '')
SUPABASE_SERVICE_KEY = os.environ.get('SUPABASE_SERVICE_KEY', '')
PDF_BUCKET = 'tanshin-pdf'


def get_supabase_client():
    """P-1: Supabase Storage クライアント取得。secret 未設定時は None"""
    if not SUPABASE_URL or not SUPABASE_SERVICE_KEY:
        print('[INFO] SUPABASE_URL/SUPABASE_SERVICE_KEY not set; PDF Storage put skipped', file=sys.stderr)
        return None
    try:
        from supabase import create_client
        return create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)
    except Exception as e:
        print(f'[WARN] supabase create_client failed: {e}', file=sys.stderr)
        return None


def upload_pdf_to_storage(sb, code, submit_date, pdf_bytes, is_correction=False):
    """P-1-b/d: Supabase Storage に PDF を put + MIME 検証

    命名規則 (v0.6 N-1): {code}/{submit_date}_{N|A}.pdf
      N = 通常版 / A = 訂正版（訂正版上書き破壊防止）

    MIME 検証 (v0.6 N-4): PDF ヘッダ (b'%PDF') 確認
    """
    if not sb:
        return None
    if not pdf_bytes or len(pdf_bytes) < 4 or pdf_bytes[:4] != b'%PDF':
        print(f'    [WARN] not a valid PDF (no %PDF header) for {code}/{submit_date}', file=sys.stderr)
        return None
    amendment_flag = 'A' if is_correction else 'N'
    path = f'{code}/{submit_date}_{amendment_flag}.pdf'
    try:
        sb.storage.from_(PDF_BUCKET).upload(
            path=path,
            file=pdf_bytes,
            file_options={'content-type': 'application/pdf', 'upsert': 'true'},
        )
        return path
    except Exception as e:
        print(f'    [WARN] upload_pdf_to_storage failed for {code}/{submit_date}: {e}', file=sys.stderr)
        return None


def get_target_codes(ss):
    """保有+監視+Top75スクリーニング銘柄コードを取得（C-5: 4桁数字 OR 末尾アルファベット銘柄 130A/212A 等を含む）

    CEO 通達 2026-06-04: Top75 を cron 対象に追加（顧客スキャン時のエラー/遅延防止）。
    Top75 は月次変動するため、cron で全件キャッシュ取得しておかないと、
    新規 Top75 入りした未キャッシュ銘柄を顧客がスキャン → 都度 PDF 取得 → エラー/遅延発生。
    """
    codes = set()
    sec_code_re = re.compile(r'^[0-9]{3}[0-9A-Z]$')
    for sheet_name in (HOLDINGS_SHEET, WATCHLIST_SHEET, SCREENING_SHEET):
        try:
            ws = ss.worksheet(sheet_name)
            data = ws.col_values(1)[1:]
            for v in data:
                v = (v or '').strip().upper()
                if sec_code_re.fullmatch(v):
                    codes.add(v)
        except Exception as e:
            print(f'[WARN] {sheet_name} 読込失敗: {e}', file=sys.stderr)
    return codes


def fetch_tdnet_index(date):
    """TDnet 日次インデックス → 行リスト（全ページ走査）

    被覆率根治（2026-05-20）: 決算短信ピーク日は TDnet が開示一覧を
    I_list_001 / I_list_002 / ... と複数ページに分割する（2026-05-14 は
    23 ページ・744 社開示）。旧実装は I_list_001（1 ページ目・約 106 件）
    しか読まず、保有/監視銘柄を大量に取りこぼしていた（2026-05 実測：
    5/12-19 に決算短信を出した顧客対象 60 社が全て page2 以降 →
    1 ページ走査では 0 社取得＝被覆率 9.4% の真因）。
    HTTP 200 が返る限り次ページを走査する。
    """
    date_str = date.strftime('%Y%m%d')
    rows = []
    consecutive_errors = 0
    MAX_CONSECUTIVE_ERRORS = 3
    for page in range(1, 40):
        url = f'{TDNET_BASE}/I_list_{page:03d}_{date_str}.html'
        try:
            r = SESSION.get(url, headers=HEADERS, timeout=30)
        except Exception as e:
            # 被覆率根治の補強（2026-05-20 エンジニア独立レビュー指摘 重要①）:
            # 旧実装は例外時に break し、5xx が _make_session の 3 回リトライ後も
            # 失敗すると例外（RetryError 等）で「その日の残ページを丸ごと放棄」
            # していた（全ページ走査で被覆率を根治した直後の取りこぼし経路）。
            # 次ページを continue で試みて単一ページの一過性障害から復旧する。
            # ただし TDnet 全体障害で全ページが例外になり 31 日分ループが
            # 暴走するのを防ぐため、連続例外が閾値に達したらその日を打ち切る
            # （存在しないページは 404 を返すので、連続「例外」は障害の指標）。
            consecutive_errors += 1
            print(f'  [ERR] {url}: {e} (consecutive={consecutive_errors})', file=sys.stderr)
            if consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
                print(f'  [ERR] {date_str}: 連続 {consecutive_errors} ページ取得失敗 '
                      f'— その日の走査を打ち切り（被覆率ゲートで検知）', file=sys.stderr)
                break
            # 5xx 連打抑制（独立エンジニアレビュー指摘）: continue は末尾の
            # time.sleep(0.2) を飛ばすため、例外時は明示的にバックオフして
            # TDnet への無待機連打（自己 DoS・マナー違反）を防ぐ。
            time.sleep(1.5 * consecutive_errors)
            continue
        consecutive_errors = 0
        if r.status_code != 200:
            break  # 存在しないページ番号 → その日の走査終了
        r.encoding = r.apparent_encoding or 'shift_jis'
        soup = BeautifulSoup(r.text, 'html.parser')
        for tr in soup.find_all('tr'):
            cells = tr.find_all('td')
            if len(cells) < 5:
                continue
            time_str = cells[0].get_text(strip=True)
            code_raw = cells[1].get_text(strip=True).strip().upper()
            # C-5: 4桁数字 OR 末尾アルファベット銘柄（130A/212A 等）に対応
            m = re.match(r'([0-9]{3}[0-9A-Z])', code_raw)
            if not m:
                continue
            code = m.group(1)
            name = cells[2].get_text(strip=True)
            title_cell = cells[3]
            title = title_cell.get_text(strip=True)
            link = title_cell.find('a')
            pdf_url = None
            if link and link.get('href'):
                href = link['href']
                if href.lower().endswith('.pdf'):
                    pdf_url = f'{TDNET_BASE}/{href}'
            rows.append({
                'time': time_str, 'code': code, 'name': name,
                'title': title, 'pdf_url': pdf_url,
            })
        time.sleep(0.2)  # TDnet マナー（ページ間）
    return rows


def is_target_tanshin(title):
    if not title:
        return False
    if '決算短信' not in title:
        return False
    # 訂正・差替・修正は除外（経営者の生のトーンが分かる初出のみ）
    for ng in ('訂正', '修正', '差替', '差替え', '一部訂正'):
        if ng in title:
            return False
    return True


def extract_pdf_text(pdf_url, code=None, submit_date=None, sb=None):
    """PDFをダウンロード→先頭ページをテキスト化 + P-1 Supabase Storage put

    Returns:
        tuple: (text, pdf_path)
          text: 抽出テキスト or None
          pdf_path: Storage 保存パス or None
    """
    try:
        r = SESSION.get(pdf_url, headers=HEADERS, timeout=60)
    except Exception as e:
        print(f'    [ERR] PDF DL失敗 {pdf_url}: {e}', file=sys.stderr)
        return None, None
    if r.status_code != 200:
        print(f'    [ERR] PDF HTTP {r.status_code}: {pdf_url}', file=sys.stderr)
        return None, None
    # 3者協議採用（SPEC v1.0 §13 No.3）: PDF ヘッダ検証。HTML エラーページ等を
    # pdfplumber に渡して空テキスト化＝静かな取りこぼしになるのを防ぐ。
    if not r.content.startswith(b'%PDF'):
        ct = (r.headers.get('Content-Type') or '?').lower()
        print(f'    [ERR] PDF ヘッダ欠如 (Content-Type={ct}): {pdf_url}', file=sys.stderr)
        return None, None
    # P-1: Supabase Storage に put（テキスト抽出と並行）
    pdf_path = None
    if sb and code and submit_date:
        pdf_path = upload_pdf_to_storage(sb, code, submit_date, r.content, is_correction=False)
    text_parts = []
    try:
        with pdfplumber.open(io.BytesIO(r.content)) as pdf:
            for i, page in enumerate(pdf.pages):
                if i >= MAX_PDF_PAGES:
                    break
                t = page.extract_text() or ''
                if t.strip():
                    text_parts.append(t)
    except Exception as e:
        print(f'    [ERR] PDF parse {pdf_url}: {e}', file=sys.stderr)
        return None, pdf_path
    text = '\n\n'.join(text_parts)
    text = re.sub(r'\n{3,}', '\n\n', text)
    text = text.strip()
    # QA 独立レビュー指摘: 画像スキャン PDF・テキスト埋め込みなし PDF は
    # pdfplumber が空〜極少のテキストしか返さない。%PDF ヘッダ検証は通るため
    # 「決算短信を取得した」と誤計上され、賢者がほぼ空の本文を分析してしまう。
    # 真正な決算短信はサマリー情報だけで数千字あるため、極端に短い抽出結果は
    # 取得失敗（None）として扱い、Sheet キャッシュに格納しない。
    if len(text) < MIN_TEXT_CHARS:
        print(f'    [ERR] 抽出テキスト過少 ({len(text)}字 < {MIN_TEXT_CHARS}・'
              f'画像PDF/抽出失敗の疑い): {pdf_url}', file=sys.stderr)
        return None, pdf_path
    if len(text) > MAX_TEXT_CHARS:
        text = text[:MAX_TEXT_CHARS] + '\n\n[... 以降省略 ...]'
    return text, pdf_path


def ensure_cache_sheet(ss):
    """P-1-c: Sheet 'F 列 pdf_path' に対応"""
    try:
        ws = ss.worksheet(CACHE_SHEET)
    except gspread.exceptions.WorksheetNotFound:
        ws = ss.add_worksheet(title=CACHE_SHEET, rows=300, cols=6)
        ws.update('A1:F1', [['銘柄コード', '提出日', '表題', '本文', '取得日', 'pdf_path']])
    return ws


def load_existing(ws):
    """code -> submit_date のキャッシュ済 dict"""
    out = {}
    rows = ws.get_all_values()[1:]
    for r in rows:
        if len(r) >= 2 and r[0]:
            # M-2 (2026-06-05): 同一コードが複数行ある場合は最新の提出日を採用。
            # 'YYYY-MM-DD' は辞書順＝時系列順のため max で最新が残る
            # （旧実装の「最終行勝ち」だと行順次第で古い日付に化ける不安定さを排除）。
            out[r[0]] = max(out.get(r[0], ''), r[1] or '')
    return out


def upsert(ws, code, submit_date, title, text, pdf_path=None):
    """既存行更新 or 追加 + P-1-c: F 列 pdf_path

    CEO 通達 2026-06-04: Sheets セル 50,000 字制限による sheet write 失敗
    （1928 積水ハウス / 6432 竹内製作所 有報事案）を構造的に防ぐため、
    MAX_TEXT_CHARS 超過時は末尾を切り詰めて投入。投資判断に必要な
    要約・サマリーは冒頭にあるため影響軽微。
    """
    if DRY_RUN:
        print(f'    [DRY-RUN] would upsert {code} {submit_date} {str(title)[:50]} ({len(text or "")}字)', flush=True)
        return
    if text and len(text) > MAX_TEXT_CHARS:
        truncated_marker = f'\n\n[... 元文書 {len(text):,} 字 / Sheets セル制限により末尾 truncate ...]'
        text = text[:MAX_TEXT_CHARS - len(truncated_marker)] + truncated_marker
    fetched_at = datetime.now(JST).strftime('%Y-%m-%d %H:%M JST')
    row = [code, submit_date, title, text, fetched_at, pdf_path or '']
    cells = ws.col_values(1)
    found_row = None
    for i, c in enumerate(cells, 1):
        if c == code:
            found_row = i
            break
    if found_row:
        # M-1 (2026-06-05): append_row(336) と同様 RAW 固定で型強制（数値化・日付化）を防止。
        ws.update(f'A{found_row}:F{found_row}', [row], value_input_option='RAW')
    else:
        ws.append_row(row, value_input_option='RAW')


# ── CEO 通達 2026-06-04: EDINET 補完取得関数群 ──
# 賢者 GAS の searchEdinet / fetchDocText / htmlToText / getDocTypeName を
# Python に移植。既存 TDnet 取得ロジックは一切変更しない（既存破壊ゼロ）。

def _edinet_get_doc_type_name(ord_code, form_code):
    """EDINET 書類種別名（賢者 GAS getDocTypeName と同等）"""
    if ord_code == '010' and form_code == '030000': return '有価証券報告書'
    if ord_code == '010' and form_code == '043000': return '四半期報告書'
    if ord_code == '010' and form_code == '030001': return '有価証券報告書(訂正)'
    if ord_code == '010' and form_code == '043001': return '四半期報告書(訂正)'
    if ord_code == '010' and form_code == '050000': return '半期報告書'
    return f'{ord_code}/{form_code}'


def _html_to_text(html):
    """HTML → plain text（賢者 GAS htmlToText と同等のロジックを Python 化）"""
    text = re.sub(r'<script[^>]*>[\s\S]*?</script>', '', html, flags=re.IGNORECASE)
    text = re.sub(r'<style[^>]*>[\s\S]*?</style>', '', text, flags=re.IGNORECASE)
    text = re.sub(r'</th>', '\t', text, flags=re.IGNORECASE)
    text = re.sub(r'</td>', '\t', text, flags=re.IGNORECASE)
    text = re.sub(r'</tr>', '\n', text, flags=re.IGNORECASE)
    text = re.sub(r'<br\s*/?>', '\n', text, flags=re.IGNORECASE)
    text = re.sub(r'</p>', '\n\n', text, flags=re.IGNORECASE)
    text = re.sub(r'</div>', '\n', text, flags=re.IGNORECASE)
    text = re.sub(r'</h[1-6]>', '\n\n', text, flags=re.IGNORECASE)
    text = re.sub(r'<[^>]+>', '', text)
    text = (text.replace('&nbsp;', ' ').replace('&amp;', '&')
            .replace('&lt;', '<').replace('&gt;', '>').replace('&quot;', '"'))
    text = re.sub(r'&#\d+;', '', text)
    text = re.sub(r'[ \t]+', ' ', text)
    text = re.sub(r'\n\s*\n\s*\n', '\n\n', text)
    return text.strip()


def edinet_sweep_latest_for_codes(target_codes, lookback_days, api_key, today):
    """EDINET 当日インデックスを日付走査し、対象【全銘柄】の最新の有報/半期/四半期を返す。

    System B（2026-06-09）: 旧 edinet_search_best_doc_for_code（銘柄ごとに過去 N 日を遡る・
    268社×90日＝API 過多）を置換。日付ごとに documents.json を 1 回だけ取得し、対象銘柄の
    該当書類をまとめて収集する（O(日数)＝約 lookback_days 回）。銘柄ごとに提出日最新
    （同日は formCode 優先 有報>四半期>半期）を採用。

    Args:
        target_codes: 4桁（末尾英字含む）銘柄コードの集合
    Returns:
        dict {code(4桁): best_doc}  best_doc は submit_date(YYYY-MM-DD) と EDINET メタを保持
    """
    # EDINET の secCode は 5 桁（4桁+'0'）。5桁→対象4桁 の逆引きを作る。
    code5_to_4 = {}
    for c in target_codes:
        c5 = c if len(c) == 5 else c + '0'
        code5_to_4[c5] = c
    best_by_code = {}
    auth401_count = 0
    scanned_days = 0
    for d in range(lookback_days):
        dt = today - timedelta(days=d)
        date_str = dt.strftime('%Y-%m-%d')
        url = f'{EDINET_API_BASE}/documents.json?date={date_str}&type=2&Subscription-Key={api_key}'
        try:
            r = SESSION.get(url, timeout=30)
            if r.status_code != 200:
                time.sleep(0.1)
                continue
            text = r.text
            if '"StatusCode": 401' in text or '"StatusCode":401' in text:
                auth401_count += 1
                if auth401_count >= 3:
                    print('  [ERR] EDINET 認証障害（401 連発）= sweep 中断', file=sys.stderr)
                    break
                time.sleep(0.1)
                continue
            j = r.json()
            if 'results' not in j:
                time.sleep(0.1)
                continue
            scanned_days += 1
            for doc in j.get('results', []):
                sec5 = doc.get('secCode')
                if sec5 not in code5_to_4 or doc.get('formCode') not in EDINET_MAIN_FORMS:
                    continue
                code4 = code5_to_4[sec5]
                submit_full = doc.get('submitDateTime', '') or ''
                submit_date = submit_full[:10]
                if not submit_date:
                    continue
                cand = {
                    'docID': doc.get('docID'),
                    'filerName': doc.get('filerName', ''),
                    'docDescription': doc.get('docDescription', ''),
                    'submitDateTime': submit_full,
                    'submit_date': submit_date,
                    'ordinanceCode': doc.get('ordinanceCode', ''),
                    'formCode': doc.get('formCode', ''),
                }
                prev = best_by_code.get(code4)
                # 提出日が新しい方を採用。同日は formCode 優先（priority 小＝上位）。
                if (prev is None
                        or submit_date > prev['submit_date']
                        or (submit_date == prev['submit_date']
                            and EDINET_FORM_PRIORITY.get(cand['formCode'], 99)
                            < EDINET_FORM_PRIORITY.get(prev['formCode'], 99))):
                    best_by_code[code4] = cand
        except Exception as e:
            print(f'  [WARN] EDINET sweep {date_str}: {e}', file=sys.stderr)
        time.sleep(0.1)  # EDINET マナー
    print(f'  EDINET sweep: {scanned_days}/{lookback_days}日走査・対象該当 {len(best_by_code)}社',
          file=sys.stderr)
    return best_by_code


def edinet_fetch_doc_text(doc_id, api_key):
    """EDINET 書類 ZIP を取得 → HTML を結合してテキスト化"""
    try:
        url = f'{EDINET_API_BASE}/documents/{doc_id}?type=1&Subscription-Key={api_key}'
        r = SESSION.get(url, timeout=120)
        if r.status_code != 200:
            return None
        try:
            zf = zipfile.ZipFile(io.BytesIO(r.content))
        except Exception:
            return None
        html_names = []
        for name in zf.namelist():
            lower = name.lower()
            if lower.endswith(('.htm', '.html')) and 'manifest' not in lower and 'viewer' not in lower:
                html_names.append(name)
        if not html_names:
            return None
        html_names.sort()
        all_text = ''
        for fname in html_names:
            try:
                content = zf.read(fname).decode('utf-8', errors='ignore')
                section = _html_to_text(content)
                if len(section) > 100:
                    all_text += f'\n\n=== {fname} ===\n{section}'
            except Exception:
                continue
        text = all_text.strip()
        if len(text) > MAX_TEXT_CHARS:
            text = text[:MAX_TEXT_CHARS] + '\n\n[... 以降省略 ...]'
        return text if len(text) >= MIN_TEXT_CHARS else None
    except Exception as e:
        print(f'    [ERR] EDINET doc fetch {doc_id}: {e}', file=sys.stderr)
        return None


def main():
    print(f'=== fetch_tanshin start {datetime.now(JST):%Y-%m-%d %H:%M JST} ===')
    if DRY_RUN:
        print('=== DRY-RUN モード: Sheet 書込・Storage put をスキップ（取得と判定のみ） ===')
    ss = get_spreadsheet()
    sb = get_supabase_client()  # P-1: Supabase Storage クライアント
    if DRY_RUN:
        sb = None
    if sb:
        print(f'  Supabase Storage 連携: 有効 (bucket={PDF_BUCKET})')
    else:
        print(f'  Supabase Storage 連携: 無効（PDF は Sheet キャッシュのみ）')

    target_codes = get_target_codes(ss)
    all_targets = frozenset(target_codes)  # 被覆率算出用に元集合を保持
    print(f'対象銘柄: {len(target_codes)}社')
    if not target_codes:
        print('対象なし。終了')
        # H-1 (2026-06-05): 対象0社は異常（監視シート読込失敗の疑い）。
        # 死活監視が検知できるよう coverage=0 のサマリを出力する。
        print('MONITOR_SUMMARY new=0 err=0 coverage=0.0')
        return 0

    cache_ws = ensure_cache_sheet(ss)
    existing = load_existing(cache_ws)
    print(f'既存キャッシュ: {len(existing)}社')

    today = datetime.now(JST).date()
    found_new = 0
    err_count = 0
    pdf_uploaded = 0  # P-1: Storage put 成功カウント

    # 新しい日付から順に走査（より新しい決算短信を優先）
    for d in range(LOOKBACK_DAYS):
        if not target_codes:
            break  # 全銘柄カバー済
        date = today - timedelta(days=d)
        rows = fetch_tdnet_index(date)
        if not rows:
            time.sleep(0.5)
            continue
        relevant = [r for r in rows if r['code'] in target_codes
                    and is_target_tanshin(r['title']) and r['pdf_url']]
        if relevant:
            print(f'  {date}: {len(relevant)}件の対象決算短信')
        # 3者協議採用: 訂正/修正短信を検知したら警告（賢者は通常版を参照・
        # 訂正版の本格対応は販売後 E-1）。顧客に古い数値が出るリスクの可視化。
        for r in rows:
            if (r['code'] in target_codes and '決算短信' in r['title']
                    and not is_target_tanshin(r['title'])):
                print(f'  [訂正注意] {r["code"]} {date} {r["title"][:46]}', file=sys.stderr)

        for row in relevant:
            code = row['code']
            submit_date = date.strftime('%Y-%m-%d')
            # 既存より新しいときだけ更新（同日は冪等）
            if existing.get(code) and existing[code] >= submit_date:
                target_codes.discard(code)
                continue
            print(f'    [{code}] {submit_date} {row["title"][:50]}', flush=True)
            text, pdf_path = extract_pdf_text(row['pdf_url'], code=code, submit_date=submit_date, sb=sb)
            if not text:
                err_count += 1
                continue
            if pdf_path:
                pdf_uploaded += 1
            try:
                upsert(cache_ws, code, submit_date, row['title'], text, pdf_path)
                existing[code] = submit_date
                found_new += 1
                target_codes.discard(code)
            except Exception as e:
                print(f'    [ERR] sheet write {code}: {e}', file=sys.stderr)
                err_count += 1
            time.sleep(2)  # OpenAI/Sheets rate limiting + TDnet マナー
        time.sleep(1)

    # ── System B（2026-06-09）: EDINET 最新書類の常時取込 ──
    # CEO 指示: 決算短信の鮮度内に有報/半期が出たら最新書類で分析する。
    # 旧実装（未取得 or 31日 stale 限定 + 銘柄ごと90日遡り＝268×90 API）を、
    # 「全銘柄 + 日付インデックス走査（O(日数)＝約 lookback 回）」に置換。
    # ライブ searchEdinet（賢者 GAS 側）は停止のまま＝顧客は高速。本処理が裏でキャッシュへ反映。
    # 賢者 fetchTanshinFromCache は同銘柄から submitDate 最新を選ぶため、短信より新しい
    # 有報/半期だけが採用される（新しい短信を古い有報で上書きしないガードを下に明示）。
    edinet_found = 0
    edinet_err = 0
    edinet_doctype_counts = {}
    if not EDINET_API_KEY:
        print('::warning::EDINET 取込スキップ: EDINET_API_KEY 未設定（GitHub Secrets に追加してください）')
    else:
        print(f'\n=== EDINET 最新書類 走査開始: 全{len(all_targets)}社・過去{EDINET_LOOKBACK_DAYS}日（日付インデックス走査）===')
        best_by_code = edinet_sweep_latest_for_codes(
            all_targets, EDINET_LOOKBACK_DAYS, EDINET_API_KEY, today)
        print(f'  EDINET で該当書類が見つかった銘柄: {len(best_by_code)}社')
        for code in sorted(best_by_code.keys()):
            best_doc = best_by_code[code]
            submit_date = best_doc['submit_date']
            # 既存（短信含む）が同日 or より新しければ skip（新しい短信を古い有報で上書きしない・冪等）
            if existing.get(code) and existing[code] >= submit_date:
                continue
            doc_type = _edinet_get_doc_type_name(
                best_doc.get('ordinanceCode', ''), best_doc.get('formCode', ''))
            full_title = (f'[EDINET補完] {doc_type} - '
                          f'{best_doc.get("docDescription", "")[:80]}')
            print(f'    [{code}] EDINET {submit_date} {doc_type}', flush=True)
            try:
                text = edinet_fetch_doc_text(best_doc['docID'], EDINET_API_KEY)
            except Exception as e:
                print(f'    [ERR] EDINET doc fetch {code}: {e}', file=sys.stderr)
                edinet_err += 1
                continue
            if not text:
                edinet_err += 1
                continue
            try:
                upsert(cache_ws, code, submit_date, full_title, text, '')
                existing[code] = submit_date
                edinet_found += 1
                edinet_doctype_counts[doc_type] = edinet_doctype_counts.get(doc_type, 0) + 1
            except Exception as e:
                print(f'    [ERR] EDINET sheet write {code}: {e}', file=sys.stderr)
                edinet_err += 1
            time.sleep(2)  # EDINET + Sheets rate limit
        print(f'\n=== EDINET 最新書類 取込結果 ===')
        print(f'  新規/更新 (EDINET) : {edinet_found}件 {edinet_doctype_counts}')
        print(f'  エラー (EDINET)    : {edinet_err}件')

    # 3者協議採用（SPEC v1.0 §9/§10）: 被覆率の可視化＋下限ゲート。
    # 「取りこぼしに誰も気づかない」を防ぐ。TDnet ページ分割バグが
    # 長期放置された（被覆率 9.4%）再発防止の本丸。
    # CEO 通達 2026-06-04: TDnet 決算短信 + EDINET 補完 の合算被覆率。
    cached_targets = all_targets & set(existing.keys())
    uncovered = sorted(all_targets - set(existing.keys()))
    coverage = (len(cached_targets) / len(all_targets) * 100.0) if all_targets else 0.0
    print(f'\n=== 結果 ===')
    print(f'  新規/更新 (TDnet)   : {found_new}件')
    print(f'  新規/更新 (EDINET補完): {edinet_found}件')
    print(f'  PDF Storage         : {pdf_uploaded}件（P-1）')
    print(f'  エラー (TDnet)      : {err_count}件')
    print(f'  エラー (EDINET)     : {edinet_err}件')
    print(f'  キャッシュ計        : {len(existing)}件')
    print(f'  対象銘柄            : {len(all_targets)}社')
    print(f'  被覆 (短信+EDINET) : {len(cached_targets)}社 / 被覆率 {coverage:.1f}%')
    if uncovered:
        print(f'  未取得 {len(uncovered)}社: {", ".join(uncovered)}')
    # 被覆率下限ゲート: 閾値未満は GitHub Actions に ::warning:: を伝播
    if coverage < 40.0:
        print(f'::warning::決算短信+EDINET 被覆率 {coverage:.1f}% '
              f'(対象{len(all_targets)}社中{len(cached_targets)}社) '
              f'— 閾値40%未満。TDnet+EDINET 取得経路を点検のこと')
    # H-1 (2026-06-05): 死活監視用の機械可読サマリ 1 行。
    # yml の監視はこの行のみを parse する（表示文言のドリフトで grep が空振りし
    # 「異常でも job 緑」になった run 26925050076 の再発防止）。
    # System B (2026-06-09): CEO 報告用に edinet_new/doctype を末尾追記（yml の grep は
    # new/err/coverage を個別抽出するため後方互換・追記は監視を壊さない）。
    _doctype_str = '/'.join(f'{k}{v}' for k, v in sorted(edinet_doctype_counts.items())) or 'none'
    print(f'MONITOR_SUMMARY new={found_new + edinet_found} '
          f'err={err_count + edinet_err} coverage={coverage:.1f} '
          f'edinet_new={edinet_found} edinet_doctype={_doctype_str}')
    return 0


if __name__ == '__main__':
    sys.exit(main())

#!/usr/bin/env python3
"""
fetch_tanshin.py
TDnet（東証適時開示）から保有・監視銘柄の決算短信PDFを取得し、
テキスト化してGoogle Sheetsの「決算短信_キャッシュ」シートに格納する。

GitHub Actions: 毎週月曜 11:30 JST 自動実行（weekly_update 完了後）

機能:
  1. 直近35日のTDnet日次インデックスをスクレイプ
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
from datetime import datetime, timedelta, timezone

import gspread
import pdfplumber
import requests
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

CACHE_SHEET = '決算短信_キャッシュ'
HOLDINGS_SHEET = '保有銘柄_v4.3スコア'
WATCHLIST_SHEET = '監視銘柄_v4.3スコア'
MAX_TEXT_CHARS = 50000   # Sheets セル上限 50,000 文字
MAX_PDF_PAGES = 25

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
    """保有+監視銘柄コードを取得（C-5: 4桁数字 OR 末尾アルファベット銘柄 130A/212A 等を含む）"""
    codes = set()
    sec_code_re = re.compile(r'^[0-9]{3}[0-9A-Z]$')
    for sheet_name in (HOLDINGS_SHEET, WATCHLIST_SHEET):
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
    """TDnet 日次インデックス → 行リスト"""
    url = f'{TDNET_BASE}/I_list_001_{date.strftime("%Y%m%d")}.html'
    try:
        r = requests.get(url, headers=HEADERS, timeout=30)
    except Exception as e:
        print(f'  [ERR] {url}: {e}', file=sys.stderr)
        return []
    if r.status_code != 200:
        return []
    r.encoding = r.apparent_encoding or 'shift_jis'
    soup = BeautifulSoup(r.text, 'html.parser')
    rows = []
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
        r = requests.get(pdf_url, headers=HEADERS, timeout=60)
    except Exception as e:
        print(f'    [ERR] PDF DL失敗 {pdf_url}: {e}', file=sys.stderr)
        return None, None
    if r.status_code != 200:
        print(f'    [ERR] PDF HTTP {r.status_code}: {pdf_url}', file=sys.stderr)
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
            out[r[0]] = r[1] or ''
    return out


def upsert(ws, code, submit_date, title, text, pdf_path=None):
    """既存行更新 or 追加 + P-1-c: F 列 pdf_path"""
    fetched_at = datetime.now(JST).strftime('%Y-%m-%d %H:%M JST')
    row = [code, submit_date, title, text, fetched_at, pdf_path or '']
    cells = ws.col_values(1)
    found_row = None
    for i, c in enumerate(cells, 1):
        if c == code:
            found_row = i
            break
    if found_row:
        ws.update(f'A{found_row}:F{found_row}', [row])
    else:
        ws.append_row(row, value_input_option='RAW')


def main():
    print(f'=== fetch_tanshin start {datetime.now(JST):%Y-%m-%d %H:%M JST} ===')
    ss = get_spreadsheet()
    sb = get_supabase_client()  # P-1: Supabase Storage クライアント
    if sb:
        print(f'  Supabase Storage 連携: 有効 (bucket={PDF_BUCKET})')
    else:
        print(f'  Supabase Storage 連携: 無効（PDF は Sheet キャッシュのみ）')

    target_codes = get_target_codes(ss)
    print(f'対象銘柄: {len(target_codes)}社')
    if not target_codes:
        print('対象なし。終了')
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

    print(f'\n=== 結果 ===')
    print(f'  新規/更新   : {found_new}件')
    print(f'  PDF Storage : {pdf_uploaded}件（P-1）')
    print(f'  エラー      : {err_count}件')
    print(f'  キャッシュ計: {len(existing)}件')
    return 0


if __name__ == '__main__':
    sys.exit(main())

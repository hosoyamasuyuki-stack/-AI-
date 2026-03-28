# ============================================================
# manage_stock.py
# AI投資判断システム 銘柄管理（追加・削除・移動）
#
# 引数: --code 銘柄コード --action add/remove/move --target 保有/監視
# 追加時: J-Quants APIで財務データ取得 → v4.3スコア計算 → シート書き込み
# 削除時: 対象シートから該当行を削除
# 移動時: 一方から削除 → もう一方に追加（スコアは再計算）
#
# 実行: python manage_stock.py --code 7203 --action add --target 保有
# ============================================================
import os, sys, json, argparse, requests, time, warnings
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import gspread
from google.oauth2.service_account import Credentials
from core.config import (SPREADSHEET_ID, JQUANTS_API_KEY, JQUANTS_HEADERS,
                          JQUANTS_BASE, GSHEETS_SCOPE,
                          ROE_THR, FCR_THR, RS_THR, FS_THR, PEG_THR, FCY_THR)
from core.auth import get_spreadsheet
from core.scoring import safe, thr_high, thr_low, slope_fn
from core.api import get_price_jq, get_shares_jq, get_fin_jq

warnings.filterwarnings('ignore')

# ── 認証 ─────────────────────────────────────────────────────
ss = get_spreadsheet()

NOW   = datetime.now().strftime('%Y/%m/%d %H:%M')
TODAY = datetime.now()
DATA_YEARS = 10
CUTOFF = (TODAY - timedelta(days=365 * DATA_YEARS)).strftime('%Y-%m-%d')

SHEET_MAP = {
    '保有': '保有銘柄_v4.3スコア',
    '監視': '監視銘柄_v4.3スコア',
}

# シート列定義（保有/監視シートの列順序）
SHEET_COLS = ['コード', '銘柄名', '業種', '総合スコア', 'ランク',
              '変数1', '変数2', '変数3',
              'ROE平均', 'FCR平均', 'ROEトレンド',
              'PEG', 'FCF利回り', '株価']

# ── J-Quants V2 データ取得（銘柄名のみローカル）─────────────
def get_stock_name_jq(code):
    """銘柄名と業種をJ-Quantsマスターから取得"""
    try:
        code5 = code + '0' if len(code) == 4 else code
        r = requests.get(f"{JQUANTS_BASE}/v2/equities/master",
                         headers=JQUANTS_HEADERS,
                         params={"code": code5}, timeout=10)
        if r.status_code == 200:
            data = r.json().get('data', [])
            if data:
                d = data[0]
                name = d.get('CompanyNameFull', d.get('CompanyName', ''))
                sector = d.get('Sector33CodeName', '')
                return name, sector
        return None, None
    except: return None, None

# ── v4.3スコア計算（weekly_update.pyと同一ロジック）──────────
def calc_v43_score(df, price_info):
    if df is None or len(df) < 2: return 0, 'D', {}
    roe_s = df['ROE'].dropna() if 'ROE' in df.columns else pd.Series()
    fcr_s = df['FCR'].dropna() if 'FCR' in df.columns else pd.Series()
    roe_mean  = safe(roe_s.mean()) if len(roe_s) > 0 else None
    fcr_clean = fcr_s[(fcr_s >= -300) & (fcr_s <= 300)] if len(fcr_s) > 0 else pd.Series()
    fcr_mean  = safe(fcr_clean.mean()) if len(fcr_clean) > 0 else None
    s1 = round(thr_high(roe_mean, ROE_THR) * 0.60 +
               (thr_high(fcr_mean, FCR_THR) if fcr_mean is not None else 30) * 0.40)
    roe_trend = slope_fn(roe_s.tail(8))    if len(roe_s)    >= 3 else 0
    fcr_trend = slope_fn(fcr_clean.tail(8)) if len(fcr_clean) >= 3 else 0
    s2 = round(thr_high(roe_trend, RS_THR) * 0.60 +
               thr_high(fcr_trend, FS_THR) * 0.40)
    peg = None
    if 'EPS' in df.columns and len(df) >= 3:
        eps_s = df['EPS'].dropna()
        if len(eps_s) >= 3:
            e_now = float(eps_s.iloc[-1])
            e_old = float(eps_s.iloc[-3])
            if e_old > 0 and e_now > 0:
                eg = (e_now / e_old) ** (1/2) - 1
                if 'FEPS' in df.columns:
                    feps = df['FEPS'].dropna()
                    if len(feps) > 0 and float(feps.iloc[-1]) > 0:
                        eg = float(feps.iloc[-1]) / e_now - 1
                price = price_info.get('price')
                if price and e_now > 0 and eg > 0.01:
                    per = float(price) / e_now
                    peg = per / (eg * 100)
    fy = None
    if 'FCF' in df.columns:
        fcf_l = df['FCF'].dropna()
        if len(fcf_l) > 0:
            fcf_v      = float(fcf_l.iloc[-1])
            market_cap = price_info.get('market_cap')
            if market_cap and market_cap > 0:
                fy = fcf_v / market_cap * 100
            elif 'TA' in df.columns:
                ta_l = df['TA'].dropna()
                if len(ta_l) > 0:
                    fy = fcf_v / float(ta_l.iloc[-1]) * 100
    s3    = round(thr_high(peg, PEG_THR) * 0.50 + thr_high(fy, FCY_THR) * 0.50)
    total = round(s1 * 0.40 + s2 * 0.35 + s3 * 0.25, 1)
    rank  = ('S' if total >= 80 else 'A' if total >= 65 else
             'B' if total >= 50 else 'C' if total >= 35 else 'D')
    return total, rank, {
        'roe': roe_mean, 'fcr': fcr_mean,
        'roe_slope': safe(roe_trend, 2), 'fcr_slope': safe(fcr_trend, 2),
        'peg': safe(peg, 2), 'fcf_yield': safe(fy, 1),
        's1': s1, 's2': s2, 's3': s3,
        'price': price_info.get('price'),
        'market_cap': price_info.get('market_cap'),
        'data_years': len(df),
    }

# ── メイン処理 ───────────────────────────────────────────────
def find_row_by_code(ws, code):
    """シート内で銘柄コードの行番号を返す（1-indexed、なければNone）"""
    all_vals = ws.get_all_values()
    if len(all_vals) < 2: return None, all_vals
    header = all_vals[0]
    code_col = header.index('コード') if 'コード' in header else 0
    for i, row in enumerate(all_vals[1:], start=2):
        if str(row[code_col]).strip() == str(code).strip():
            return i, all_vals
    return None, all_vals

def add_stock(code, target):
    """銘柄を追加（スコア計算してシートに書き込み）"""
    sheet_name = SHEET_MAP[target]
    ws = ss.worksheet(sheet_name)

    # 重複チェック
    row_num, _ = find_row_by_code(ws, code)
    if row_num:
        print(f"ERROR: {code} は既に {sheet_name} に存在します（行{row_num}）")
        sys.exit(1)

    # コアスキャン_v4.3にも重複チェック（もう一方のシートもチェック）
    other_target = '監視' if target == '保有' else '保有'
    other_ws = ss.worksheet(SHEET_MAP[other_target])
    other_row, _ = find_row_by_code(other_ws, code)
    if other_row:
        print(f"WARNING: {code} は {SHEET_MAP[other_target]} に存在します。移動の場合は --action move を使ってください。")
        sys.exit(1)

    # 銘柄名・業種を取得
    name, sector = get_stock_name_jq(code)
    if not name:
        print(f"ERROR: {code} の銘柄情報を取得できません")
        sys.exit(1)
    print(f"  銘柄: {code} {name} ({sector})")

    # 財務データ取得 + スコア計算
    print(f"  財務データ取得中...")
    df_fin, price_info = get_fin_jq(code, cutoff_date=CUTOFF, today=TODAY)
    if df_fin is None or len(df_fin) < 2:
        print(f"ERROR: {code} の財務データが不足しています")
        sys.exit(1)

    total, rank, details = calc_v43_score(df_fin, price_info)
    print(f"  スコア: {total}点 ランク:{rank}")
    print(f"  変数1:{details['s1']} 変数2:{details['s2']} 変数3:{details['s3']}")

    # シートに行追加
    new_row = [
        str(code),
        name,
        sector,
        total,
        rank,
        details['s1'],
        details['s2'],
        details['s3'],
        details['roe'] if details['roe'] is not None else '',
        details['fcr'] if details['fcr'] is not None else '',
        details['roe_slope'] if details['roe_slope'] is not None else '',
        details['peg'] if details['peg'] is not None else '',
        details['fcf_yield'] if details['fcf_yield'] is not None else '',
        details['price'] if details['price'] is not None else '',
    ]

    all_vals = ws.get_all_values()
    next_row = len(all_vals) + 1
    ws.update(f'A{next_row}', [new_row])
    print(f"  {sheet_name} の行{next_row}に追加完了")

    # コアスキャン_v4.3にも追加
    try:
        cs_ws = ss.worksheet('コアスキャン_v4.3')
        cs_row, _ = find_row_by_code(cs_ws, code)
        if not cs_row:
            cs_all = cs_ws.get_all_values()
            cs_next = len(cs_all) + 1
            cs_ws.update(f'A{cs_next}', [new_row])
            print(f"  コアスキャン_v4.3 の行{cs_next}にも追加")
    except Exception as e:
        print(f"  WARNING: コアスキャン_v4.3への追加失敗: {e}")

    return total, rank

def remove_stock(code, target):
    """銘柄をシートから削除"""
    sheet_name = SHEET_MAP[target]
    ws = ss.worksheet(sheet_name)

    row_num, all_vals = find_row_by_code(ws, code)
    if not row_num:
        print(f"ERROR: {code} は {sheet_name} に存在しません")
        sys.exit(1)

    name = all_vals[row_num - 1][1] if len(all_vals[row_num - 1]) > 1 else code
    ws.delete_rows(row_num)
    print(f"  {sheet_name} から {code} {name} を削除（行{row_num}）")

def move_stock(code, target):
    """銘柄を target に移動（もう一方から削除 → target に追加）"""
    other_target = '監視' if target == '保有' else '保有'
    other_sheet = SHEET_MAP[other_target]
    other_ws = ss.worksheet(other_sheet)

    row_num, all_vals = find_row_by_code(other_ws, code)
    if not row_num:
        print(f"ERROR: {code} は {other_sheet} に存在しません（移動元がありません）")
        sys.exit(1)

    # 移動先に既に存在しないかチェック
    target_ws = ss.worksheet(SHEET_MAP[target])
    target_row, _ = find_row_by_code(target_ws, code)
    if target_row:
        print(f"ERROR: {code} は既に {SHEET_MAP[target]} に存在します")
        sys.exit(1)

    # 移動元から行データを取得
    row_data = all_vals[row_num - 1]
    name = row_data[1] if len(row_data) > 1 else code

    # 移動元から削除
    other_ws.delete_rows(row_num)
    print(f"  {other_sheet} から {code} {name} を削除")

    # 移動先に追加（既存スコアをそのまま使う）
    target_all = target_ws.get_all_values()
    next_row = len(target_all) + 1
    target_ws.update(f'A{next_row}', [row_data])
    print(f"  {SHEET_MAP[target]} の行{next_row}に追加")

# ── エントリーポイント ───────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description='銘柄管理（追加・削除・移動）')
    parser.add_argument('--code',   required=True, help='銘柄コード（4桁）')
    parser.add_argument('--action', required=True, choices=['add', 'remove', 'move'],
                        help='操作: add=追加, remove=削除, move=移動')
    parser.add_argument('--target', required=True, choices=['保有', '監視'],
                        help='対象シート: 保有 or 監視')
    args = parser.parse_args()

    code = args.code.strip()
    if not code.isdigit() or len(code) != 4:
        print(f"ERROR: 銘柄コードは4桁の数字で指定してください: {code}")
        sys.exit(1)

    print(f"{'='*50}")
    print(f"銘柄管理: {args.action} {code} -> {args.target}")
    print(f"実行日時: {NOW}")
    print(f"{'='*50}")

    if args.action == 'add':
        add_stock(code, args.target)
    elif args.action == 'remove':
        remove_stock(code, args.target)
    elif args.action == 'move':
        move_stock(code, args.target)

    print(f"\n完了: {args.action} {code} -> {args.target}")

if __name__ == '__main__':
    main()

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
                # J-Quants V2スキーマ変更対応: CoName/S33Nm が新キー、旧キーはフォールバック
                name = d.get('CoName') or d.get('CompanyNameFull') or d.get('CompanyName', '')
                sector = d.get('S33Nm') or d.get('Sector33CodeName', '')
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
    # PEG は低いほど割安（thr_low）。thr_high 誤用バグ修正（CLAUDE.md Bug C2と同等）
    s3    = round(thr_low(peg, PEG_THR) * 0.50 + thr_high(fy, FCY_THR) * 0.50)
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
    """シート内で銘柄コードの行番号を返す（1-indexed、なければNone）
    ヘッダー名が「コード」または「銘柄コード」の列を自動検出。
    予測記録シート（行1がサブヘッダー）にも対応。
    """
    all_vals = ws.get_all_values()
    if len(all_vals) < 2: return None, all_vals
    header = all_vals[0]
    code_col = None
    for name in ('コード', '銘柄コード'):
        if name in header:
            code_col = header.index(name)
            break
    if code_col is None:
        code_col = 0
    # 予測記録は行1がサブヘッダー・行2からデータ
    sheet_title = getattr(ws, 'title', '') or ''
    data_start = 2 if '予測記録' in sheet_title else 1
    for i, row in enumerate(all_vals[data_start:], start=data_start + 1):
        if len(row) > code_col and str(row[code_col]).strip() == str(code).strip():
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

    # ヘッダー名→値のマップ（列順に依存しない書き込みのため）
    value_map = {
        'コード':       str(code),
        '銘柄名':       name,
        '業種':         sector,
        '総合スコア':   total,
        'ランク':       rank,
        '変数1':        details['s1'],
        '変数2':        details['s2'],
        '変数3':        details['s3'],
        'ROE平均':      details['roe']       if details['roe']       is not None else '',
        'FCR平均':      details['fcr']       if details['fcr']       is not None else '',
        'ROEトレンド':  details['roe_slope'] if details['roe_slope'] is not None else '',
        'PEG':          details['peg']       if details['peg']       is not None else '',
        'FCF利回り':    details['fcf_yield'] if details['fcf_yield'] is not None else '',
        '株価':         details['price']     if details['price']     is not None else '',
    }

    def build_row_from_header(header):
        """シート実ヘッダー順に値を並べる（未知ヘッダーは空欄）"""
        return [value_map.get(h, '') for h in header]

    all_vals = ws.get_all_values()
    header = all_vals[0] if all_vals else list(value_map.keys())
    new_row = build_row_from_header(header)
    next_row = len(all_vals) + 1
    ws.update(f'A{next_row}', [new_row])
    print(f"  {sheet_name} の行{next_row}に追加完了")

    # コアスキャン_v4.3にも追加／既存行があればヘッダー順で上書き
    # （既存行が古い列順で書かれていた場合の整合性確保）
    try:
        cs_ws = ss.worksheet('コアスキャン_v4.3')
        cs_row, _ = find_row_by_code(cs_ws, code)
        cs_all = cs_ws.get_all_values()
        cs_header = cs_all[0] if cs_all else header
        cs_new_row = build_row_from_header(cs_header)
        if cs_row:
            # 既存行を最新値で上書き（古いバグ版書き込みの修復）
            cs_ws.update(f'A{cs_row}', [cs_new_row])
            print(f"  コアスキャン_v4.3 行{cs_row}を上書き（既存データを修復）")
        else:
            cs_next = len(cs_all) + 1
            cs_ws.update(f'A{cs_next}', [cs_new_row])
            print(f"  コアスキャン_v4.3 の行{cs_next}に追加")
    except Exception as e:
        print(f"  WARNING: コアスキャン_v4.3への追加失敗: {e}")

    # 予測記録シートにも初期予測を記録（ランクベースで暫定方向）
    # 4軸予測システムの精度トラッキングを可能にする
    try:
        pred_ws = ss.worksheet('予測記録')
        pred_all = pred_ws.get_all_values()
        pred_row, _ = find_row_by_code(pred_ws, code)
        if not pred_row and len(pred_all) >= 2:
            # ランクベース初期予測（STEP0スタイル）
            dir_map = {
                'S': '強気↑↑', 'A': '強気↑',
                'B': '中立→',   'C': '弱気↓',
                'D': '弱気↓↓',
            }
            init_dir = dir_map.get(rank, '中立→')

            # 目標株価（ランク別の想定騰落率）
            target_map_pct = {'S': 15, 'A': 10, 'B': 5, 'C': -5, 'D': -10}
            pct = target_map_pct.get(rank, 0)
            price = details.get('price') or 0
            target_price = round(price * (1 + pct / 100)) if price else ''

            # 検証予定日（軸ごと）
            today_dt = datetime.now()
            ver_4w = (today_dt + timedelta(days=28)).strftime('%Y/%m/%d')
            ver_1y = (today_dt + timedelta(days=365)).strftime('%Y/%m/%d')
            ver_3y = (today_dt + timedelta(days=365*3)).strftime('%Y/%m/%d')
            ver_5y = (today_dt + timedelta(days=365*5)).strftime('%Y/%m/%d')

            basis = f"v4.3スコア{total}点(ランク{rank})に基づく初期予測"

            # 列構成: 0:記録日 1:コード 2:名 3:業種 4:記録時株価 5:総合 6:ランク 7:アクション
            #        8-15:目先(4週) 16-23:短期(1年) 24-31:中期(3年) 32-39:長期(5年)
            # 各軸8列: 予測方向,目標株価,根拠,検証予定日,実績株価,騰落率,日経比超過,勝敗
            action = '買い検討' if rank in ('S', 'A') else ('様子見' if rank == 'B' else '時期尚早')
            pred_row_data = [
                today_dt.strftime('%Y/%m/%d'),  # 0
                str(code), name, sector, price, total, rank, action,  # 1-7
                # 目先(4週) 8-15
                init_dir, target_price, basis, ver_4w, '', '', '', '',
                # 短期(1年) 16-23
                init_dir, target_price, basis, ver_1y, '', '', '', '',
                # 中期(3年) 24-31
                init_dir, target_price, basis, ver_3y, '', '', '', '',
                # 長期(5年) 32-39
                init_dir, target_price, basis, ver_5y, '', '', '', '',
            ]
            pred_next = len(pred_all) + 1
            pred_ws.update(f'A{pred_next}', [pred_row_data])
            print(f"  予測記録 の行{pred_next}に初期予測登録（方向={init_dir}・目標{target_price}円）")
    except Exception as e:
        print(f"  WARNING: 予測記録への追加失敗: {e}")

    return total, rank

def remove_stock(code, target):
    """銘柄を4シート横断で削除（破損データの残留を防ぐ・協議合意事項#1）
    対象: 保有/監視銘柄_v4.3スコア、コアスキャン_v4.3、コアスキャン_日次、予測記録
    """
    sheet_name = SHEET_MAP[target]
    ws = ss.worksheet(sheet_name)
    row_num, all_vals = find_row_by_code(ws, code)
    if not row_num:
        print(f"ERROR: {code} は {sheet_name} に存在しません")
        sys.exit(1)
    name = all_vals[row_num - 1][1] if len(all_vals[row_num - 1]) > 1 else code
    ws.delete_rows(row_num)
    print(f"  {sheet_name} から {code} {name} を削除（行{row_num}）")

    # 派生シートからも同銘柄を削除（バグ版データの残留・伝播を防止）
    CASCADE_SHEETS = ['コアスキャン_v4.3', 'コアスキャン_日次', '予測記録']
    for sn in CASCADE_SHEETS:
        try:
            sws = ss.worksheet(sn)
            deleted = 0
            # 予測記録はコード列が 1 列目、それ以外は 0 列目
            # find_row_by_code は自動検出するので安心
            while True:
                r, _ = find_row_by_code(sws, code)
                if not r:
                    break
                sws.delete_rows(r)
                deleted += 1
                if deleted > 5:  # セーフガード: 無限ループ防止
                    break
            if deleted:
                print(f"  {sn} からも {code} を {deleted}行 削除")
        except Exception as e:
            print(f"  WARNING: {sn} の削除に失敗: {e}")

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

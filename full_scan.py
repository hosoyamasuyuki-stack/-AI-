# ============================================================
# full_scan.py
# AI投資判断システム 全日本株スクリーニング（週次）
#
# 全上場銘柄（約3,800社）をv4.3スコアでスキャンし、
# 上位50銘柄をスプレッドシートに書き出す。
#
# 実行: 毎週日曜 22:00 JST（GitHub Actions）
# 想定実行時間: 90-120分
# ============================================================
import os, sys, json, requests, time, warnings, csv
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

TOP_N = 50
CHECKPOINT_INTERVAL = 500
CHECKPOINT_FILE = '/tmp/full_scan_checkpoint.csv'

print(f"=== Full Market Scan ===")
print(f"Date: {NOW}")

# ── v4.3スコア計算 ──────────────────────────────────────────
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

# ============================================================
# Phase 1: 全上場銘柄リスト取得
# ============================================================
print(f"\n{'='*60}")
print("Phase 1: 上場銘柄一覧取得")
print('='*60)

stocks = []

# --- 方法A: JPX公式 東証上場銘柄一覧（Excel） ---
JPX_URL = 'https://www.jpx.co.jp/markets/statistics-equities/misc/tvdivq0000001vg2-att/data_j.xls'
print(f"  試行: JPX公式Excel ({JPX_URL})")
try:
    import io
    r = requests.get(JPX_URL, timeout=30,
                     headers={'User-Agent': 'Mozilla/5.0'})
    print(f"  HTTP status: {r.status_code}, size: {len(r.content)} bytes")
    if r.status_code == 200:
        df_jpx = pd.read_excel(io.BytesIO(r.content), dtype=str)
        # 列名: 日付, コード, 銘柄名, 市場・商品区分, 33業種コード, 33業種区分, ...
        code_col = [c for c in df_jpx.columns if 'コード' in str(c)]
        name_col = [c for c in df_jpx.columns if '銘柄名' in str(c)]
        market_col = [c for c in df_jpx.columns if '市場' in str(c)]
        sector_col = [c for c in df_jpx.columns if '33業種区分' in str(c) or '業種' in str(c)]
        if code_col:
            cc = code_col[0]
            nc = name_col[0] if name_col else cc
            mc = market_col[0] if market_col else None
            sc = sector_col[0] if sector_col else None
            for _, row in df_jpx.iterrows():
                code = str(row[cc]).strip()
                if not code or not code.isdigit() or len(code) != 4:
                    continue
                # プライム・スタンダード・グロースのみ（ETF/REIT除外）
                market = str(row[mc]) if mc else ''
                if mc and not any(m in market for m in ['プライム', 'スタンダード', 'グロース']):
                    continue
                stocks.append({
                    'Code': code,
                    'CompanyName': str(row[nc]).strip() if nc else '',
                    'Sector33CodeName': str(row[sc]).strip() if sc else '',
                    'MarketCodeName': market,
                })
            print(f"  成功: JPX Excel ({len(stocks)}銘柄)")
    else:
        print(f"  失敗: JPX Excel status={r.status_code}")
except Exception as e:
    import traceback
    print(f"  エラー: JPX Excel {e}")
    traceback.print_exc()

# --- 方法B: J-Quants APIフォールバック ---
if not stocks:
    print("  JPX Excel失敗 → J-Quants APIにフォールバック")
    for ep in ['/v2/equities/listed', '/v2/equities/master']:
        print(f"  試行: {ep}")
        try:
            r = requests.get(f"{JQUANTS_BASE}{ep}",
                             headers=JQUANTS_HEADERS, timeout=30)
            if r.status_code == 200:
                body = r.json()
                all_master = (body.get('data') or body.get('info')
                              or body.get('listed_info') or [])
                if all_master:
                    VALID_MARKETS = ['0111', '0112', '0113']
                    stocks = [d for d in all_master
                              if d.get('MarketCode') in VALID_MARKETS]
                    print(f"  成功: {ep} ({len(stocks)}銘柄)")
                    break
            else:
                print(f"  失敗: {ep} status={r.status_code}")
        except Exception as e:
            print(f"  エラー: {ep} {e}")

if not stocks:
    print("ERROR: 銘柄一覧取得に全て失敗")
    sys.exit(1)

print(f"  TSE普通株: {len(stocks)}銘柄")

# ============================================================
# Phase 2: 保有/監視銘柄を除外
# ============================================================
print(f"\n{'='*60}")
print("Phase 2: 保有/監視銘柄除外")
print('='*60)

exclude_codes = set()
for sheet_name in ['保有銘柄_v4.3スコア', '監視銘柄_v4.3スコア']:
    try:
        ws = ss.worksheet(sheet_name)
        rows = ws.get_all_values()
        if len(rows) > 1:
            header = rows[0]
            code_idx = header.index('コード') if 'コード' in header else 0
            for row in rows[1:]:
                c = str(row[code_idx]).strip()
                if c:
                    exclude_codes.add(c)
    except Exception as e:
        print(f"  WARNING: {sheet_name} 読み込みエラー: {e}")

print(f"  除外銘柄: {len(exclude_codes)}件")

scan_targets = []
for s in stocks:
    code = s.get('Code', '')
    if len(code) == 5: code = code[:4]
    if code not in exclude_codes:
        scan_targets.append({
            'code': code,
            'name': s.get('CompanyName', ''),
            'sector': s.get('Sector33CodeName', ''),
        })

print(f"  スキャン対象: {len(scan_targets)}件")

# ============================================================
# Phase 3: 全銘柄スキャン
# ============================================================
print(f"\n{'='*60}")
print(f"Phase 3: v4.3スコア計算（{len(scan_targets)}銘柄）")
print('='*60)

# チェックポイント読み込み
scanned_codes = set()
results = []
if os.path.exists(CHECKPOINT_FILE):
    try:
        with open(CHECKPOINT_FILE, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                results.append(row)
                scanned_codes.add(row['code'])
        print(f"  チェックポイント復元: {len(results)}件")
    except:
        pass

start_time = time.time()
errors = 0
skipped = 0

for i, s in enumerate(scan_targets):
    code = s['code']
    if code in scanned_codes:
        skipped += 1
        continue

    if (i + 1) % 100 == 0:
        elapsed = time.time() - start_time
        rate = (i + 1 - skipped) / max(elapsed, 1) * 60
        remaining = (len(scan_targets) - i - 1) / max(rate, 0.1)
        print(f"  [{i+1}/{len(scan_targets)}] {rate:.0f}銘柄/分 残り{remaining:.0f}分")

    try:
        # デバッグ：最初の5件のコードを出力
        if i < 5:
            print(f"  DEBUG code={code!r} len={len(code)}")
        df_fin, price_info = get_fin_jq(code, cutoff_date=CUTOFF, today=TODAY)
        time.sleep(0.35)

        if df_fin is None or len(df_fin) < 2:
            if i < 5:
                print(f"  DEBUG {code}: df_fin={df_fin}, price_info={price_info}")
            errors += 1
            continue

        total, rank, details = calc_v43_score(df_fin, price_info)

        results.append({
            'code': code,
            'name': s['name'],
            'sector': s['sector'],
            'total': total,
            'rank': rank,
            's1': details.get('s1', 0),
            's2': details.get('s2', 0),
            's3': details.get('s3', 0),
            'roe': details.get('roe', ''),
            'fcr': details.get('fcr', ''),
            'roe_slope': details.get('roe_slope', ''),
            'peg': details.get('peg', ''),
            'fcf_yield': details.get('fcf_yield', ''),
            'price': details.get('price', ''),
        })

    except Exception as e:
        errors += 1
        continue

    # チェックポイント保存
    if len(results) % CHECKPOINT_INTERVAL == 0 and len(results) > 0:
        with open(CHECKPOINT_FILE, 'w', encoding='utf-8', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=results[0].keys())
            writer.writeheader()
            writer.writerows(results)
        print(f"  checkpoint saved: {len(results)}件")

elapsed_total = time.time() - start_time
print(f"\n  完了: {len(results)}銘柄スキャン / {errors}件エラー / {elapsed_total/60:.1f}分")

# ============================================================
# Phase 4: Top 50 抽出
# ============================================================
print(f"\n{'='*60}")
print(f"Phase 4: Top {TOP_N} 抽出")
print('='*60)

results_sorted = sorted(results, key=lambda x: float(x.get('total', 0)), reverse=True)
top50 = results_sorted[:TOP_N]

if not top50:
    print(f"  WARNING: スコア計算結果が0件。{errors}件エラー。")
    print("  J-Quants APIの認証・レート制限を確認してください。")
    sys.exit(1)

print(f"  Top {TOP_N} スコア範囲: {top50[0]['total']}〜{top50[-1]['total']}")
print(f"  ランク分布:")
rank_counts = {}
for r in top50:
    rk = r.get('rank', 'D')
    rank_counts[rk] = rank_counts.get(rk, 0) + 1
for rk in ['S', 'A', 'B', 'C', 'D']:
    if rk in rank_counts:
        print(f"    {rk}: {rank_counts[rk]}銘柄")

print(f"\n  Top 10:")
for j, r in enumerate(top50[:10], 1):
    print(f"    {j:2d}. {r['code']} {r['name'][:10]:10s} {r['total']:5.1f}pt {r['rank']}")

# ============================================================
# Phase 5: スプレッドシート書き出し
# ============================================================
print(f"\n{'='*60}")
print("Phase 5: スプレッドシート書き出し")
print('='*60)

SHEET_NAME = 'スクリーニング_Top50'
SHEET_COLS = ['コード', '銘柄名', '業種', '総合スコア', 'ランク',
              '変数1', '変数2', '変数3',
              'ROE平均', 'FCR平均', 'ROEトレンド',
              'PEG', 'FCF利回り', '株価', '算出日時']

# シート取得or作成
try:
    ws = ss.worksheet(SHEET_NAME)
    ws.clear()
    print(f"  {SHEET_NAME} クリア完了")
except gspread.exceptions.WorksheetNotFound:
    ws = ss.add_worksheet(title=SHEET_NAME, rows=60, cols=15)
    print(f"  {SHEET_NAME} 新規作成")

# ヘッダー + データ書き込み
rows_to_write = [SHEET_COLS]
for r in top50:
    rows_to_write.append([
        str(r['code']),
        str(r['name']),
        str(r['sector']),
        float(r['total']),
        str(r['rank']),
        r['s1'],
        r['s2'],
        r['s3'],
        r['roe'] if r['roe'] != '' else '',
        r['fcr'] if r['fcr'] != '' else '',
        r['roe_slope'] if r['roe_slope'] != '' else '',
        r['peg'] if r['peg'] != '' else '',
        r['fcf_yield'] if r['fcf_yield'] != '' else '',
        r['price'] if r['price'] != '' else '',
        NOW,
    ])

ws.update(f'A1:O{len(rows_to_write)}', rows_to_write)
print(f"  {SHEET_NAME} に {len(top50)} 銘柄書き出し完了")

# チェックポイント削除
if os.path.exists(CHECKPOINT_FILE):
    os.remove(CHECKPOINT_FILE)

print(f"\n{'='*60}")
print(f"Full Market Scan 完了")
print(f"  スキャン: {len(results)}銘柄 / Top {TOP_N}: {top50[0]['total']}〜{top50[-1]['total']}pt")
print(f"  実行時間: {elapsed_total/60:.1f}分")
print(f"{'='*60}")

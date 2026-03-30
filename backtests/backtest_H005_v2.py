# backtest_H005_v2.py
# H005: MacroPhase判定の有効性バックテスト（全パターン網羅版）
#
# 検証戦略:
# A: RED回避（RED月はキャッシュ、それ以外は投資）
# B: スコア連動（score/100でポジション比例調整）
# C: 閾値変更（GREEN=50/40に緩和）
# D: 逆指標（RED時に買い=反証チェック）
# E: Layer A単独（VIX/HYG/TEDだけで判定）
# F: Layer A+B（リスク+金融政策で判定）
# G: VIX単独（VIX<20で投資、>=25でキャッシュ）
#
# 実行: python backtest_H005_v2.py
#       環境変数: FRED_API_KEY
# 2026/03/29

import os
import numpy as np
import pandas as pd
import yfinance as yf
import requests
from datetime import datetime, timedelta
from scipy import stats
import warnings
warnings.filterwarnings("ignore")
import time

FRED_API_KEY = os.environ.get('FRED_API_KEY', '')
if not FRED_API_KEY:
    print("ERROR: FRED_API_KEY not set")
    exit(1)

print("=" * 70)
print("H005 v2: MacroPhase Comprehensive Backtest")
print(f"Date: {datetime.now().strftime('%Y/%m/%d %H:%M')}")
print("=" * 70)

# ============================================================
# PHASE 1: ヒストリカルデータ取得
# ============================================================
print("\n[PHASE 1] Historical Data Fetch")

DATA_START = '2014-01-01'
DATA_END   = '2024-12-31'

def fetch_fred(series_id):
    try:
        r = requests.get(
            "https://api.stlouisfed.org/fred/series/observations",
            params={
                "series_id": series_id, "api_key": FRED_API_KEY,
                "file_type": "json", "sort_order": "asc",
                "observation_start": DATA_START, "observation_end": DATA_END,
            }, timeout=30)
        if r.status_code == 200:
            obs = r.json().get("observations", [])
            df = pd.DataFrame(obs)[["date", "value"]]
            df["date"] = pd.to_datetime(df["date"])
            df["value"] = pd.to_numeric(df["value"], errors="coerce")
            return df.dropna().set_index("date")["value"]
    except Exception as e:
        print(f"  WARN: {series_id} -> {e}")
    return pd.Series(dtype=float)

def fetch_yf(ticker, start=DATA_START, end=DATA_END):
    try:
        df = yf.download(ticker, start=start, end=end, progress=False, auto_adjust=True)
        if df.empty: return pd.Series(dtype=float)
        df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]
        return df["Close"]
    except:
        return pd.Series(dtype=float)

FRED_SERIES = {
    'VIX': 'VIXCLS', 'HY_SPREAD': 'BAMLH0A0HYM2', 'TED_SPREAD': 'TEDRATE',
    'YIELD_SPREAD': 'T10Y2Y', 'JAPAN_M2': 'MYAGM2JPM189S',
    'FRB_BALANCE': 'WALCL', 'ISM_PMI': 'MANEMP', 'UNEMPLOYMENT': 'UNRATE',
}

fred_data = {}
for name, sid in FRED_SERIES.items():
    fred_data[name] = fetch_fred(sid)
    print(f"  {name}: {len(fred_data[name])} obs")
    time.sleep(0.5)

# CAPE
sp500 = fetch_yf("^GSPC", start="2004-01-01", end=DATA_END)
if len(sp500) > 0:
    monthly_sp = sp500.resample("ME").last()
    ma10y = monthly_sp.rolling(120).mean()
    cape_s = (monthly_sp / ma10y * 20).dropna()
    fred_data['CAPE'] = cape_s.reindex(pd.date_range(cape_s.index[0], cape_s.index[-1], freq='D')).ffill()
    print(f"  CAPE: {len(fred_data['CAPE'])} obs")

# Nikkei
nikkei = fetch_yf("^N225")
print(f"  Nikkei: {len(nikkei)} obs")

# ============================================================
# PHASE 2: 日次MacroPhaseスコア計算
# ============================================================
print("\n[PHASE 2] Daily MacroPhase Score Calculation")

def to_daily(s):
    if s.empty: return s
    return s.reindex(pd.date_range(s.index[0], s.index[-1], freq='D')).ffill()

def mom(s): return s.diff(1)
def mom_pct(s): return (s / s.shift(1) - 1) * 100
def dev_pct(s, w=63):
    ma = s.rolling(w).mean()
    return ((s / ma) - 1) * 100

vix_d   = to_daily(fred_data.get('VIX', pd.Series(dtype=float)))
hyg_d   = to_daily(fred_data.get('HY_SPREAD', pd.Series(dtype=float)))
ted_d   = to_daily(fred_data.get('TED_SPREAD', pd.Series(dtype=float)))
m2_d    = to_daily(fred_data.get('JAPAN_M2', pd.Series(dtype=float)))
m2_mom  = mom_pct(m2_d)
frb_d   = to_daily(fred_data.get('FRB_BALANCE', pd.Series(dtype=float)))
frb_mom = mom(frb_d)
ism_d   = to_daily(fred_data.get('ISM_PMI', pd.Series(dtype=float)))
ism_dev = dev_pct(ism_d)
ism_m   = mom(ism_d)
unemp_d = to_daily(fred_data.get('UNEMPLOYMENT', pd.Series(dtype=float)))
cape_d  = fred_data.get('CAPE', pd.Series(dtype=float))

def get_v(series, date):
    v = series.get(date) if not series.empty else None
    return v if v is not None and not (isinstance(v, float) and np.isnan(v)) else None

def calc_score(date):
    """Full MacroPhase score (same as daily_update.py)"""
    # Layer A: Risk (40pt)
    la = 0
    v = get_v(vix_d, date)
    if v is not None: la += 15 if v < 15 else 10 if v < 20 else 5 if v < 25 else 0
    v = get_v(hyg_d, date)
    if v is not None: la += 15 if v < 3 else 10 if v < 4 else 5 if v < 5 else 0
    v = get_v(ted_d, date)
    if v is not None: la += 10 if v < 0.3 else 5 if v < 0.5 else 0

    # Layer B: Monetary (30pt)
    lb = 0
    v = get_v(m2_mom, date)
    if v is not None: lb += 15 if v > 0.3 else 8 if v > 0 else 0
    v = get_v(frb_mom, date)
    if v is not None: lb += 15 if v > 0 else 8 if v > -50000 else 0

    # Layer C: Economic (20pt)
    lc = 0
    id_ = get_v(ism_dev, date)
    im_ = get_v(ism_m, date)
    if id_ is not None and im_ is not None:
        if id_ > 0 and im_ > 0: lc += 10
        elif id_ > -1 or im_ > 0: lc += 5
    v = get_v(unemp_d, date)
    if v is not None: lc += 10 if v < 4.0 else 5 if v < 5.0 else 0

    # Layer D: Valuation (10pt)
    ld = 0
    v = get_v(cape_d, date)
    if v is not None: ld += 10 if v < 20 else 5 if v < 28 else 0

    total = la + lb + lc + ld
    return total, la, lb, lc, ld

# 計算
dates = pd.date_range('2017-01-01', '2024-12-31', freq='D')
scores = []
for d in dates:
    t, la, lb, lc, ld = calc_score(d)
    scores.append({'date': d, 'score': t, 'LA': la, 'LB': lb, 'LC': lc, 'LD': ld})

df_p = pd.DataFrame(scores).set_index('date')
df_p['phase'] = df_p['score'].apply(lambda x: 'GREEN' if x >= 60 else 'YELLOW' if x >= 30 else 'RED')

g = (df_p['phase'] == 'GREEN').sum()
y = (df_p['phase'] == 'YELLOW').sum()
r = (df_p['phase'] == 'RED').sum()
print(f"  GREEN: {g} ({g/len(df_p)*100:.1f}%) | YELLOW: {y} ({y/len(df_p)*100:.1f}%) | RED: {r} ({r/len(df_p)*100:.1f}%)")
print(f"  Score: min={df_p['score'].min()} max={df_p['score'].max()} mean={df_p['score'].mean():.1f}")

# ============================================================
# PHASE 3: 全戦略のウォークフォワード検証
# ============================================================
print("\n[PHASE 3] Multi-Strategy Walk-Forward Analysis")

WINDOWS = [
    ('W1', '2017-03-31', '2020-03-31'),
    ('W2', '2018-03-31', '2021-03-31'),
    ('W3', '2019-03-31', '2022-03-31'),
    ('W4', '2020-03-31', '2023-03-31'),
    ('W5', '2021-03-31', '2024-03-31'),
]

nk_monthly = nikkei.resample('ME').last()

def run_strategy(name, position_fn, desc=""):
    """ウォークフォワード5ウィンドウで戦略を検証"""
    results = []
    for wname, wstart, wend in WINDOWS:
        ws, we = pd.Timestamp(wstart), pd.Timestamp(wend)
        w_phase = df_p.loc[ws:we].resample('ME').last()
        w_nk = nk_monthly.loc[ws:we]
        w_ret = w_nk.pct_change().dropna()
        common = w_phase.index.intersection(w_ret.index)
        if len(common) < 6: continue

        w_phase_c = w_phase.loc[common]
        w_ret_c = w_ret.loc[common]

        # ポジションサイズ（0~1）
        positions = w_phase_c.apply(position_fn, axis=1)
        strat_ret = w_ret_c * positions

        years = (we - ws).days / 365.25
        bnh_cum = (1 + w_ret_c).prod() - 1
        strat_cum = (1 + strat_ret).prod() - 1
        bnh_a = (1 + bnh_cum) ** (1/years) - 1
        strat_a = (1 + strat_cum) ** (1/years) - 1
        excess = strat_a - bnh_a
        invested = (positions > 0).sum()

        results.append({
            'window': wname, 'bnh': bnh_a, 'strat': strat_a,
            'excess': excess, 'win': excess > 0,
            'invested_months': invested, 'total_months': len(common),
        })
    return results

def evaluate(name, results, desc=""):
    """統計検定+結果表示"""
    if not results:
        print(f"\n  [{name}] No data")
        return
    df_r = pd.DataFrame(results)
    exc = df_r['excess'].values * 100
    wins = df_r['win'].sum()
    losses = len(df_r) - wins
    mean_e = exc.mean()
    if len(exc) > 1 and np.std(exc) > 0:
        t, p2 = stats.ttest_1samp(exc, 0)
        p1 = p2/2 if t > 0 else 1 - p2/2
    else:
        t, p1 = 0, 1.0

    r1 = p1 > 0.05
    r2 = mean_e < 3.9
    r3 = losses >= 3
    verdict = 'REJECTED' if (r1 or r2 or r3) else 'ADOPTED'

    inv_pct = df_r['invested_months'].sum() / df_r['total_months'].sum() * 100

    print(f"\n  {'='*65}")
    print(f"  [{name}] {desc}")
    print(f"  {'='*65}")
    for _, row in df_r.iterrows():
        print(f"    {row['window']}: B&H {row['bnh']*100:+7.2f}%  Strat {row['strat']*100:+7.2f}%  "
              f"Excess {row['excess']*100:+7.2f}%  {'O' if row['win'] else 'X'}  "
              f"({row['invested_months']}/{row['total_months']}mo invested)")
    print(f"  Mean excess: {mean_e:+.2f}%/yr | Wins: {wins}/{len(df_r)} | "
          f"p={p1:.4f} | Invested: {inv_pct:.0f}% | {verdict}")
    return {'name': name, 'desc': desc, 'mean_excess': mean_e, 'wins': wins,
            'total': len(df_r), 'p': p1, 'verdict': verdict, 'invested_pct': inv_pct}

all_results = []

# --- Strategy A: RED回避（RED月はキャッシュ） ---
res = run_strategy('A', lambda r: 0 if r['phase'] == 'RED' else 1)
all_results.append(evaluate('A: RED Avoidance', res, 'RED月=キャッシュ、YELLOW/GREEN=投資'))

# --- Strategy B: スコア連動（score/100でポジション） ---
res = run_strategy('B', lambda r: r['score'] / 100)
all_results.append(evaluate('B: Score Proportional', res, 'ポジション=score/100'))

# --- Strategy C1: 閾値50（score>=50で投資） ---
res = run_strategy('C1', lambda r: 1 if r['score'] >= 50 else 0)
all_results.append(evaluate('C1: Threshold 50', res, 'score>=50で投資'))

# --- Strategy C2: 閾値40（score>=40で投資） ---
res = run_strategy('C2', lambda r: 1 if r['score'] >= 40 else 0)
all_results.append(evaluate('C2: Threshold 40', res, 'score>=40で投資'))

# --- Strategy C3: 閾値30（score>=30=非RED） ---
res = run_strategy('C3', lambda r: 1 if r['score'] >= 30 else 0)
all_results.append(evaluate('C3: Threshold 30 (=non-RED)', res, 'score>=30で投資（=RED回避と同じ）'))

# --- Strategy D: 逆指標（RED時に買い=反証） ---
res = run_strategy('D', lambda r: 1 if r['phase'] == 'RED' else 0)
all_results.append(evaluate('D: Contrarian (RED=Buy)', res, 'RED月のみ投資（反証チェック）'))

# --- Strategy E: Layer A単独（リスク指標のみ） ---
res = run_strategy('E', lambda r: 1 if r['LA'] >= 25 else 0)
all_results.append(evaluate('E: Layer A Only (Risk>=25)', res, 'VIX/HYG/TED合計25点以上で投資'))

# --- Strategy E2: Layer A緩和（リスク指標>=15） ---
res = run_strategy('E2', lambda r: 1 if r['LA'] >= 15 else 0)
all_results.append(evaluate('E2: Layer A Only (Risk>=15)', res, 'VIX/HYG/TED合計15点以上で投資'))

# --- Strategy F: Layer A+B（リスク+金融政策） ---
res = run_strategy('F', lambda r: 1 if (r['LA'] + r['LB']) >= 40 else 0)
all_results.append(evaluate('F: Layer A+B (Risk+Monetary>=40)', res, 'リスク+金融政策合計40点以上'))

# --- Strategy G: VIX単独 ---
res = run_strategy('G', lambda r: 1 if get_v(vix_d, r.name) is not None and get_v(vix_d, r.name) < 20 else 0.5 if get_v(vix_d, r.name) is not None and get_v(vix_d, r.name) < 25 else 0)
all_results.append(evaluate('G: VIX Only', res, 'VIX<20=100%, VIX<25=50%, VIX>=25=0%'))

# --- Strategy H: VIX回避のみ（VIX>=30でキャッシュ） ---
res = run_strategy('H', lambda r: 0 if get_v(vix_d, r.name) is not None and get_v(vix_d, r.name) >= 30 else 1)
all_results.append(evaluate('H: VIX Spike Avoidance', res, 'VIX>=30のみキャッシュ、それ以外は投資'))

# ============================================================
# PHASE 4: 総合比較表
# ============================================================
print("\n" + "=" * 70)
print("[PHASE 4] Comprehensive Comparison")
print("=" * 70)

print(f"\n  {'Strategy':<35} {'Excess':>8} {'Wins':>6} {'p-val':>8} {'Inv%':>6} {'Verdict':<10}")
print(f"  {'-'*35} {'-'*8} {'-'*6} {'-'*8} {'-'*6} {'-'*10}")
for r in all_results:
    if r is None: continue
    print(f"  {r['name']:<35} {r['mean_excess']:+7.2f}% {r['wins']}/{r['total']}   "
          f"{r['p']:.4f}  {r['invested_pct']:5.0f}%  {r['verdict']}")

# ベスト戦略
valid = [r for r in all_results if r is not None]
if valid:
    best = max(valid, key=lambda x: x['mean_excess'])
    print(f"\n  Best strategy: {best['name']} ({best['mean_excess']:+.2f}%/yr, p={best['p']:.4f})")

print(f"\n{'='*70}")
print(f"H005 v2 Complete: {datetime.now().strftime('%Y/%m/%d %H:%M')}")
print(f"{'='*70}")

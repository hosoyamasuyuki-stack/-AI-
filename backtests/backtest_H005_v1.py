# backtest_H005_v1.py
# H005: MacroPhase判定の有効性バックテスト
#
# 仮説: MacroPhaseスコアでGREEN期間に投資すると、
#        買い持ち（バイ・アンド・ホールド）より高いリターンを得られる
#
# 方法: 2017-2024のFRED/yfinanceヒストリカルデータからMacroPhaseを再計算し、
#        5ウォークフォワードウィンドウでGREEN投資vsバイ&ホールドを比較
#
# 実行: python backtest_H005_v1.py
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

FRED_API_KEY = os.environ.get('FRED_API_KEY', '')
if not FRED_API_KEY:
    print("ERROR: FRED_API_KEY not set")
    exit(1)

print("=" * 60)
print("H005: MacroPhase Backtest")
print(f"Date: {datetime.now().strftime('%Y/%m/%d %H:%M')}")
print("=" * 60)

# ============================================================
# PHASE 1: ヒストリカルデータ取得
# ============================================================
print("\n[PHASE 1] Historical Data Fetch (2014-2024)")

DATA_START = '2014-01-01'
DATA_END   = '2024-12-31'

def fetch_fred(series_id, start=DATA_START, end=DATA_END):
    """FREDから指定期間のデータを取得"""
    try:
        r = requests.get(
            "https://api.stlouisfed.org/fred/series/observations",
            params={
                "series_id": series_id,
                "api_key": FRED_API_KEY,
                "file_type": "json",
                "sort_order": "asc",
                "observation_start": start,
                "observation_end": end,
            },
            timeout=30,
        )
        if r.status_code == 200:
            obs = r.json().get("observations", [])
            df = pd.DataFrame(obs)[["date", "value"]]
            df["date"] = pd.to_datetime(df["date"])
            df["value"] = pd.to_numeric(df["value"], errors="coerce")
            df = df.dropna().set_index("date")
            return df["value"]
    except Exception as e:
        print(f"  WARN: {series_id} -> {e}")
    return pd.Series(dtype=float)

def fetch_yf(ticker, start=DATA_START, end=DATA_END):
    """yfinanceから指定期間の終値を取得"""
    try:
        df = yf.download(ticker, start=start, end=end, progress=False, auto_adjust=True)
        if df.empty:
            return pd.Series(dtype=float)
        df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]
        s = df["Close"].copy()
        s.index = pd.to_datetime(s.index)
        return s
    except:
        return pd.Series(dtype=float)

# FRED指標取得
import time

FRED_SERIES = {
    'VIX':          'VIXCLS',
    'HY_SPREAD':    'BAMLH0A0HYM2',
    'TED_SPREAD':   'TEDRATE',
    'YIELD_SPREAD': 'T10Y2Y',
    'JAPAN_M2':     'MYAGM2JPM189S',
    'FRB_BALANCE':  'WALCL',
    'ISM_PMI':      'MANEMP',        # 注: 製造業雇用者数（PMI代替）
    'UNEMPLOYMENT': 'UNRATE',
}

fred_data = {}
for name, sid in FRED_SERIES.items():
    s = fetch_fred(sid)
    fred_data[name] = s
    n = len(s)
    print(f"  {name}: {n} observations ({s.index[0].strftime('%Y-%m') if n > 0 else 'N/A'} - {s.index[-1].strftime('%Y-%m') if n > 0 else 'N/A'})")
    time.sleep(0.5)

# SP500 for Shiller CAPE calculation
print("  Fetching SP500 for CAPE...")
sp500 = fetch_yf("^GSPC", start="2004-01-01", end=DATA_END)
if len(sp500) > 0:
    monthly_sp = sp500.resample("ME").last()
    ma10y = monthly_sp.rolling(120).mean()
    cape_series = (monthly_sp / ma10y * 20).dropna()
    # 日次に展開（前方補完）
    cape_daily = cape_series.reindex(pd.date_range(cape_series.index[0], cape_series.index[-1], freq='D')).ffill()
    fred_data['CAPE'] = cape_daily
    print(f"  CAPE: {len(cape_daily)} observations")
else:
    fred_data['CAPE'] = pd.Series(dtype=float)
    print("  CAPE: FAILED")

# ベンチマーク: 日経225
print("  Fetching Nikkei 225...")
nikkei = fetch_yf("^N225")
print(f"  Nikkei225: {len(nikkei)} observations")

print(f"\n  Total: {len(fred_data)} indicator series loaded")

# ============================================================
# PHASE 2: 日次MacroPhaseスコア再計算
# ============================================================
print("\n[PHASE 2] Daily MacroPhase Score Calculation")

# 月次データを日次に展開（前方補完）
def to_daily(series, fill='ffill'):
    if series.empty:
        return series
    idx = pd.date_range(series.index[0], series.index[-1], freq='D')
    return series.reindex(idx).ffill()

# 前月比を計算
def mom(series):
    return series.diff(1)

# 前月比%を計算
def mom_pct(series):
    return (series / series.shift(1) - 1) * 100

# 乖離率%
def deviation_pct(series, window=63):
    ma = series.rolling(window).mean()
    return ((series / ma) - 1) * 100

# 日次データ準備
vix_d      = to_daily(fred_data.get('VIX', pd.Series(dtype=float)))
hyg_d      = to_daily(fred_data.get('HY_SPREAD', pd.Series(dtype=float)))
ted_d      = to_daily(fred_data.get('TED_SPREAD', pd.Series(dtype=float)))
m2_d       = to_daily(fred_data.get('JAPAN_M2', pd.Series(dtype=float)))
m2_mom     = mom_pct(m2_d)
frb_d      = to_daily(fred_data.get('FRB_BALANCE', pd.Series(dtype=float)))
frb_mom    = mom(frb_d)
ism_d      = to_daily(fred_data.get('ISM_PMI', pd.Series(dtype=float)))
ism_dev    = deviation_pct(ism_d)
ism_mom_s  = mom(ism_d)
unemp_d    = to_daily(fred_data.get('UNEMPLOYMENT', pd.Series(dtype=float)))
cape_d     = fred_data.get('CAPE', pd.Series(dtype=float))

# MacroPhaseスコアを日次で計算
# daily_update.py calc_macro_phase()と同一ロジック
def calc_phase_score(date):
    """指定日のMacroPhaseスコアを計算（daily_update.pyと同一閾値）"""
    total = 0

    # Layer A: リスク指標 (40点)
    layer_a = 0
    v = vix_d.get(date)
    if v is not None and not np.isnan(v):
        layer_a += 15 if v < 15 else 10 if v < 20 else 5 if v < 25 else 0
    v = hyg_d.get(date)
    if v is not None and not np.isnan(v):
        layer_a += 15 if v < 3 else 10 if v < 4 else 5 if v < 5 else 0
    v = ted_d.get(date)
    if v is not None and not np.isnan(v):
        layer_a += 10 if v < 0.3 else 5 if v < 0.5 else 0
    total += layer_a

    # Layer B: 金融政策 (30点)
    layer_b = 0
    v = m2_mom.get(date)
    if v is not None and not np.isnan(v):
        layer_b += 15 if v > 0.3 else 8 if v > 0 else 0
    v = frb_mom.get(date)
    if v is not None and not np.isnan(v):
        layer_b += 15 if v > 0 else 8 if v > -50000 else 0
    total += layer_b

    # Layer C: 経済活動 (20点)
    layer_c = 0
    i_dev = ism_dev.get(date)
    i_mom = ism_mom_s.get(date)
    if i_dev is not None and i_mom is not None and not np.isnan(i_dev) and not np.isnan(i_mom):
        if i_dev > 0 and i_mom > 0:
            layer_c += 10
        elif i_dev > -1 or i_mom > 0:
            layer_c += 5
    v = unemp_d.get(date)
    if v is not None and not np.isnan(v):
        layer_c += 10 if v < 4.0 else 5 if v < 5.0 else 0
    total += layer_c

    # Layer D: バリュエーション (10点)
    layer_d = 0
    v = cape_d.get(date)
    if v is not None and not np.isnan(v):
        layer_d += 10 if v < 20 else 5 if v < 28 else 0
    total += layer_d

    phase = 'GREEN' if total >= 60 else 'YELLOW' if total >= 30 else 'RED'
    return total, phase, layer_a, layer_b, layer_c, layer_d

# 計算対象期間: 2017-01-01 to 2024-12-31
calc_start = pd.Timestamp('2017-01-01')
calc_end   = pd.Timestamp('2024-12-31')
dates = pd.date_range(calc_start, calc_end, freq='D')

scores = []
for d in dates:
    total, phase, la, lb, lc, ld = calc_phase_score(d)
    scores.append({
        'date': d, 'score': total, 'phase': phase,
        'LayerA': la, 'LayerB': lb, 'LayerC': lc, 'LayerD': ld
    })

df_phase = pd.DataFrame(scores).set_index('date')

# フェーズ分布
green_days  = (df_phase['phase'] == 'GREEN').sum()
yellow_days = (df_phase['phase'] == 'YELLOW').sum()
red_days    = (df_phase['phase'] == 'RED').sum()
total_days  = len(df_phase)
print(f"  Period: {calc_start.strftime('%Y-%m-%d')} to {calc_end.strftime('%Y-%m-%d')}")
print(f"  GREEN:  {green_days} days ({green_days/total_days*100:.1f}%)")
print(f"  YELLOW: {yellow_days} days ({yellow_days/total_days*100:.1f}%)")
print(f"  RED:    {red_days} days ({red_days/total_days*100:.1f}%)")
print(f"  Score range: {df_phase['score'].min()} - {df_phase['score'].max()}")
print(f"  Score mean:  {df_phase['score'].mean():.1f}")

# ============================================================
# PHASE 3: ウォークフォワード5ウィンドウ検証
# ============================================================
print("\n[PHASE 3] Walk-Forward 5-Window Analysis")

WINDOWS = [
    ('W1', '2017-03-31', '2020-03-31'),
    ('W2', '2018-03-31', '2021-03-31'),
    ('W3', '2019-03-31', '2022-03-31'),
    ('W4', '2020-03-31', '2023-03-31'),
    ('W5', '2021-03-31', '2024-03-31'),
]

# 日経225の月次リターンを計算
nikkei_monthly = nikkei.resample('ME').last()

results = []

for wname, wstart, wend in WINDOWS:
    ws = pd.Timestamp(wstart)
    we = pd.Timestamp(wend)
    print(f"\n  [{wname}] {wstart} -> {wend}")

    # ウィンドウ内のフェーズデータ
    w_phase = df_phase.loc[ws:we].copy()
    if len(w_phase) == 0:
        print(f"    SKIP: no phase data")
        continue

    # 月次でフェーズを判定（月末のスコアを使用）
    w_monthly = w_phase.resample('ME').last()

    # 日経225の月次リターン
    w_nikkei = nikkei_monthly.loc[ws:we]
    w_nk_ret = w_nikkei.pct_change().dropna()

    # 共通インデックス
    common = w_monthly.index.intersection(w_nk_ret.index)
    if len(common) < 6:
        print(f"    SKIP: insufficient data ({len(common)} months)")
        continue

    w_monthly = w_monthly.loc[common]
    w_nk_ret  = w_nk_ret.loc[common]

    # 戦略A: GREEN月のみ投資（それ以外は現金=0%リターン）
    green_mask = w_monthly['phase'] == 'GREEN'
    strategy_returns = w_nk_ret.copy()
    strategy_returns[~green_mask] = 0  # GREEN以外は投資しない

    # 累積リターン
    bnh_cumret  = (1 + w_nk_ret).prod() - 1       # バイ&ホールド
    strat_cumret = (1 + strategy_returns).prod() - 1  # GREEN戦略

    # 年率換算
    years = (we - ws).days / 365.25
    bnh_annual  = (1 + bnh_cumret) ** (1/years) - 1
    strat_annual = (1 + strat_cumret) ** (1/years) - 1
    excess = strat_annual - bnh_annual

    green_months = green_mask.sum()
    total_months = len(common)
    green_pct = green_months / total_months * 100

    print(f"    Months: {total_months} (GREEN: {green_months} = {green_pct:.0f}%)")
    print(f"    Buy&Hold:      {bnh_annual*100:+.2f}%/year  (cum: {bnh_cumret*100:+.1f}%)")
    print(f"    GREEN-only:    {strat_annual*100:+.2f}%/year  (cum: {strat_cumret*100:+.1f}%)")
    print(f"    Excess return: {excess*100:+.2f}%/year")
    win = excess > 0

    results.append({
        'window': wname, 'start': wstart, 'end': wend,
        'months': total_months, 'green_months': green_months,
        'green_pct': green_pct,
        'bnh_annual': bnh_annual, 'strat_annual': strat_annual,
        'excess': excess, 'win': win,
        'bnh_cum': bnh_cumret, 'strat_cum': strat_cumret,
    })

# ============================================================
# PHASE 4: 統計的有意性検定
# ============================================================
print("\n" + "=" * 60)
print("[PHASE 4] Statistical Significance Test")
print("=" * 60)

df_results = pd.DataFrame(results)
if len(df_results) == 0:
    print("ERROR: No results to analyze")
    exit(1)

wins = df_results['win'].sum()
losses = len(df_results) - wins
excess_arr = df_results['excess'].values * 100  # パーセントに変換
mean_excess = excess_arr.mean()
std_excess  = excess_arr.std()

# t検定: 超過リターン > 0 の片側検定
t_stat, p_two = stats.ttest_1samp(excess_arr, 0)
p_one = p_two / 2 if t_stat > 0 else 1 - p_two / 2

print(f"\n  Windows:      {len(df_results)}")
print(f"  Wins:         {wins}/{len(df_results)}")
print(f"  Mean excess:  {mean_excess:+.2f}%/year")
print(f"  Std excess:   {std_excess:.2f}%")
print(f"  t-statistic:  {t_stat:.4f}")
print(f"  p-value (1s): {p_one:.4f}")

# 3段階棄却ルール
print(f"\n  --- 3-Stage Rejection Rules ---")
reject1 = p_one > 0.05
reject2 = mean_excess < 3.9
reject3 = losses >= 3
print(f"  Rule 1 (p > 0.05):     {'REJECT' if reject1 else 'PASS'} (p={p_one:.4f})")
print(f"  Rule 2 (excess < 3.9): {'REJECT' if reject2 else 'PASS'} (excess={mean_excess:+.2f}%)")
print(f"  Rule 3 (3+ losses):    {'REJECT' if reject3 else 'PASS'} ({losses} losses)")

if reject1 or reject2 or reject3:
    verdict = 'REJECTED'
else:
    verdict = 'ADOPTED'

print(f"\n  *** H005 VERDICT: {verdict} ***")

# ============================================================
# PHASE 5: 結果サマリー
# ============================================================
print("\n" + "=" * 60)
print("[PHASE 5] Results Summary")
print("=" * 60)

print(f"\n  {'Window':<6} {'Period':<25} {'B&H':<12} {'GREEN':<12} {'Excess':<12} {'Win'}")
print(f"  {'-'*6} {'-'*25} {'-'*12} {'-'*12} {'-'*12} {'-'*4}")
for _, r in df_results.iterrows():
    print(f"  {r['window']:<6} {r['start']} - {r['end']}  "
          f"{r['bnh_annual']*100:+7.2f}%    {r['strat_annual']*100:+7.2f}%    "
          f"{r['excess']*100:+7.2f}%    {'O' if r['win'] else 'X'}")

print(f"\n  Mean excess return: {mean_excess:+.2f}%/year")
print(f"  Win rate: {wins}/{len(df_results)} ({wins/len(df_results)*100:.0f}%)")
print(f"  p-value: {p_one:.4f}")
print(f"  Verdict: {verdict}")

# フェーズ分布サマリー
print(f"\n  Phase Distribution (2017-2024):")
print(f"    GREEN  (>=60): {green_days:4d} days ({green_days/total_days*100:.1f}%)")
print(f"    YELLOW (30-59): {yellow_days:4d} days ({yellow_days/total_days*100:.1f}%)")
print(f"    RED    (<30):  {red_days:4d} days ({red_days/total_days*100:.1f}%)")

print(f"\n{'='*60}")
print(f"H005 Backtest Complete: {datetime.now().strftime('%Y/%m/%d %H:%M')}")
print(f"{'='*60}")

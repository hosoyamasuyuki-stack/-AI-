# backtest_H005B_v1.py
# H005-B: 暴落時買い戦略の有効性バックテスト
#
# 細矢さんの投資哲学の定量検証：
# 「暴落時（VIX>=30 / PBR<1）こそ、長期投資の最大の買い場である」
#
# 検証方法：
# - VIX>=30の月に日経225（市場全体の代替）を買い、3年保有
# - 通常時（VIX<25）に買って3年保有した場合と比較
# - 超過リターンが統計的に有意かを検定
#
# 実行: python backtest_H005B_v1.py
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
print("H005-B: Crash-Buy Strategy Backtest")
print("Hypothesis: Buying during panics (VIX>=30) yields higher")
print("            long-term returns than buying during calm periods")
print(f"Date: {datetime.now().strftime('%Y/%m/%d %H:%M')}")
print("=" * 70)

# ============================================================
# PHASE 1: データ取得
# ============================================================
print("\n[PHASE 1] Data Fetch")

def fetch_fred(series_id, start='2007-01-01', end='2024-12-31'):
    try:
        r = requests.get(
            "https://api.stlouisfed.org/fred/series/observations",
            params={
                "series_id": series_id, "api_key": FRED_API_KEY,
                "file_type": "json", "sort_order": "asc",
                "observation_start": start, "observation_end": end,
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

# VIX (2007-2024: リーマン・コロナ・2022暴落を含む)
vix = fetch_fred('VIXCLS', start='2007-01-01')
print(f"  VIX: {len(vix)} obs ({vix.index[0].strftime('%Y-%m')} - {vix.index[-1].strftime('%Y-%m')})")
time.sleep(1)

# 日経225
nikkei = yf.download("^N225", start="2007-01-01", end="2024-12-31", progress=False, auto_adjust=True)
nikkei.columns = [c[0] if isinstance(c, tuple) else c for c in nikkei.columns]
nk = nikkei["Close"]
print(f"  Nikkei225: {len(nk)} obs ({nk.index[0].strftime('%Y-%m')} - {nk.index[-1].strftime('%Y-%m')})")

# TOPIX
topix = yf.download("1306.T", start="2007-01-01", end="2024-12-31", progress=False, auto_adjust=True)
topix.columns = [c[0] if isinstance(c, tuple) else c for c in topix.columns]
tp = topix["Close"] if not topix.empty else pd.Series(dtype=float)
print(f"  TOPIX: {len(tp)} obs")

# 月次に変換
vix_monthly = vix.resample('ME').mean()  # 月平均VIX
nk_monthly = nk.resample('ME').last()
tp_monthly = tp.resample('ME').last() if not tp.empty else pd.Series(dtype=float)

# ============================================================
# PHASE 2: 暴落月 vs 通常月の特定
# ============================================================
print("\n[PHASE 2] Identify Panic vs Calm Months")

# 暴落月: VIX月平均>=30
panic_months = vix_monthly[vix_monthly >= 30].index
calm_months  = vix_monthly[vix_monthly < 20].index
mid_months   = vix_monthly[(vix_monthly >= 20) & (vix_monthly < 30)].index

print(f"  Panic months (VIX>=30): {len(panic_months)}")
for m in panic_months:
    print(f"    {m.strftime('%Y-%m')} VIX={vix_monthly[m]:.1f}")
print(f"  Calm months  (VIX<20):  {len(calm_months)}")
print(f"  Mid months   (20-30):   {len(mid_months)}")

# ============================================================
# PHASE 3: 各月から3年保有リターンを計算
# ============================================================
print("\n[PHASE 3] 3-Year Forward Returns from Each Entry Month")

HOLD_YEARS = 3
HOLD_MONTHS = HOLD_YEARS * 12

def calc_forward_return(prices, entry_date, months=36):
    """エントリー月から指定月数後のリターンを計算"""
    try:
        entry_idx = prices.index.get_indexer([entry_date], method='nearest')[0]
        exit_idx = entry_idx + months
        if exit_idx >= len(prices):
            return None
        entry_price = prices.iloc[entry_idx]
        exit_price = prices.iloc[exit_idx]
        if entry_price <= 0:
            return None
        total_return = (exit_price / entry_price) - 1
        annual_return = (1 + total_return) ** (1/HOLD_YEARS) - 1
        return annual_return
    except:
        return None

# 全月の3年リターンを計算
all_returns = []
for date in nk_monthly.index:
    ret = calc_forward_return(nk_monthly, date, HOLD_MONTHS)
    if ret is not None:
        vix_val = vix_monthly.get(date)
        if vix_val is not None and not np.isnan(vix_val):
            category = 'PANIC' if vix_val >= 30 else 'CALM' if vix_val < 20 else 'MID'
            all_returns.append({
                'date': date, 'vix': vix_val,
                'return_3y_annual': ret, 'category': category,
            })

df_ret = pd.DataFrame(all_returns)
print(f"  Total entry months with 3Y forward data: {len(df_ret)}")

# カテゴリ別統計
for cat in ['PANIC', 'CALM', 'MID']:
    sub = df_ret[df_ret['category'] == cat]
    if len(sub) > 0:
        print(f"  {cat:6s}: n={len(sub):3d}  mean={sub['return_3y_annual'].mean()*100:+.2f}%/yr  "
              f"median={sub['return_3y_annual'].median()*100:+.2f}%/yr  "
              f"min={sub['return_3y_annual'].min()*100:+.2f}%  max={sub['return_3y_annual'].max()*100:+.2f}%")

# ============================================================
# PHASE 4: 統計検定
# ============================================================
print("\n" + "=" * 70)
print("[PHASE 4] Statistical Tests")
print("=" * 70)

panic_ret = df_ret[df_ret['category'] == 'PANIC']['return_3y_annual'].values * 100
calm_ret  = df_ret[df_ret['category'] == 'CALM']['return_3y_annual'].values * 100

print(f"\n  Test 1: PANIC vs CALM (independent t-test)")
print(f"  PANIC: n={len(panic_ret)}, mean={panic_ret.mean():+.2f}%/yr")
print(f"  CALM:  n={len(calm_ret)}, mean={calm_ret.mean():+.2f}%/yr")
print(f"  Difference: {panic_ret.mean() - calm_ret.mean():+.2f}%/yr")

if len(panic_ret) >= 2 and len(calm_ret) >= 2:
    t_stat, p_val = stats.ttest_ind(panic_ret, calm_ret, alternative='greater')
    print(f"  t-statistic: {t_stat:.4f}")
    print(f"  p-value (one-sided, PANIC > CALM): {p_val:.4f}")
    print(f"  Significant at alpha=0.05? {'YES' if p_val < 0.05 else 'NO'}")
    print(f"  Significant at alpha=0.025 (Bonferroni)? {'YES' if p_val < 0.025 else 'NO'}")
else:
    print(f"  SKIP: insufficient sample (PANIC n={len(panic_ret)})")
    p_val = 1.0
    t_stat = 0

# Test 2: PANIC月のリターンは正か？
print(f"\n  Test 2: PANIC months return > 0? (one-sample t-test)")
if len(panic_ret) >= 2:
    t2, p2 = stats.ttest_1samp(panic_ret, 0)
    p2_one = p2/2 if t2 > 0 else 1 - p2/2
    print(f"  t={t2:.4f}, p(one-sided)={p2_one:.4f}")
    print(f"  PANIC買いは有意にプラスか? {'YES' if p2_one < 0.05 else 'NO'}")

# Test 3: VIXレベル別の3年リターンの相関
print(f"\n  Test 3: VIX level vs 3Y return correlation")
vix_arr = df_ret['vix'].values
ret_arr = df_ret['return_3y_annual'].values * 100
corr, p_corr = stats.pearsonr(vix_arr, ret_arr)
print(f"  Pearson correlation: r={corr:.4f}, p={p_corr:.6f}")
print(f"  Interpretation: {'VIX高い時に買うと3Yリターンが高い' if corr > 0 else 'VIX低い時に買うと3Yリターンが高い'}")

# Test 4: VIX>=25で買った場合
print(f"\n  Test 4: VIX>=25 vs VIX<20 comparison")
high_vix = df_ret[df_ret['vix'] >= 25]['return_3y_annual'].values * 100
low_vix = df_ret[df_ret['vix'] < 20]['return_3y_annual'].values * 100
if len(high_vix) >= 2 and len(low_vix) >= 2:
    t4, p4 = stats.ttest_ind(high_vix, low_vix, alternative='greater')
    print(f"  VIX>=25: n={len(high_vix)}, mean={high_vix.mean():+.2f}%/yr")
    print(f"  VIX<20:  n={len(low_vix)}, mean={low_vix.mean():+.2f}%/yr")
    print(f"  Difference: {high_vix.mean() - low_vix.mean():+.2f}%/yr")
    print(f"  t={t4:.4f}, p={p4:.4f}")

# Test 5: 5年保有でも検証
print(f"\n  Test 5: 5-Year hold period (PANIC vs CALM)")
panic_5y = []
calm_5y = []
for _, row in df_ret.iterrows():
    ret5 = calc_forward_return(nk_monthly, row['date'], 60)
    if ret5 is not None:
        annual5 = (1 + ret5) ** (1/5) - 1  # already annualized by calc
        if row['category'] == 'PANIC':
            panic_5y.append(ret5 * 100)
        elif row['category'] == 'CALM':
            calm_5y.append(ret5 * 100)

panic_5y = np.array(panic_5y)
calm_5y = np.array(calm_5y)
if len(panic_5y) >= 2 and len(calm_5y) >= 2:
    t5, p5 = stats.ttest_ind(panic_5y, calm_5y, alternative='greater')
    print(f"  PANIC(5Y): n={len(panic_5y)}, mean={panic_5y.mean():+.2f}%/yr")
    print(f"  CALM(5Y):  n={len(calm_5y)}, mean={calm_5y.mean():+.2f}%/yr")
    print(f"  Difference: {panic_5y.mean() - calm_5y.mean():+.2f}%/yr")
    print(f"  t={t5:.4f}, p={p5:.4f}")

# ============================================================
# PHASE 5: 結論
# ============================================================
print("\n" + "=" * 70)
print("[PHASE 5] Conclusion")
print("=" * 70)

print(f"\n  H005-B: Crash-Buy Strategy (VIX>=30 entry, 3Y hold)")
print(f"  ─────────────────────────────────────────────────")
if len(panic_ret) >= 2:
    print(f"  PANIC entry mean:  {panic_ret.mean():+.2f}%/year (n={len(panic_ret)})")
    print(f"  CALM entry mean:   {calm_ret.mean():+.2f}%/year (n={len(calm_ret)})")
    print(f"  Excess (PANIC-CALM): {panic_ret.mean()-calm_ret.mean():+.2f}%/year")
    print(f"  p-value: {p_val:.4f}")

    if p_val < 0.025 and (panic_ret.mean() - calm_ret.mean()) > 3.9:
        verdict = 'ADOPTED'
    elif p_val < 0.05:
        verdict = 'CONDITIONALLY ADOPTED'
    else:
        verdict = 'REJECTED (but directionally correct)' if panic_ret.mean() > calm_ret.mean() else 'REJECTED'
    print(f"\n  *** H005-B VERDICT: {verdict} ***")
else:
    print(f"  Insufficient PANIC data (n={len(panic_ret)})")
    print(f"  *** H005-B VERDICT: INSUFFICIENT DATA ***")

print(f"\n  VIX-Return Correlation: r={corr:.4f} (p={p_corr:.6f})")
if corr > 0 and p_corr < 0.05:
    print(f"  >> CONFIRMED: Higher VIX at entry = higher 3Y returns")
    print(f"  >> This supports the crash-buy philosophy")
elif corr > 0:
    print(f"  >> DIRECTIONALLY CORRECT but not statistically significant")
else:
    print(f"  >> NOT SUPPORTED by data")

print(f"\n{'='*70}")
print(f"H005-B Complete: {datetime.now().strftime('%Y/%m/%d %H:%M')}")
print(f"{'='*70}")

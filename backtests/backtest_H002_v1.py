# backtest_H002_v1.py
# H002: Variable1(Real ROIC)のみで3年超過リターンが生じるか
# 仮説登録済み 2026/03/24 / Bonferroni補正 α=0.025
#
# Colab実行:
#   from google.colab import auth
#   auth.authenticate_user()

import os
import gspread
import numpy as np
import pandas as pd
from google.auth import default
from datetime import datetime
from scipy import stats

creds, _ = default()
gc = gspread.authorize(creds)
SPREADSHEET_ID = '1GtlVhGcPjMU0pJWsijwnmTe1rFJXAGvkaJFjav9gGcE'
ss = gc.open_by_key(SPREADSHEET_ID)
NOW = datetime.now().strftime('%Y/%m/%d %H:%M')
print(f"OK: {ss.title} ({NOW})")

print("\n[STEP1] スコアデータ取得")

def load_scores(sheet_name):
    try:
        ws = ss.worksheet(sheet_name)
        data = ws.get_all_records()
        df = pd.DataFrame(data)
        print(f"  {sheet_name}: {len(df)}銘柄")
        return df
    except Exception as e:
        print(f"  WARN: {sheet_name} -> {e}")
        return pd.DataFrame()

df_hold = load_scores('保有銘柄_v4.3スコア')
df_watch = load_scores('監視銘柄_v4.3スコア')
df_all = pd.concat([df_hold, df_watch], ignore_index=True)
print(f"  合計: {len(df_all)}銘柄")

v1_col = None
for col in df_all.columns:
    if 'V1' in col or 'Variable1' in col or 'ROIC' in col or 'v1' in col:
        v1_col = col
        break
if v1_col is None:
    score_cols = [c for c in df_all.columns if any(x in c for x in ['スコア','score','Score','V1','V2','V3'])]
    print(f"  スコア列: {score_cols}")
    for col in df_all.columns:
        if '総合' in col or '合計' in col or 'total' in col.lower():
            v1_col = col
            break
    if v1_col is None:
        print(f"  全列: {list(df_all.columns)}")
else:
    print(f"  V1列: {v1_col}")

import requests
JQUANTS_API_KEY = os.environ.get('JQUANTS_API_KEY', '')

def get_price(code, start, end):
    try:
        code_str = str(code).zfill(4) + '0'
        url = 'https://api.jquants.com/v1/prices/daily_quotes'
        headers = {'Authorization': f'Bearer {JQUANTS_API_KEY}'}
        params = {'code': code_str, 'from': start, 'to': end}
        res = requests.get(url, headers=headers, params=params, timeout=15)
        if res.status_code == 200:
            data = res.json().get('daily_quotes', [])
            if data:
                df = pd.DataFrame(data)
                df['Date'] = pd.to_datetime(df['Date'])
                return df.sort_values('Date')
    except:
        pass
    return None

PHASES = {
    'PHASE1_下落': ('20190101', '20220101'),
    'PHASE2_回復': ('20200401', '20230401'),
    'PHASE3_成長': ('20210101', '20240101'),
}

code_col = None
for col in df_all.columns:
    if 'コード' in col or 'code' in col.lower() or 'Code' in col:
        code_col = col
        break
if code_col is None:
    code_col = df_all.columns[0]
print(f"\n  コード列: {code_col} | V1列: {v1_col}")

print("\n[STEP2] フェーズ別リターン計算（最大30銘柄）")
results = []
test_codes = df_all[code_col].dropna().unique()[:30]

for phase_name, (buy_date, sell_date) in PHASES.items():
    print(f"\n  [{phase_name}]")
    phase_results = []
    for code in test_codes:
        price_df = get_price(code, buy_date, sell_date)
        if price_df is None or len(price_df) < 10:
            continue
        buy_price = price_df.iloc[0].get('AdjustmentClose') or price_df.iloc[0].get('Close')
        sell_price = price_df.iloc[-1].get('AdjustmentClose') or price_df.iloc[-1].get('Close')
        if not buy_price or not sell_price or float(buy_price) == 0:
            continue
        ret_3y = (float(sell_price) / float(buy_price) - 1) * 100
        row = df_all[df_all[code_col].astype(str) == str(code)]
        v1_score = float(row[v1_col].values[0]) if v1_col and len(row) > 0 else 50.0
        phase_results.append({'code': code, 'v1_score': v1_score, 'ret_3y': ret_3y})
    if len(phase_results) < 5:
        print(f"    データ不足: {len(phase_results)}")
        continue
    df_phase = pd.DataFrame(phase_results)
    q75 = df_phase['v1_score'].quantile(0.75)
    q25 = df_phase['v1_score'].quantile(0.25)
    high_v1 = df_phase[df_phase['v1_score'] >= q75]['ret_3y']
    low_v1  = df_phase[df_phase['v1_score'] <= q25]['ret_3y']
    try:
        import yfinance as yf
        nk = yf.download('^N225', start=buy_date[:4]+'-'+buy_date[4:6]+'-'+buy_date[6:], end=sell_date[:4]+'-'+sell_date[4:6]+'-'+sell_date[6:], progress=False, auto_adjust=True)
        nk_ret = float((nk['Close'].iloc[-1] / nk['Close'].iloc[0] - 1) * 100) if not nk.empty else 0
    except:
        nk_ret = 0
    excess = high_v1.mean() - nk_ret
    t_stat, p_val = stats.ttest_1samp(high_v1, 0)
    p_one = p_val / 2 if t_stat > 0 else 1.0
    adopted = excess >= 3.9 and p_one < 0.025
    print(f"    N={len(df_phase)} 日経={nk_ret:.1f}% V1上={high_v1.mean():.1f}% 超過={excess:+.1f}% p={p_one:.3f} {'★採用' if adopted else '棄却'}")
    results.append({'phase':phase_name,'n':len(df_phase),'nikkei':round(nk_ret,2),'v1_high':round(high_v1.mean(),2),'excess':round(excess,2),'t':round(t_stat,3),'p':round(p_one,4),'adopted':adopted})

print("\n[STEP3] スプレッドシート保存")
RESULT_SHEET = 'H002_Variable1_バックテスト'
try:
    ss.del_worksheet(ss.worksheet(RESULT_SHEET))
except:
    pass
if results:
    ws_r = ss.add_worksheet(title=RESULT_SHEET, rows=30, cols=9)
    ws_r.update('A1', [['H002 暫定結果(30銘柄テスト)'],['実行:NOW'],[''],['フェーズ','N','日経%','V1上%','超過%','t','p(片側)','採用']] + [[r['phase'],r['n'],r['nikkei'],r['v1_high'],r['excess'],r['t'],r['p'],'採用' if r['adopted'] else '棄却'] for r in results])
    adopted_cnt = sum(1 for r in results if r['adopted'])
    print(f"OK: {RESULT_SHEET} | 採用フェーズ: {adopted_cnt}/{len(results)}")
    print('→ 本番119銘柄で再実行要' if adopted_cnt >= 2 else '→ 要検討')
else:
    print('結果なし')

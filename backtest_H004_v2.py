"""
backtest_H004_v2.py
H004: Variable3（価格スコア）の有効性バックテスト Phase2（本番計算）

【仮説】Variable3（PEGスコア50%+FCF利回り50%）上位銘柄は3年超過リターンを得られる
【登録】2026/03/25 / Bonferroni補正 α=0.025
【結果】条件付き採択（年率+9.13% / 5ウォークフォワード全勝 / p=0.0321）
【役割】Phase2: 実際の3年リターン計算・統計検定（Phase1の設計を受けて本番実行）
【実行】Google Colab推奨:
    from google.colab import auth
    auth.authenticate_user()
【依存】GOOGLE_CREDENTIALS / SPREADSHEET_ID（環境変数）
"""
# backtest_H004_v2.py
# H004 Phase2: Variable3(価格スコア)上位銘柄の実際の3年リターン計算
# Colabで実行: auth.authenticate_user() -> exec(code)
# 2026/03/25

import gspread
import numpy as np
import pandas as pd
from google.auth import default
from datetime import datetime
import yfinance as yf
import warnings
warnings.filterwarnings("ignore")
from scipy import stats

creds, _ = default()
gc = gspread.authorize(creds)
SPREADSHEET_ID = '1GtlVhGcPjMU0pJWsijwnmTe1rFJXAGvkaJFjav9gGcE'
ss = gc.open_by_key(SPREADSHEET_ID)
NOW = datetime.now().strftime('%Y/%m/%d %H:%M')
print(f"OK: {ss.title} ({NOW})")

# ============================================================
# STEP1: スコアデータ読み込み
# ============================================================
print("\n[STEP1] スコアデータ読み込み")

def load_scores(sheet_name):
    try:
        ws = ss.worksheet(sheet_name)
        df = pd.DataFrame(ws.get_all_records())
        print(f"  {sheet_name}: {len(df)}銘柄")
        return df
    except Exception as e:
        print(f"  WARN: {sheet_name} -> {e}")
        return pd.DataFrame()

df = pd.concat([
    load_scores('保有銘柄_v4.3スコア'),
    load_scores('監視銘柄_v4.3スコア'),
    load_scores('学習用銘柄_v4.2スコア'),
], ignore_index=True)

# 価格スコア列を特定
score_col = '価格(s3)'
code_col  = 'コード'
print(f"  合計: {len(df)}銘柄 / スコア列: {score_col}")

# 数値変換
df[score_col] = pd.to_numeric(df[score_col], errors='coerce')
df[code_col]  = df[code_col].astype(str).str.replace('.0','',regex=False)
df = df.dropna(subset=[score_col, code_col])
print(f"  有効銘柄: {len(df)}銘柄")

# ============================================================
# STEP2: ウォークフォワード5ウィンドウ
# ============================================================
windows = [
    ("W1", "2017-03-31", "2020-03-31"),
    ("W2", "2018-03-31", "2021-03-31"),
    ("W3", "2019-03-31", "2022-03-31"),
    ("W4", "2020-03-31", "2023-03-31"),
    ("W5", "2021-03-31", "2024-03-31"),
]

# 日経225リターン（Phase1で取得済み・再取得）
nk225_rets = {}
nk = yf.Ticker("^N225")
for w, s, e in windows:
    try:
        h = nk.history(start=s, end=e)
        if len(h) >= 2:
            nk225_rets[w] = (h["Close"].iloc[-1] - h["Close"].iloc[0]) / h["Close"].iloc[0] * 100
    except:
        nk225_rets[w] = None

# ============================================================
# STEP3: 各ウィンドウで上位25%・下位25%のリターン計算
# ============================================================
print("\n[STEP3] Variable3スコアでグループ分け・リターン計算")

def get_3yr_return(code, start, end):
    try:
        ticker = str(code).zfill(4) + ".T"
        h = yf.download(ticker, start=start, end=end, progress=False, auto_adjust=True)
        if isinstance(h.columns, pd.MultiIndex):
            close = h['Close'].iloc[:,0]
        else:
            close = h['Close']
        close = close.dropna()
        if len(close) >= 2:
            return (close.iloc[-1] - close.iloc[0]) / close.iloc[0] * 100
    except:
        pass
    return None

results = []
win_count = 0

for w, start, end in windows:
    print(f"\n  {w}: {start} -> {end}")
    nk_ret = nk225_rets.get(w)

    # Variable3スコアでランク付け
    q75 = df[score_col].quantile(0.75)
    q25 = df[score_col].quantile(0.25)
    top_codes    = df[df[score_col] >= q75][code_col].tolist()
    bottom_codes = df[df[score_col] <= q25][code_col].tolist()
    print(f"    上位25%({len(top_codes)}銘柄 score>={q75:.1f}) / 下位25%({len(bottom_codes)}銘柄 score<={q25:.1f})")

    # 上位グループのリターン取得（最大30銘柄でサンプリング）
    top_sample = top_codes[:30]
    top_rets = []
    for code in top_sample:
        r = get_3yr_return(code, start, end)
        if r is not None:
            top_rets.append(r)

    if len(top_rets) == 0:
        print(f"    リターン取得失敗")
        continue

    top_mean = np.mean(top_rets)
    excess   = top_mean - nk_ret if nk_ret is not None else None
    win      = excess > 0 if excess is not None else False
    if win: win_count += 1

    print(f"    上位平均リターン: {top_mean:+.2f}%")
    print(f"    日経: {nk_ret:+.2f}%")
    print(f"    超過リターン: {excess:+.2f}% -> {'◎ 勝ち' if win else '✕ 負け'}")

    results.append({
        'window': w, 'start': start, 'end': end,
        'nk225': round(nk_ret,2) if nk_ret else None,
        'top_mean': round(top_mean,2),
        'excess': round(excess,2) if excess else None,
        'n_stocks': len(top_rets),
        'result': '◎' if win else '✕'
    })

# ============================================================
# STEP4: 統計検定
# ============================================================
print("\n[STEP4] 統計検定")
excesses = [r['excess'] for r in results if r['excess'] is not None]
if len(excesses) >= 3:
    t_stat, p_val = stats.ttest_1samp(excesses, 0)
    mean_excess = np.mean(excesses)
    annualized  = mean_excess / 3
    print(f"  平均超過リターン: {mean_excess:+.2f}% (年率: {annualized:+.2f}%)")
    print(f"  t統計量: {t_stat:.3f} / p値: {p_val:.4f}")
    print(f"  勝ちウィンドウ: {win_count}/{len(results)}")
    adopted = p_val < 0.025 and annualized >= 3.9 and win_count >= 3
    verdict = "✅ 採択" if adopted else "❌ 棄却"
    print(f"  判定: {verdict}")
else:
    p_val = None; mean_excess = None; annualized = None; verdict = "データ不足"

# ============================================================
# STEP5: スプレッドシートに結果を書き込み
# ============================================================
print("\n[STEP5] 結果をスプレッドシートに記録")
RESULT_SHEET = "H004_Variable3_バックテスト"
try:
    ws_r = ss.worksheet(RESULT_SHEET)
except:
    ws_r = ss.add_worksheet(title=RESULT_SHEET, rows=60, cols=12)

rows_out = [
    ["H004: Variable3(価格スコア)バックテスト Phase2結果","","","","","",""],
    ["実行日", NOW,"","","","",""],
    ["","","","","","",""],
    ["■ 判定基準","","","","","",""],
    ["採択条件1", "p値 < 0.025 (Bonferroni補正)","","","","",""],
    ["採択条件2", "年率超過リターン >= +3.9%","","","","",""],
    ["採択条件3", "5ウィンドウ中3回以上勝ち","","","","",""],
    ["","","","","","",""],
    ["■ ウォークフォワード結果","","","","","",""],
    ["ウィンドウ","期間","日経%","上位平均%","超過%","銘柄数","勝敗"],
]
for r in results:
    rows_out.append([
        r['window'], f"{r['start']}→{r['end']}",
        f"{r['nk225']:+.2f}%" if r['nk225'] else "-",
        f"{r['top_mean']:+.2f}%",
        f"{r['excess']:+.2f}%" if r['excess'] else "-",
        r['n_stocks'], r['result']
    ])
rows_out += [
    ["","","","","","",""],
    ["■ 統計検定結果","","","","","",""],
    ["平均超過リターン", f"{mean_excess:+.2f}%" if mean_excess else "-","","","","",""],
    ["年率換算", f"{annualized:+.2f}%" if annualized else "-","","","","",""],
    ["p値", f"{p_val:.4f}" if p_val else "-","","","","",""],
    ["勝ちウィンドウ", f"{win_count}/{len(results)}","","","","",""],
    ["最終判定", verdict,"","","","",""],
]
ws_r.clear()
ws_r.update("A1", rows_out)
ws_r.format("A1:G1", {"textFormat": {"bold": True}})
ws_r.format("A9:G9", {"textFormat": {"bold": True}})
print(f"  シート '{RESULT_SHEET}' 更新完了")

# ============================================================
# STEP6: 仮説登録簿を更新
# ============================================================
try:
    ws_h = ss.worksheet("仮説登録簿")
    all_rows = ws_h.get_all_values()
    for i, row in enumerate(all_rows):
        if row and row[0] == "H004":
            ws_h.update(f"E{i+1}", [[verdict]])
            print(f"  仮説登録簿 H004 更新: {verdict}")
            break
except Exception as e:
    print(f"  仮説登録簿更新失敗: {e}")

# 作業ログ
try:
    wl = ss.worksheet("作業ログ")
    last = len(wl.get_all_values()) + 1
    wl.update(f"A{last}", [[NOW, "backtest_H004_v2.py",
        f"Variable3バックテスト完了。{verdict} 年率{annualized:+.2f}% p={p_val:.4f}" if annualized else "H004 データ不足",
        "Colab実行", "完了"]])
except: pass

print(f"\n===== H004 Phase2完了 =====")
print(f"次回: 結果を見てH004の採択・棄却を最終判断する")

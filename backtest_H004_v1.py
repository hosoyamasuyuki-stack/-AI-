# backtest_H004_v1.py
# H004: Variable3(価格スコア)のみで3年超過リターンが生じるか
# 仮説登録済み 2026/03/25 / Bonferroni補正 α=0.025
# Variable3 = PEGスコア(50%) + FCF利回りスコア(50%)
#
# Colab実行:
#   from google.colab import auth
#   auth.authenticate_user()

import gspread
import numpy as np
import pandas as pd
from google.auth import default
from datetime import datetime
from scipy import stats
import yfinance as yf
import warnings
warnings.filterwarnings("ignore")

creds, _ = default()
gc = gspread.authorize(creds)
SPREADSHEET_ID = '1GtlVhGcPjMU0pJWsijwnmTe1rFJXAGvkaJFjav9gGcE'
ss = gc.open_by_key(SPREADSHEET_ID)
NOW = datetime.now().strftime('%Y/%m/%d %H:%M')
print(f"OK: {ss.title} ({NOW})")

# ============================================================
# Variable3スコア計算関数
# ============================================================

def calc_peg_score(peg):
    if peg is None or peg <= 0: return 26
    if peg <= 0.5: return 100
    if peg <= 1.0: return 72
    if peg <= 1.5: return 42
    return 26

def calc_fcf_yield_score(fcf_yield_pct):
    if fcf_yield_pct is None: return 20
    if fcf_yield_pct >= 8: return 100
    if fcf_yield_pct >= 4: return 70
    if fcf_yield_pct >= 2: return 38
    return 8

def calc_variable3(peg, fcf_yield_pct):
    peg_s = calc_peg_score(peg)
    fcf_s = calc_fcf_yield_score(fcf_yield_pct)
    return round(peg_s * 0.5 + fcf_s * 0.5, 2)

# ============================================================
# STEP1: スコアデータ取得
# ============================================================
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

df_hold  = load_scores('保有銘柄_v4.3スコア')
df_watch = load_scores('監視銘柄_v4.3スコア')
df_learn = load_scores('学習用銘柄_v4.2スコア')
df_all = pd.concat([df_hold, df_watch, df_learn], ignore_index=True)
print(f"  合計: {len(df_all)}銘柄")

# ============================================================
# STEP2: Variable3スコアで上位・下位グループ分け
# ============================================================
print("\n[STEP2] Variable3スコアでグループ分け")

score_col = None
for col in df_all.columns:
    if 'var3' in col.lower() or '価格' in col or 'variable3' in col.lower() or 'v3' in col.lower():
        score_col = col
        break

if score_col is None:
    print("  Variable3列が見つからない -> 総合スコアで代替")
    for col in df_all.columns:
        if 'score' in col.lower() or 'スコア' in col:
            score_col = col
            break

print(f"  使用列: {score_col}")
print(f"  全列: {list(df_all.columns)[:10]}")

# ============================================================
# STEP3: 銘柄コード取得
# ============================================================
print("\n[STEP3] 銘柄コード確認")
code_col = None
for col in df_all.columns:
    if 'code' in col.lower() or 'コード' in col or '銘柄コード' in col:
        code_col = col
        break
print(f"  コード列: {code_col}")
print(f"  サンプル: {df_all[code_col].head(5).tolist() if code_col else 'なし'}")

# ============================================================
# STEP4: ウォークフォワード5ウィンドウ設計
# ============================================================
print("\n[STEP4] ウォークフォワード設計")
windows = [
    ("W1", "2017-03-31", "2020-03-31"),
    ("W2", "2018-03-31", "2021-03-31"),
    ("W3", "2019-03-31", "2022-03-31"),
    ("W4", "2020-03-31", "2023-03-31"),
    ("W5", "2021-03-31", "2024-03-31"),
]
for w, s, e in windows:
    print(f"  {w}: {s} -> {e}")

# ============================================================
# STEP5: 日経225リターン取得
# ============================================================
print("\n[STEP5] 日経225リターン取得")
nk225_returns = {}
nk = yf.Ticker("^N225")
for w, start, end in windows:
    try:
        h = nk.history(start=start, end=end)
        if len(h) >= 2:
            ret = (h["Close"].iloc[-1] - h["Close"].iloc[0]) / h["Close"].iloc[0] * 100
            nk225_returns[w] = round(ret, 2)
            print(f"  {w}: 日経225 {ret:+.2f}%")
    except Exception as e:
        print(f"  {w}: 日経取得失敗 {e}")

# ============================================================
# STEP6: 結果シート作成
# ============================================================
print("\n[STEP6] 結果をスプレッドシートに記録")
RESULT_SHEET = "H004_Variable3_バックテスト"
try:
    ss.del_worksheet(ss.worksheet(RESULT_SHEET))
except:
    pass
ws_r = ss.add_worksheet(title=RESULT_SHEET, rows=50, cols=15)

header = [
    ["H004: Variable3(価格スコア)バックテスト", "", "", "", "", ""],
    ["実行日", NOW, "", "", "", ""],
    ["仮説", "Variable3スコア上位銘柄は3年後に日経を超過するか", "", "", "", ""],
    ["棄却基準1", "p値 > 0.025 (Bonferroni補正)", "", "", "", ""],
    ["棄却基準2", "超過リターン < +3.9%/年", "", "", "", ""],
    ["棄却基準3", "ウォークフォワード5窓で3回以上負け", "", "", "", ""],
    ["", "", "", "", "", ""],
    ["■ ウォークフォワード設計", "", "", "", "", ""],
    ["ウィンドウ", "開始", "終了", "日経リターン%", "Variable3上位超過%", "勝敗"],
]

summary_data = []
for w, start, end in windows:
    nk_ret = nk225_returns.get(w, "取得失敗")
    summary_data.append([w, start, end, f"{nk_ret:+.2f}%" if isinstance(nk_ret, float) else nk_ret, "Colab実行後に記入", ""])

result_rows = header + summary_data + [
    ["", "", "", "", "", ""],
    ["■ 注意", "", "", "", "", ""],
    ["このシートは枠組みのみ。実際のバックテストはColab実行が必要。", "", "", "", "", ""],
    ["理由: J-Quants財務データ（10年分）の取得にはColab認証が必要。", "", "", "", "", ""],
    ["手順: Colabでbacktest_H004_v1.pyを実行 -> 本シートに結果が書き込まれる", "", "", "", "", ""],
]

ws_r.update("A1", result_rows)
ws_r.format("A1:F1", {"textFormat": {"bold": True}})
ws_r.format("A8:F8", {"textFormat": {"bold": True}})
ws_r.format("A9:F9", {"textFormat": {"bold": True}})
print(f"  シート '{RESULT_SHEET}' 作成完了")

# ============================================================
# STEP7: 仮説登録簿に記録
# ============================================================
print("\n[STEP7] 仮説登録簿に H004 を記録")
try:
    ws_hyp = ss.worksheet("仮説登録簿")
    rows = ws_hyp.get_all_values()
    last = len(rows) + 1
    ws_hyp.update(f"A{last}", [[
        "H004", "Variable3(価格スコア)の有効性",
        "Variable3スコア上位銘柄は3年後に日経比+3.9%/年以上の超過リターンを生む",
        "2026/03/25", "検証中", "backtest_H004_v1.py",
        "PEGスコア50%+FCF利回りスコア50%", "3年ウォークフォワード5窓"
    ]])
    print(f"  仮説登録簿 行{last}に追記完了")
except Exception as e:
    print(f"  仮説登録簿への記録失敗: {e}")

print(f"\n===== H004バックテスト枠組み完成 =====")
print(f"次のステップ: このコード(backtest_H004_v1.py)をColabで実行")
print(f"実行日時: {NOW}")

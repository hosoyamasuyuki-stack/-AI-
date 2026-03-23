# ============================================================
# verify_0415.py v2（完全自動化版）
# 2026/04/15 9:00 JST 自動実行
# ============================================================

import os, json, warnings
from datetime import datetime
import gspread
from google.oauth2.service_account import Credentials
import yfinance as yf
warnings.filterwarnings("ignore")

SPREADSHEET_ID = "1GtlVhGcPjMU0pJWsijwnmTe1rFJXAGvkaJFjav9gGcE"
scope = ["https://spreadsheets.google.com/feeds",
         "https://www.googleapis.com/auth/drive"]
creds_dict = json.loads(os.environ.get("GOOGLE_CREDENTIALS", "{}"))
creds = Credentials.from_service_account_info(creds_dict, scopes=scope)
gc = gspread.authorize(creds)
ss = gc.open_by_key(SPREADSHEET_ID)
NOW = datetime.now().strftime("%Y/%m/%d %H:%M")
print(f"✅ 接続完了: {ss.title} ({NOW})")

# ── 日経225当日騰落率を自動取得 ──
def get_nk225_change():
    try:
        h = yf.Ticker("^N225").history(period="5d")
        if len(h) >= 2:
            now  = float(h["Close"].iloc[-1])
            prev = float(h["Close"].iloc[-2])
            chg  = round((now - prev) / prev * 100, 2)
            print(f"  日経225: {now:,.0f}円 ({chg:+.2f}%)")
            return now, chg
    except Exception as e:
        print(f"  ⚠️ 日経取得失敗: {e}")
    return None, None

# ── 銘柄株価を自動取得 ──
def get_price(code):
    try:
        ticker = str(code).replace(".T","") + ".T"
        h = yf.Ticker(ticker).history(period="5d")
        if len(h) >= 1:
            return round(float(h["Close"].iloc[-1]), 0)
    except:
        pass
    # J-Quants フォールバック
    try:
        import requests as req
        API_KEY = "7bEWg3-b2MPc0DWG1vjSugW48LahAiVi622Nxy8S7PA"
        today = datetime.now().strftime("%Y%m%d")
        url = f"https://api.jquants.com/v2/equities/bars/daily?code={code}0&from={today}&to={today}"
        r = req.get(url, headers={"x-api-key": API_KEY})
        data = r.json().get("data", [])
        if data:
            return round(float(data[-1].get("AdjC", 0)), 0)
    except:
        pass
    return None

# ── 予測記録から対象銘柄を取得 ──
ws_pred = ss.worksheet("予測記録")
rows = ws_pred.get_all_values()
header = rows[0]
data = rows[1:]

step0_rows = [r for r in data if "2026/03" in r[0] or "2026-03" in r[0]]
if not step0_rows:
    step0_rows = data[:20]
print(f"  対象銘柄: {len(step0_rows)}件")

# ── 日経データ取得 ──
nk_price, nk_chg = get_nk225_change()

# ── 検証シート作成 ──
VERIFY_SHEET = "STEP0_目先検証_0415"
try:
    ss.del_worksheet(ss.worksheet(VERIFY_SHEET))
except: pass
ws_v = ss.add_worksheet(title=VERIFY_SHEET, rows=60, cols=12)

meta_rows = [
    ["STEP0 目先予測 初回検証シート（完全自動化版）","","","","","","","","","","",""],
    ["検証日", NOW, "", "", "", "", "", "", "", "", "", ""],
    ["日経225当日", f"{nk_price:,.0f}円" if nk_price else "取得失敗",
     f"{nk_chg:+.2f}%" if nk_chg else "", "", "", "", "", "", "", "", "", ""],
    ["","","","","","","","","","","",""],
    ["■ 判定基準","","","","","","","","","","",""],
    ["勝率80%以上","→ v4.3は機能している（ウェイト据え置き）","","","","","","","","","",""],
    ["勝率60-80%","→ 継続観察（パラメータ微調整検討）","","","","","","","","","",""],
    ["勝率50%以下","→ 設計見直し（根本再検討）","","","","","","","","","",""],
    ["","","","","","","","","","","",""],
    ["銘柄コード","銘柄名","業種","予測スコア","予測ランク",
     "目先予測","予測時株価","検証時株価(自動)","騰落率%","日経比較","勝敗","備考"],
]

data_rows = []
win = 0; total = 0

for row in step0_rows:
    def gc_safe(idx, default=""):
        return row[idx] if len(row) > idx else default

    code       = gc_safe(0)
    name       = gc_safe(1)
    sect       = gc_safe(2)
    score      = gc_safe(3)
    rank       = gc_safe(4)
    direction  = gc_safe(5)
    pred_price_raw = gc_safe(6)

    # 予測時株価
    try:
        pred_price = float(str(pred_price_raw).replace(",",""))
    except:
        pred_price = None

    # 検証時株価（自動取得）
    curr_price = get_price(code) if code else None

    # 騰落率計算
    if pred_price and curr_price and pred_price > 0:
        change_pct = round((curr_price - pred_price) / pred_price * 100, 2)
    else:
        change_pct = None

    # 日経比較
    if change_pct is not None and nk_chg is not None:
        vs_nk = round(change_pct - nk_chg, 2)
    else:
        vs_nk = None

    # 勝敗判定（日経比超過で勝ち）
    if vs_nk is not None:
        result = "◎" if vs_nk > 0 else "✕"
        total += 1
        if vs_nk > 0: win += 1
    else:
        result = "データなし"

    data_rows.append([
        code, name, sect, score, rank, direction,
        f"{pred_price:,.0f}" if pred_price else pred_price_raw,
        f"{curr_price:,.0f}" if curr_price else "取得失敗",
        f"{change_pct:+.2f}%" if change_pct is not None else "",
        f"{vs_nk:+.2f}%" if vs_nk is not None else "",
        result, ""
    ])

# 勝率サマリー
win_rate = round(win / total * 100, 1) if total > 0 else 0
if win_rate >= 80:   verdict = "✅ v4.3は機能している"
elif win_rate >= 60: verdict = "⚠️ 継続観察"
else:                verdict = "🔴 設計見直し"

summary_rows = [
    ["","","","","","","","","","","",""],
    ["■ 検証結果サマリー","","","","","","","","","","",""],
    ["対象銘柄数", total, "", "勝ち", win, "負け", total-win, "", "", "", "", ""],
    ["勝率", f"{win_rate}%", "", "判定", verdict, "", "", "", "", "", "", ""],
]

all_rows = meta_rows + data_rows + summary_rows
ws_v.update("A1", all_rows)
ws_v.format("A10:L10", {"textFormat": {"bold": True}})

print(f"\n✅ 検証シート生成完了")
print(f"   勝率: {win_rate}% ({win}/{total}) → {verdict}")

# 作業ログ
try:
    wl = ss.worksheet("作業ログ")
    last = len(wl.get_all_values()) + 1
    wl.update(f"A{last}", [[
        NOW, "verify_0415.py v2",
        f"STEP0目先検証完了。勝率{win_rate}%({win}/{total})。{verdict}",
        "完全自動化", "✅完了"
    ]])
except: pass

print(f"✅ verify_0415.py v2 完了: {NOW}")

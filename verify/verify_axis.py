# verify_axis.py
# 4軸予測システムの時間軸別検証スクリプト（汎用）
# Usage: python verify/verify_axis.py --axis 短期|中期|長期 [--only_past_due]
#
# 仕様:
# - 予測記録シートから指定時間軸の予測方向・目標・検証予定日を読む
# - 各銘柄の現在株価と日経225騰落率を取得
# - 予測方向 vs 実際（日経比超過の正負）で勝敗判定
# - 予測記録シートの「実績株価」「騰落率」「日経比超過」「勝敗」列を更新
# - STEP0_<AXIS> 検証サマリーシートを生成/更新
import os, sys, json, argparse, warnings
from datetime import datetime, timedelta
import yfinance as yf
warnings.filterwarnings("ignore")

from core.auth import get_spreadsheet

ap = argparse.ArgumentParser()
ap.add_argument('--axis', required=True, choices=['目先', '短期', '中期', '長期'])
ap.add_argument('--only_past_due', action='store_true',
                help='検証予定日が到来した銘柄のみ対象')
args = ap.parse_args()

AXIS = args.axis
AXIS_EN = {'目先': 'near', '短期': 'short', '中期': 'mid', '長期': 'long'}[AXIS]

# 時間軸の開始列（予測記録のスキーマに合わせる）
AXIS_START = {'目先': 8, '短期': 16, '中期': 24, '長期': 32}[AXIS]
# 各軸8列: 0=方向 1=目標 2=根拠 3=検証日 4=実績株価 5=騰落率 6=日経比 7=勝敗

ss = get_spreadsheet()
NOW = datetime.now().strftime('%Y/%m/%d %H:%M')
TODAY = datetime.now()
print(f"OK: {ss.title} ({NOW}) axis={AXIS}")

def get_nk225():
    try:
        h = yf.Ticker("^N225").history(period="5d")
        if len(h) >= 2:
            c = float(h["Close"].iloc[-1])
            p = float(h["Close"].iloc[-2])
            chg = round((c - p) / p * 100, 2)
            print(f"  NK225: {c:,.0f} ({chg:+.2f}%)")
            return c, chg
    except Exception as e:
        print(f"  NK225 error: {e}")
    return None, None

def get_price(code):
    try:
        h = yf.Ticker(str(code).replace(".T", "") + ".T").history(period="5d")
        if len(h) >= 1:
            return round(float(h["Close"].iloc[-1]), 0)
    except:
        pass
    try:
        import requests as req
        API_KEY = os.environ.get('JQUANTS_API_KEY', '')
        today = datetime.now().strftime("%Y%m%d")
        url = f"https://api.jquants.com/v2/equities/bars/daily?code={code}0&from={today}&to={today}"
        r = req.get(url, headers={"x-api-key": API_KEY})
        data = r.json().get("data", [])
        if data:
            return round(float(data[-1].get("AdjC", 0)), 0)
    except:
        pass
    return None

def direction_sign(dir_str):
    """予測方向文字列から +1(上昇)/0(中立)/-1(下落) を返す"""
    if not dir_str:
        return 0
    s = dir_str.strip()
    if '↑' in s or '上' in s or '強気' in s or '買' in s:
        return 1
    if '↓' in s or '下' in s or '弱気' in s or '売' in s:
        return -1
    return 0

ws_pred = ss.worksheet("予測記録")
rows = ws_pred.get_all_values()
data = rows[2:]  # skip header + subheader

nk_price, nk_chg = get_nk225()

VERIFY_SHEET = f"STEP0_{AXIS_EN}"
try:
    ss.del_worksheet(ss.worksheet(VERIFY_SHEET))
except:
    pass
ws_v = ss.add_worksheet(title=VERIFY_SHEET, rows=max(len(data) + 20, 60), cols=14)

meta = [
    [f"STEP0 {AXIS}({AXIS_EN}) verification", "", "", "", "", "", "", "", "", "", "", "", "", ""],
    ["verify_date", NOW, "", "", "", "", "", "", "", "", "", "", "", ""],
    ["NK225", f"{nk_price:,.0f}" if nk_price else "error",
     f"{nk_chg:+.2f}%" if nk_chg else "", "", "", "", "", "", "", "", "", "", "", ""],
    ["", "", "", "", "", "", "", "", "", "", "", "", "", ""],
    ["win>=80%", "functioning", "", "", "", "", "", "", "", "", "", "", "", ""],
    ["win 60-80%", "watch", "", "", "", "", "", "", "", "", "", "", "", ""],
    ["win<60%", "review", "", "", "", "", "", "", "", "", "", "", "", ""],
    ["", "", "", "", "", "", "", "", "", "", "", "", "", ""],
    ["", "", "", "", "", "", "", "", "", "", "", "", "", ""],
    ["code", "name", "sector", "score", "rank", "direction",
     "pred_target", "curr_price", "change%", "vs_nk", "ver_date",
     "days_elapsed", "result", "note"],
]

rows_out = []
win = 0
total = 0
row_index_in_sheet = 2  # 予測記録のrow 2から開始（row 0=header, row 1=subheader）
updates = []  # 予測記録シートの一括更新用

for row in data:
    row_index_in_sheet += 1

    def s(i, d=""):
        return row[i] if len(row) > i else d

    code = s(1)  # COL_CODE
    if not code:
        continue
    name = s(2)
    sect = s(3)
    pred_price_raw = s(4)  # 記録時株価
    score = s(5)
    rank = s(6)

    # 当該軸の8列を読む
    direction = s(AXIS_START)
    target    = s(AXIS_START + 1)
    ver_date  = s(AXIS_START + 3)

    if not direction or direction in ('-', '—', ''):
        continue

    # --only_past_due: 検証予定日が今日以降ならスキップ
    if args.only_past_due and ver_date:
        try:
            vd = datetime.strptime(ver_date.replace('-', '/'), '%Y/%m/%d')
            if vd > TODAY:
                continue
        except:
            pass

    # 当時の株価（目標ではなく記録時株価）
    try:
        pred = float(str(pred_price_raw).replace(",", ""))
    except:
        pred = None

    curr = get_price(code) if code else None
    chg = round((curr - pred) / pred * 100, 2) if pred and curr and pred > 0 else None
    vs = round(chg - nk_chg, 2) if chg is not None and nk_chg is not None else None

    # 勝敗判定: 予測方向と実際（日経比超過）の符号が一致するか
    dir_sign = direction_sign(direction)
    result = "no data"
    if vs is not None:
        total += 1
        if dir_sign > 0:
            # 上昇予測 → 日経比超過がプラスで勝ち
            ok = (vs > 0)
        elif dir_sign < 0:
            # 下落予測 → 日経比超過がマイナスで勝ち
            ok = (vs < 0)
        else:
            # 中立 → ±2%以内なら勝ち
            ok = (abs(vs) <= 2.0)
        result = "win" if ok else "lose"
        if ok:
            win += 1

    # 経過日数
    days_elapsed = ""
    try:
        rec_date_str = s(0)  # 記録日
        rec_date = datetime.strptime(rec_date_str.replace('-', '/'), '%Y/%m/%d')
        days_elapsed = (TODAY - rec_date).days
    except:
        pass

    rows_out.append([
        code, name, sect, score, rank, direction,
        target,
        f"{curr:,.0f}" if curr else "error",
        f"{chg:+.2f}%" if chg is not None else "",
        f"{vs:+.2f}%" if vs is not None else "",
        ver_date,
        days_elapsed,
        result, ""
    ])

    # 予測記録シートの実績列を更新（実績株価/騰落率/日経比/勝敗）
    if result in ("win", "lose") and curr is not None:
        from gspread.utils import rowcol_to_a1
        cells = [
            (row_index_in_sheet, AXIS_START + 4 + 1, f"{curr:,.0f}"),       # 実績株価
            (row_index_in_sheet, AXIS_START + 5 + 1, f"{chg:+.2f}%" if chg is not None else ""),  # 騰落率
            (row_index_in_sheet, AXIS_START + 6 + 1, f"{vs:+.2f}%" if vs is not None else ""),    # 日経比超過
            (row_index_in_sheet, AXIS_START + 7 + 1, '勝' if result == 'win' else '負'),           # 勝敗
        ]
        for r_, c_, v_ in cells:
            updates.append({'range': rowcol_to_a1(r_, c_), 'values': [[v_]]})

rate = round(win / total * 100, 1) if total > 0 else 0
verdict = "OK functioning" if rate >= 80 else "WATCH" if rate >= 60 else "REVIEW"
summary = [
    ["", "", "", "", "", "", "", "", "", "", "", "", "", ""],
    ["summary", "", "", "", "", "", "", "", "", "", "", "", "", ""],
    ["total", total, "", "win", win, "lose", total - win,
     "", "", "", "", "", "", ""],
    ["win_rate", f"{rate}%", "", "verdict", verdict,
     "", "", "", "", "", "", "", "", ""],
]

ws_v.update("A1", meta + rows_out + summary)
ws_v.format("A10:N10", {"textFormat": {"bold": True}})
print(f"done: {rate}% ({win}/{total}) -> {verdict}")

# 予測記録シートの実績列を一括更新
if updates:
    try:
        ws_pred.batch_update(updates)
        print(f"  予測記録 実績列を {len(updates)} セル更新（勝敗トラッキング）")
    except Exception as e:
        print(f"  WARNING: 予測記録 更新失敗: {e}")

# work_log に記録
try:
    wl = ss.worksheet("work_log")
    last = len(wl.get_all_values()) + 1
    wl.update(f"A{last}", [[NOW, f"verify_axis.py --axis {AXIS}",
                             f"win_rate={rate}%({win}/{total}) {verdict}",
                             "auto", "done"]])
except:
    pass
print(f"verify_axis.py {AXIS} complete: {NOW}")

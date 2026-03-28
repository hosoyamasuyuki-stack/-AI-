# verify_0415.py v3
# col mapping fixed / API key updated / 2026-03-25
import os, json, warnings
from datetime import datetime
import gspread
from google.oauth2.service_account import Credentials
import yfinance as yf
warnings.filterwarnings("ignore")

from core.auth import get_spreadsheet
ss = get_spreadsheet()
NOW = datetime.now().strftime("%Y/%m/%d %H:%M")
print(f"OK: {ss.title} ({NOW})")

# col index (row0=header, row1=subheader, row2+=data)
COL_DATE=0; COL_CODE=1; COL_NAME=2; COL_SECT=3
COL_PRICE=4; COL_SCORE=5; COL_RANK=6; COL_ACTION=7
COL_DIR=8; COL_TARGET=9; COL_BASIS=10; COL_VERDATE=11

def get_nk225():
    try:
        h = yf.Ticker("^N225").history(period="5d")
        if len(h) >= 2:
            c = float(h["Close"].iloc[-1]); p = float(h["Close"].iloc[-2])
            chg = round((c-p)/p*100,2)
            print(f"  NK225: {c:,.0f} ({chg:+.2f}%)")
            return c, chg
    except Exception as e:
        print(f"  NK225 error: {e}")
    return None, None

def get_price(code):
    try:
        h = yf.Ticker(str(code).replace(".T","")+".T").history(period="5d")
        if len(h) >= 1:
            return round(float(h["Close"].iloc[-1]),0)
    except:
        pass
    try:
        import requests as req
        API_KEY = os.environ.get('JQUANTS_API_KEY', '')
        today = datetime.now().strftime("%Y%m%d")
        url = f"https://api.jquants.com/v2/equities/bars/daily?code={code}0&from={today}&to={today}"
        r = req.get(url, headers={"x-api-key": API_KEY})
        data = r.json().get("data",[])
        if data: return round(float(data[-1].get("AdjC",0)),0)
    except:
        pass
    return None

ws_pred = ss.worksheet("予測記録")
rows = ws_pred.get_all_values()
data = rows[2:]  # skip header(0) and subheader(1)
step0_rows = [r for r in data if "2026/03" in r[COL_DATE] or "2026-03" in r[COL_DATE]]
if not step0_rows: step0_rows = data[:20]
print(f"  targets: {len(step0_rows)}")

nk_price, nk_chg = get_nk225()

VERIFY_SHEET = "STEP0_0415"
try: ss.del_worksheet(ss.worksheet(VERIFY_SHEET))
except: pass
ws_v = ss.add_worksheet(title=VERIFY_SHEET, rows=60, cols=12)

meta = [
    ["STEP0 v3","","","","","","","","","","",""],
    ["verify_date", NOW,"","","","","","","","","",""],
    ["NK225", f"{nk_price:,.0f}" if nk_price else "error", f"{nk_chg:+.2f}%" if nk_chg else "","","","","","","","","",""],
    ["","","","","","","","","","","",""],
    ["win>=80%","functioning","","","","","","","","","",""],
    ["win 60-80%","watch","","","","","","","","","",""],
    ["win<50%","review","","","","","","","","","",""],
    ["","","","","","","","","","","",""],
    ["","","","","","","","","","","",""],
    ["code","name","sector","score","rank","direction","pred_price","curr_price","change%","vs_nk","result","note"],
]
rows_out = []; win=0; total=0

for row in step0_rows:
    def s(i,d=""): return row[i] if len(row)>i else d
    code=s(COL_CODE); name=s(COL_NAME); sect=s(COL_SECT)
    score=s(COL_SCORE); rank=s(COL_RANK); direction=s(COL_DIR)
    pred_raw=s(COL_PRICE)
    try: pred=float(str(pred_raw).replace(",",""))
    except: pred=None
    curr=get_price(code) if code else None
    chg=round((curr-pred)/pred*100,2) if pred and curr and pred>0 else None
    vs=round(chg-nk_chg,2) if chg is not None and nk_chg is not None else None
    if vs is not None:
        result="win" if vs>0 else "lose"; total+=1
        if vs>0: win+=1
    else: result="no data"
    rows_out.append([code,name,sect,score,rank,direction,
        f"{pred:,.0f}" if pred else pred_raw,
        f"{curr:,.0f}" if curr else "error",
        f"{chg:+.2f}%" if chg is not None else "",
        f"{vs:+.2f}%" if vs is not None else "",
        result,""])

rate=round(win/total*100,1) if total>0 else 0
verdict="OK functioning" if rate>=80 else "WATCH" if rate>=60 else "REVIEW"
summary=[
    ["","","","","","","","","","","",""],
    ["summary","","","","","","","","","","",""],
    ["total",total,"","win",win,"lose",total-win,"","","","",""],
    ["win_rate",f"{rate}%","","verdict",verdict,"","","","","","",""],
]
ws_v.update("A1", meta+rows_out+summary)
ws_v.format("A10:L10",{"textFormat":{"bold":True}})
print(f"done: {rate}% ({win}/{total}) -> {verdict}")

try:
    wl=ss.worksheet("work_log"); last=len(wl.get_all_values())+1
    wl.update(f"A{last}",[[NOW,"verify_0415.py v3",f"win_rate={rate}%({win}/{total}) {verdict}","auto","done"]])
except: pass
print(f"verify_0415.py v3 complete: {NOW}")

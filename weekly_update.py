import os
import json
import requests
import time
import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import gspread
from google.oauth2.service_account import Credentials

# ============================================================
# 認証
# ============================================================
FRED_API_KEY    = os.environ["FRED_API_KEY"]
SPREADSHEET_ID  = os.environ["SPREADSHEET_ID"]
creds_json      = os.environ["GOOGLE_CREDENTIALS"]
creds_dict      = json.loads(creds_json)
scopes = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive"
]
creds  = Credentials.from_service_account_info(creds_dict, scopes=scopes)
gc     = gspread.authorize(creds)
ss     = gc.open_by_key(SPREADSHEET_ID)
print("✅ 認証完了")

# ============================================================
# 定数
# ============================================================
HOLDINGS = [
    ("1605","INPEX","鉱業",1769,300,"資源・エネルギー"),
    ("1847","イチケン","建設業",2398,100,"建設・インフラ"),
    ("1879","新日本建設","建設業",1806,100,"建設・インフラ"),
    ("1928","積水ハウス","建設業",3135,100,"住宅・不動産"),
    ("1942","関電工","建設業",6051,25,"電気工事"),
    ("2003","日東富士製粉","食料品",4643,100,"食品素材"),
    ("2768","双日","卸売業",3330,100,"総合商社"),
    ("2914","JT","食料品",4341,300,"高配当・タバコ"),
    ("3496","アズーム","サービス業",2261,200,"駐車場DX"),
    ("4063","信越化学","化学",4164,300,"半導体材料"),
    ("4221","大倉工業","化学",3015,100,"化学素材"),
    ("5838","楽天銀行","銀行業",6190,30,"ネット銀行"),
    ("6098","リクルートHD","サービス業",6577,10,"HR・DX"),
    ("6200","インソース","サービス業",710,100,"人材・研修"),
    ("6501","日立","電気機器",4611,20,"デジタル・インフラ"),
    ("6637","寺崎電気産業","電気機器",2791,200,"電気部品"),
    ("6920","レーザーテック","電気機器",15380,20,"半導体検査"),
    ("7187","ジェイリース","その他金融業",1306,100,"リース・保証"),
    ("7741","HOYA","精密機器",15690,3,"光学・医療"),
    ("7974","任天堂","その他製品",8787,40,"ゲーム"),
    ("8001","伊藤忠","卸売業",1291,500,"総合商社"),
    ("8053","住友商事","卸売業",2514,400,"総合商社"),
    ("8058","三菱商事","卸売業",970,700,"総合商社"),
    ("8136","サンリオ","その他製品",4976,60,"IP・エンタメ"),
    ("8303","SBI新生銀行","銀行業",1450,100,"金利恩恵"),
    ("8306","三菱UFJ FG","銀行業",874,1800,"メガバンク"),
    ("8316","三井住友FG","銀行業",1478,900,"メガバンク"),
    ("8331","千葉銀行","銀行業",1145,200,"地銀"),
    ("8343","秋田銀行","銀行業",2985,100,"地銀"),
    ("8386","百十四銀行","銀行業",2579,200,"地銀"),
    ("8410","セブン銀行","銀行業",295,300,"決済・金融"),
    ("8473","SBIホールディングス","その他金融業",1475,2100,"ネット証券・金融"),
    ("8541","愛媛銀行","銀行業",985,400,"地銀"),
    ("8591","オリックス","その他金融業",1673,400,"総合金融"),
    ("8593","三菱HCキャピタル","その他金融業",588,900,"リース"),
    ("8600","トモニHD","銀行業",530,200,"地銀"),
    ("8630","SOMPOホールディングス","保険業",1746,300,"損害保険"),
    ("8771","Eギャランティ","その他金融業",1308,200,"信用保証"),
    ("8935","FJネクストHD","不動産業",1174,100,"不動産"),
    ("9069","センコーグループHD","陸運業",1106,100,"物流"),
    ("9432","NTT","情報通信業",162,5900,"通信インフラ"),
    ("9433","KDDI","情報通信業",2020,300,"通信"),
    ("9434","ソフトバンク","情報通信業",139,3000,"通信"),
]

SECTOR_PROXIES = {
    "水産・農林業":"1332.T","鉱業":"1605.T","建設業":"1928.T",
    "食料品":"2914.T","繊維製品":"3401.T","パルプ・紙":"3861.T",
    "化学":"4063.T","医薬品":"4502.T","石油・石炭製品":"5019.T",
    "ゴム製品":"5108.T","ガラス・土石製品":"5201.T","鉄鋼":"5401.T",
    "非鉄金属":"5713.T","金属製品":"5801.T","機械":"6301.T",
    "電気機器":"6501.T","輸送用機器":"7203.T","精密機器":"7741.T",
    "その他製品":"7974.T","電気・ガス業":"9501.T","陸運業":"9020.T",
    "海運業":"9101.T","空運業":"9202.T","倉庫・運輸関連":"9147.T",
    "情報通信業":"9432.T","卸売業":"8058.T","小売業":"3382.T",
    "銀行業":"8306.T","証券・商品先物":"8601.T","保険業":"8630.T",
    "その他金融業":"8591.T","不動産業":"8801.T","サービス業":"6098.T",
}

FRED_INDICATORS = {
    "M2SL":("米M2","マクロ"),"T10Y2Y":("逆イールド","金利"),
    "DEXJPUS":("ドル円","為替"),"VIXCLS":("VIX","リスク"),
    "BAMLH0A0HYM2":("HYスプレッド","リスク"),
}

# ============================================================
# スコアリングクラス
# ============================================================
class ThreeLayerScorer:
    def __init__(self, macro_data):
        self.macro = macro_data
    def calc_macro_score(self):
        scores = {}
        if "T10Y2Y" in self.macro:
            s = self.macro["T10Y2Y"]["value"]
            scores["yield_curve"] = +20 if s>0.5 else (+10 if s>0 else (-10 if s>-0.5 else -20))
        if "VIXCLS" in self.macro:
            v = self.macro["VIXCLS"]["value"]
            scores["vix"] = +20 if v<15 else (+10 if v<20 else (0 if v<25 else (-15 if v<35 else -25)))
        if "DEXJPUS" in self.macro:
            fx = self.macro["DEXJPUS"]["value"]
            scores["fx"] = +15 if 140<fx<160 else (-10 if fx>=160 else (-15 if fx<130 else +5))
        if "M2SL" in self.macro:
            scores["m2"] = +15 if self.macro["M2SL"]["change"]>0 else -15
        if "BAMLH0A0HYM2" in self.macro:
            hy = self.macro["BAMLH0A0HYM2"]["value"]
            scores["hy"] = +10 if hy<3.5 else (0 if hy<5.0 else -15)
        total = max(-100, min(100, sum(scores.values())))
        return {"score":total,"label":self._label(total)}
    def calc_stock_score(self, code):
        try:
            df = yf.download(f"{code}.T",
                             start=datetime.today()-timedelta(days=180),
                             end=datetime.today(), progress=False, auto_adjust=True)
            if df.empty or len(df)<30:
                return {"score":0,"latest_price":0,"ret_1m":0}
            df.columns = [c[0] if isinstance(c,tuple) else c for c in df.columns]
            close = df["Close"]
            cur   = float(close.iloc[-1])
            ma25  = float(close.rolling(25).mean().iloc[-1])
            ma75  = float(close.rolling(min(75,len(close))).mean().iloc[-1])
            sc = {}
            if cur>ma25>ma75:    sc["trend"]=+25
            elif cur>ma25:        sc["trend"]=+15
            elif cur<ma25<ma75:   sc["trend"]=-20
            else:                 sc["trend"]=0
            ret = (cur-float(close.iloc[-22]))/float(close.iloc[-22])*100 if len(close)>=22 else 0
            sc["mom"] = +20 if ret>10 else (+10 if ret>3 else (0 if ret>-3 else (-10 if ret>-10 else -20)))
            vol = float(close.pct_change().rolling(20).std().iloc[-1])*100
            sc["vol"] = +10 if vol<1 else (+5 if vol<2 else (0 if vol<3.5 else -10))
            return {"score":max(-100,min(100,sum(sc.values()))),"latest_price":cur,"ret_1m":ret}
        except:
            return {"score":0,"latest_price":0,"ret_1m":0}
    def _label(self,s):
        return "🟢" if s>=60 else ("🟡" if s>=30 else ("⚪" if s>=-30 else ("🟠" if s>=-60 else "🔴")))

def calc_sector_score(ticker):
    try:
        df = yf.download(ticker,
                         start=datetime.today()-timedelta(days=100),
                         end=datetime.today(), progress=False, auto_adjust=True)
        if df.empty or len(df)<20: return 0
        df.columns = [c[0] if isinstance(c,tuple) else c for c in df.columns]
        close = df["Close"].dropna()
        cur  = float(close.iloc[-1])
        ma25 = float(close.rolling(min(25,len(close))).mean().iloc[-1])
        ma75 = float(close.rolling(min(75,len(close))).mean().iloc[-1])
        sc = 0
        if cur>ma25>ma75:    sc+=30
        elif cur>ma25:        sc+=15
        elif cur<ma25<ma75:   sc-=25
        if len(close)>=22:
            ret = (cur-float(close.iloc[-22]))/float(close.iloc[-22])*100
            sc += +20 if ret>5 else (+10 if ret>2 else (0 if ret>-2 else (-10 if ret>-5 else -20)))
        return max(-100,min(100,sc))
    except: return 0

# ============================================================
# メイン処理
# ============================================================
print(f"\n🔄 週次更新開始: {datetime.now().strftime('%Y-%m-%d %H:%M')}")

# Step1: マクロ指標取得
print("📡 マクロ指標取得中...")
macro_data = {}
for sid,(name,cat) in FRED_INDICATORS.items():
    res = requests.get("https://api.stlouisfed.org/fred/series/observations",
                       params={"series_id":sid,"api_key":FRED_API_KEY,
                               "file_type":"json","sort_order":"asc"})
    if res.status_code==200:
        obs = res.json().get("observations",[])
        if len(obs)>=2:
            df = pd.DataFrame(obs)[["date","value"]]
            df["value"] = pd.to_numeric(df["value"],errors="coerce")
            df = df.dropna()
            macro_data[sid] = {
                "name":name,"category":cat,
                "date":df.iloc[-1]["date"],
                "value":float(df.iloc[-1]["value"]),
                "prev":float(df.iloc[-2]["value"]),
                "change":float(df.iloc[-1]["value"]-df.iloc[-2]["value"])
            }
    time.sleep(0.3)
print(f"  ✅ {len(macro_data)}指標")

# Step2: 業種スコア取得
print("📡 業種スコア計算中...")
sector_scores = {}
for sector, ticker in SECTOR_PROXIES.items():
    sector_scores[sector] = calc_sector_score(ticker)
    time.sleep(0.2)
avg_sec = sum(sector_scores.values())/len(sector_scores)
print(f"  ✅ 33業種 平均{avg_sec:+.1f}")

# Step3: 銘柄スコアリング
print("📡 銘柄スコアリング中...")
scorer       = ThreeLayerScorer(macro_data)
macro_result = scorer.calc_macro_score()
today        = datetime.now().strftime("%Y-%m-%d")
ws_pred      = ss.worksheet("予測記録")
results      = []

for code,name,sector,cost,qty,theme in HOLDINGS:
    stock  = scorer.calc_stock_score(code)
    sec_sc = sector_scores.get(sector, avg_sec)
    comp   = round(macro_result["score"]*0.4 + sec_sc*0.3 + stock["score"]*0.3, 1)
    p      = stock["latest_price"]
    upside = 1.10 if comp>50 else (1.05 if comp>20 else 1.02)
    target = round(p*upside)
    stop   = round(p*0.93)
    direction = "上昇" if comp>20 else ("下落" if comp<-20 else "中立")
    ws_pred.append_row([today,code,name,p,
                        macro_result["score"],round(sec_sc,1),stock["score"],comp,
                        scorer._label(comp),direction,target,stop,
                        f"テーマ:{theme}","","","","",""])
    results.append((code,name,comp))
    time.sleep(0.4)

bull = sum(1 for _,_,s in results if s>=30)

# Step4: 業種スコアシート更新
ws_sec = ss.worksheet("業種スコア")
ws_sec.clear()
ws_sec.update(range_name="A1", values=[["業種","スコア","判定","更新日時"]]+[
    [sec, sc,
     "🟢 強気" if sc>=30 else ("🟡 中立強" if sc>=0 else ("🟠 中立弱" if sc>=-30 else "🔴 弱気")),
     today]
    for sec,sc in sorted(sector_scores.items(),key=lambda x:-x[1])
])

# Step5: ログ追記
ws_log   = ss.worksheet("作業ログ")
existing = ws_log.get_all_values()
ws_log.update(existing + [
    ["",""],[f"★週次自動更新 {today}",""],
    ["マクロスコア",f"{macro_result['score']:+.0f}"],
    ["業種平均",f"{avg_sec:+.1f}"],
    ["買い検討銘柄数",f"{bull}銘柄"],
    ["実行方法","GitHub Actions自動実行"],
])

print(f"\n✅ 週次更新完了")
print(f"  マクロ:{macro_result['score']:+.0f} / 業種:{avg_sec:+.1f} / 買い検討:{bull}銘柄")

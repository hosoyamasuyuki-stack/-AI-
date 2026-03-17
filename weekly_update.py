import os
import json
import requests
import time
import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
import gspread
from google.oauth2.service_account import Credentials

# ============================================================
# 認証
# ============================================================
FRED_API_KEY   = os.environ["FRED_API_KEY"]
SPREADSHEET_ID = os.environ["SPREADSHEET_ID"]
creds_json     = os.environ["GOOGLE_CREDENTIALS"]
creds_dict     = json.loads(creds_json)
scopes = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive"
]
creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
gc    = gspread.authorize(creds)
ss    = gc.open_by_key(SPREADSHEET_ID)
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

# 業種別営業利益率基準
SECTOR_BENCHMARKS = {
    "鉱業":(30,0,5),"建設業":(5,5,5),"食料品":(5,3,5),
    "化学":(15,5,5),"電気機器":(10,5,10),"精密機器":(15,8,10),
    "その他製品":(10,5,5),"卸売業":(3,5,5),"銀行業":(25,5,5),
    "保険業":(10,5,5),"その他金融業":(15,10,10),"不動産業":(15,5,5),
    "情報通信業":(15,5,8),"陸運業":(8,3,5),"サービス業":(15,10,15),
    "その他":(10,5,5),
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
        return {"score": total, "label": self._label(total)}
    def _label(self, s):
        return "🟢" if s>=60 else ("🟡" if s>=30 else ("⚪" if s>=-30 else ("🟠" if s>=-60 else "🔴")))

# ============================================================
# 経営品質スコア（業種別基準）
# ============================================================
def get_sector_benchmark(sector):
    for key in SECTOR_BENCHMARKS:
        if key in sector:
            return SECTOR_BENCHMARKS[key]
    return SECTOR_BENCHMARKS["その他"]

def calc_mq_score(code, sector):
    try:
        info = yf.Ticker(f"{code}.T").info
        op_thr, rev_thr, eps_thr = get_sector_benchmark(sector)
        scores = {}
        rg = info.get("revenueGrowth")
        if rg:
            rg*=100
            if rg>rev_thr*2:   scores["sales"]=+25
            elif rg>rev_thr:    scores["sales"]=+15
            elif rg>0:          scores["sales"]=+5
            elif rg>-rev_thr:   scores["sales"]=-5
            else:               scores["sales"]=-20
        om = info.get("operatingMargins")
        if om:
            om*=100
            if om>op_thr*1.5:   scores["margin"]=+20
            elif om>op_thr:      scores["margin"]=+10
            elif om>op_thr*0.7:  scores["margin"]=0
            elif om>0:           scores["margin"]=-10
            else:                scores["margin"]=-20
        eg = info.get("earningsGrowth")
        if eg:
            eg*=100
            if eg>eps_thr*2:   scores["eps"]=+20
            elif eg>eps_thr:    scores["eps"]=+10
            elif eg>0:          scores["eps"]=+5
            elif eg>-eps_thr:   scores["eps"]=-5
            else:               scores["eps"]=-15
        roe = info.get("returnOnEquity")
        if roe:
            rp=roe*100
            roe_thr=8 if any(x in sector for x in ["銀行","保険","金融"]) else 12
            if rp>roe_thr*1.5:  scores["roe"]=+15
            elif rp>roe_thr:     scores["roe"]=+5
            elif rp>0:           scores["roe"]=0
            else:                scores["roe"]=-15
        return max(-100,min(100,sum(scores.values()))) if scores else 0
    except: return 0

# ============================================================
# PEG・バリュー成長スコア
# ============================================================
def calc_peg_score(code, sector, new_comp, theme):
    try:
        info    = yf.Ticker(f"{code}.T").info
        per     = info.get("trailingPE") or info.get("forwardPE")
        eps_g   = info.get("earningsGrowth")
        roe     = info.get("returnOnEquity")
        pbr     = info.get("priceToBook")

        peg = round(per/(eps_g*100),2) if per and eps_g and eps_g>0 else None

        if peg is not None:
            if peg<0.5:   peg_label="超割安成長"; peg_score=+30
            elif peg<1.0: peg_label="割安成長";   peg_score=+20
            elif peg<1.5: peg_label="適正";       peg_score=+5
            elif peg<2.0: peg_label="やや割高";   peg_score=-10
            else:         peg_label="割高";        peg_score=-20
        else:
            if pbr and pbr<1.0:    peg_label="PBR割安"; peg_score=+15
            elif roe and roe>0.15: peg_label="高ROE";   peg_score=+10
            else:                  peg_label="データ不足"; peg_score=0

        if new_comp>=30 and peg_score>=20:   final="強買い推奨"
        elif new_comp>=20 and peg_score>=20: final="買い推奨"
        elif new_comp>=20 and peg_score>=5:  final="候補"
        elif new_comp>=30 and peg_score<5:   final="タイミング待ち"
        elif peg_score>=20 and new_comp<20:  final="割安だが時期尚早"
        else:                                final="様子見"

        return [
            code, "", sector,
            round(per,1) if per else "",
            round(eps_g*100,1) if eps_g else "",
            peg or "",
            peg_label, new_comp, final,
            round(pbr,2) if pbr else "",
            round(roe*100,1) if roe else "",
            theme
        ]
    except:
        return [code,"",sector,"","","","データ不足",new_comp,"様子見","","",theme]

# ============================================================
# 株価取得（並列）
# ============================================================
def fetch_stock(code, days=90):
    try:
        df = yf.download(f"{code}.T",
                         start=datetime.today()-timedelta(days=days),
                         end=datetime.today(),
                         progress=False, auto_adjust=True, timeout=10)
        if df is None or df.empty or len(df)<5: return code, None
        df.columns = [c[0] if isinstance(c,tuple) else c for c in df.columns]
        close = df["Close"].dropna()
        cur   = float(close.iloc[-1])
        if np.isnan(cur) or cur<=0: return code, None
        ma25  = float(close.rolling(min(25,len(close))).mean().iloc[-1])
        ma75  = float(close.rolling(min(75,len(close))).mean().iloc[-1])
        sc = {}
        if cur>ma25>ma75:    sc["trend"]=+25
        elif cur>ma25:        sc["trend"]=+15
        elif cur<ma25<ma75:   sc["trend"]=-20
        else:                 sc["trend"]=0
        ret = (cur-float(close.iloc[-22]))/float(close.iloc[-22])*100 if len(close)>=22 else 0
        sc["mom"] = +20 if ret>10 else (+10 if ret>3 else (0 if ret>-3 else (-10 if ret>-10 else -20)))
        try:
            vol = float(close.pct_change().rolling(20).std().iloc[-1])*100
            if np.isnan(vol): vol=2.0
        except: vol=2.0
        sc["vol"] = +10 if vol<1 else (+5 if vol<2 else (0 if vol<3.5 else -10))
        return code, {"score":max(-100,min(100,sum(sc.values()))),"price":cur,"ret_1m":ret}
    except: return code, None

def fetch_all_stocks_parallel(holdings, max_workers=8):
    results = {}
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(fetch_stock, code): code for code,*_ in holdings}
        for future in as_completed(futures, timeout=120):
            code = futures[future]
            try:
                code, result = future.result(timeout=15)
                results[code] = result
            except: results[code] = None
    return results

def calc_sector_score(ticker):
    try:
        df = yf.download(ticker,
                         start=datetime.today()-timedelta(days=100),
                         end=datetime.today(),
                         progress=False, auto_adjust=True, timeout=10)
        if df.empty or len(df)<20: return 0
        df.columns = [c[0] if isinstance(c,tuple) else c for c in df.columns]
        close = df["Close"].dropna()
        cur   = float(close.iloc[-1])
        ma25  = float(close.rolling(min(25,len(close))).mean().iloc[-1])
        ma75  = float(close.rolling(min(75,len(close))).mean().iloc[-1])
        sc = 0
        if cur>ma25>ma75: sc+=30
        elif cur>ma25:     sc+=15
        elif cur<ma25<ma75:sc-=25
        if len(close)>=22:
            ret=(cur-float(close.iloc[-22]))/float(close.iloc[-22])*100
            sc+=+20 if ret>5 else (+10 if ret>2 else (0 if ret>-2 else (-10 if ret>-5 else -20)))
        return max(-100,min(100,sc))
    except: return 0

# ============================================================
# メイン処理
# ============================================================
print(f"\n{'='*55}")
print(f"🔄 週次更新開始（統合スコア+PEG版）: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
print(f"   マクロ35%・業種30%・テクニカル25%・経営品質10%")
print(f"{'='*55}\n")

# Step1: マクロ指標取得
print("📡 Step1: マクロ指標取得中...")
macro_data = {}
for sid,(name,cat) in FRED_INDICATORS.items():
    try:
        res = requests.get("https://api.stlouisfed.org/fred/series/observations",
                           params={"series_id":sid,"api_key":FRED_API_KEY,
                                   "file_type":"json","sort_order":"asc"},timeout=10)
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
    except: pass
    time.sleep(0.3)
print(f"  ✅ {len(macro_data)}指標")

# Step2: 業種スコア取得
print("📡 Step2: 33業種体温計更新中...")
sector_scores = {}
for sector, ticker in SECTOR_PROXIES.items():
    sector_scores[sector] = calc_sector_score(ticker)
    time.sleep(0.2)
avg_sec = sum(sector_scores.values())/len(sector_scores)
print(f"  ✅ 33業種 平均{avg_sec:+.1f}")

# Step3: 全銘柄株価並列取得
print("📡 Step3: 全銘柄株価取得中（並列）...")
stock_results = fetch_all_stocks_parallel(HOLDINGS, max_workers=8)
success = sum(1 for v in stock_results.values() if v)
print(f"  ✅ {success}/{len(HOLDINGS)}銘柄取得成功")

# Step4: 経営品質スコア取得
print("📡 Step4: 経営品質スコア計算中...")
mq_scores = {}
for code, name, sector, *_ in HOLDINGS:
    mq_scores[code] = calc_mq_score(code, sector)
    time.sleep(0.3)
print(f"  ✅ 経営品質スコア計算完了")

# Step5: 統合スコアリング・予測記録追記
print("📡 Step5: 統合スコアリング中...")
scorer       = ThreeLayerScorer(macro_data)
macro_result = scorer.calc_macro_score()
macro_s      = macro_result["score"]
today        = datetime.now().strftime("%Y-%m-%d")
ws_pred      = ss.worksheet("予測記録")
results      = []

for code, name, sector, cost, qty, theme in HOLDINGS:
    try:
        stock   = stock_results.get(code) or {"score":0,"price":0,"ret_1m":0}
        sec_s   = sector_scores.get(sector, avg_sec)
        stock_s = stock["score"]
        mq_s    = mq_scores.get(code, 0)
        p       = stock.get("price", 0)
        if not p or np.isnan(float(p)): p=0

        # 統合スコア：マクロ35%・業種30%・テクニカル25%・経営品質10%
        integrated = round(macro_s*0.35 + sec_s*0.30 + stock_s*0.25 + mq_s*0.10, 1)
        old_comp   = round(macro_s*0.40 + sec_s*0.30 + stock_s*0.30, 1)

        upside    = 1.10 if integrated>50 else (1.05 if integrated>20 else 1.02)
        target    = int(round(p*upside)) if p>0 else 0
        stop      = int(round(p*0.93))   if p>0 else 0
        direction = "上昇" if integrated>20 else ("下落" if integrated<-20 else "中立")

        if integrated>=60:    label="強買い"
        elif integrated>=30:  label="買い検討"
        elif integrated>=-30: label="中立"
        elif integrated>=-60: label="様子見"
        else:                 label="売り検討"

        ws_pred.append_row([
            today, code, name,
            float(p) if p>0 else "",
            macro_s, round(sec_s,1), stock_s, integrated,
            label, direction, target, stop,
            f"テーマ:{theme} MQ:{mq_s:+.0f}", "", "", "", "", ""
        ])
        results.append((code, name, integrated, mq_s))
        print(f"  ✅ {code} {name}: 統合{integrated:+.1f} MQ:{mq_s:+.0f}")
    except Exception as e:
        print(f"  ❌ {code} {name}: {e}")
    time.sleep(0.1)

bull = sum(1 for _,_,s,_ in results if s>=30)
print(f"\n  📊 統合買い検討: {bull}銘柄")

# Step6: バリュー成長スコア（PEG）自動更新
print("\n📡 Step6: バリュー成長スコア（PEG）更新中...")
peg_rows = []
for code, name, sector, cost, qty, theme in HOLDINGS:
    int_r    = next((r for r in results if r[0]==code), None)
    new_comp = int_r[2] if int_r else 0
    row = calc_peg_score(code, sector, new_comp, theme)
    row[1] = name  # 銘柄名をセット
    peg_rows.append(row)
    time.sleep(0.2)

# バリュー成長スコアシート更新
try:
    ws_vg = ss.worksheet("バリュー成長スコア")
    ss.del_worksheet(ws_vg)
except: pass
ws_vg = ss.add_worksheet(title="バリュー成長スコア", rows=200, cols=12)
priority_map = {"強買い推奨":0,"買い推奨":1,"候補":2,"タイミング待ち":3,"割安だが時期尚早":4,"様子見":5}
sorted_peg = sorted(peg_rows, key=lambda x: (priority_map.get(x[8],9), -(x[7] or 0)))
ws_vg.update(range_name="A1", values=[
    ["コード","銘柄名","業種","PER","EPS成長率%","PEG",
     "PEG判定","統合スコア","最終判定","PBR","ROE%","テーマ"]
] + sorted_peg)

buy_peg  = sum(1 for r in peg_rows if r[8] in ["強買い推奨","買い推奨"])
print(f"  ✅ バリュー成長スコア更新完了 / 買い推奨:{buy_peg}銘柄")

# Step7: 業種スコアシート更新
ws_sec = ss.worksheet("業種スコア")
ws_sec.clear()
ws_sec.update(range_name="A1", values=[["業種","スコア","判定","更新日時"]]+[
    [sec, sc,
     "強気" if sc>=30 else ("中立強" if sc>=0 else ("中立弱" if sc>=-30 else "弱気")),
     today]
    for sec,sc in sorted(sector_scores.items(),key=lambda x:-x[1])
])
print("  ✅ 業種スコアシート更新完了")

# Step8: ログ追記
ws_log   = ss.worksheet("作業ログ")
existing = ws_log.get_all_values()
ws_log.update(existing + [
    ["",""],
    [f"★週次自動更新（統合+PEG版） {today}",""],
    ["マクロスコア",f"{macro_s:+.0f}"],
    ["業種平均",f"{avg_sec:+.1f}"],
    ["統合買い検討",f"{bull}銘柄"],
    ["PEG買い推奨",f"{buy_peg}銘柄"],
    ["実行方法","GitHub Actions自動実行（統合スコア+PEG版）"],
])

print(f"\n{'='*55}")
print(f"✅ 週次更新完了（統合+PEG版）: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
print(f"   マクロ:     {macro_s:+.0f}")
print(f"   業種平均:   {avg_sec:+.1f}")
print(f"   統合買い検討: {bull}銘柄")
print(f"   PEG買い推奨: {buy_peg}銘柄")
print(f"{'='*55}")

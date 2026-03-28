"""
learning_batch_monthly.py
学習用99銘柄 月次自動更新スクリプト
GitHub Actions で毎月1日 9:00 JST に自動実行される

【認証】サービスアカウント（環境変数 GOOGLE_CREDENTIALS）
【目的】精度向上専用。投資しない。ダッシュボードに表示しない。
"""

import os, json, time, warnings
import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from google.oauth2.service_account import Credentials
import gspread
from core.config import (SPREADSHEET_ID, ROE_THR, FCR_THR, RS_THR,
                          FS_THR, PEG_THR, FCY_THR)
from core.auth import get_spreadsheet

warnings.filterwarnings('ignore')

# ── 認証 ────────────────────────────────────────────────────
ss = get_spreadsheet()
NOW             = datetime.now().strftime('%Y/%m/%d %H:%M')
TODAY           = datetime.now()
print(f"✅ 接続完了: {ss.title}  実行日時: {NOW}")

# ── 99銘柄マスタ ─────────────────────────────────────────────
STOCKS = [
    ('食品','2914','JT','大'),('食品','2802','味の素','中'),('食品','2809','キユーピー','小'),
    ('繊維','3401','帝人','大'),('繊維','3402','東レ','中'),('繊維','3103','ユニチカ','小'),
    ('パルプ・紙','3861','王子HD','大'),('パルプ・紙','3863','日本製紙','中'),('パルプ・紙','3880','大王製紙','小'),
    ('化学','4063','信越化学','大'),('化学','4188','三菱ケミカル','中'),('化学','4901','富士フイルムHD','小'),
    ('医薬品','4519','中外製薬','大'),('医薬品','4502','武田薬品','中'),('医薬品','4527','ロート製薬','小'),
    ('ゴム','5108','ブリヂストン','大'),('ゴム','5101','横浜ゴム','中'),('ゴム','5189','櫻護謨','小'),
    ('ガラス・土石','5201','AGC','大'),('ガラス・土石','5202','日本板硝子','中'),('ガラス・土石','5233','太平洋セメント','小'),
    ('鉄鋼','5401','日本製鉄','大'),('鉄鋼','5411','JFEホールディングス','中'),('鉄鋼','5471','大同特殊鋼','小'),
    ('非鉄金属','5713','住友金属鉱山','大'),('非鉄金属','5706','三井金属','中'),('非鉄金属','5741','UACJ','小'),
    ('金属製品','5801','古河電気工業','大'),('金属製品','5803','フジクラ','中'),('金属製品','5947','リンナイ','小'),
    ('機械','6273','SMC','大'),('機械','6302','住友重機械工業','中'),('機械','6413','ダイキン工業','小'),
    ('電機','6501','日立','大'),('電機','6752','パナソニック','中'),('電機','6504','富士電機','小'),
    ('輸送機器','7203','トヨタ自動車','大'),('輸送機器','7267','本田技研工業','中'),('輸送機器','7270','SUBARU','小'),
    ('精密機器','7741','HOYA','大'),('精密機器','7751','キヤノン','中'),('精密機器','7762','シチズン時計','小'),
    ('その他製品','7974','任天堂','大'),('その他製品','7912','大日本印刷','中'),('その他製品','7911','凸版印刷','小'),
    ('鉱業','1605','INPEX','大'),('鉱業','1662','石油資源開発','中'),('鉱業','1663','K&Oエナジーグループ','小'),
    ('建設','1802','大林組','大'),('建設','1928','積水ハウス','中'),('建設','1847','イチケン','小'),
    ('電気・ガス','9501','東京電力HD','大'),('電気・ガス','9503','関西電力','中'),('電気・ガス','9531','東京ガス','小'),
    ('陸運','9020','JR東日本','大'),('陸運','9064','ヤマトHD','中'),('陸運','9069','センコーグループHD','小'),
    ('海運','9101','日本郵船','大'),('海運','9104','商船三井','中'),('海運','9107','川崎汽船','小'),
    ('空運','9202','ANA HD','大'),('空運','9201','日本航空','中'),('空運','9206','スターフライヤー','小'),
    ('倉庫・運輸','9301','三菱倉庫','大'),('倉庫・運輸','9305','ヤマタネ','中'),('倉庫・運輸','9302','三菱倉庫','小'),
    ('情報通信','9432','NTT','大'),('情報通信','9433','KDDI','中'),('情報通信','4307','野村総研','小'),
    ('卸売','8058','三菱商事','大'),('卸売','2768','双日','中'),('卸売','8015','豊田通商','小'),
    ('小売','9983','ファーストリテイリング','大'),('小売','3382','セブン&アイHD','中'),('小売','9843','ニトリHD','小'),
    ('銀行','8306','三菱UFJ','大'),('銀行','8316','三井住友FG','中'),('銀行','8331','千葉銀行','小'),
    ('証券','8604','野村HD','大'),('証券','8601','大和証券G','中'),('証券','8473','SBIホールディングス','小'),
    ('保険','8630','SOMPO','大'),('保険','8725','MS&ADインシュアランス','中'),('保険','8729','ソニーFG','小'),
    ('その他金融','8591','オリックス','大'),('その他金融','8593','三菱HCキャピタル','中'),('その他金融','8771','Eギャランティ','小'),
    ('不動産','8801','三井不動産','大'),('不動産','8802','三菱地所','中'),('不動産','8935','FJネクストHD','小'),
    ('サービス','6098','リクルートHD','大'),('サービス','4751','サイバーエージェント','中'),('サービス','6200','インソース','小'),
    ('半導体','8035','東京エレクトロン','大'),('半導体','6857','アドバンテスト','中'),('半導体','6146','ディスコ','小'),
]

# ── v4.2スコア計算（閾値はcore/config.pyからimport済み）─────

def thr(v,t):
    if v is None or (isinstance(v,float) and (np.isnan(v) or np.isinf(v))): return 0
    for th,s in t:
        if v>=th: return s
    return 0

def slope(s):
    v=pd.Series(s).replace([np.inf,-np.inf],np.nan).dropna().values
    return float(np.polyfit(range(len(v)),v,1)[0]) if len(v)>=2 else 0.0

def safe(v,d=1):
    if v is None: return None
    try:
        f=float(v); return None if (np.isnan(f) or np.isinf(f)) else round(f,d)
    except: return None

def safe_str(v):
    if v is None: return ''
    try:
        f=float(v)
        return '' if (np.isnan(f) or np.isinf(f)) else str(round(f,1))
    except: return str(v) if v else ''

def get_data(code):
    try:
        t=yf.Ticker(f"{code}.T")
        fin=t.financials; cf=t.cashflow; bs=t.balance_sheet; info=t.info
        if fin is None or fin.empty: return None,{}
        fin=fin.T.sort_index()
        cf =cf.T.sort_index()  if cf  is not None and not cf.empty  else pd.DataFrame()
        bs =bs.T.sort_index()  if bs  is not None and not bs.empty  else pd.DataFrame()
        d=pd.DataFrame(index=fin.index)
        for src,dst in [('Net Income','ni')]: 
            if src in fin.columns: d[dst]=fin[src]
        for src,dst in [('Operating Cash Flow','cfo'),('Investing Cash Flow','cfi')]:
            if src in cf.columns: d[dst]=cf[src]
        for src,dst in [('Stockholders Equity','eq'),
                        ('Total Equity Gross Minority Interest','eq')]:
            if src in bs.columns and 'eq' not in d.columns: d[dst]=bs[src]
        if 'cfo' in d.columns and 'cfi' in d.columns: d['fcf']=d['cfo']+d['cfi']
        if 'ni'  in d.columns and 'eq'  in d.columns: d['roe']=d['ni']/d['eq'].replace(0,np.nan)*100
        if 'fcf' in d.columns and 'ni'  in d.columns: d['fcr']=d['fcf']/d['ni'].replace(0,np.nan)*100
        return d.replace([np.inf,-np.inf],np.nan).dropna(how='all'),{
            'per':info.get('trailingPE'),'market_cap':info.get('marketCap'),
            'eps_growth':info.get('earningsGrowth'),
            'price':info.get('currentPrice') or info.get('regularMarketPrice'),
        }
    except: return None,{}

def calc(d,di):
    if d is None: return 0,'D',{}
    roe=safe(d['roe'].dropna().mean()) if 'roe' in d.columns else None
    fcr=safe(d['fcr'].dropna().mean())  if 'fcr' in d.columns else None
    s1 =round(thr(roe,ROE_THR)*0.6+thr(fcr,FCR_THR)*0.4) if fcr else round(thr(roe,ROE_THR)*0.6+30*0.4)
    rsl=slope(d['roe'].dropna().tail(4)) if 'roe' in d.columns else 0
    fsl=slope(d['fcr'].dropna().tail(4)) if 'fcr' in d.columns else 0
    s2 =round(thr(rsl,RS_THR)*0.6+thr(fsl,FS_THR)*0.4)
    per=di.get('per'); eg=di.get('eps_growth')
    if eg is None and 'ni' in d.columns and len(d)>=3:
        s0,s1d,n=d['ni'].iloc[0],d['ni'].iloc[-1],len(d)-1
        if s0>0 and s1d>0: eg=(s1d/s0)**(1/n)-1
    peg=per/(eg*100) if per and eg and eg>0.01 else None
    mc=di.get('market_cap')
    fcf=d['fcf'].dropna().iloc[-1] if 'fcf' in d.columns and len(d['fcf'].dropna())>0 else None
    fy=abs(fcf)/mc*100 if fcf and mc and mc>0 else None
    s3=round(thr(peg,PEG_THR)*0.5+thr(fy,FCY_THR)*0.5)
    tot=round(s1*0.4+s2*0.35+s3*0.25,1)
    rk='S' if tot>=80 else 'A' if tot>=65 else 'B' if tot>=50 else 'C' if tot>=35 else 'D'
    return tot,rk,{'s1':s1,'s2':s2,'s3':s3,'roe':roe,'fcr':fcr,
                   'roe_slope':safe(rsl,2),'peg':safe(peg,2),
                   'fcf_yield':safe(fy,1),'price':di.get('price')}

# ── Step1: スコア計算 ────────────────────────────────────────
print(f"\n{'='*50}\nStep1: v4.2スコア計算（{len(STOCKS)}銘柄）\n{'='*50}")
results = []
for i,(sec,code,name,sz) in enumerate(STOCKS):
    print(f"  [{i+1:02d}/{len(STOCKS)}] {code} {name}({sz}) ... ", end='', flush=True)
    d,di=get_data(code); time.sleep(0.4)
    tot,rk,ev=calc(d,di)
    results.append({'業種':sec,'コード':code,'銘柄名':name,'時価総額区分':sz,
                    '総合スコア':tot,'ランク':rk,
                    'Real ROIC(s1)':ev.get('s1'),'トレンド(s2)':ev.get('s2'),'価格(s3)':ev.get('s3'),
                    'ROE平均':ev.get('roe'),'FCR平均':ev.get('fcr'),
                    'ROE傾き':ev.get('roe_slope'),'PEG':ev.get('peg'),
                    'FCF利回り':ev.get('fcf_yield'),'株価':ev.get('price'),'算出日時':NOW})
    print(f"{tot}点({rk})")

df=pd.DataFrame(results)

# ── Step2: スコアシートを上書き保存 ─────────────────────────
print(f"\nStep2: スコアシート保存")
SHEET='学習用銘柄_v4.2スコア'
try: ss.del_worksheet(ss.worksheet(SHEET))
except: pass
ws=ss.add_worksheet(title=SHEET,rows=len(df)+5,cols=16)
hdr=list(df.columns)
rows=[hdr]+[['' if (v is None or (isinstance(v,float) and np.isnan(v))) else v
             for v in r] for _,r in df.iterrows()]
ws.update('A1',rows)
print(f"✅ 保存: '{SHEET}'（{len(df)}銘柄）")

# ── Step3: 予測記録に月次追記 ────────────────────────────────
print(f"\nStep3: 予測記録への追記")
ws_pred=ss.worksheet('予測記録')
existing=ws_pred.get_all_values()
exist_keys=set()
for row in existing[2:]:
    if len(row)>=2 and row[0] and row[1]:
        exist_keys.add(f"{row[0][:10]}_{row[1]}")

today_str=TODAY.strftime('%Y/%m/%d')
new_rows=[]

def arr(s,h=65,m=50):
    try: s=float(s); return '↑↑強気' if s>=h else '↑やや強気' if s>=m else '→中立' if s>=35 else '↓弱気'
    except: return '→中立'

def tp(price,score,years,peg):
    try:
        p=float(price); s=float(score); pg=float(peg) if peg else 1.0
        if np.isnan(p) or np.isnan(s): return ''
        return str(round(p*(1+s*0.002*years+max(0,(1.0-pg)*0.08 if pg<1.5 else 0))))
    except: return ''

# 短期・中期スコアを現在値から取得
try:
    ws_sig=ss.worksheet('週次シグナル')
    sig_data=ws_sig.get_all_values()
    if len(sig_data)>1:
        last_sig=sig_data[-1]
        short_score=float(last_sig[1]) if len(last_sig)>1 and last_sig[1] else 29
        medium_score=float(last_sig[3]) if len(last_sig)>3 and last_sig[3] else 25
    else:
        short_score,medium_score=29,25
except:
    short_score,medium_score=29,25

print(f"  現在の短期スコア: {short_score}点 / 中期スコア: {medium_score}点")

for _,r in df.iterrows():
    code=str(r['コード'])
    key=f"{today_str}_{code}"
    if key in exist_keys: continue
    sc=float(r['総合スコア'])
    if sc==0: continue
    rk=str(r['ランク'])
    p=r.get('株価'); peg=r.get('PEG') or 1.0
    roe=r.get('ROE平均') or 0; fcr=r.get('FCR平均') or 0; rs=r.get('ROE傾き') or 0
    sc_s=max(0,min(100,short_score-5))
    sc_m=max(0,min(100,medium_score+5))
    action=('長期強買い' if rk in ['S','A'] and float(peg or 1)<1 else
            '買い検討' if rk in ['S','A'] else '様子見' if rk in ['B','C'] else '売却検討')
    new_rows.append([
        today_str,code,str(r['銘柄名']),f"{r['業種']}（{r['時価総額区分']}）",
        safe_str(p),f"{safe_str(sc)}点",rk,f"{action}【学習用】",
        arr(sc,70,55),tp(p,sc,0.08,peg),
        f"v4.2:{safe_str(sc)}pt/{r['業種']}({r['時価総額区分']})",
        (TODAY+timedelta(weeks=4)).strftime('%Y/%m/%d'),'','','','',
        arr(sc_s),tp(p,sc_s,1.0,peg),f"短期{short_score:.0f}点×{r['業種']}業種",
        (TODAY+timedelta(days=365)).strftime('%Y/%m/%d'),'','','','',
        arr(sc_m,60,45),tp(p,sc_m,3.0,peg),
        f"日本M2加速→2027年後半予測/ROE傾き{safe_str(rs)}%/年",
        (TODAY+timedelta(days=365*3)).strftime('%Y/%m/%d'),'','','','',
        arr(sc),tp(p,sc,5.0,peg),
        f"Real ROIC:ROE{safe_str(roe)}%×FCR{safe_str(fcr)}%",
        (TODAY+timedelta(days=365*5)).strftime('%Y/%m/%d'),'','','','',
    ])

if new_rows:
    next_row=len(existing)+1
    needed=next_row+len(new_rows)
    if needed>ws_pred.row_count:
        ss.batch_update({"requests":[{"updateSheetProperties":{
            "properties":{"sheetId":ws_pred.id,
                          "gridProperties":{"rowCount":needed+100}},
            "fields":"gridProperties(rowCount)"}}]})
    ws_pred.update(f'A{next_row}',new_rows)
    print(f"✅ 予測記録に{len(new_rows)}銘柄を追加")
else:
    print(f"ℹ️ 本日分は登録済み")

# ── 作業ログ ─────────────────────────────────────────────────
try:
    wl=ss.worksheet('作業ログ'); last=len(wl.get_all_values())+1
    wl.update(f'A{last}',[[NOW,'月次学習バッチ',f'{len(STOCKS)}銘柄スキャン',
                            f'予測記録{len(new_rows)}件追加','✅完了']])
except: pass

# ── サマリー ─────────────────────────────────────────────────
print(f"\n{'='*50}\n月次学習バッチ 完了\n{'='*50}")
print(f"  処理銘柄: {len(df)}銘柄 / 予測記録追加: {len(new_rows)}件")
print(f"  ランク分布:", end='')
for rk in ['S','A','B','C','D']:
    n=len(df[df['ランク']==rk])
    print(f"  {rk}:{n}", end='')
print(f"\n✅ 完了: {NOW}")

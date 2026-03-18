# ============================================================
# weekly_update.py 完全版 v3.0
# AI投資判断システム 週次自動更新
#
# 【実行タイミング】
# GitHub Actions: 毎週月曜 10:00 JST（01:00 UTC）
#
# 【実行内容】
# 1. J-Quants v2で株価データ更新
# 2. yfinanceでマクロ指標更新
# 3. v4.2アルティメットコアスキャン（56銘柄）
# 4. 短期スコア（SOX×SP500×HYG×VIX）
# 5. 中期スコア（日本M2加速度ラグ15M×米GDP×WTI）
# 6. 統合スコア（長期50%+短期25%+中期25%）
# 7. 予測記録シートに買いシグナル銘柄を自動追記
# 8. 週次シグナルを記録
# 9. 作業ログに記録
#
# 【認証情報】
# J-Quants APIキー: 環境変数 JQUANTS_API_KEY
# Googleスプレッドシート: 環境変数 GOOGLE_CREDENTIALS
# スプレッドシートID: 1GtlVhGcPjMU0pJWsijwnmTe1rFJXAGvkaJFjav9gGcE
# ============================================================

import os
import json
import requests
import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from scipy import stats
import time
import warnings
warnings.filterwarnings('ignore')

import gspread
from google.oauth2.service_account import Credentials

# ============================================================
# 認証・接続
# ============================================================
SPREADSHEET_ID = '1GtlVhGcPjMU0pJWsijwnmTe1rFJXAGvkaJFjav9gGcE'
JQUANTS_API_KEY = os.environ.get('JQUANTS_API_KEY',
                  '7bEWg3-b2MPc0DWG1vjSugW48LahAiVi622Nxy8S7PA')
JQUANTS_HEADERS = {"x-api-key": JQUANTS_API_KEY}

# Googleスプレッドシート認証
scope = ['https://spreadsheets.google.com/feeds',
         'https://www.googleapis.com/auth/drive']
creds_json = os.environ.get('GOOGLE_CREDENTIALS', '{}')
creds_dict = json.loads(creds_json)
creds = Credentials.from_service_account_info(creds_dict, scopes=scope)
gc = gspread.authorize(creds)
ss = gc.open_by_key(SPREADSHEET_ID)

NOW   = datetime.now().strftime('%Y/%m/%d %H:%M')
TODAY = datetime.now()
print(f"✅ 接続完了: {ss.title}")
print(f"実行日時: {NOW}")

# ============================================================
# 56銘柄マスタ
# ============================================================
STOCKS = [
    {'code':'1605','name':'INPEX',               'sector':'エネルギー'},
    {'code':'1847','name':'イチケン',             'sector':'建設'},
    {'code':'1879','name':'新日本建設',           'sector':'建設'},
    {'code':'1928','name':'積水ハウス',           'sector':'建設'},
    {'code':'1942','name':'関電工',               'sector':'建設'},
    {'code':'2768','name':'双日',                 'sector':'商社'},
    {'code':'3496','name':'アズーム',             'sector':'サービス'},
    {'code':'4221','name':'大倉工業',             'sector':'化学'},
    {'code':'6098','name':'リクルートHD',         'sector':'サービス'},
    {'code':'6200','name':'インソース',           'sector':'サービス'},
    {'code':'6501','name':'日立',                 'sector':'電機'},
    {'code':'6637','name':'寺崎電気産業',         'sector':'電機'},
    {'code':'7187','name':'ジェイリース',         'sector':'サービス'},
    {'code':'7741','name':'HOYA',                 'sector':'精密機器'},
    {'code':'7974','name':'任天堂',               'sector':'その他製品'},
    {'code':'8058','name':'三菱商事',             'sector':'商社'},
    {'code':'8136','name':'サンリオ',             'sector':'その他製品'},
    {'code':'8331','name':'千葉銀行',             'sector':'銀行'},
    {'code':'8386','name':'百十四銀行',           'sector':'銀行'},
    {'code':'8541','name':'愛媛銀行',             'sector':'銀行'},
    {'code':'8935','name':'FJネクストHD',         'sector':'不動産'},
    {'code':'2003','name':'日東富士製粉',         'sector':'食品'},
    {'code':'2914','name':'JT',                   'sector':'食品'},
    {'code':'4063','name':'信越化学',             'sector':'化学'},
    {'code':'5838','name':'楽天銀行',             'sector':'銀行'},
    {'code':'6920','name':'レーザーテック',       'sector':'半導体'},
    {'code':'8001','name':'伊藤忠',               'sector':'商社'},
    {'code':'8053','name':'住友商事',             'sector':'商社'},
    {'code':'8303','name':'SBI新生銀行',          'sector':'銀行'},
    {'code':'8306','name':'三菱UFJ',              'sector':'銀行'},
    {'code':'8316','name':'三井住友FG',           'sector':'銀行'},
    {'code':'8343','name':'秋田銀行',             'sector':'銀行'},
    {'code':'8410','name':'セブン銀行',           'sector':'銀行'},
    {'code':'8473','name':'SBIホールディングス',  'sector':'証券'},
    {'code':'8591','name':'オリックス',           'sector':'金融'},
    {'code':'8593','name':'三菱HCキャピタル',     'sector':'金融'},
    {'code':'8600','name':'トモニHD',             'sector':'銀行'},
    {'code':'8630','name':'SOMPO',                'sector':'保険'},
    {'code':'8771','name':'Eギャランティ',        'sector':'金融'},
    {'code':'9069','name':'センコーグループHD',   'sector':'輸送'},
    {'code':'9432','name':'NTT',                  'sector':'通信'},
    {'code':'9433','name':'KDDI',                 'sector':'通信'},
    {'code':'9434','name':'ソフトバンク',         'sector':'通信'},
    {'code':'4519','name':'中外製薬',             'sector':'医薬品'},
    {'code':'9983','name':'ファーストリテイリング','sector':'小売'},
    {'code':'4307','name':'野村総研',             'sector':'情報通信'},
    {'code':'6273','name':'SMC',                  'sector':'機械'},
    {'code':'2802','name':'味の素',               'sector':'食品'},
    {'code':'4188','name':'三菱ケミカル',         'sector':'素材'},
    {'code':'7751','name':'キヤノン',             'sector':'精密機器'},
    {'code':'8035','name':'東京エレクトロン',     'sector':'半導体'},
    {'code':'3382','name':'セブン&アイHD',        'sector':'流通'},
    {'code':'9020','name':'JR東日本',             'sector':'陸運'},
    {'code':'6857','name':'アドバンテスト',       'sector':'半導体'},
    {'code':'6146','name':'ディスコ',             'sector':'半導体'},
    {'code':'3436','name':'SUMCO',                'sector':'素材'},
]

# ============================================================
# ヘルパー関数
# ============================================================
def safe(val, d=1):
    if val is None: return None
    try:
        f = float(val)
        return None if (np.isnan(f) or np.isinf(f)) else round(f, d)
    except: return None

def safe_list(lst):
    return ['' if (v is None or (isinstance(v,float) and
            (np.isnan(v) or np.isinf(v)))) else v for v in lst]

def thr_high(val, thresholds):
    """高いほど良い指標（降順閾値）"""
    if val is None or (isinstance(val,float) and
       (np.isnan(val) or np.isinf(val))): return 50
    for t, s in thresholds:
        if val >= t: return s
    return 10

def thr_low(val, thresholds):
    """低いほど良い指標（昇順閾値）"""
    if val is None or (isinstance(val,float) and
       (np.isnan(val) or np.isinf(val))): return 50
    for t, s in thresholds:
        if val <= t: return s
    return 10

def slope(series):
    v = pd.Series(series).replace([np.inf,-np.inf],np.nan).dropna().values
    if len(v) < 2: return 0.0
    return float(np.polyfit(range(len(v)), v, 1)[0])

def get_ss_accel(sheet_name, lag_months=0):
    """スプレッドシートから前年比加速度をラグ適用して取得"""
    try:
        ws   = ss.worksheet(sheet_name)
        data = ws.get_all_values()
        df   = pd.DataFrame(data[1:], columns=data[0])
        cols = df.columns.tolist()
        df['date']  = pd.to_datetime(df[cols[0]], errors='coerce')
        df['value'] = pd.to_numeric(df[cols[1]], errors='coerce')
        df = df.dropna(subset=['date','value']).set_index('date').sort_index()
        monthly = df['value'].resample('MS').last().dropna()
        if len(monthly) < lag_months + 14: return None
        yoy   = monthly.pct_change(12).dropna()
        accel = yoy.diff().dropna()
        if len(accel) < lag_months + 2: return None
        return float(accel.iloc[-(lag_months + 1)])
    except:
        return None

def get_monthly_ret(ticker):
    """yfinanceから直近月次リターンを取得"""
    try:
        start = (TODAY - timedelta(days=100)).strftime('%Y-%m-%d')
        hist  = yf.download(ticker, start=start,
                           end=TODAY.strftime('%Y-%m-%d'),
                           interval='1mo', progress=False, auto_adjust=True)
        if hist is None or len(hist) < 2: return None
        close = hist['Close']
        if isinstance(close, pd.DataFrame): close = close.iloc[:,0]
        return float(close.pct_change().dropna().iloc[-1])
    except:
        return None

# ============================================================
# Part1: v4.2 アルティメットコアスキャン
# ============================================================
print(f"\n{'='*60}")
print("Part1: v4.2 コアスキャン（56銘柄）")
print('='*60)

# スコア閾値定義
ROE_THR = [(25,100),(20,85),(15,70),(12,58),(10,46),(8,35),(5,20),(0,8)]
FCR_THR = [(120,100),(100,90),(80,78),(60,62),(40,44),(20,26),(0,10)]
RS_THR  = [(4.0,100),(2.0,82),(0.5,64),(-0.5,46),(-2.0,28),(-999,12)]
FS_THR  = [(8.0,100),(4.0,80),(0.0,60),(-4.0,40),(-8.0,20),(-999,8)]
PEG_THR = [(0.5,100),(0.8,85),(1.0,72),(1.2,58),(1.5,42),(2.0,26),(999,12)]
FCY_THR = [(8,100),(6,85),(4,70),(3,55),(2,38),(1,22),(0,8)]

def get_fin_data(code):
    try:
        t    = yf.Ticker(f"{code}.T")
        fin  = t.financials
        cf   = t.cashflow
        bs   = t.balance_sheet
        info = t.info
        if fin is None or fin.empty: return None, {}
        fin = fin.T.sort_index()
        cf  = cf.T.sort_index() if cf  is not None and not cf.empty  else pd.DataFrame()
        bs  = bs.T.sort_index() if bs  is not None and not bs.empty  else pd.DataFrame()
        d   = pd.DataFrame(index=fin.index)
        for src,dst in [('Total Revenue','sales'),('Operating Income','op_profit'),
                        ('Net Income','net_income')]:
            if src in fin.columns: d[dst] = fin[src]
        for src,dst in [('Operating Cash Flow','cf_ope'),
                        ('Investing Cash Flow','cf_inv')]:
            if src in cf.columns: d[dst] = cf[src]
        for src,dst in [('Stockholders Equity','equity'),
                        ('Total Equity Gross Minority Interest','equity')]:
            if src in bs.columns and 'equity' not in d.columns: d[dst] = bs[src]
        if 'cf_ope' in d.columns and 'cf_inv' in d.columns:
            d['fcf'] = d['cf_ope'] + d['cf_inv']
        if 'net_income' in d.columns and 'equity' in d.columns:
            d['roe'] = d['net_income'] / d['equity'].replace(0,np.nan) * 100
        if 'fcf' in d.columns and 'net_income' in d.columns:
            d['fcf_ratio'] = d['fcf'] / d['net_income'].replace(0,np.nan) * 100
        return d.replace([np.inf,-np.inf],np.nan).dropna(how='all'), {
            'per':        info.get('trailingPE'),
            'market_cap': info.get('marketCap'),
            'eps_growth': info.get('earningsGrowth'),
            'price':      info.get('currentPrice') or info.get('regularMarketPrice'),
        }
    except:
        return None, {}

def calc_v42_score(d, di):
    if d is None: return 0, 'D', {}
    roe  = safe(d['roe'].dropna().mean()) if 'roe' in d.columns else None
    fcr  = safe(d['fcf_ratio'].dropna().mean()) if 'fcf_ratio' in d.columns else None
    rs   = thr_high(roe, ROE_THR)
    fcs  = thr_high(fcr, FCR_THR) if fcr is not None else 30
    s1   = round(rs*0.60 + fcs*0.40)

    rsl  = slope(d['roe'].dropna().tail(4)) if 'roe' in d.columns else 0
    fsl  = slope(d['fcf_ratio'].dropna().tail(4)) if 'fcf_ratio' in d.columns else 0
    s2   = round(thr_high(rsl,RS_THR)*0.60 + thr_high(fsl,FS_THR)*0.40)

    per  = di.get('per')
    eg   = di.get('eps_growth')
    if eg is None and 'net_income' in d.columns and len(d)>=3:
        s0,s1d,n = d['net_income'].iloc[0],d['net_income'].iloc[-1],len(d)-1
        if s0>0 and s1d>0: eg = (s1d/s0)**(1/n)-1
    peg  = per/(eg*100) if per and eg and eg>0.01 else None
    mc   = di.get('market_cap')
    fcf  = d['fcf'].dropna().iloc[-1] if 'fcf' in d.columns and len(d['fcf'].dropna())>0 else None
    fy   = abs(fcf)/mc*100 if fcf and mc and mc>0 else None
    s3   = round(thr_high(peg,PEG_THR)*0.50 + thr_high(fy,FCY_THR)*0.50)

    tot  = round(s1*0.40 + s2*0.35 + s3*0.25, 1)
    rnk  = ('S' if tot>=80 else 'A' if tot>=65 else
            'B' if tot>=50 else 'C' if tot>=35 else 'D')
    return tot, rnk, {
        'roe':roe,'fcr':fcr,'roe_slope':safe(rsl,2),
        'peg':safe(peg,2),'fcf_yield':safe(fy,1),
        's1':s1,'s2':s2,'s3':s3,'price':di.get('price')
    }

scan_results = []
for s in STOCKS:
    code, name, sector = s['code'], s['name'], s['sector']
    print(f"  {code} {name} ... ", end='')
    d, di = get_fin_data(code)
    time.sleep(0.4)
    tot, rnk, ev = calc_v42_score(d, di)
    scan_results.append({
        'コード':code,'銘柄名':name,'業種':sector,
        '総合スコア':tot,'ランク':rnk,
        'ROE平均':ev.get('roe'),'FCR平均':ev.get('fcr'),
        'ROE傾き':ev.get('roe_slope'),
        'PEG':ev.get('peg'),'FCF利回り':ev.get('fcf_yield'),
        '変数1':ev.get('s1'),'変数2':ev.get('s2'),'変数3':ev.get('s3'),
        '株価':ev.get('price'),'算出日時':NOW,
    })
    print(f"{tot}点({rnk})")

df_scan = pd.DataFrame(scan_results).sort_values('総合スコア',ascending=False).reset_index(drop=True)

# スキャン結果を保存
SHEET_SCAN = 'コアスキャン_v4.2'
try: ss.del_worksheet(ss.worksheet(SHEET_SCAN))
except: pass
ws_scan = ss.add_worksheet(title=SHEET_SCAN, rows=len(df_scan)+5, cols=16)
h_scan  = list(df_scan.columns)
rows_scan = [h_scan]
for _, r in df_scan.iterrows():
    rows_scan.append(safe_list([r[c] for c in h_scan]))
ws_scan.update('A1', rows_scan)
print(f"\n✅ コアスキャン保存: '{SHEET_SCAN}'（{len(df_scan)}銘柄）")

# ランク分布
for rk in ['S','A','B','C','D']:
    n = len(df_scan[df_scan['ランク']==rk])
    if n > 0:
        names = '/'.join(df_scan[df_scan['ランク']==rk]['銘柄名'].tolist()[:5])
        print(f"  {rk}({n}): {names}")

# ============================================================
# Part2: 短期スコア計算
# ============================================================
print(f"\n{'='*60}")
print("Part2: 短期スコア計算（市場体温計）")
print('='*60)

# 閾値定義
SOX_THR   = [(0.08,100),(0.04,80),(0.02,65),(0.0,50),(-0.02,38),(-0.05,25),(-0.10,12)]
SP5_THR   = [(0.06,100),(0.03,80),(0.01,65),(0.0,50),(-0.02,38),(-0.04,25),(-0.08,12)]
HYG_THR   = [(0.03,100),(0.01,80),(0.0,60),(-0.01,50),(-0.02,40),(-0.04,25),(-0.08,10)]
VIX_THR   = [(-0.20,100),(-0.10,80),(-0.05,65),(0.0,50),(0.05,38),(0.10,25),(0.20,12)]

sox_ret   = get_monthly_ret('^SOX')
sp5_ret   = get_monthly_ret('^GSPC')
hyg_ret   = get_monthly_ret('HYG')
vix_ret   = get_monthly_ret('^VIX')
time.sleep(0.5)

sox_s  = thr_high(sox_ret, SOX_THR)
sp5_s  = thr_high(sp5_ret, SP5_THR)
hyg_s  = thr_high(hyg_ret, HYG_THR)
vix_s  = thr_low( vix_ret, VIX_THR)

short_score = round(sox_s*0.30 + sp5_s*0.25 + hyg_s*0.25 + vix_s*0.20)

def sig_s(s):
    return ('🟢🟢強気' if s>=70 else '🟢やや強気' if s>=55 else
            '🟡中立' if s>=45 else '🔴やや弱気' if s>=30 else '🔴🔴弱気')

fmt_r = lambda v: f"{v:+.2%}" if v is not None else "取得失敗"
print(f"  SOX:{fmt_r(sox_ret)}→{sox_s}pt / SP500:{fmt_r(sp5_ret)}→{sp5_s}pt")
print(f"  HYG:{fmt_r(hyg_ret)}→{hyg_s}pt / VIX:{fmt_r(vix_ret)}→{vix_s}pt")
print(f"  短期スコア: {short_score}点 {sig_s(short_score)}")

# ============================================================
# Part3: 中期スコア計算
# ============================================================
print(f"\n{'='*60}")
print("Part3: 中期スコア計算（先行指標ラグ適用）")
print('='*60)

# 閾値定義
JM2_THR = [(0.003,100),(0.001,80),(0.0005,65),(0.0,50),(-0.0005,40),(-0.001,25),(-0.003,10)]
GDP_THR = [(2.0,100),(1.0,80),(0.5,65),(0.0,50),(-0.5,40),(-1.0,25),(-2.0,10)]
WTI_THR = [(-0.10,100),(-0.05,80),(-0.02,65),(0.02,50),(0.05,38),(0.10,25),(0.20,10)]

jm2_accel = get_ss_accel('日本M2', lag_months=15)
time.sleep(0.3)
gdp_accel = get_ss_accel('米GDP成長率', lag_months=12)
time.sleep(0.3)
wti_accel = get_ss_accel('WTI原油', lag_months=10)
time.sleep(0.3)

jm2_s = thr_high(jm2_accel, JM2_THR)
gdp_s = thr_high(gdp_accel, GDP_THR)
wti_s = thr_low( wti_accel, WTI_THR)

medium_score = round(jm2_s*0.50 + gdp_s*0.30 + wti_s*0.20)

def sig_m(s):
    return ('🟢🟢強気（1〜2年後好転）' if s>=70 else '🟢やや強気' if s>=55 else
            '🟡中立' if s>=45 else '🔴やや弱気' if s>=30 else '🔴🔴弱気（1〜2年後悪化リスク）')

fmt_a = lambda v: f"{v:+.4f}" if v is not None else "取得中"
fmt_g = lambda v: f"{v:+.2f}" if v is not None else "取得中"
print(f"  日本M2加速度(15M前):{fmt_a(jm2_accel)}→{jm2_s}pt")
print(f"  米GDP加速度(12M前): {fmt_g(gdp_accel)}→{gdp_s}pt")
print(f"  WTI加速度(10M前):   {fmt_a(wti_accel)}→{wti_s}pt")
print(f"  中期スコア: {medium_score}点 {sig_m(medium_score)}")

# ============================================================
# Part4: 統合スコア計算（長期50%+短期25%+中期25%）
# ============================================================
print(f"\n{'='*60}")
print("Part4: 統合スコア計算")
print('='*60)

# 業種別感応度補正（実証相関値から設定）
SECTOR_S_BONUS = {
    '半導体':+8,'精密機器':+5,'電機':+5,'銀行':+3,'証券':+3,'金融':+3
}
SECTOR_M_BONUS = {
    '商社':+10,'小売':+7,'不動産':+7,'銀行':+5,
    '陸運':+5,'ゴム':+5,'医薬品':+4,'輸送機器':-7,'自動車':-7
}
RANK_THR = {'S':80,'A':65,'B':50,'C':35}

int_results = []
for _, r in df_scan.iterrows():
    sec    = str(r['業種'])
    ls     = float(r['総合スコア'])
    adj_s  = min(100, max(0, short_score  + SECTOR_S_BONUS.get(sec, 0)))
    adj_m  = min(100, max(0, medium_score + SECTOR_M_BONUS.get(sec, 0)))
    integ  = round(ls*0.50 + adj_s*0.25 + adj_m*0.25, 1)
    irk    = ('S' if integ>=RANK_THR['S'] else 'A' if integ>=RANK_THR['A'] else
               'B' if integ>=RANK_THR['B'] else 'C' if integ>=RANK_THR['C'] else 'D')
    int_results.append({
        'コード':r['コード'],'銘柄名':r['銘柄名'],'業種':sec,
        '長期スコア':ls,'短期スコア':adj_s,'中期スコア':adj_m,
        '統合スコア':integ,'統合ランク':irk,
        '短期シグナル':sig_s(short_score),'中期シグナル':sig_m(medium_score),
        '算出日時':NOW,
    })

df_int = pd.DataFrame(int_results).sort_values('統合スコア',ascending=False)

# 統合スコアを保存
SHEET_INT = '統合スコア_週次'
try: ss.del_worksheet(ss.worksheet(SHEET_INT))
except: pass
ws_int = ss.add_worksheet(title=SHEET_INT, rows=len(df_int)+5, cols=12)
ws_int.update('A1', [list(df_int.columns)] +
              [[str(v) for v in r] for _, r in df_int.iterrows()])
print(f"✅ 統合スコア保存: '{SHEET_INT}'")

for rk in ['S','A','B','C','D']:
    n = len(df_int[df_int['統合ランク']==rk])
    if n > 0: print(f"  {rk}({n}銘柄)", end='')
print()

# ============================================================
# Part5: 予測記録シートへの自動追記（Aランク以上・60点以上）
# ============================================================
print(f"\n{'='*60}")
print("Part5: 予測記録シートへの自動追記")
print('='*60)

try:
    ws_pred = ss.worksheet('予測記録')
    existing = ws_pred.get_all_values()
    existing_keys = set()
    for row in existing[2:]:
        if len(row) >= 2 and row[0] and row[1]:
            existing_keys.add(f"{row[0][:10]}_{row[1]}")

    today_str = TODAY.strftime('%Y/%m/%d')
    new_rows  = []
    targets   = df_scan[
        (df_scan['ランク'].isin(['S','A'])) |
        (df_scan['総合スコア'] >= 58)
    ]

    for _, r in targets.iterrows():
        key = f"{today_str}_{r['コード']}"
        if key in existing_keys: continue

        sc  = float(r['総合スコア'])
        rnk = r['ランク']
        peg = r.get('PEG') or 1.0

        def dir_str(s, h=65, m=50):
            return '↑↑強気' if s>=h else '↑やや強気' if s>=m else '→中立' if s>=35 else '↓弱気'

        def tp(s, yrs):
            p = r.get('株価')
            if not p: return ''
            b = s*0.002*yrs
            bo = max(0,(1.0-peg)*0.08) if peg and peg<1.5 else 0
            return str(round(float(p)*(1+b+bo)))

        misaki_d = (TODAY+timedelta(weeks=4)).strftime('%Y/%m/%d')
        tanki_d  = (TODAY+timedelta(days=365)).strftime('%Y/%m/%d')
        chuki_d  = (TODAY+timedelta(days=365*3)).strftime('%Y/%m/%d')
        choki_d  = (TODAY+timedelta(days=365*5)).strftime('%Y/%m/%d')

        sc_s = max(0,min(100,short_score-5))
        sc_m = max(0,min(100,medium_score+5))

        action = ('長期強買い' if rnk in ['S','A'] and peg<1.0 else
                  '買い検討'   if rnk in ['S','A'] else
                  'タイミング待ち' if sc>=58 else '中立観察')

        new_rows.append([
            today_str, r['コード'], r['銘柄名'], r['業種'],
            str(r.get('株価') or ''), f"{sc}点", rnk, action,
            dir_str(sc,70,55), tp(sc,0.08),
            f"v4.2:{sc}pt / ROIC:{r.get('変数1',0)}pt / トレンド:{r.get('変数2',0)}pt",
            misaki_d,'','','','',
            dir_str(sc_s),tp(sc_s,1.0),
            f"短期{sig_s(short_score)} / PEG{peg:.2f} / {r['業種']}",
            tanki_d,'','','','',
            dir_str(sc_m,60,45),tp(sc_m,3.0),
            f"日本M2加速中→2027年後半内需好転予測 / ROE傾き{r.get('ROE傾き',0):+.1f}%/年",
            chuki_d,'','','','',
            dir_str(sc),tp(sc,5.0),
            f"Real ROIC: ROE{r.get('ROE平均',0):.1f}%×FCR{r.get('FCR平均',0):.0f}%",
            choki_d,'','','','',
        ])

    if new_rows:
        next_row = len(existing) + 1
        ws_pred.update(f'A{next_row}', new_rows)
        print(f"✅ {len(new_rows)}銘柄を予測記録に追加")
        for row in new_rows:
            print(f"  → {row[2]}（{row[5]}/{row[6]}）")
    else:
        print("ℹ️ 新規追加なし（全て登録済み）")
except Exception as e:
    print(f"⚠️ 予測記録追記スキップ: {e}")

# ============================================================
# Part6: 週次シグナル記録（蓄積）
# ============================================================
print(f"\n{'='*60}")
print("Part6: 週次シグナル記録")
print('='*60)

SHEET_SIG = '週次シグナル'
try:
    ws_sig = ss.worksheet(SHEET_SIG)
except:
    ws_sig = ss.add_worksheet(title=SHEET_SIG, rows=500, cols=15)
    ws_sig.update('A1', [[
        '記録日','短期スコア','短期シグナル','中期スコア','中期シグナル',
        'SOXスコア','SP500スコア','HYGスコア','VIXスコア',
        '日本M2加速度(15M前)','米GDPスコア','WTIスコア',
        '短期推奨業種','中期推奨業種','メモ'
    ]])

short_rec  = ('半導体・精密機器・電機' if short_score>=60 else
              '食品・通信・医薬品' if short_score<=40 else '中立')
medium_rec = ('商社・小売・不動産・銀行' if medium_score>=60 else
              '輸送機器・通信' if medium_score<=40 else '中立')

last_row = len(ws_sig.get_all_values()) + 1
ws_sig.update(f'A{last_row}', [[
    NOW, short_score, sig_s(short_score),
    medium_score, sig_m(medium_score),
    sox_s, sp5_s, hyg_s, vix_s,
    fmt_a(jm2_accel), gdp_s, wti_s,
    short_rec, medium_rec, ''
]])
print(f"✅ 週次シグナル記録（行{last_row}）")

# ============================================================
# Part7: 作業ログ記録
# ============================================================
try:
    ws_log = ss.worksheet('作業ログ')
    last   = len(ws_log.get_all_values()) + 1
    ws_log.update(f'A{last}', [[
        NOW, '週次自動更新', 'weekly_update.py v3.0',
        f'コアスキャン完了・短期{short_score}点・中期{medium_score}点',
        '✅完了'
    ]])
    print(f"✅ 作業ログ記録完了")
except: pass

# ============================================================
# 最終サマリー
# ============================================================
print(f"\n{'='*60}")
print("週次更新 完了サマリー")
print(f"{'='*60}")
print(f"  実行日時:     {NOW}")
print(f"  短期スコア:   {short_score}点 {sig_s(short_score)}")
print(f"  中期スコア:   {medium_score}点 {sig_m(medium_score)}")
print(f"  短期推奨業種: {short_rec}")
print(f"  中期推奨業種: {medium_rec}")
sa = df_int[df_int['統合ランク'].isin(['S','A'])]['銘柄名'].tolist()
if sa: print(f"  統合S/Aランク: {' / '.join(sa[:8])}")
else:  print(f"  ※ 全銘柄Bランク以下（短期・中期が弱い環境）")
print(f"\n✅ 全処理完了")
print(f"URL: https://docs.google.com/spreadsheets/d/{SPREADSHEET_ID}")

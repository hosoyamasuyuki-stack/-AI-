# ============================================================
# weekly_update.py v4.0
# AI投資判断システム 週次自動更新
#
# v3.0からの変更点：
# ・Part1のデータソースをyfinance→J-Quants V2（v4.3）に変更
# ・財務データを10年分（過去10年）で計算
# ・FCFをCFO+CFIで直接取得（精度向上）
# ・ROEトレンドを最大8期分で計算
# ・FCF利回りを時価総額ベースに変更（株価連動）
# ・FCR異常値を±300%でクリップ
#
# 【実行タイミング】毎週月曜 10:00 JST（GitHub Actions）
# 【認証】JQUANTS_API_KEY・GOOGLE_CREDENTIALS（環境変数）
# ============================================================

import os, json, requests, time, warnings
import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import gspread
from google.oauth2.service_account import Credentials
warnings.filterwarnings('ignore')

# ── 認証 ────────────────────────────────────────────────────
SPREADSHEET_ID  = '1GtlVhGcPjMU0pJWsijwnmTe1rFJXAGvkaJFjav9gGcE'
JQUANTS_API_KEY = os.environ.get('JQUANTS_API_KEY',
                  '7bEWg3-b2MPc0DWG1vjSugW48LahAiVi622Nxy8S7PA')
JQUANTS_HEADERS = {'x-api-key': JQUANTS_API_KEY}
JQUANTS_BASE    = 'https://api.jquants.com'

scope      = ['https://spreadsheets.google.com/feeds',
              'https://www.googleapis.com/auth/drive']
creds_dict = json.loads(os.environ.get('GOOGLE_CREDENTIALS','{}'))
creds      = Credentials.from_service_account_info(creds_dict, scopes=scope)
gc         = gspread.authorize(creds)
ss         = gc.open_by_key(SPREADSHEET_ID)

NOW        = datetime.now().strftime('%Y/%m/%d %H:%M')
TODAY      = datetime.now()
DATA_YEARS = 10  # 過去10年分のデータを使用
CUTOFF     = (TODAY - timedelta(days=365 * DATA_YEARS)).strftime('%Y-%m-%d')

print(f"✅ 接続完了: {ss.title}")
print(f"実行日時: {NOW}")
print(f"データ期間: 過去{DATA_YEARS}年分（{CUTOFF[:7]}以降）")

# ── 56銘柄マスタ ─────────────────────────────────────────────
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

# ── ヘルパー関数 ─────────────────────────────────────────────
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

def slope_fn(series):
    v = pd.Series(series).replace([np.inf,-np.inf],np.nan).dropna().values
    if len(v) < 2: return 0.0
    return float(np.polyfit(range(len(v)), v, 1)[0])

def get_ss_accel(sheet_name, lag_months=0):
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
    except: return None

def get_monthly_ret(ticker):
    try:
        start = (TODAY - timedelta(days=100)).strftime('%Y-%m-%d')
        hist  = yf.download(ticker, start=start,
                           end=TODAY.strftime('%Y-%m-%d'),
                           interval='1mo', progress=False, auto_adjust=True)
        if hist is None or len(hist) < 2: return None
        close = hist['Close']
        if isinstance(close, pd.DataFrame): close = close.iloc[:,0]
        return float(close.pct_change().dropna().iloc[-1])
    except: return None

# ── J-Quants V2 データ取得関数（v4.3）───────────────────────
def get_price_jq(code):
    """J-Quants V2から最新株価と時価総額を取得"""
    try:
        code5 = code + '0' if len(code) == 4 else code
        for days_ago in range(1, 8):
            date_str = (TODAY - timedelta(days=days_ago)).strftime('%Y-%m-%d')
            r = requests.get(f"{JQUANTS_BASE}/v2/equities/bars/daily",
                           headers=JQUANTS_HEADERS,
                           params={"code": code5, "date": date_str},
                           timeout=10)
            if r.status_code == 200:
                data = r.json().get('data', [])
                if data:
                    d = data[0]
                    price = d.get('AdjC') or d.get('C')
                    # 発行済み株数は銘柄マスターから取得
                    shares = get_shares_jq(code5)
                    market_cap = float(price) * shares if price and shares else None
                    return {
                        'price': price,
                        'market_cap': market_cap,
                        'date': date_str
                    }
        return {}
    except: return {}

def get_shares_jq(code5):
    """J-Quants V2の銘柄マスターから発行済み株数を取得"""
    try:
        r = requests.get(f"{JQUANTS_BASE}/v2/equities/master",
                        headers=JQUANTS_HEADERS,
                        params={"code": code5}, timeout=10)
        if r.status_code == 200:
            data = r.json().get('data', [])
            if data:
                d = data[0]
                # 発行済み株数（単元株数×単元数）
                shares = d.get('TotalMarketValue')
                if shares: return float(shares)
        return None
    except: return None

def get_fin_jq(code):
    """J-Quants V2 fins/summaryから財務データを取得（10年分）"""
    try:
        code5 = code + '0' if len(code) == 4 else code
        r = requests.get(f"{JQUANTS_BASE}/v2/fins/summary",
                        headers=JQUANTS_HEADERS,
                        params={"code": code5}, timeout=15)
        if r.status_code != 200: return None, {}

        data = r.json().get('data', [])
        if not data: return None, {}

        df = pd.DataFrame(data)

        # 過去10年分にフィルタ
        if 'CurPerEn' in df.columns:
            df['CurPerEn'] = pd.to_datetime(df['CurPerEn'], errors='coerce')
            df = df[df['CurPerEn'] >= pd.Timestamp(CUTOFF)].copy()
            df = df.sort_values('CurPerEn').reset_index(drop=True)

        if len(df) < 2: return None, {}

        # 年次決算のみ抽出
        if 'DocType' in df.columns:
            annual = df[
                df['DocType'].str.contains('FinancialStatements', na=False) &
                ~df['DocType'].str.contains('2Q|3Q|1Q|HalfYear|Quarter', na=False)
            ].copy()
            if len(annual) >= 2:
                df = annual

        # 数値変換
        for col in ['Sales','OP','NP','EPS','DEPS','TA','Eq','EqAR',
                    'CFO','CFI','FEPS','FOP','FNP','ShOutFY']:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors='coerce')

        # 派生指標計算
        if 'NP' in df.columns and 'Eq' in df.columns:
            df['ROE'] = df['NP'] / df['Eq'].replace(0, np.nan) * 100
        if 'CFO' in df.columns and 'CFI' in df.columns:
            df['FCF'] = df['CFO'] + df['CFI']
        if 'FCF' in df.columns and 'NP' in df.columns:
            df['FCR'] = df['FCF'] / df['NP'].replace(0, np.nan) * 100

        # 株価情報
        price_info = get_price_jq(code)

        # 発行済み株数（fins/summaryのShOutFYを優先使用）
        if 'ShOutFY' in df.columns:
            shares_latest = df['ShOutFY'].dropna()
            if len(shares_latest) > 0:
                price_info['shares'] = float(shares_latest.iloc[-1])

        return df.replace([np.inf,-np.inf], np.nan).dropna(how='all'), price_info

    except Exception as e:
        return None, {}

# ── v4.3スコア計算 ───────────────────────────────────────────
ROE_THR = [(25,100),(20,85),(15,70),(12,58),(10,46),(8,35),(5,20),(0,8)]
FCR_THR = [(120,100),(100,90),(80,78),(60,62),(40,44),(20,26),(0,10)]
RS_THR  = [(4.0,100),(2.0,82),(0.5,64),(-0.5,46),(-2.0,28),(-999,12)]
FS_THR  = [(8.0,100),(4.0,80),(0.0,60),(-4.0,40),(-8.0,20),(-999,8)]
PEG_THR = [(0.5,100),(0.8,85),(1.0,72),(1.2,58),(1.5,42),(2.0,26),(999,12)]
FCY_THR = [(8,100),(6,85),(4,70),(3,55),(2,38),(1,22),(0,8)]

def calc_v43_score(df, price_info):
    """
    v4.3スコア計算
    v4.2との違い：
    ・J-Quants V2（10年分）でROE・FCR・EPS計算
    ・FCF利回りを時価総額ベースに変更（株価連動）← STEP④
    ・FCR異常値±300%クリップ
    ・ROEトレンドを最大8期分で計算
    """
    if df is None or len(df) < 2: return 0, 'D', {}

    # 変数1：Real ROIC
    roe_s = df['ROE'].dropna() if 'ROE' in df.columns else pd.Series()
    fcr_s = df['FCR'].dropna() if 'FCR' in df.columns else pd.Series()

    roe_mean = safe(roe_s.mean()) if len(roe_s) > 0 else None
    # FCR異常値クリップ（±300%）
    fcr_clean = fcr_s[(fcr_s >= -300) & (fcr_s <= 300)] if len(fcr_s) > 0 else pd.Series()
    fcr_mean  = safe(fcr_clean.mean()) if len(fcr_clean) > 0 else None

    s1 = round(thr_high(roe_mean, ROE_THR) * 0.60 +
               (thr_high(fcr_mean, FCR_THR) if fcr_mean is not None else 30) * 0.40)

    # 変数2：トレンド（最大8期分）
    roe_trend = slope_fn(roe_s.tail(8))   if len(roe_s) >= 3 else 0
    fcr_trend = slope_fn(fcr_clean.tail(8)) if len(fcr_clean) >= 3 else 0
    s2 = round(thr_high(roe_trend, RS_THR) * 0.60 +
               thr_high(fcr_trend, FS_THR) * 0.40)

    # 変数3：価格（PEG + FCF利回り）
    peg = None
    if 'EPS' in df.columns and len(df) >= 3:
        eps_s = df['EPS'].dropna()
        if len(eps_s) >= 3:
            e_now = float(eps_s.iloc[-1])
            e_old = float(eps_s.iloc[-3])
            if e_old > 0 and e_now > 0:
                eg = (e_now / e_old) ** (1/2) - 1
                if 'FEPS' in df.columns:
                    feps = df['FEPS'].dropna()
                    if len(feps) > 0 and float(feps.iloc[-1]) > 0:
                        eg = float(feps.iloc[-1]) / e_now - 1
                price = price_info.get('price')
                if price and e_now > 0 and eg > 0.01:
                    per = float(price) / e_now
                    peg = per / (eg * 100)

    # FCF利回り：時価総額ベース（株価連動）← STEP④
    fy = None
    if 'FCF' in df.columns:
        fcf_l = df['FCF'].dropna()
        if len(fcf_l) > 0:
            fcf_v     = float(fcf_l.iloc[-1])
            market_cap = price_info.get('market_cap')
            # 時価総額が取れない場合は総資産で代替
            if market_cap and market_cap > 0:
                fy = abs(fcf_v) / market_cap * 100  # ← 時価総額ベース（株価連動）
            elif 'TA' in df.columns:
                ta_l = df['TA'].dropna()
                if len(ta_l) > 0:
                    fy = abs(fcf_v) / float(ta_l.iloc[-1]) * 100  # 総資産で代替

    s3 = round(thr_high(peg, PEG_THR) * 0.50 +
               thr_high(fy,  FCY_THR) * 0.50)

    total = round(s1 * 0.40 + s2 * 0.35 + s3 * 0.25, 1)
    rank  = ('S' if total >= 80 else 'A' if total >= 65 else
             'B' if total >= 50 else 'C' if total >= 35 else 'D')

    return total, rank, {
        'roe': roe_mean, 'fcr': fcr_mean,
        'roe_slope': safe(roe_trend, 2), 'fcr_slope': safe(fcr_trend, 2),
        'peg': safe(peg, 2), 'fcf_yield': safe(fy, 1),
        's1': s1, 's2': s2, 's3': s3,
        'price': price_info.get('price'),
        'market_cap': price_info.get('market_cap'),
        'data_years': len(df),
    }

# ============================================================
# Part1: v4.3 アルティメットコアスキャン（J-Quants V2）
# ============================================================
print(f"\n{'='*60}")
print("Part1: v4.3 コアスキャン（J-Quants V2・10年分）")
print('='*60)

scan_results = []
for s in STOCKS:
    code, name, sector = s['code'], s['name'], s['sector']
    print(f"  {code} {name} ... ", end='', flush=True)
    df_fin, price_info = get_fin_jq(code)
    time.sleep(0.35)  # レートリミット対策（60req/分）
    tot, rnk, ev = calc_v43_score(df_fin, price_info)
    scan_results.append({
        'コード': code, '銘柄名': name, '業種': sector,
        '総合スコア': tot, 'ランク': rnk,
        'ROE平均': ev.get('roe'), 'FCR平均': ev.get('fcr'),
        'ROEトレンド': ev.get('roe_slope'),
        'PEG': ev.get('peg'), 'FCF利回り': ev.get('fcf_yield'),
        '変数1': ev.get('s1'), '変数2': ev.get('s2'), '変数3': ev.get('s3'),
        '株価': ev.get('price'), '時価総額': ev.get('market_cap'),
        'データ期数': ev.get('data_years'), '算出日時': NOW,
    })
    print(f"{tot}点({rnk}) [{ev.get('data_years','?')}期]")

df_scan = pd.DataFrame(scan_results).sort_values(
    '総合スコア', ascending=False).reset_index(drop=True)

# スキャン結果を保存
SHEET_SCAN = 'コアスキャン_v4.3'
try: ss.del_worksheet(ss.worksheet(SHEET_SCAN))
except: pass
ws_scan   = ss.add_worksheet(title=SHEET_SCAN, rows=len(df_scan)+5, cols=18)
h_scan    = list(df_scan.columns)
rows_scan = [h_scan] + [safe_list([r[c] for c in h_scan])
                        for _, r in df_scan.iterrows()]
ws_scan.update('A1', rows_scan)
print(f"\n✅ コアスキャン保存: '{SHEET_SCAN}'（{len(df_scan)}銘柄）")
for rk in ['S','A','B','C','D']:
    n = len(df_scan[df_scan['ランク']==rk])
    if n > 0:
        names = '/'.join(df_scan[df_scan['ランク']==rk]['銘柄名'].tolist()[:5])
        print(f"  {rk}({n}): {names}")

# ============================================================
# Part2: 短期スコア計算（変更なし）
# ============================================================
print(f"\n{'='*60}")
print("Part2: 短期スコア計算（市場体温計）")
print('='*60)

SOX_THR = [(0.08,100),(0.04,80),(0.02,65),(0.0,50),(-0.02,38),(-0.05,25),(-0.10,12)]
SP5_THR = [(0.06,100),(0.03,80),(0.01,65),(0.0,50),(-0.02,38),(-0.04,25),(-0.08,12)]
HYG_THR = [(0.03,100),(0.01,80),(0.0,60),(-0.01,50),(-0.02,40),(-0.04,25),(-0.08,10)]
VIX_THR = [(-0.20,100),(-0.10,80),(-0.05,65),(0.0,50),(0.05,38),(0.10,25),(0.20,12)]

sox_ret = get_monthly_ret('^SOX')
sp5_ret = get_monthly_ret('^GSPC')
hyg_ret = get_monthly_ret('HYG')
vix_ret = get_monthly_ret('^VIX')
time.sleep(0.5)

sox_s = thr_high(sox_ret, SOX_THR)
sp5_s = thr_high(sp5_ret, SP5_THR)
hyg_s = thr_high(hyg_ret, HYG_THR)
vix_s = thr_low( vix_ret, VIX_THR)  # VIXは低いほど良い

short_score = round(sox_s*0.30 + sp5_s*0.25 + hyg_s*0.25 + vix_s*0.20)

def sig_s(s):
    return ('🟢🟢強気' if s>=70 else '🟢やや強気' if s>=55 else
            '🟡中立'   if s>=45 else '🔴やや弱気' if s>=30 else '🔴🔴弱気')

fmt_r = lambda v: f"{v:+.2%}" if v is not None else "取得失敗"
print(f"  SOX:{fmt_r(sox_ret)}→{sox_s}pt / SP500:{fmt_r(sp5_ret)}→{sp5_s}pt")
print(f"  HYG:{fmt_r(hyg_ret)}→{hyg_s}pt / VIX:{fmt_r(vix_ret)}→{vix_s}pt")
print(f"  短期スコア: {short_score}点 {sig_s(short_score)}")

# ============================================================
# Part3: 中期スコア計算（変更なし）
# ============================================================
print(f"\n{'='*60}")
print("Part3: 中期スコア計算（日本M2加速度ラグ15M）")
print('='*60)

M2JP_ACCEL_THR = [( 0.005,100),( 0.002,80),(0.0,60),(-0.002,40),(-0.005,20),(-999,8)]
GDP_ACCEL_THR  = [( 0.5,100),  ( 0.2,80), (0.0,60),(-0.2, 40), (-0.5, 20), (-999,8)]
WTI_ACCEL_THR  = [(-0.05,100),(-0.02,80),(0.0,60),( 0.02,40), ( 0.05,20), (999, 8)]

m2jp_accel = get_ss_accel('日本M2_月次', lag_months=15)
gdp_accel  = get_ss_accel('米GDP_月次',  lag_months=12)
wti_accel  = get_ss_accel('WTI原油_月次',lag_months=10)

m2jp_s = thr_high(m2jp_accel, M2JP_ACCEL_THR)
gdp_s  = thr_high(gdp_accel,  GDP_ACCEL_THR)
wti_s  = thr_low( wti_accel,  WTI_ACCEL_THR)

medium_score = round(m2jp_s*0.50 + gdp_s*0.30 + wti_s*0.20)

def sig_m(s):
    return ('🟢🟢強気' if s>=70 else '🟢やや強気' if s>=55 else
            '🟡中立'   if s>=45 else '🔴やや弱気' if s>=30 else '🔴🔴弱気')

print(f"  日本M2加速(15Mラグ):{m2jp_accel}→{m2jp_s}pt")
print(f"  米GDP加速(12Mラグ): {gdp_accel}→{gdp_s}pt")
print(f"  WTI加速(10Mラグ):   {wti_accel}→{wti_s}pt")
print(f"  中期スコア: {medium_score}点 {sig_m(medium_score)}")

# ============================================================
# Part4: 統合スコア（長期50%+短期25%+中期25%）
# ============================================================
print(f"\n{'='*60}")
print("Part4: 統合スコア計算")
print('='*60)

integration_results = []
for _, r in df_scan.iterrows():
    long_s = float(r['総合スコア'])
    intg   = round(long_s*0.50 + short_score*0.25 + medium_score*0.25, 1)
    integration_results.append({
        'コード': r['コード'], '銘柄名': r['銘柄名'], '業種': r['業種'],
        '統合スコア': intg,
        '長期スコア(v4.3)': long_s, '長期ランク': r['ランク'],
        '短期スコア': short_score, '中期スコア': medium_score,
        '株価': r.get('株価'), '算出日時': NOW,
    })

df_intg = pd.DataFrame(integration_results).sort_values(
    '統合スコア', ascending=False).reset_index(drop=True)

SHEET_INTG = '統合スコア_週次'
try: ss.del_worksheet(ss.worksheet(SHEET_INTG))
except: pass
ws_intg = ss.add_worksheet(title=SHEET_INTG, rows=len(df_intg)+5, cols=12)
h_intg  = list(df_intg.columns)
ws_intg.update('A1', [h_intg] + [safe_list([r[c] for c in h_intg])
                                   for _, r in df_intg.iterrows()])
print(f"✅ 統合スコア保存: '{SHEET_INTG}'（{len(df_intg)}銘柄）")
print(f"  統合スコア上位5：")
for _, r in df_intg.head(5).iterrows():
    print(f"    {r['銘柄名']}：{r['統合スコア']}点（長期{r['長期ランク']}・短期{short_score}・中期{medium_score}）")

# ============================================================
# Part5: 週次シグナル記録（蓄積）
# ============================================================
print(f"\n{'='*60}")
print("Part5: 週次シグナル記録")
print('='*60)

try:
    ws_sig  = ss.worksheet('週次シグナル')
    sig_row = [NOW, short_score, sig_s(short_score),
               medium_score, sig_m(medium_score),
               sox_ret, sp5_ret, hyg_ret, vix_ret,
               m2jp_accel, gdp_accel, wti_accel]
    last    = len(ws_sig.get_all_values()) + 1
    ws_sig.update(f'A{last}', [safe_list(sig_row)])
    print(f"✅ 週次シグナル記録：行{last}")
except Exception as e:
    print(f"⚠️ 週次シグナル記録失敗: {e}")

# ============================================================
# Part6: 作業ログ記録
# ============================================================
try:
    wl   = ss.worksheet('作業ログ')
    last = len(wl.get_all_values()) + 1
    wl.update(f'A{last}', [[NOW, 'weekly_update v4.0',
                             f'v4.3スキャン56銘柄・短期{short_score}点・中期{medium_score}点',
                             'J-Quants V2（10年分）', '✅完了']])
    print(f"\n✅ 作業ログ記録完了")
except: pass

# ============================================================
# 最終サマリー
# ============================================================
print(f"\n{'='*60}")
print(f"weekly_update v4.0 完了サマリー")
print(f"{'='*60}")
print(f"  データソース: J-Quants V2 fins/summary（{DATA_YEARS}年分）")
print(f"  短期スコア: {short_score}点 {sig_s(short_score)}")
print(f"  中期スコア: {medium_score}点 {sig_m(medium_score)}")
for rk in ['S','A','B','C','D']:
    n = len(df_scan[df_scan['ランク']==rk])
    print(f"  {rk}ランク: {n}銘柄", end='')
print(f"\n✅ 全処理完了: {NOW}")

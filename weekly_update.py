# ============================================================
# weekly_update.py v4.2
# AI投資判断システム 週次自動更新
#
# v4.1からの変更点：
# ・Part6 追加：インデックス予測記録（Phase 2-D）
#   - 日経225・S&P500の短期/中期/長期予測を毎週自動記録
#   - 4週前予測の自動検証（騰落率・勝敗を自動入力）
#   - 新設シート「インデックス予測記録」に蓄積
#   - 10件蓄積後にウェイト自動調整開始（準備）
#
# 【三者会議修正点 2026/03/22】
# 修正① 長期予測はv21でバリュエーション取得先修正後に有効化
#        それまでは'データ未整備'でスキップ（誤CAPEで蓄積しない）
# 修正② 短期予測の備考列に'米国指標ベース'を明記
#        （SOX/SP500/HYG/VIXで日経を予測している旨を記録）
# 修正③ 勝敗判定で中立（△）を的中率分母から除外
#        check_weight_adjustment()で◎と$2715のみをカウント
#
# 【バグ修正 2026/03/24】失敗35
# Part3 中期スコアのシート名を実際の名前に修正
#   日本M2_月次  → 日本M2       （存在しなかった）
#   米GDP_月次   → 米設備稼働率  （存在しなかった・代替）
#   WTI原油_月次 → WTI原油      （存在しなかった）
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

# ── 認証 ──────────────────────────────────────────────────────
SPREADSHEET_ID = '1GtlVhGcPjMU0pJWsijwnmTe1rFJXAGvkaJFjav9gGcE'
JQUANTS_API_KEY = os.environ.get('JQUANTS_API_KEY', '')
FRED_API_KEY    = os.environ.get('FRED_API_KEY', '')
JQUANTS_HEADERS = {'x-api-key': JQUANTS_API_KEY}
JQUANTS_BASE    = 'https://api.jquants.com'
scope = ['https://spreadsheets.google.com/feeds',
         'https://www.googleapis.com/auth/drive']
creds_dict = json.loads(os.environ.get('GOOGLE_CREDENTIALS','{}'))
creds = Credentials.from_service_account_info(creds_dict, scopes=scope)
gc = gspread.authorize(creds)
ss = gc.open_by_key(SPREADSHEET_ID)
NOW   = datetime.now().strftime('%Y/%m/%d %H:%M')
TODAY = datetime.now()
DATA_YEARS = 10
CUTOFF = (TODAY - timedelta(days=365 * DATA_YEARS)).strftime('%Y-%m-%d')

# ── フラグ管理 ─────────────────────────────────────────────────
LONG_TERM_ENABLED = True

print(f"$2705 接続完了: {ss.title}")
print(f"実行日時: {NOW}")
print(f"データ期間: 過去{DATA_YEARS}年分（{CUTOFF[:7]}以降）")
print(f"長期予測: {'有効' if LONG_TERM_ENABLED else '$26A0$FE0F データ未整備（v21修正後に有効化）'}")

# ── 銘柄マスタ ─────────────────────────────────────────────────
STOCKS = [
    {'code':'1605','name':'INPEX',          'sector':'エネルギー'},
    {'code':'1847','name':'イチケン',         'sector':'建設'},
    {'code':'1879','name':'新日本建設',       'sector':'建設'},
    {'code':'1928','name':'積水ハウス',       'sector':'建設'},
    {'code':'1942','name':'関電工',           'sector':'建設'},
    {'code':'2768','name':'双日',             'sector':'商社'},
    {'code':'3496','name':'アズーム',         'sector':'サービス'},
    {'code':'4221','name':'大倉工業',         'sector':'化学'},
    {'code':'6098','name':'リクルートHD',     'sector':'サービス'},
    {'code':'6200','name':'インソース',       'sector':'サービス'},
    {'code':'6501','name':'日立',             'sector':'電機'},
    {'code':'6637','name':'寺崎電気産業',     'sector':'電機'},
    {'code':'7187','name':'ジェイリース',     'sector':'サービス'},
    {'code':'7741','name':'HOYA',             'sector':'精密機器'},
    {'code':'7974','name':'任天堂',           'sector':'その他製品'},
    {'code':'8058','name':'三菱商事',         'sector':'商社'},
    {'code':'8136','name':'サンリオ',         'sector':'その他製品'},
    {'code':'8331','name':'千葉銀行',         'sector':'銀行'},
    {'code':'8386','name':'百十四銀行',       'sector':'銀行'},
    {'code':'8541','name':'愛媛銀行',         'sector':'銀行'},
    {'code':'8935','name':'FJネクストHD',     'sector':'不動産'},
    {'code':'2003','name':'日東富士製粉',     'sector':'食品'},
    {'code':'2914','name':'JT',               'sector':'食品'},
    {'code':'4063','name':'信越化学',         'sector':'化学'},
    {'code':'5838','name':'楽天銀行',         'sector':'銀行'},
    {'code':'6920','name':'レーザーテック',   'sector':'半導体'},
    {'code':'8001','name':'伊藤忠',           'sector':'商社'},
    {'code':'8053','name':'住友商事',         'sector':'商社'},
    {'code':'8303','name':'SBI新生銀行',      'sector':'銀行'},
    {'code':'8306','name':'三菱UFJ',          'sector':'銀行'},
    {'code':'8316','name':'三井住友FG',       'sector':'銀行'},
    {'code':'8343','name':'秋田銀行',         'sector':'銀行'},
    {'code':'8410','name':'セブン銀行',       'sector':'銀行'},
    {'code':'8473','name':'SBIホールディングス','sector':'証券'},
    {'code':'8591','name':'オリックス',       'sector':'金融'},
    {'code':'8593','name':'三菱HCキャピタル', 'sector':'金融'},
    {'code':'8600','name':'トモニHD',         'sector':'銀行'},
    {'code':'8630','name':'SOMPO',            'sector':'保険'},
    {'code':'8771','name':'Eギャランティ',    'sector':'金融'},
    {'code':'9069','name':'センコーグループHD','sector':'輸送'},
    {'code':'9432','name':'NTT',              'sector':'通信'},
    {'code':'9433','name':'KDDI',             'sector':'通信'},
    {'code':'9434','name':'ソフトバンク',     'sector':'通信'},
    {'code':'4519','name':'中外製薬',         'sector':'医薬品'},
    {'code':'9983','name':'ファーストリテイリング','sector':'小売'},
    {'code':'4307','name':'野村総研',         'sector':'情報通信'},
    {'code':'6273','name':'SMC',              'sector':'機械'},
    {'code':'2802','name':'味の素',           'sector':'食品'},
    {'code':'4188','name':'三菱ケミカル',     'sector':'素材'},
    {'code':'7751','name':'キヤノン',         'sector':'精密機器'},
    {'code':'8035','name':'東京エレクトロン', 'sector':'半導体'},
    {'code':'3382','name':'セブン&アイHD',    'sector':'流通'},
    {'code':'9020','name':'JR東日本',         'sector':'陸運'},
    {'code':'6857','name':'アドバンテスト',   'sector':'半導体'},
    {'code':'6146','name':'ディスコ',         'sector':'半導体'},
    {'code':'3436','name':'SUMCO',            'sector':'素材'},
]

# ── ヘルパー関数 ───────────────────────────────────────────────
def safe(val, d=1):
    if val is None: return None
    try:
        f = float(val)
        return None if (np.isnan(f) or np.isinf(f)) else round(f, d)
    except: return None

def safe_list(lst):
    return ['' if (v is None or (isinstance(v, float) and
            (np.isnan(v) or np.isinf(v)))) else v for v in lst]

def thr_high(val, thresholds):
    if val is None or (isinstance(val, float) and
       (np.isnan(val) or np.isinf(val))): return 50
    for t, s in thresholds:
        if val >= t: return s
    return 10

def thr_low(val, thresholds):
    if val is None or (isinstance(val, float) and
       (np.isnan(val) or np.isinf(val))): return 50
    for t, s in thresholds:
        if val <= t: return s
    return 10

def slope_fn(series):
    v = pd.Series(series).replace([np.inf, -np.inf], np.nan).dropna().values
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

def get_current_price(ticker):
    try:
        hist = yf.download(ticker,
                           start=(TODAY - timedelta(days=10)).strftime('%Y-%m-%d'),
                           end=TODAY.strftime('%Y-%m-%d'),
                           interval='1d', progress=False, auto_adjust=True)
        if hist is None or len(hist) == 0: return None
        close = hist['Close']
        if isinstance(close, pd.DataFrame): close = close.iloc[:,0]
        val = close.dropna()
        return float(val.iloc[-1]) if len(val) > 0 else None
    except: return None

# ── J-Quants V2 データ取得関数 ────────────────────────────────
def get_price_jq(code):
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
                    price      = d.get('AdjC') or d.get('C')
                    shares     = get_shares_jq(code5)
                    market_cap = float(price) * shares if price and shares else None
                    return {'price': price, 'market_cap': market_cap, 'date': date_str}
        return {}
    except: return {}

def get_shares_jq(code5):
    try:
        r = requests.get(f"{JQUANTS_BASE}/v2/equities/master",
                         headers=JQUANTS_HEADERS,
                         params={"code": code5}, timeout=10)
        if r.status_code == 200:
            data = r.json().get('data', [])
            if data:
                shares = data[0].get('TotalMarketValue')
                if shares: return float(shares)
        return None
    except: return None

def get_fin_jq(code):
    try:
        code5 = code + '0' if len(code) == 4 else code
        r = requests.get(f"{JQUANTS_BASE}/v2/fins/summary",
                         headers=JQUANTS_HEADERS,
                         params={"code": code5}, timeout=15)
        if r.status_code != 200: return None, {}
        data = r.json().get('data', [])
        if not data: return None, {}
        df = pd.DataFrame(data)
        if 'CurPerEn' in df.columns:
            df['CurPerEn'] = pd.to_datetime(df['CurPerEn'], errors='coerce')
            df = df[df['CurPerEn'] >= pd.Timestamp(CUTOFF)].copy()
            df = df.sort_values('CurPerEn').reset_index(drop=True)
        if len(df) < 2: return None, {}
        if 'DocType' in df.columns:
            annual = df[
                df['DocType'].str.contains('FinancialStatements', na=False) &
                ~df['DocType'].str.contains('2Q|3Q|1Q|HalfYear|Quarter', na=False)
            ].copy()
            if len(annual) >= 2: df = annual
        for col in ['Sales','OP','NP','EPS','DEPS','TA','Eq','EqAR',
                    'CFO','CFI','FEPS','FOP','FNP','ShOutFY']:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors='coerce')
        if 'NP' in df.columns and 'Eq' in df.columns:
            df['ROE'] = df['NP'] / df['Eq'].replace(0, np.nan) * 100
        if 'CFO' in df.columns and 'CFI' in df.columns:
            df['FCF'] = df['CFO'] + df['CFI']
        if 'FCF' in df.columns and 'NP' in df.columns:
            df['FCR'] = df['FCF'] / df['NP'].replace(0, np.nan) * 100
        price_info = get_price_jq(code)
        if 'ShOutFY' in df.columns:
            shares_latest = df['ShOutFY'].dropna()
            if len(shares_latest) > 0:
                price_info['shares'] = float(shares_latest.iloc[-1])
                # market_capをShOutFY（正確な発行済み株数）で再計算
                if price_info.get('price'):
                    price_info['market_cap'] = float(price_info['price']) * float(shares_latest.iloc[-1])
        return df.replace([np.inf, -np.inf], np.nan).dropna(how='all'), price_info
    except: return None, {}

# ── v4.3スコア計算 ────────────────────────────────────────────
ROE_THR = [(25,100),(20,85),(15,70),(12,58),(10,46),(8,35),(5,20),(0,8)]
FCR_THR = [(120,100),(100,90),(80,78),(60,62),(40,44),(20,26),(0,10)]
RS_THR  = [(4.0,100),(2.0,82),(0.5,64),(-0.5,46),(-2.0,28),(-999,12)]
FS_THR  = [(8.0,100),(4.0,80),(0.0,60),(-4.0,40),(-8.0,20),(-999,8)]
PEG_THR = [(0.5,100),(0.8,85),(1.0,72),(1.2,58),(1.5,42),(2.0,26),(999,12)]
FCY_THR = [(8,100),(6,85),(4,70),(3,55),(2,38),(1,22),(0,8)]

def calc_v43_score(df, price_info):
    if df is None or len(df) < 2: return 0, 'D', {}
    roe_s = df['ROE'].dropna() if 'ROE' in df.columns else pd.Series()
    fcr_s = df['FCR'].dropna() if 'FCR' in df.columns else pd.Series()
    roe_mean  = safe(roe_s.mean()) if len(roe_s) > 0 else None
    fcr_clean = fcr_s[(fcr_s >= -300) & (fcr_s <= 300)] if len(fcr_s) > 0 else pd.Series()
    fcr_mean  = safe(fcr_clean.mean()) if len(fcr_clean) > 0 else None
    s1 = round(thr_high(roe_mean, ROE_THR) * 0.60 +
               (thr_high(fcr_mean, FCR_THR) if fcr_mean is not None else 30) * 0.40)
    roe_trend = slope_fn(roe_s.tail(8))    if len(roe_s)    >= 3 else 0
    fcr_trend = slope_fn(fcr_clean.tail(8)) if len(fcr_clean) >= 3 else 0
    s2 = round(thr_high(roe_trend, RS_THR) * 0.60 +
               thr_high(fcr_trend, FS_THR) * 0.40)
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
    fy = None
    if 'FCF' in df.columns:
        fcf_l = df['FCF'].dropna()
        if len(fcf_l) > 0:
            fcf_v      = float(fcf_l.iloc[-1])
            market_cap = price_info.get('market_cap')
            if market_cap and market_cap > 0:
                fy = fcf_v / market_cap * 100
            elif 'TA' in df.columns:
                ta_l = df['TA'].dropna()
                if len(ta_l) > 0:
                    fy = fcf_v / float(ta_l.iloc[-1]) * 100
    s3    = round(thr_high(peg, PEG_THR) * 0.50 + thr_high(fy, FCY_THR) * 0.50)
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
# Part1: v4.3 アルティメットコアスキャン
# ============================================================
print(f"\n{'='*60}")
print("Part1: v4.3 コアスキャン（J-Quants V2・10年分）")
print('='*60)
scan_results = []
for s in STOCKS:
    code, name, sector = s['code'], s['name'], s['sector']
    print(f"  {code} {name} ... ", end='', flush=True)
    df_fin, price_info = get_fin_jq(code)
    time.sleep(0.35)
    tot, rnk, ev = calc_v43_score(df_fin, price_info)
    scan_results.append({
        'コード': code, '銘柄名': name, '業種': sector,
        '総合スコア': tot, 'ランク': rnk,
        'ROE平均': ev.get('roe'), 'FCR平均': ev.get('fcr'),
        'ROEトレンド': ev.get('roe_slope'), 'PEG': ev.get('peg'),
        'FCF利回り': ev.get('fcf_yield'),
        '変数1': ev.get('s1'), '変数2': ev.get('s2'), '変数3': ev.get('s3'),
        '株価': ev.get('price'), '時価総額': ev.get('market_cap'),
        'データ期数': ev.get('data_years'), '算出日時': NOW,
    })
    print(f"{tot}点({rnk}) [{ev.get('data_years','?')}期]")

df_scan = pd.DataFrame(scan_results).sort_values(
    '総合スコア', ascending=False).reset_index(drop=True)
SHEET_SCAN = 'コアスキャン_v4.3'
try: ss.del_worksheet(ss.worksheet(SHEET_SCAN))
except: pass
ws_scan    = ss.add_worksheet(title=SHEET_SCAN, rows=len(df_scan)+5, cols=18)
h_scan     = list(df_scan.columns)
rows_scan  = [h_scan] + [safe_list([r[c] for c in h_scan])
                          for _, r in df_scan.iterrows()]
ws_scan.update('A1', rows_scan)
print(f"\n$2705 コアスキャン保存: '{SHEET_SCAN}'（{len(df_scan)}銘柄）")
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
vix_s = thr_low( vix_ret, VIX_THR)
short_score = round(sox_s*0.30 + sp5_s*0.25 + hyg_s*0.25 + vix_s*0.20)

def sig_s(s):
    return ('強気↑↑' if s>=70 else 'やや強気↑' if s>=55 else
            '中立→'  if s>=45 else 'やや弱気↓' if s>=30 else '弱気↓↓')

fmt_r = lambda v: f"{v:+.2%}" if v is not None else "取得失敗"
print(f"  SOX:{fmt_r(sox_ret)}→{sox_s}pt / SP500:{fmt_r(sp5_ret)}→{sp5_s}pt")
print(f"  HYG:{fmt_r(hyg_ret)}→{hyg_s}pt / VIX:{fmt_r(vix_ret)}→{vix_s}pt")
print(f"  短期スコア: {short_score}点 {sig_s(short_score)}")

# ============================================================
# Part3: 中期スコア計算
# ============================================================
print(f"\n{'='*60}")
print("Part3: 中期スコア計算（日本M2加速度ラグ15M）")
print(f"  ※ 2026/03/24 バグ修正済み（失敗35）")
print(f"  シート名を実際の名前に修正")
print('='*60)

M2JP_ACCEL_THR = [( 0.005,100),( 0.002,80),(0.0,60),(-0.002,40),(-0.005,20),(-999,8)]
CAP_ACCEL_THR  = [( 0.5,100), ( 0.2,80), (0.0,60),(-0.2, 40), (-0.5, 20), (-999,8)]
WTI_ACCEL_THR  = [(-0.05,100),(-0.02,80),(0.0,60),( 0.02,40), ( 0.05,20), (999, 8)]

# $2705 バグ修正（2026/03/24）: 実際のシート名に修正
m2jp_accel = get_ss_accel('日本M2',      lag_months=15)  # 修正: 日本M2_月次→日本M2
gdp_accel  = get_ss_accel('米設備稼働率', lag_months=12)  # 修正: 米GDP_月次→米設備稼働率（代替）
wti_accel  = get_ss_accel('WTI原油',     lag_months=10)  # 修正: WTI原油_月次→WTI原油

m2jp_s = thr_high(m2jp_accel, M2JP_ACCEL_THR)
gdp_s  = thr_high(gdp_accel,  CAP_ACCEL_THR)
wti_s  = thr_low( wti_accel,  WTI_ACCEL_THR)
medium_score = round(m2jp_s*0.50 + gdp_s*0.30 + wti_s*0.20)

def sig_m(s):
    return ('強気↑↑' if s>=70 else 'やや強気↑' if s>=55 else
            '中立→'  if s>=45 else 'やや弱気↓' if s>=30 else '弱気↓↓')

print(f"  日本M2加速(15Mラグ):  {m2jp_accel}→{m2jp_s}pt  $2705シート:'日本M2'")
print(f"  米設備稼働率加速(12M): {gdp_accel}→{gdp_s}pt   $2705シート:'米設備稼働率'")
print(f"  WTI加速(10Mラグ):     {wti_accel}→{wti_s}pt   $2705シート:'WTI原油'")
print(f"  中期スコア: {medium_score}点 {sig_m(medium_score)}")

# ============================================================
# Part4: 統合スコア
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
        '統合スコア': intg, '長期スコア(v4.3)': long_s,
        '長期ランク': r['ランク'],
        '短期スコア': short_score, '中期スコア': medium_score,
        '株価': r.get('株価'), '算出日時': NOW,
    })
df_intg = pd.DataFrame(integration_results).sort_values(
    '統合スコア', ascending=False).reset_index(drop=True)
SHEET_INTG = '統合スコア_週次'
try: ss.del_worksheet(ss.worksheet(SHEET_INTG))
except: pass
ws_intg  = ss.add_worksheet(title=SHEET_INTG, rows=len(df_intg)+5, cols=12)
h_intg   = list(df_intg.columns)
ws_intg.update('A1', [h_intg] + [safe_list([r[c] for c in h_intg])
                                   for _, r in df_intg.iterrows()])
print(f"$2705 統合スコア保存: '{SHEET_INTG}'（{len(df_intg)}銘柄）")
print(f"  統合スコア上位5：")
for _, r in df_intg.head(5).iterrows():
    print(f"  {r['銘柄名']}：{r['統合スコア']}点")

# ============================================================
# Part5: 週次シグナル記録
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
    last = len(ws_sig.get_all_values()) + 1
    ws_sig.update(f'A{last}', [safe_list(sig_row)])
    print(f"$2705 週次シグナル記録：行{last}")
except Exception as e:
    print(f"$26A0$FE0F 週次シグナル記録失敗: {e}")

# ============================================================
# Part5.5: 週次因子劣化チェック
# ============================================================
print(f"\n{'='*60}")
print("Part5.5: 週次因子劣化チェック")
print('='*60)
try:
    ws_sig_data = ws_sig.get_all_values()
    if len(ws_sig_data) >= 5:
        recent         = ws_sig_data[-5:]
        short_history  = []
        medium_history = []
        for row in recent:
            try: short_history.append(float(row[1]))
            except: pass
        for row in recent:
            try: medium_history.append(float(row[3]))
            except: pass
        decay_alerts = []
        if len(short_history) >= 3:
            if short_history[-1] < short_history[-2] < short_history[-3]:
                decay_alerts.append(
                    f"短期スコア3週連続低下："
                    f"{short_history[-3]:.0f}→{short_history[-2]:.0f}→{short_history[-1]:.0f}点")
        if len(short_history) >= 4:
            drop = short_history[-1] - short_history[-4]
            if drop <= -20:
                decay_alerts.append(
                    f"短期スコア急落（4週比）："
                    f"{short_history[-4]:.0f}→{short_history[-1]:.0f}点（{drop:+.0f}）")
        if len(medium_history) >= 3:
            if medium_history[-1] < medium_history[-2] < medium_history[-3]:
                decay_alerts.append(
                    f"中期スコア3週連続低下："
                    f"{medium_history[-3]:.0f}→{medium_history[-2]:.0f}→{medium_history[-1]:.0f}点")
        if short_score < 30 and medium_score < 30:
            decay_alerts.append(
                f"ダブル弱気警報：短期{short_score}点・中期{medium_score}点 → 現金比率引き上げ推奨")
        try:
            vix_this = float(recent[-1][7]) if len(recent[-1]) > 7 else None
            if vix_this and vix_this > 0.15:
                decay_alerts.append(f"VIX急騰：{vix_this*100:+.1f}%（恐怖指数上昇中）")
        except: pass
        if decay_alerts:
            print(f"  $26A0$FE0F 因子劣化アラート {len(decay_alerts)}件：")
            for a in decay_alerts: print(f"  $26A0$FE0F {a}")
        else:
            print(f"  $2705 因子劣化なし（直近5週正常範囲内）")
        SHEET_DECAY = '因子劣化チェック'
        try:
            ws_decay = ss.worksheet(SHEET_DECAY)
        except:
            ws_decay = ss.add_worksheet(title=SHEET_DECAY, rows=500, cols=6)
            ws_decay.update('A1', [['実行日時','短期スコア','中期スコア',
                                    'アラート件数','アラート内容','判定']])
        alert_text = ' / '.join(decay_alerts) if decay_alerts else 'なし'
        judgment   = ('要注意' if len(decay_alerts) >= 2 else
                      '注意'   if decay_alerts else '$2705正常')
        last_decay = len(ws_decay.get_all_values()) + 1
        ws_decay.update(f'A{last_decay}', [[
            NOW, short_score, medium_score,
            len(decay_alerts), alert_text, judgment
        ]])
        print(f"  $2705 因子劣化チェック記録：行{last_decay}（判定：{judgment}）")
    else:
        print(f"  $2139$FE0F 週次シグナル蓄積不足（{len(ws_sig_data)-1}週分）。5週分以上で劣化チェック開始。")
except Exception as e:
    print(f"$26A0$FE0F 因子劣化チェック失敗: {e}")

# ============================================================
# Part6: インデックス予測記録（v4.2新規追加 Phase 2-D）
# ============================================================
print(f"\n{'='*60}")
print("Part6: インデックス予測記録（Phase 2-D）")
print('='*60)
INDEX_SHEET  = 'インデックス予測記録'
INDEX_HEADER = [
    '記録日時','日経_短期予測方向','日経_中期予測方向','日経_長期予測方向',
    '日経_5年期待リターン%','SP500_短期予測方向','SP500_中期予測方向',
    'SP500_長期予測方向','SP500_5年期待リターン%','短期スコア','中期スコア',
    'シラーPER_JP','シラーPER_US','日経_記録時水準','SP500_記録時水準',
    '日経_4週後実績騰落率%','SP500_4週後実績騰落率%',
    '短期予測勝敗_日経','短期予測勝敗_SP500','備考',
]

def ensure_index_sheet():
    try: return ss.worksheet(INDEX_SHEET)
    except:
        ws = ss.add_worksheet(title=INDEX_SHEET,
                              rows=500, cols=len(INDEX_HEADER)+2)
        ws.update('A1', [INDEX_HEADER])
        print(f"  $2705 新設シート作成: '{INDEX_SHEET}'")
        return ws

def score_to_dir(score, thresholds=(70, 55, 45, 30)):
    if score >= thresholds[0]: return '強気↑↑'
    if score >= thresholds[1]: return 'やや強気↑'
    if score >= thresholds[2]: return '中立→'
    if score >= thresholds[3]: return 'やや弱気↓'
    return '弱気↓↓'

def cape_to_direction(cape):
    if cape is None or cape <= 0: return 'データ未整備', None
    ret_annual = round(1 / cape * 100 + 2.0, 2)
    if   ret_annual >= 8: label = f'買い好機↑↑({ret_annual}%/年)'
    elif ret_annual >= 5: label = f'平均的→({ret_annual}%/年)'
    elif ret_annual >= 3: label = f'やや割高↓({ret_annual}%/年)'
    else:                 label = f'割高警戒↓↓({ret_annual}%/年)'
    return label, ret_annual

def auto_verify_4weeks_ago(ws_idx, nikkei_now, sp500_now):
    if nikkei_now is None and sp500_now is None:
        print(f"  $26A0$FE0F 指数水準が取得できなかったため4週前検証をスキップ")
        return
    try:
        all_rows     = ws_idx.get_all_values()
        if len(all_rows) < 2: return
        target_date  = TODAY - timedelta(days=28)
        verified_count = 0
        for i, row in enumerate(all_rows[1:], start=2):
            if len(row) < 15: continue
            if len(row) > 15 and row[15] != '': continue
            try: rec_date = datetime.strptime(row[0][:10], '%Y/%m/%d')
            except: continue
            if abs((rec_date - target_date).days) > 3: continue
            try:
                nikkei_rec = float(row[13]) if len(row) > 13 and row[13] else None
                sp500_rec  = float(row[14]) if len(row) > 14 and row[14] else None
            except: continue
            if nikkei_rec and nikkei_rec > 0 and nikkei_now:
                nikkei_ret = round((nikkei_now / nikkei_rec - 1) * 100, 2)
                pred = row[1]
                if '強気' in pred or ('↑' in pred and '中立' not in pred):
                    win_nikkei = '◎' if nikkei_ret > 0 else '$2715'
                elif '弱気' in pred or ('↓' in pred and '中立' not in pred):
                    win_nikkei = '◎' if nikkei_ret < 0 else '$2715'
                else: win_nikkei = '判定対象外'
            else:
                nikkei_ret = ''
                win_nikkei = ''
            if sp500_rec and sp500_rec > 0 and sp500_now:
                sp500_ret = round((sp500_now / sp500_rec - 1) * 100, 2)
                pred = row[5]
                if '強気' in pred or ('↑' in pred and '中立' not in pred):
                    win_sp500 = '◎' if sp500_ret > 0 else '$2715'
                elif '弱気' in pred or ('↓' in pred and '中立' not in pred):
                    win_sp500 = '◎' if sp500_ret < 0 else '$2715'
                else: win_sp500 = '判定対象外'
            else:
                sp500_ret = ''
                win_sp500 = ''
            ws_idx.update(f'P{i}', [[nikkei_ret, sp500_ret, win_nikkei, win_sp500]])
            print(f"  $2705 4週前予測を自動検証（行{i}）："
                  f"日経{nikkei_ret}%/{win_nikkei} SP500{sp500_ret}%/{win_sp500}")
            verified_count += 1
        if verified_count == 0:
            print(f"  $2139$FE0F 4週前に検証対象の未検証行なし（正常）")
    except Exception as e:
        print(f"  $26A0$FE0F 4週前自動検証失敗: {e}")

def check_weight_adjustment(ws_idx):
    try:
        all_rows     = ws_idx.get_all_values()
        if len(all_rows) < 2: return
        judged_rows  = [r for r in all_rows[1:] if len(r) > 17 and r[17] in ('◎','$2715')]
        neutral_rows = [r for r in all_rows[1:] if len(r) > 17 and r[17] == '判定対象外']
        n = len(judged_rows)
        if n < 10:
            print(f"  $2139$FE0F 判定対象{n}件（10件でウェイト自動調整開始）"
                  f" ※中立除外:{len(neutral_rows)}件")
            return
        wins = sum(1 for r in judged_rows if r[17] == '◎')
        rate = round(wins / n * 100, 1)
        print(f"  $D83D$DCCA 日経短期予測的中率（中立除外）：{rate}%（{wins}/{n}件）"
              f" ※中立除外:{len(neutral_rows)}件")
        if   rate >= 70: print(f"  $2705 的中率70%超 → ウェイト据え置き")
        elif rate >= 60: print(f"  $26A0$FE0F 的中率60-70% → 継続観察（修正検討）")
        else:            print(f"  $D83D$DD34 的中率60%未満 → ウェイト見直し推奨")
    except Exception as e:
        print(f"  $26A0$FE0F 的中率チェック失敗: {e}")

try:
    ws_idx     = ensure_index_sheet()
    print(f"  指数水準を取得中...")
    nikkei_now = get_current_price('^N225')
    sp500_now  = get_current_price('^GSPC')
    time.sleep(0.5)
    print(f"  日経225: {nikkei_now:.0f}円"    if nikkei_now else "  日経225: 取得失敗")
    print(f"  S&P500:  {sp500_now:.2f}ドル"   if sp500_now  else "  S&P500:  取得失敗")
    dir_nikkei_short = score_to_dir(short_score)
    dir_sp500_short  = score_to_dir(short_score)
    dir_nikkei_mid   = score_to_dir(medium_score, thresholds=(65, 52, 45, 32))
    dir_sp500_mid    = score_to_dir(medium_score, thresholds=(65, 52, 45, 32))
    if LONG_TERM_ENABLED:
        cape_jp, cape_us   = None, None
        dir_nikkei_long, ret_jp = cape_to_direction(cape_jp)
        dir_sp500_long, ret_us  = cape_to_direction(cape_us)
    else:
        dir_nikkei_long = dir_sp500_long = 'データ未整備'
        ret_jp = ret_us = cape_jp = cape_us = None
    note = ('v4.2自動記録 / '
            '短期=米国指標ベース(SOX×30+SP500×25+HYG×25+VIX×20) / '
            '中期=日本M2・米設備稼働率・WTI原油（2026/03/24バグ修正済）')
    new_row  = safe_list([
        NOW, dir_nikkei_short, dir_nikkei_mid, dir_nikkei_long, ret_jp,
        dir_sp500_short, dir_sp500_mid, dir_sp500_long, ret_us,
        short_score, medium_score, cape_jp, cape_us,
        round(nikkei_now, 0) if nikkei_now else '',
        round(sp500_now,  2) if sp500_now  else '',
        '', '', '', '', note,
    ])
    last_row = len(ws_idx.get_all_values()) + 1
    ws_idx.update(f'A{last_row}', [new_row])
    print(f"\n  $2705 インデックス予測記録：行{last_row}")
    print(f"  日経  → 短期:{dir_nikkei_short} / 中期:{dir_nikkei_mid} / 長期:{dir_nikkei_long}")
    print(f"  SP500 → 短期:{dir_sp500_short}  / 中期:{dir_sp500_mid}  / 長期:{dir_sp500_long}")
    print(f"\n  4週前予測の自動検証...")
    auto_verify_4weeks_ago(ws_idx, nikkei_now, sp500_now)
    print(f"\n  的中率チェック（中立除外）...")
    check_weight_adjustment(ws_idx)
except Exception as e:
    print(f"$26A0$FE0F Part6 インデックス予測記録失敗: {e}")
    import traceback; traceback.print_exc()

# ============================================================
# v4.3スコアを保有/監視シートに書き戻し
# ============================================================
print(f"\n{'='*60}")
print("v4.3スコアを保有/監視シートに書き戻し")
print('='*60)

# コアスキャン結果をコード→データのdictに変換
scan_map = {}
for _, r in df_scan.iterrows():
    scan_map[str(r['コード'])] = r

SYNC_SHEETS = ['保有銘柄_v4.3スコア', '監視銘柄_v4.3スコア']
SYNC_COLS   = ['総合スコア', 'ランク', '変数1', '変数2', '変数3',
               'ROE平均', 'FCR平均', 'ROEトレンド', 'PEG', 'FCF利回り', '株価']
RANK_ORDER  = {'S': 5, 'A': 4, 'B': 3, 'C': 2, 'D': 1}

for sheet_name in SYNC_SHEETS:
    try:
        ws = ss.worksheet(sheet_name)
        all_vals = ws.get_all_values()
        if len(all_vals) < 2:
            print(f"  {sheet_name}: データなし（スキップ）")
            continue

        header = all_vals[0]
        col_idx = {}
        for col_name in ['コード', '前回ランク'] + SYNC_COLS:
            if col_name in header:
                col_idx[col_name] = header.index(col_name)

        if 'コード' not in col_idx:
            print(f"  {sheet_name}: コード列なし（スキップ）")
            continue

        # 前回ランク列がなければ追加
        if '前回ランク' not in col_idx:
            new_col = len(header) + 1
            ws.update_cell(1, new_col, '前回ランク')
            col_idx['前回ランク'] = new_col - 1
            print(f"  {sheet_name}: 前回ランク列を追加（列{new_col}）")

        updates = 0
        degrades = 0
        batch_updates = []

        for row_num in range(1, len(all_vals)):
            row = all_vals[row_num]
            code = str(row[col_idx['コード']]).strip()
            if code not in scan_map:
                continue

            # 現在のランクを前回ランクとして保存
            if 'ランク' in col_idx:
                current_rank = str(row[col_idx['ランク']]).strip()
                if current_rank in RANK_ORDER:
                    prev_ci = col_idx['前回ランク']
                    cell_label = gspread.utils.rowcol_to_a1(row_num + 1, prev_ci + 1)
                    batch_updates.append({
                        'range': cell_label,
                        'values': [[current_rank]]
                    })

            # 新しいスコア・ランクを書き込み
            sr = scan_map[code]
            new_rank = str(sr.get('ランク', 'D'))
            for col_name in SYNC_COLS:
                if col_name not in col_idx:
                    continue
                ci = col_idx[col_name]
                new_val = sr.get(col_name)
                if new_val is not None and str(new_val) not in ('', 'nan', 'None'):
                    cell_label = gspread.utils.rowcol_to_a1(row_num + 1, ci + 1)
                    batch_updates.append({
                        'range': cell_label,
                        'values': [[float(new_val) if isinstance(new_val, (int, float, np.integer, np.floating)) else str(new_val)]]
                    })

            # ランク変動検知
            if current_rank in RANK_ORDER and new_rank in RANK_ORDER:
                if RANK_ORDER[new_rank] < RANK_ORDER[current_rank]:
                    name = str(row[1]).strip() if len(row) > 1 else code
                    print(f"    DEGRADE: {code} {name} {current_rank}->{new_rank}")
                    degrades += 1

            updates += 1

        if batch_updates:
            ws.batch_update(batch_updates)
            print(f"  {sheet_name}: {updates}銘柄を更新（{len(batch_updates)}セル）")
            if degrades > 0:
                print(f"  WARNING: {degrades}銘柄がランク下落")
        else:
            print(f"  {sheet_name}: 更新対象なし")

    except Exception as e:
        print(f"  {sheet_name}: エラー {e}")

print(f"$2705 保有/監視シート書き戻し完了")

# ============================================================
# 作業ログ記録
# ============================================================
try:
    wl   = ss.worksheet('作業ログ')
    last = len(wl.get_all_values()) + 1
    wl.update(f'A{last}', [[
        NOW, 'weekly_update v4.2（バグ修正済）',
        f'v4.3スキャン{len(df_scan)}銘柄・短期{short_score}点・中期{medium_score}点・'
        f'因子劣化チェック・インデックス予測記録・'
        f'保有/監視シート書き戻し済',
        'J-Quants V2（10年分）', '$2705完了'
    ]])
    print(f"\n$2705 作業ログ記録完了")
except: pass

# ============================================================
# 最終サマリー
# ============================================================
print(f"\n{'='*60}")
print(f"weekly_update v4.2（バグ修正済） 完了サマリー")
print(f"{'='*60}")
print(f"  データソース: J-Quants V2 fins/summary（{DATA_YEARS}年分）")
print(f"  短期スコア: {short_score}点 {sig_s(short_score)}")
print(f"  中期スコア: {medium_score}点 {sig_m(medium_score)}")
for rk in ['S','A','B','C','D']:
    n = len(df_scan[df_scan['ランク']==rk])
    if n > 0: print(f"  {rk}ランク: {n}銘柄", end=' ')
print(f"\n  [バグ修正] Part3シート名修正（失敗35・2026/03/24）")
print(f"    日本M2_月次→日本M2 / WTI原油_月次→WTI原油 / 米GDP_月次→米設備稼働率")
print(f"$2705 全処理完了: {NOW}")

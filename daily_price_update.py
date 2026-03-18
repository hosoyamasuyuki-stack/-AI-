# ============================================================
# daily_price_update.py
# 変数3（価格）を毎日更新する日次スクリプト
#
# 【設計思想】
# 変数1（Real ROIC）→ 財務データ → 四半期に1回しか変わらない → 週次
# 変数2（トレンド）  → 財務データ → 四半期に1回しか変わらない → 週次
# 変数3（価格）     → 株価データ → 毎日変わる              → 日次 ← ここ
#
# 【暴落検知】
# 前日比 ±5% 以上の変動を検知して「割安度変化アラート」を記録
#
# 【FCF利回り】
# 時価総額ベース（株価×発行済み株数）で計算 ← 株価連動
# 株価10%下落 → 時価総額10%低下 → FCF利回り11%上昇 → 変数3スコア上昇
#
# 【実行タイミング】毎日 7:30 JST（GitHub Actions）
# ============================================================

import os, json, requests, time, warnings
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
creds_dict = json.loads(os.environ.get('GOOGLE_CREDENTIALS', '{}'))
creds      = Credentials.from_service_account_info(creds_dict, scopes=scope)
gc         = gspread.authorize(creds)
ss         = gc.open_by_key(SPREADSHEET_ID)

NOW   = datetime.now().strftime('%Y/%m/%d %H:%M')
TODAY = datetime.now()

print(f"✅ 接続完了: {ss.title}")
print(f"実行日時: {NOW}")
print(f"\n{'='*60}")
print("日次 変数3（価格）更新スクリプト")
print('='*60)

# ── 56銘柄マスタ（weekly_update_v4.pyと同一）────────────────
STOCKS = [
    {'code':'1605','name':'INPEX'},
    {'code':'1847','name':'イチケン'},
    {'code':'1879','name':'新日本建設'},
    {'code':'1928','name':'積水ハウス'},
    {'code':'1942','name':'関電工'},
    {'code':'2768','name':'双日'},
    {'code':'3496','name':'アズーム'},
    {'code':'4221','name':'大倉工業'},
    {'code':'6098','name':'リクルートHD'},
    {'code':'6200','name':'インソース'},
    {'code':'6501','name':'日立'},
    {'code':'6637','name':'寺崎電気産業'},
    {'code':'7187','name':'ジェイリース'},
    {'code':'7741','name':'HOYA'},
    {'code':'7974','name':'任天堂'},
    {'code':'8058','name':'三菱商事'},
    {'code':'8136','name':'サンリオ'},
    {'code':'8331','name':'千葉銀行'},
    {'code':'8386','name':'百十四銀行'},
    {'code':'8541','name':'愛媛銀行'},
    {'code':'8935','name':'FJネクストHD'},
    {'code':'2003','name':'日東富士製粉'},
    {'code':'2914','name':'JT'},
    {'code':'4063','name':'信越化学'},
    {'code':'5838','name':'楽天銀行'},
    {'code':'6920','name':'レーザーテック'},
    {'code':'8001','name':'伊藤忠'},
    {'code':'8053','name':'住友商事'},
    {'code':'8303','name':'SBI新生銀行'},
    {'code':'8306','name':'三菱UFJ'},
    {'code':'8316','name':'三井住友FG'},
    {'code':'8343','name':'秋田銀行'},
    {'code':'8410','name':'セブン銀行'},
    {'code':'8473','name':'SBIホールディングス'},
    {'code':'8591','name':'オリックス'},
    {'code':'8593','name':'三菱HCキャピタル'},
    {'code':'8600','name':'トモニHD'},
    {'code':'8630','name':'SOMPO'},
    {'code':'8771','name':'Eギャランティ'},
    {'code':'9069','name':'センコーグループHD'},
    {'code':'9432','name':'NTT'},
    {'code':'9433','name':'KDDI'},
    {'code':'9434','name':'ソフトバンク'},
    {'code':'4519','name':'中外製薬'},
    {'code':'9983','name':'ファーストリテイリング'},
    {'code':'4307','name':'野村総研'},
    {'code':'6273','name':'SMC'},
    {'code':'2802','name':'味の素'},
    {'code':'4188','name':'三菱ケミカル'},
    {'code':'7751','name':'キヤノン'},
    {'code':'8035','name':'東京エレクトロン'},
    {'code':'3382','name':'セブン&アイHD'},
    {'code':'9020','name':'JR東日本'},
    {'code':'6857','name':'アドバンテスト'},
    {'code':'6146','name':'ディスコ'},
    {'code':'3436','name':'SUMCO'},
]

# ── ヘルパー関数 ─────────────────────────────────────────────
def safe(val, d=1):
    if val is None: return None
    try:
        f = float(val)
        return None if (np.isnan(f) or np.isinf(f)) else round(f, d)
    except: return None

def thr_high(val, thresholds):
    if val is None or (isinstance(val,float) and
       (np.isnan(val) or np.isinf(val))): return 50
    for t, s in thresholds:
        if val >= t: return s
    return 10

PEG_THR = [(0.5,100),(0.8,85),(1.0,72),(1.2,58),(1.5,42),(2.0,26),(999,12)]
FCY_THR = [(8,100),(6,85),(4,70),(3,55),(2,38),(1,22),(0,8)]

# ── 株価取得（2営業日分：当日と前日）───────────────────────
def get_price_2days(code):
    """当日と前日の株価を取得（前日比計算用）"""
    code5   = code + '0' if len(code) == 4 else code
    prices  = {}
    for label, days_ago in [('today', 1), ('yesterday', 2)]:
        for d_offset in range(days_ago, days_ago + 5):
            date_str = (TODAY - timedelta(days=d_offset)).strftime('%Y-%m-%d')
            try:
                r = requests.get(
                    f"{JQUANTS_BASE}/v2/equities/bars/daily",
                    headers=JQUANTS_HEADERS,
                    params={"code": code5, "date": date_str},
                    timeout=10)
                if r.status_code == 200:
                    data = r.json().get('data', [])
                    if data:
                        d = data[0]
                        prices[label] = {
                            'price': d.get('AdjC') or d.get('C'),
                            'date':  date_str,
                            'volume': d.get('Vo'),
                        }
                        break
            except: pass
    return prices

def get_fin_summary_latest(code):
    """最新の財務サマリーから FCF・EPS・発行済み株数を取得"""
    try:
        code5 = code + '0' if len(code) == 4 else code
        r = requests.get(f"{JQUANTS_BASE}/v2/fins/summary",
                        headers=JQUANTS_HEADERS,
                        params={"code": code5}, timeout=15)
        if r.status_code != 200: return {}
        data = r.json().get('data', [])
        if not data: return {}
        df   = pd.DataFrame(data)
        # 数値変換
        for col in ['CFO','CFI','NP','EPS','FEPS','ShOutFY','TA']:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors='coerce')
        # 最新年次決算を取得
        if 'DocType' in df.columns:
            annual = df[
                df['DocType'].str.contains('FinancialStatements', na=False) &
                ~df['DocType'].str.contains('2Q|3Q|1Q|HalfYear|Quarter', na=False)
            ]
            if len(annual) > 0: df = annual
        latest = df.iloc[-1] if len(df) > 0 else pd.Series()
        # FCF計算
        fcf = None
        if 'CFO' in latest and 'CFI' in latest:
            cfo = safe(latest.get('CFO'))
            cfi = safe(latest.get('CFI'))
            if cfo is not None and cfi is not None:
                fcf = cfo + cfi
        return {
            'fcf':    fcf,
            'eps':    safe(latest.get('EPS')),
            'feps':   safe(latest.get('FEPS')),
            'shares': safe(latest.get('ShOutFY')),
            'ta':     safe(latest.get('TA')),
        }
    except: return {}

# ── 変数3（価格スコア）を計算 ────────────────────────────────
def calc_s3(price, fcf, shares, eps, feps, ta):
    """
    変数3（価格）の計算
    PEG：株価÷EPS ÷ EPS成長率
    FCF利回り：FCF ÷ 時価総額（株価×発行済み株数）← 時価総額ベース
    """
    # PEG計算
    peg = None
    if price and eps and eps > 0:
        per = float(price) / eps
        # FEPS成長率（来期予想EPS÷現在EPS - 1）
        if feps and feps > 0 and eps > 0:
            eg = feps / eps - 1
        else:
            eg = 0.05  # デフォルト5%成長を仮定
        if eg > 0.01:
            peg = per / (eg * 100)

    # FCF利回り（時価総額ベース）
    fy = None
    if fcf and shares and price and shares > 0:
        market_cap = float(price) * float(shares)
        if market_cap > 0:
            fy = abs(fcf) / market_cap * 100
    elif fcf and ta and ta > 0:
        # 時価総額が取れない場合は総資産で代替
        fy = abs(fcf) / float(ta) * 100

    s3 = round(thr_high(peg, PEG_THR) * 0.50 +
               thr_high(fy,  FCY_THR) * 0.50)
    return s3, peg, fy

# ── メイン処理 ───────────────────────────────────────────────
print(f"\n【56銘柄の変数3（価格）を日次更新】")
print(f"FCF利回りの計算：時価総額ベース（株価連動）")

# 既存のv4.3スコアシートを読み込む（変数1・2を再利用）
try:
    ws_v43 = ss.worksheet('コアスキャン_v4.3')
    df_v43 = pd.DataFrame(ws_v43.get_all_records())
    df_v43['コード'] = df_v43['コード'].astype(str)
    has_existing = True
    print(f"✅ 既存v4.3スコア読み込み：{len(df_v43)}銘柄")
except:
    has_existing = False
    print("⚠️ 既存v4.3スコアが見つかりません。変数1・2はデフォルト値を使用")

daily_results = []
alerts        = []  # 暴落・急騰アラート

for s in STOCKS:
    code, name = s['code'], s['name']
    print(f"  {code} {name} ... ", end='', flush=True)

    # 株価取得（当日・前日）
    prices = get_price_2days(code)
    time.sleep(0.25)

    # 財務データ取得
    fin = get_fin_summary_latest(code)
    time.sleep(0.25)

    price_today     = prices.get('today',{}).get('price')
    price_yesterday = prices.get('yesterday',{}).get('price')

    # 前日比計算
    change_pct = None
    if price_today and price_yesterday:
        try:
            change_pct = (float(price_today) - float(price_yesterday)) / float(price_yesterday) * 100
        except: pass

    # 変数3計算
    s3, peg, fy = calc_s3(
        price_today,
        fin.get('fcf'), fin.get('shares'),
        fin.get('eps'), fin.get('feps'), fin.get('ta')
    )

    # 既存の変数1・2を取得
    s1, s2, rank_prev, total_prev = 50, 50, 'C', 50.0
    if has_existing:
        row = df_v43[df_v43['コード'] == code]
        if len(row) > 0:
            s1         = int(row.iloc[0].get('変数1', 50) or 50)
            s2         = int(row.iloc[0].get('変数2', 50) or 50)
            rank_prev  = str(row.iloc[0].get('ランク', 'C'))
            total_prev = float(row.iloc[0].get('総合スコア', 50) or 50)

    # 統合スコア再計算
    total_new = round(s1 * 0.40 + s2 * 0.35 + s3 * 0.25, 1)
    rank_new  = ('S' if total_new >= 80 else 'A' if total_new >= 65 else
                 'B' if total_new >= 50 else 'C' if total_new >= 35 else 'D')
    score_diff = round(total_new - total_prev, 1)

    # 暴落・急騰検知（±5%以上）
    alert_msg = ''
    if change_pct is not None and abs(change_pct) >= 5.0:
        direction = '📈急騰' if change_pct > 0 else '📉急落'
        if change_pct < -5:
            # 暴落時：割安度が上がることを記録
            alert_msg = (f"{direction} {change_pct:+.1f}% | "
                        f"スコア変化：{total_prev}→{total_new}（{score_diff:+.1f}）| "
                        f"本質的価値は変化なし。割安度が増加。長期投資家には買い場の可能性。")
        else:
            alert_msg = (f"{direction} {change_pct:+.1f}% | "
                        f"スコア変化：{total_prev}→{total_new}（{score_diff:+.1f}）")
        alerts.append({'コード': code, '銘柄名': name,
                       '変化率': change_pct, 'メッセージ': alert_msg})

    status = f"{total_new}点({rank_new})"
    if change_pct is not None:
        status += f" [{change_pct:+.1f}%]"
    if alert_msg:
        status += " ⚠️"
    print(status)

    daily_results.append({
        'コード': code, '銘柄名': name,
        '総合スコア_日次': total_new, 'ランク': rank_new,
        'スコア変化': score_diff,
        '変数1(週次)': s1, '変数2(週次)': s2, '変数3(日次)': s3,
        '株価': price_today, '前日比(%)': safe(change_pct, 2),
        'PEG': safe(peg, 2), 'FCF利回り(時価総額)': safe(fy, 1),
        '更新日時': NOW,
    })

df_daily = pd.DataFrame(daily_results).sort_values(
    '総合スコア_日次', ascending=False).reset_index(drop=True)

# ── スプレッドシートに保存 ────────────────────────────────────
SHEET_DAILY = 'コアスキャン_日次'
try: ss.del_worksheet(ss.worksheet(SHEET_DAILY))
except: pass
ws_daily = ss.add_worksheet(title=SHEET_DAILY, rows=len(df_daily)+5, cols=16)
h_daily  = list(df_daily.columns)
rows_d   = [h_daily] + [
    ['' if (v is None or (isinstance(v,float) and np.isnan(v))) else v
     for v in r.values()]
    for _, r in df_daily.iterrows()
]
ws_daily.update('A1', rows_d)
print(f"\n✅ 日次スコア保存：'{SHEET_DAILY}'（{len(df_daily)}銘柄）")

# ── 暴落・急騰アラートの記録 ─────────────────────────────────
if alerts:
    print(f"\n⚠️  暴落・急騰アラート（{len(alerts)}件）")
    try:
        try:
            ws_alert = ss.worksheet('暴落急騰アラート')
        except:
            ws_alert = ss.add_worksheet(title='暴落急騰アラート',
                                        rows=200, cols=5)
            ws_alert.update('A1', [['日時','コード','銘柄名','変化率(%)','メッセージ']])
        last_row = len(ws_alert.get_all_values()) + 1
        for a in alerts:
            ws_alert.update(f'A{last_row}',
                [[NOW, a['コード'], a['銘柄名'],
                  f"{a['変化率']:+.1f}%", a['メッセージ']]])
            last_row += 1
            print(f"  {a['銘柄名']}：{a['メッセージ']}")
        print(f"✅ アラート記録完了")
    except Exception as e:
        print(f"⚠️ アラート記録エラー: {e}")
else:
    print(f"\n✅ 暴落・急騰なし（全銘柄±5%以内）")

# ── 作業ログ ─────────────────────────────────────────────────
try:
    wl   = ss.worksheet('作業ログ')
    last = len(wl.get_all_values()) + 1
    wl.update(f'A{last}', [[NOW, '日次価格更新',
                             f'変数3を最新株価で再計算・時価総額ベース',
                             f'アラート{len(alerts)}件', '✅完了']])
except: pass

# ── 最終サマリー ─────────────────────────────────────────────
print(f"\n{'='*60}")
print(f"日次変数3更新 完了サマリー")
print(f"{'='*60}")
print(f"  更新銘柄数：{len(df_daily)}銘柄")
print(f"  暴落急騰アラート：{len(alerts)}件")
print(f"  FCF利回り計算：時価総額ベース（株価連動）")
print(f"  暴落時動作：株価下落→PER低下→PEG低下→変数3上昇→スコア上昇→割安度増加")
print(f"\n✅ 全処理完了：{NOW}")

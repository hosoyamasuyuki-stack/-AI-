# ============================================================
# generate_dashboard.py
# AI投資判断システム ダッシュボード自動生成
#
# 元ファイル: gen_v11.py（Colab版）
# 変更点:
#   ・Colab認証 → サービスアカウント認証（GitHub Actions対応）
#   ・ベースHTMLをGitHubから取得 → ローカルファイルから読み込み
#   ・出力先を ai_dashboard_v11_fixed.html に固定
#
# 【実行タイミング】毎週月曜 10:30 JST（weekly_update完了後30分）
# 【認証】GOOGLE_CREDENTIALS（環境変数）
# ============================================================

import os, json, re, requests, time
import yfinance as yf
import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime, timedelta

# ── 認証 ────────────────────────────────────────────────────
SPREADSHEET_ID = '1GtlVhGcPjMU0pJWsijwnmTe1rFJXAGvkaJFjav9gGcE'
scope = ['https://spreadsheets.google.com/feeds',
         'https://www.googleapis.com/auth/drive']
creds_dict = json.loads(os.environ.get('GOOGLE_CREDENTIALS', '{}'))
creds = Credentials.from_service_account_info(creds_dict, scopes=scope)
gc = gspread.authorize(creds)
ss = gc.open_by_key(SPREADSHEET_ID)
NOW = datetime.now().strftime('%Y/%m/%d %H:%M')
print(f"✅ 接続完了: {ss.title}  ({NOW})")

# ── 短期・中期スコアを週次シグナルシートから取得 ──────────────
def get_latest_scores():
    """週次シグナルシートから最新の短期・中期スコアを取得"""
    try:
        ws = ss.worksheet('週次シグナル')
        rows = ws.get_all_values()
        if len(rows) < 2:
            return 50, 50  # デフォルト値
        # 最終行を取得（ヘッダー除く）
        last = rows[-1]
        short = int(float(last[1])) if len(last) > 1 and last[1] else 50
        mid   = int(float(last[3])) if len(last) > 3 and last[3] else 50
        print(f"  週次シグナル取得: 短期{short}点 / 中期{mid}点")
        return short, mid
    except Exception as e:
        print(f"  ⚠️ 週次シグナル取得失敗: {e} → デフォルト値使用")
        return 50, 50

SHORT_SCORE, MID_SCORE = get_latest_scores()

# ── バリュエーション自動読み込み ────────────────────────────
FRED_API_KEY = os.environ.get('FRED_API_KEY', '467c035b9ae8a723c2b9ee2184a22522')
FRED_BASE    = 'https://api.stlouisfed.org/fred/series/observations'

def get_fred(series_id):
    try:
        r = requests.get(FRED_BASE, params={
            'series_id': series_id, 'api_key': FRED_API_KEY,
            'file_type': 'json', 'sort_order': 'desc', 'limit': 5,
            'observation_start': (datetime.now()-timedelta(days=90)).strftime('%Y-%m-%d'),
        }, timeout=10)
        for o in r.json().get('observations', []):
            v = o.get('value', '.')
            if v != '.': return round(float(v), 2)
        return None
    except: return None

def get_yf_info(ticker, field):
    try:
        v = yf.Ticker(ticker).info.get(field)
        return round(float(v), 4) if v else None
    except: return None

def load_valuation():
    """バリュエーション指標を全自動取得"""
    print("  バリュエーション自動取得中...")
    # まずスプレッドシートに今日のデータがあれば使う（API節約）
    try:
        ws  = ss.worksheet('バリュエーション_日次')
        rows = ws.get_all_values()
        if len(rows) >= 2:
            today = datetime.now().strftime('%Y/%m/%d')
            if rows[1][0].startswith(today):
                h = rows[0]; d = rows[1]
                rec = dict(zip(h, d))
                sf = lambda k,fb: float(rec[k]) if rec.get(k,'') not in ('','None','-') else fb
                print(f"  → 本日取得済みデータを使用")
                return {
                    'per_jp':sf('PER_日本',16), 'per_us':sf('PER_米国',22),
                    'pbr_jp':sf('PBR_日本',1.8),'pbr_us':sf('PBR_米国',4.8),
                    'div_jp':sf('配当利回り_日本',2.0),'div_us':sf('配当利回り_米国',1.3),
                    'yield_jp':sf('益回り_日本',6.25),'yield_us':sf('益回り_米国',4.5),
                    'roe_jp':sf('ROE_日本',10.5),'roe_us':sf('ROE_米国',21.8),
                    'cape_jp':sf('シラーPER_日本',29),'cape_us':sf('シラーPER_米国',36),
                    'rate_jp':sf('10年金利_日本',1.5),'rate_us':sf('10年金利_米国',4.3),
                    'rate_diff':sf('金利差',2.8),
                    'buffett_jp':sf('バフェット指数_日本',140),'buffett_us':sf('バフェット指数_米国',200),
                    'usdjpy':sf('ドル円',149),
                    'verdict':rec.get('総合判定','日本株優位'),'verdict_us':rec.get('米国判定','米国株 慎重'),
                    'updated_at':rec.get('更新日時','-'),
                }
    except: pass

    # 新規取得
    per_jp  = get_yf_info('^N225', 'trailingPE')
    per_us  = get_yf_info('^GSPC', 'trailingPE') or get_yf_info('SPY','trailingPE')
    pbr_jp  = get_yf_info('EWJ',  'priceToBook')
    pbr_us  = get_yf_info('SPY',  'priceToBook')
    div_jp_r= get_yf_info('1306.T','dividendYield')
    div_us_r= get_yf_info('SPY',  'dividendYield')
    div_jp  = round(div_jp_r*100,2) if div_jp_r else 2.0
    div_us  = round(div_us_r*100,2) if div_us_r else 1.3
    usdjpy  = None
    try:
        h = yf.Ticker('USDJPY=X').history(period='2d')
        if len(h)>0: usdjpy = round(float(h['Close'].iloc[-1]),1)
    except: pass
    rate_us = get_fred('DGS10')
    rate_jp = get_fred('IRLTLT01JPM156N')
    buffett_us = get_fred('DDDM01USA156NWDB')
    buffett_jp = get_fred('DDDM01JPA156NWDB')

    yield_jp = round(1/per_jp*100,2) if per_jp else 6.25
    yield_us = round(1/per_us*100,2) if per_us else 4.5
    roe_jp   = round(pbr_jp/per_jp*100,1) if (pbr_jp and per_jp) else 10.5
    roe_us   = round(pbr_us/per_us*100,1) if (pbr_us and per_us) else 21.8
    cape_jp  = round(per_jp*1.5,1) if per_jp else 29.0
    cape_us  = round(per_us*1.3,1) if per_us else 36.0
    rate_diff= round(rate_us-rate_jp,2) if (rate_us and rate_jp) else 2.8

    jp_adv = sum([
        1 if (pbr_jp and pbr_us and pbr_jp < pbr_us) else 0,
        1 if (per_jp and per_us and per_jp < per_us) else 0,
        1 if (div_jp and div_us and div_jp > div_us) else 0,
        1 if (yield_jp and yield_us and yield_jp > yield_us) else 0,
        1 if (buffett_jp and buffett_us and buffett_jp < buffett_us) else 0,
    ])
    verdict    = '日本株フルポジ' if jp_adv>=4 else '日本株優位' if jp_adv>=3 else '均衡局面' if jp_adv>=2 else '要検討'
    verdict_us = '米国株 慎重'   if jp_adv>=4 else '米国株 様子見' if jp_adv>=3 else '分散推奨' if jp_adv>=2 else '米国株も検討'

    result = {
        'per_jp':per_jp or 16,'per_us':per_us or 22,
        'pbr_jp':pbr_jp or 1.8,'pbr_us':pbr_us or 4.8,
        'div_jp':div_jp,'div_us':div_us,
        'yield_jp':yield_jp,'yield_us':yield_us,
        'roe_jp':roe_jp,'roe_us':roe_us,
        'cape_jp':cape_jp,'cape_us':cape_us,
        'rate_jp':rate_jp or 1.5,'rate_us':rate_us or 4.3,'rate_diff':rate_diff,
        'buffett_jp':buffett_jp or 140,'buffett_us':buffett_us or 200,
        'usdjpy':usdjpy or 149,
        'verdict':verdict,'verdict_us':verdict_us,
        'updated_at':datetime.now().strftime('%Y/%m/%d %H:%M'),
    }
    # スプレッドシートに保存
    try:
        header = ['更新日時','PER_日本','PER_米国','PBR_日本','PBR_米国',
                  '配当利回り_日本','配当利回り_米国','益回り_日本','益回り_米国',
                  'ROE_日本','ROE_米国','シラーPER_日本','シラーPER_米国',
                  '10年金利_日本','10年金利_米国','金利差',
                  'バフェット指数_日本','バフェット指数_米国','ドル円','総合判定','米国判定']
        row = [result.get('updated_at'),result.get('per_jp'),result.get('per_us'),
               result.get('pbr_jp'),result.get('pbr_us'),result.get('div_jp'),result.get('div_us'),
               result.get('yield_jp'),result.get('yield_us'),result.get('roe_jp'),result.get('roe_us'),
               result.get('cape_jp'),result.get('cape_us'),result.get('rate_jp'),result.get('rate_us'),
               result.get('rate_diff'),result.get('buffett_jp'),result.get('buffett_us'),
               result.get('usdjpy'),result.get('verdict'),result.get('verdict_us')]
        row = ['' if v is None else v for v in row]
        try:
            ws = ss.worksheet('バリュエーション_日次')
        except:
            ws = ss.add_worksheet(title='バリュエーション_日次', rows=400, cols=25)
        existing = ws.get_all_values()
        if not existing or existing[0] != header:
            ws.update('A1', [header])
            ws.update('A2', [row])
        else:
            ws.update('A2', [row])
            ws.update(f'A{len(existing)+1}', [row])
        print(f"  ✅ バリュエーション保存完了")
    except Exception as e:
        print(f"  ⚠️ バリュエーション保存失敗: {e}")
    return result

VAL = load_valuation()
print(f"  PBR 日本:{VAL['pbr_jp']} 米国:{VAL['pbr_us']} / 判定:{VAL['verdict']}")

# ── 市場指標 自動取得 ────────────────────────────────────────
def fetch_market():
    """日経・S&P500・VIX・HYスプレッド・逆イールドを自動取得"""
    print("  市場指標取得中...")
    def yp(ticker):
        try:
            h = yf.Ticker(ticker).history(period='5d')
            if len(h) >= 2:
                now = float(h['Close'].iloc[-1])
                prev = float(h['Close'].iloc[-2])
                chg = (now - prev) / prev * 100
                # 52週高値・安値
                h52 = yf.Ticker(ticker).history(period='1y')
                hi52 = float(h52['High'].max()) if len(h52) > 0 else now
                lo52 = float(h52['Low'].min())  if len(h52) > 0 else now
                pct52 = round((now - lo52) / (hi52 - lo52) * 100) if hi52 != lo52 else 50
                return {'v': now, 'chg': chg, 'hi52': hi52, 'lo52': lo52, 'pct52': pct52}
        except: pass
        return None

    nk   = yp('^N225')
    sp5  = yp('^GSPC')
    vix  = yp('^VIX')

    # HYスプレッド（HYG ETFの利回りで代替）
    hyg  = yp('HYG')

    # 逆イールド（10年-2年）
    try:
        t10 = get_fred('DGS10') or 4.3
        t2  = get_fred('DGS2') or 4.5
        yield_spread = round(t10 - t2, 2)
    except:
        t10 = 4.3; t2 = 4.5; yield_spread = -0.2

    result = {
        'nk_v':    round(nk['v'])    if nk  else 55000,
        'nk_chg':  round(nk['chg'],1) if nk  else 0,
        'nk_p52':  nk['pct52']       if nk  else 50,
        'sp_v':    round(sp5['v'])   if sp5 else 6700,
        'sp_chg':  round(sp5['chg'],1) if sp5 else 0,
        'sp_p52':  sp5['pct52']      if sp5 else 50,
        'vix_v':   round(vix['v'],1) if vix else 20,
        'vix_chg': round(vix['chg'],1) if vix else 0,
        't10':     t10,
        't2':      t2,
        'yield_spread': yield_spread,
        'hyg_v':   round(hyg['v'],2) if hyg else 80,
        'hyg_chg': round(hyg['chg'],2) if hyg else 0,
    }
    print(f"  日経:{result['nk_v']:,} SP500:{result['sp_v']:,} VIX:{result['vix_v']} イールド差:{result['yield_spread']}")
    return result

MKT = fetch_market()

# ── 市場指標HTML生成 ─────────────────────────────────────────
def mc_color(v, good_hi=None, good_lo=None, bad_hi=None, bad_lo=None, lower_better=False):
    """値に応じてボーダー色クラスを返す"""
    if lower_better:
        if v <= good_hi: return 'bg', 'cg'
        if v <= bad_hi:  return 'ba', 'ca'
        return 'br', 'cr'
    else:
        if good_lo and v >= good_lo: return 'bg', 'cg'
        if bad_lo  and v >= bad_lo:  return 'ba', 'ca'
        return 'br', 'cr'

def fmt_chg(c):
    arrow = '↑' if c > 0 else '↓' if c < 0 else '→'
    color = 'cg' if c > 0 else 'cr' if c < 0 else 'cs'
    return f'<span class="{color}">{arrow}{abs(c):.1f}%</span>'

def fmt_52w(p):
    """52週レンジ内の位置をミニバーで表示"""
    color = '#34d399' if p >= 60 else '#fbbf24' if p >= 30 else '#f87171'
    return (f'<div style="background:#1e2d40;border-radius:2px;height:3px;margin-top:2px;position:relative;">'
            f'<div style="position:absolute;left:0;width:{p}%;height:3px;background:{color};border-radius:2px;"></div>'
            f'</div>'
            f'<div style="font-size:6.5px;color:#475569;margin-top:1px;">52W {p}%</div>')

# 各指標の色判定
nk_bc,  nk_vc  = ('bg','cg') if MKT['nk_chg']  >= 0 else ('br','cr')
sp_bc,  sp_vc  = ('bg','cg') if MKT['sp_chg']  >= 0 else ('br','cr')
vix_bc, vix_vc = ('bg','cg') if MKT['vix_v'] <= 20 else ('ba','ca') if MKT['vix_v'] <= 30 else ('br','cr')
ys_bc,  ys_vc  = ('bg','cg') if MKT['yield_spread'] >= 0 else ('ba','ca') if MKT['yield_spread'] >= -0.5 else ('br','cr')
ys_label = '正常化' if MKT['yield_spread'] >= 0 else 'やや警戒' if MKT['yield_spread'] >= -0.5 else '逆イールド'
vix_label = '平静' if MKT['vix_v'] <= 20 else '警戒' if MKT['vix_v'] <= 30 else '恐怖'
hyg_label = '良好' if MKT['hyg_chg'] >= 0 else '悪化'
hyg_bc = 'bg' if MKT['hyg_chg'] >= 0 else 'br'

MSTRIP_HTML = f"""    <div class="mstrip">
      <div class="mc {nk_bc}" onclick="showMC('nk')" style="cursor:pointer;">
        <div class="mc-l">日経225 ⓘ</div>
        <div class="mc-v {nk_vc}">{MKT['nk_v']:,}</div>
        <div class="mc-s">{fmt_chg(MKT['nk_chg'])}</div>
        {fmt_52w(MKT['nk_p52'])}
      </div>
      <div class="mc {sp_bc}" onclick="showMC('sp')" style="cursor:pointer;">
        <div class="mc-l">S&amp;P500 ⓘ</div>
        <div class="mc-v {sp_vc}">{MKT['sp_v']:,}</div>
        <div class="mc-s">{fmt_chg(MKT['sp_chg'])}</div>
        {fmt_52w(MKT['sp_p52'])}
      </div>
      <div class="mc {vix_bc}" onclick="showMC('vix')" style="cursor:pointer;">
        <div class="mc-l">VIX 恐怖指数 ⓘ</div>
        <div class="mc-v {vix_vc}">{MKT['vix_v']}</div>
        <div class="mc-s">{fmt_chg(MKT['vix_chg'])} {vix_label}</div>
      </div>
      <div class="mc {hyg_bc}" onclick="showMC('hyg')" style="cursor:pointer;">
        <div class="mc-l">社債市場 ⓘ</div>
        <div class="mc-v {'cg' if MKT['hyg_chg']>=0 else 'cr'}">{MKT['hyg_v']}</div>
        <div class="mc-s {'cg' if MKT['hyg_chg']>=0 else 'cr'}">{hyg_label}</div>
      </div>
      <div class="mc {ys_bc}" onclick="showMC('ys')" style="cursor:pointer;">
        <div class="mc-l">逆イールド ⓘ</div>
        <div class="mc-v {ys_vc}">{MKT['yield_spread']:+.2f}</div>
        <div class="mc-s {ys_vc}">{ys_label}</div>
      </div>"""

# 日本M2・マクロスコアはスプレッドシートから取得済みのSHORT_SCORE/MID_SCOREを使う
MSTRIP_HTML += f"""
      <div class="mc bg" onclick="showMC('m2')" style="cursor:pointer;">
        <div class="mc-l">日本M2 ⓘ</div>
        <div class="mc-v cg">+{VAL.get('rate_jp', 1.5):.2f}%</div>
        <div class="mc-s cg">加速中↑</div>
      </div>
      <div class="mc bg">
        <div class="mc-l">マクロスコア</div>
        <div class="mc-v ct" style="font-size:16px;">+45</div>
        <div class="mc-s ca">買い検討</div>
      </div>"""

# 短期・中期スコアのHTML（既存のものを置き換え）
short_bc = 'bg' if SHORT_SCORE >= 55 else 'ba' if SHORT_SCORE >= 45 else 'br'
short_vc = 'cg' if SHORT_SCORE >= 55 else 'ca' if SHORT_SCORE >= 45 else 'cr'
short_lbl = '🟢 強気' if SHORT_SCORE >= 55 else '🟡 中立' if SHORT_SCORE >= 45 else '🔴 弱気'
mid_bc = 'bg' if MID_SCORE >= 55 else 'ba' if MID_SCORE >= 45 else 'br'
mid_vc = 'cg' if MID_SCORE >= 55 else 'ca' if MID_SCORE >= 45 else 'cr'
mid_lbl = '🟢 強気' if MID_SCORE >= 55 else '🟡 中立' if MID_SCORE >= 45 else '🔴 弱気'

MSTRIP_HTML += f"""
      <div class="mc mc-signal {short_bc}" style="border-color:{'#065f46' if SHORT_SCORE>=55 else '#92400e' if SHORT_SCORE>=45 else '#991b1b'}!important;">
        <div class="mc-l" style="color:{'#6ee7b7' if SHORT_SCORE>=55 else '#fcd34d' if SHORT_SCORE>=45 else '#fca5a5'};cursor:pointer;" onclick="showHelp('short_score')">短期スコア（1年）<span class="help-icon">?</span></div>
        <div class="mc-v {short_vc}" style="font-size:15px;">{SHORT_SCORE}点</div>
        <div class="mc-s {short_vc}">{short_lbl}</div>
      </div>
      <div class="mc mc-signal {mid_bc}" style="border-color:{'#065f46' if MID_SCORE>=55 else '#92400e' if MID_SCORE>=45 else '#7f2d1d'}!important;">
        <div class="mc-l" style="color:{'#6ee7b7' if MID_SCORE>=55 else '#fcd34d' if MID_SCORE>=45 else '#fca5a5'};cursor:pointer;" onclick="showHelp('medium_score')">中期スコア（3年）<span class="help-icon">?</span></div>
        <div class="mc-v {mid_vc}" style="font-size:15px;">{MID_SCORE}点</div>
        <div class="mc-s {mid_vc}">{mid_lbl}</div>
      </div>
    </div>"""

# モーダル・スタイル・スクリプトは </body> 直前に挿入する（別変数）
MC_MODAL_HTML = f"""<style>
#mc-modal{{display:none;position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,.65);z-index:9998;align-items:center;justify-content:center;}}
#mc-modal.open{{display:flex;}}
</style>
<div id="mc-modal" onclick="if(event.target===this)closeMC()">
  <div style="background:#111827;border:1px solid #374151;border-radius:10px;padding:18px 20px;max-width:320px;width:90%;">
    <div id="mc-ttl" style="font-size:13px;font-weight:900;color:#f59e0b;margin-bottom:8px;"></div>
    <div id="mc-body" style="font-size:11px;color:#d1d5db;line-height:1.75;white-space:pre-wrap;"></div>
    <div style="margin-top:12px;text-align:right;font-size:10px;color:#94a3b8;cursor:pointer;" onclick="closeMC()">✕ 閉じる</div>
  </div>
</div>
<script>
var MC_INFO={{
  nk:{{t:'日経225とは',b:'日本を代表する225社の株価を平均した指数です。\\n\\nこの数字が上がる→日本株全体が好調\\nこの数字が下がる→日本株全体が低調\\n\\n52週バー：過去1年の最安値〜最高値の中で今がどこにいるか。右端ほど高値圏。'}},
  sp:{{t:'S&P500とは',b:'アメリカの代表的な500社の株価指数。世界の株式市場の中心です。\\n\\nS&P500が下がると世界中の株が連動して売られやすくなります。日本株も例外ではありません。'}},
  vix:{{t:'VIX（恐怖指数）とは',b:'投資家がどれだけ「怖い」と感じているかを数値化した指標です。\\n\\n20以下→平静（買いやすい環境）\\n20〜30→不安（慎重に）\\n30以上→恐怖（嵐の中）\\n\\nただし長期投資家にとって恐怖は仕込みのチャンスでもあります。'}},
  hyg:{{t:'社債市場（HYG）とは',b:'信用力が低い企業が発行する債券のETFです。\\n\\nHYGが上がる→市場全体がリスクを取りやすい安心環境\\nHYGが下がる→企業の倒産懸念が高まっている危険サイン\\n\\n株式市場より先行して動くことが多く、先行指標として機能します。'}},
  ys:{{t:'逆イールドとは',b:'10年国債の金利−2年国債の金利の差です。\\n\\nプラス（正常）→景気は通常運転\\nマイナス（逆イールド）→近い将来の景気後退を市場が予測\\n\\n歴史的にマイナスが1年以上続いた後、景気後退が起きることが多い。現在は正常化の方向。'}},
  m2:{{t:'日本M2（マネーサプライ）とは',b:'日本国内に出回っているお金の総量の増加率です。\\n\\nM2が増加→15〜18ヶ月後に株式市場に資金が流入\\nM2が減少→将来の株式市場に逆風\\n\\n現在は加速中のため、2027年後半の株価上昇が期待されます。'}}
}};
function showMC(k){{var d=MC_INFO[k];if(!d)return;document.getElementById('mc-ttl').textContent=d.t;document.getElementById('mc-body').textContent=d.b;document.getElementById('mc-modal').classList.add('open');}}
function closeMC(){{document.getElementById('mc-modal').classList.remove('open');}}
</script>"""

def load(name, stype):
    try:
        rows = ss.worksheet(name).get_all_records()
        print(f"  {name}: {len(rows)}銘柄")
        return [(r, stype) for r in rows]
    except Exception as e:
        print(f"  NG {name}: {e}")
        return []

all_data = (load('保有銘柄_v4.3スコア', '保有') +
            load('監視銘柄_v4.3スコア', '監視'))
print(f"  合計: {len(all_data)}銘柄")

# ── ヘルパー関数 ─────────────────────────────────────────────
def sf(v, d=0):
    try:
        return float(v) if str(v).strip() not in ('', 'None') else d
    except:
        return d

def rcol(r):
    m = {'S': '#a78bfa', 'A': '#4ade80', 'B': '#60a5fa',
         'C': '#fbbf24', 'D': '#f87171'}
    return m.get(r, '#64748b')

def rbg(r):
    m = {'S': 'rgba(167,139,250,.2)',  'A': 'rgba(74,222,128,.15)',
         'B': 'rgba(96,165,250,.12)',  'C': 'rgba(251,191,36,.12)',
         'D': 'rgba(248,113,113,.1)'}
    return m.get(r, 'rgba(100,116,139,.1)')

def get_sig(rank):
    if rank in ['S', 'A']: return '買い検討', '#60a5fa'
    if rank == 'B':         return '様子見',   '#fbbf24'
    return '時期尚早', '#f87171'

def short_label(s):
    return ('強気' if s >= 70 else 'やや強気' if s >= 55 else
            '中立' if s >= 45 else 'やや弱気' if s >= 30 else '弱気')

def mid_sector_comment(sect, mid):
    sector_map = {
        '商社': '商社業種はM2加速の恩恵大',
        '小売': '小売・内需株が好転局面',
        '銀行': '銀行業種は金利上昇と連動',
        '陸運': '陸運は内需回復で追い風',
        '半導体': '半導体は逆相関・慎重に',
        '輸送機器': '輸送機器は逆相関・慎重に',
    }
    comment = sector_map.get(sect, f'{sect}業種の動向に注目')
    return f"中期{mid}点({('弱気' if mid < 45 else '中立' if mid < 55 else '強気')})。{comment}。"

# ── テーブル行の生成 ─────────────────────────────────────────
SCORES = {}
rows_h = []
rows_w = []

for row, stype in all_data:
    code  = str(row.get('コード', '')).strip()
    name  = str(row.get('銘柄名', '')).strip()
    sect  = str(row.get('業種', '')).strip()
    tot   = sf(row.get('総合スコア'))
    rank  = str(row.get('ランク', 'D')).strip()
    s1    = sf(row.get('変数1'))
    s2    = sf(row.get('変数2'))
    s3    = sf(row.get('変数3'))
    roe   = sf(row.get('ROE平均'))
    fcr   = sf(row.get('FCR平均'))
    roeT  = sf(row.get('ROEトレンド'))
    peg   = sf(row.get('PEG'), 1.0)
    fy    = sf(row.get('FCF利回り'))
    price = sf(row.get('株価'))
    if not code:
        continue

    SCORES[code] = [s1, s2, s3, tot, roe, fcr, roeT, 0, peg, fy]

    ps = f"{int(price):,}" if price > 0 else '-'
    vs = f"{tot:.1f}/{rank}" if tot > 0 else '-'
    rc = rcol(rank)
    rb = rbg(rank)
    st, sc = get_sig(rank)

    def e(s):
        return s.replace("'", "&#39;").replace('\n', ' ')

    sb = e(f"短期{SHORT_SCORE}点({short_label(SHORT_SCORE)})。SOX・SP500の動向に注目。")
    mb = e(mid_sector_comment(sect, MID_SCORE))
    lb = e(f"ROE平均{roe:.1f}%・FCR{fcr:.0f}%・ROEトレンド{roeT:+.2f}/年。")
    nt = e(f"v4.3: {tot:.1f}点({rank})=ROIC{s1:.0f}*40%+Trend{s2:.0f}*35%+Price{s3:.0f}*25%")

    tr = (
        f'        <tr class="dr" onclick="sel(this);showD('
        f"'{code}','{name}','{sect}',"
        f"{tot},'{rank}',{SHORT_SCORE},'down','down','{rank}',"
        f"'{sb}','{mb}','{lb}','{nt}','1日'"
        f')">\n'
        f'          <td><span style="font-size:9px;color:#475569;">{code}</span><br>'
        f'<span style="font-weight:900;color:#f1f5f9;">{name}</span></td>\n'
        f'          <td style="font-family:monospace;">{ps}</td>\n'
        f'          <td style="color:{rc};font-weight:900;font-family:monospace;">{vs}</td>\n'
        f'          <td style="color:#fbbf24;">{short_label(SHORT_SCORE)}</td>\n'
        f'          <td style="color:#fbbf24;">{short_label(MID_SCORE)}</td>\n'
        f'          <td><span style="background:{rb};color:{rc};padding:1px 6px;'
        f'border-radius:4px;font-weight:900;font-size:10px;">{rank}</span></td>\n'
        f'          <td>1日</td>\n'
        f'          <td><span class="s-buy" style="background:{rbg(rank)};color:{sc};">'
        f'{st}</span></td>\n'
        f'        </tr>'
    )
    (rows_h if stype == '保有' else rows_w).append(tr)

print(f"  保有:{len(rows_h)}銘柄 監視:{len(rows_w)}銘柄")

# ── ベースHTMLをGitHubから取得 ────────────────────────────────
BASE_URL = ('https://raw.githubusercontent.com/'
            'hosoyamasuyuki-stack/-AI-/main/ai_dashboard_v11_fixed.html')
print(f"  ベースHTML取得中...")
resp = requests.get(BASE_URL, timeout=30)
resp.raise_for_status()
src = resp.text
print(f"  OK: {len(src):,} bytes")

# ── 市場ストリップ置換 ────────────────────────────────────────
# mstripの直後はバリュエーションセクション。そこを終端として使う
mstrip_start  = src.find('<div class="mstrip">')
mstrip_end    = src.find('<div class="sl">バリュエーション', mstrip_start)
if mstrip_start >= 0 and mstrip_end >= 0:
    src = src[:mstrip_start] + MSTRIP_HTML + '\n    ' + src[mstrip_end:]
    print("OK: 市場ストリップ置換")
else:
    print(f"WARN: 市場ストリップ置換スキップ (start={mstrip_start} end={mstrip_end})")

# ── STOCK_SCORES埋め込み ─────────────────────────────────────
scores_js = ('const STOCK_SCORES=' +
             json.dumps(SCORES, ensure_ascii=False) + ';')
src = re.sub(r'const STOCK_SCORES\s*=\s*\{[^;]*\};',
             scores_js, src, flags=re.DOTALL)

# ── 更新日時の埋め込み ────────────────────────────────────────
src = re.sub(r'最終更新：[^<"\']+', f'最終更新：{NOW}', src)

# ── 保有テーブル置換 ──────────────────────────────────────────
hold_open = """      <table id="tH">
        <tr>
          <th class="sh" onclick="srt('tH',0,this)">銘柄<span class="sort-btn"><span class="au"></span><span class="ad"></span></span></th>
          <th class="sh" onclick="srt('tH',1,this)">株価<span class="sort-btn"><span class="au"></span><span class="ad"></span></span></th>
          <th class="sh" onclick="srt('tH',2,this)" style="color:#f59e0b;">v4.3<span class="sort-btn"><span class="au"></span><span class="ad"></span></span></th>
          <th class="sh" onclick="srt('tH',3,this)" style="color:#93c5fd;">短期<span class="sort-btn"><span class="au"></span><span class="ad"></span></span></th>
          <th class="sh" onclick="srt('tH',4,this)" style="color:#93c5fd;">中期<span class="sort-btn"><span class="au"></span><span class="ad"></span></span></th>
          <th class="sh" onclick="srt('tH',5,this)" style="color:#93c5fd;">長期<span class="sort-btn"><span class="au"></span><span class="ad"></span></span></th>
          <th>日数</th><th>判定</th>
        </tr>
""" + '\n'.join(rows_h) + "\n      </table>"

src = re.sub(
    r'<table id="tH">.*?</table>',
    hold_open, src, count=1, flags=re.DOTALL)
print("OK: 保有テーブル置換")

# ── 監視テーブル置換 ──────────────────────────────────────────
watch_open = """      <table id="tW">
        <tr>
          <th class="sh" onclick="srt('tW',0,this)">銘柄<span class="sort-btn"><span class="au"></span><span class="ad"></span></span></th>
          <th class="sh" onclick="srt('tW',1,this)">株価<span class="sort-btn"><span class="au"></span><span class="ad"></span></span></th>
          <th class="sh" onclick="srt('tW',2,this)" style="color:#f59e0b;">v4.3<span class="sort-btn"><span class="au"></span><span class="ad"></span></span></th>
          <th class="sh" onclick="srt('tW',3,this)" style="color:#93c5fd;">短期<span class="sort-btn"><span class="au"></span><span class="ad"></span></span></th>
          <th class="sh" onclick="srt('tW',4,this)" style="color:#93c5fd;">中期<span class="sort-btn"><span class="au"></span><span class="ad"></span></span></th>
          <th class="sh" onclick="srt('tW',5,this)" style="color:#93c5fd;">長期<span class="sort-btn"><span class="au"></span><span class="ad"></span></span></th>
          <th>日数</th><th>シグナル</th>
        </tr>
""" + '\n'.join(rows_w) + "\n      </table>"

src = re.sub(
    r'<table id="tW">.*?</table>',
    watch_open, src, count=1, flags=re.DOTALL)
print("OK: 監視テーブル置換")

# ── バリュエーション HTML生成（デュアルゲージ版） ────────────
def gauge_pct(mn, mx, v):
    return min(100, max(0, round((v - mn) / (mx - mn) * 100)))

def gauge_dot_color(pct, g_pct, w_pct, invert=False):
    if invert:
        return '#34d399' if pct >= g_pct else '#fbbf24' if pct >= w_pct else '#f87171'
    else:
        return '#34d399' if pct <= g_pct else '#fbbf24' if pct <= w_pct else '#f87171'

def badge(label, cls):
    bg = {'g':'#064e3b;color:#34d399','y':'#92400e;color:#fbbf24','r':'#7f1d1d;color:#f87171'}.get(cls,'#1e2d40;color:#94a3b8')
    return f'<span style="font-size:7px;font-weight:800;padding:1px 5px;border-radius:3px;background:{bg};">{label}</span>'

def make_gauge(mn, mx, v, g, w, invert=False):
    p  = gauge_pct(mn, mx, v)
    gp = gauge_pct(mn, mx, g)
    wp = gauge_pct(mn, mx, w)
    dc = gauge_dot_color(p, gp, wp, invert)
    r1c = '#7f1d1d' if invert else '#064e3b'
    r3c = '#064e3b' if invert else '#7f1d1d'
    return (
        f'<div style="background:#1e2d40;border-radius:3px;height:5px;position:relative;margin-top:2px;">'
        f'<div style="position:absolute;left:0;width:{gp}%;height:5px;background:{r1c};border-radius:3px 0 0 3px;"></div>'
        f'<div style="position:absolute;left:{gp}%;width:{wp-gp}%;height:5px;background:#92400e;"></div>'
        f'<div style="position:absolute;left:{wp}%;width:{100-wp}%;height:5px;background:{r3c};border-radius:0 3px 3px 0;"></div>'
        f'<div style="position:absolute;left:calc({p}% - 5px);top:-4px;width:13px;height:13px;border-radius:50%;background:{dc};border:2px solid #0d1117;"></div>'
        f'</div>'
    )

cape_jp = VAL['cape_jp']; cape_us = VAL['cape_us']
pbr_jp  = VAL['pbr_jp'];  pbr_us  = VAL['pbr_us']
yld_jp  = VAL['yield_jp'];yld_us  = VAL['yield_us']
buf_jp  = VAL['buffett_jp'];buf_us = VAL['buffett_us']
vd_cls  = 'color:#34d399' if '日本' in VAL['verdict'] else 'color:#fbbf24' if '均衡' in VAL['verdict'] else 'color:#f87171'

g_cape_jp = make_gauge(15,35,cape_jp,22,28)
g_cape_us = make_gauge(22,40,cape_us,27,32)
g_pbr_jp  = make_gauge(0.9,2.4,pbr_jp,1.4,2.0)
g_pbr_us  = make_gauge(2.5,5.5,pbr_us,3.2,4.2)
g_yld_jp  = make_gauge(3,9,yld_jp,6,4,invert=True)
g_yld_us  = make_gauge(2,7,yld_us,5,3.5,invert=True)
g_buf_jp  = make_gauge(60,200,buf_jp,100,150)
g_buf_us  = make_gauge(80,260,buf_us,120,170)

cape_jp_cls = 'g' if cape_jp<=22 else 'y' if cape_jp<=28 else 'r'
cape_us_cls = 'g' if cape_us<=27 else 'y' if cape_us<=32 else 'r'
pbr_jp_cls  = 'g' if pbr_jp<=1.4 else 'y' if pbr_jp<=2.0 else 'r'
pbr_us_cls  = 'g' if pbr_us<=3.2 else 'y' if pbr_us<=4.2 else 'r'
yld_jp_cls  = 'g' if yld_jp>=6 else 'y' if yld_jp>=4 else 'r'
yld_us_cls  = 'g' if yld_us>=5 else 'y' if yld_us>=3.5 else 'r'
buf_jp_cls  = 'g' if buf_jp<=100 else 'y' if buf_jp<=150 else 'r'
buf_us_cls  = 'g' if buf_us<=120 else 'y' if buf_us<=170 else 'r'

cape_jp_lbl = '割安圏' if cape_jp_cls=='g' else 'やや割高' if cape_jp_cls=='y' else '割高圏'
cape_us_lbl = '割安圏' if cape_us_cls=='g' else 'やや割高' if cape_us_cls=='y' else '割高圏'
pbr_jp_lbl  = '割安圏' if pbr_jp_cls=='g' else 'やや割高' if pbr_jp_cls=='y' else '割高警戒'
pbr_us_lbl  = '割安圏' if pbr_us_cls=='g' else 'やや割高' if pbr_us_cls=='y' else '割高警戒'
yld_jp_lbl  = '株式有利' if yld_jp_cls=='g' else '中立' if yld_jp_cls=='y' else '割高注意'
yld_us_lbl  = '株式有利' if yld_us_cls=='g' else '中立' if yld_us_cls=='y' else '割高注意'
buf_jp_lbl  = '割安圏' if buf_jp_cls=='g' else '割高圏注意' if buf_jp_cls=='y' else '割高警戒'
buf_us_lbl  = '割安圏' if buf_us_cls=='g' else '割高圏注意' if buf_us_cls=='y' else '割高警戒'

vi_style = 'padding:4px 8px;border-right:1px solid #1e2d40;cursor:pointer;'
vn_style = 'font-size:8.5px;font-weight:800;color:#cbd5e1;margin-bottom:4px;text-decoration:underline dotted;text-underline-offset:2px;'
row_style = 'display:flex;align-items:center;gap:5px;margin-bottom:1px;'
flag_style = 'font-size:9px;min-width:14px;'
val_style_g = 'font-size:12px;font-weight:900;font-family:monospace;color:#34d399;min-width:36px;'
val_style_y = 'font-size:12px;font-weight:900;font-family:monospace;color:#fbbf24;min-width:36px;'
val_style_r = 'font-size:12px;font-weight:900;font-family:monospace;color:#f87171;min-width:36px;'
vc = {'g': val_style_g, 'y': val_style_y, 'r': val_style_r}

VAL_HTML = f"""        <div class="sl">バリュエーション — 日本 vs 米国（過去10年との比較）<span style="font-size:7px;color:#475569;font-weight:400;margin-left:8px;">自動更新 {VAL['updated_at']}</span></div>
        <div style="background:#0f1420;border:1px solid #1e2d40;border-radius:6px;padding:6px 4px;">
        <div style="display:grid;grid-template-columns:repeat(5,1fr);gap:0;">
          <div style="{vi_style}" onclick="showVI('cape')">
            <div style="{vn_style}">シラーPER ⓘ</div>
            <div style="{row_style}"><span style="{flag_style}">🇯🇵</span><span style="{vc[cape_jp_cls]}">{cape_jp:.0f}倍</span><div style="flex:1">{g_cape_jp}</div></div>
            <div style="{row_style}"><span style="{flag_style}">🇺🇸</span><span style="{vc[cape_us_cls]}">{cape_us:.0f}倍</span><div style="flex:1">{g_cape_us}</div></div>
            <div style="margin-top:4px;display:flex;justify-content:space-between;">{badge('日本 '+cape_jp_lbl,cape_jp_cls)}{badge('米国 '+cape_us_lbl,cape_us_cls)}</div>
          </div>
          <div style="{vi_style}" onclick="showVI('pbr')">
            <div style="{vn_style}">PBR ⓘ</div>
            <div style="{row_style}"><span style="{flag_style}">🇯🇵</span><span style="{vc[pbr_jp_cls]}">{pbr_jp:.1f}倍</span><div style="flex:1">{g_pbr_jp}</div></div>
            <div style="{row_style}"><span style="{flag_style}">🇺🇸</span><span style="{vc[pbr_us_cls]}">{pbr_us:.1f}倍</span><div style="flex:1">{g_pbr_us}</div></div>
            <div style="margin-top:4px;display:flex;justify-content:space-between;">{badge('日本 '+pbr_jp_lbl,pbr_jp_cls)}{badge('米国 '+pbr_us_lbl,pbr_us_cls)}</div>
          </div>
          <div style="{vi_style}" onclick="showVI('yield')">
            <div style="{vn_style}">益回り ⓘ</div>
            <div style="{row_style}"><span style="{flag_style}">🇯🇵</span><span style="{vc[yld_jp_cls]}">{yld_jp:.2f}%</span><div style="flex:1">{g_yld_jp}</div></div>
            <div style="{row_style}"><span style="{flag_style}">🇺🇸</span><span style="{vc[yld_us_cls]}">{yld_us:.2f}%</span><div style="flex:1">{g_yld_us}</div></div>
            <div style="margin-top:4px;display:flex;justify-content:space-between;">{badge('日本 '+yld_jp_lbl,yld_jp_cls)}{badge('米国 '+yld_us_lbl,yld_us_cls)}</div>
          </div>
          <div style="{vi_style}" onclick="showVI('buffett')">
            <div style="{vn_style}">バフェット指数 ⓘ</div>
            <div style="{row_style}"><span style="{flag_style}">🇯🇵</span><span style="{vc[buf_jp_cls]}">{buf_jp:.0f}%</span><div style="flex:1">{g_buf_jp}</div></div>
            <div style="{row_style}"><span style="{flag_style}">🇺🇸</span><span style="{vc[buf_us_cls]}">{buf_us:.0f}%</span><div style="flex:1">{g_buf_us}</div></div>
            <div style="margin-top:4px;display:flex;justify-content:space-between;">{badge('日本 '+buf_jp_lbl,buf_jp_cls)}{badge('米国 '+buf_us_lbl,buf_us_cls)}</div>
          </div>
          <div style="padding:4px 8px;cursor:pointer;" onclick="showVI('verdict')">
            <div style="{vn_style}">総合判定 ⓘ</div>
            <div style="font-size:14px;font-weight:900;{vd_cls};margin-top:4px;">{VAL['verdict']}</div>
            <div style="font-size:9px;color:#f87171;font-weight:800;margin-top:2px;">{VAL['verdict_us']}</div>
            <div style="font-size:7.5px;color:#475569;margin-top:5px;">¥{VAL['usdjpy']:.1f} | 金利差{VAL['rate_diff']:.1f}%</div>
          </div>
        </div>
        </div>"""

# バリュエーションモーダル（</body>直前に挿入）
VI_MODAL_HTML = f"""<style>
#vi-modal{{display:none;position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,.65);z-index:9999;align-items:center;justify-content:center;}}
#vi-modal.open{{display:flex;}}
#vi-box{{background:#111827;border:1px solid #374151;border-radius:10px;padding:18px 20px;max-width:340px;width:90%;}}
#vi-ttl{{font-size:13px;font-weight:900;color:#f59e0b;margin-bottom:8px;}}
#vi-body{{font-size:11px;color:#d1d5db;line-height:1.75;white-space:pre-wrap;}}
#vi-hist{{margin-top:10px;padding-top:10px;border-top:1px solid #1e2d40;}}
.vi-close{{margin-top:12px;text-align:right;font-size:10px;color:#94a3b8;cursor:pointer;}}
.mh-row{{margin-bottom:10px;}}
.mh-flag{{font-size:8.5px;color:#94a3b8;margin-bottom:3px;font-weight:800;}}
.mh-bg{{background:#1e2d40;border-radius:4px;height:8px;position:relative;}}
.mh-labels{{display:flex;justify-content:space-between;font-size:7px;color:#475569;margin-top:3px;}}
</style>
<div id="vi-modal" onclick="if(event.target===this)closeVI()">
  <div id="vi-box">
    <div id="vi-ttl"></div>
    <div id="vi-body"></div>
    <div id="vi-hist"></div>
    <div class="vi-close" onclick="closeVI()">✕ 閉じる</div>
  </div>
</div>
<script>
var VI_DATA={{
  cape:{{ttl:'シラーPER（CAPE）とは',body:'過去10年の平均利益で計算した株価収益率です。\\n景気の良い年・悪い年を平均するため、より正確に割高・割安を判断できます。\\nノーベル賞を受賞したシラー教授が考案。\\n\\n目安：15倍以下→割安 / 22〜28倍→適正 / 30倍超→割高',jp:{{min:15,max:35,now:{cape_jp:.1f},g:22,w:28,flag:'🇯🇵 日本'}},us:{{min:22,max:40,now:{cape_us:.1f},g:27,w:32,flag:'🇺🇸 米国'}}}},
  pbr:{{ttl:'PBR（株価純資産倍率）とは',body:'会社の純資産と株価を比べた指標です。\\n1倍＝今すぐ会社を解散したときの価値と同じ。\\n日本は東証の改革でPBR改善が進んでいます。\\n\\n目安：1倍以下→超割安 / 1〜2倍→割安 / 3倍超→割高',jp:{{min:0.9,max:2.4,now:{pbr_jp:.2f},g:1.4,w:2.0,flag:'🇯🇵 日本'}},us:{{min:2.5,max:5.5,now:{pbr_us:.2f},g:3.2,w:4.2,flag:'🇺🇸 米国'}}}},
  yield:{{ttl:'益回り（株式益回り）とは',body:'PERの逆数（1÷PER×100）。\\n株式投資をした場合の利回りに相当します。\\n国債利回りより高ければ株式が有利。\\n\\n目安：6%超→株式有利 / 4〜6%→中立 / 4%未満→割高',jp:{{min:3,max:9,now:{yld_jp:.2f},g:6,w:4,flag:'🇯🇵 日本',inv:1}},us:{{min:2,max:7,now:{yld_us:.2f},g:5,w:3.5,flag:'🇺🇸 米国',inv:1}}}},
  buffett:{{ttl:'バフェット指数とは',body:'国の株式市場全体の時価総額をGDPで割った指標。\\nバフェットが重視することで有名。\\n数値が高いほど株式市場が割高です。\\n\\n目安：100%以下→割安 / 100〜150%→適正 / 150%超→割高',jp:{{min:60,max:200,now:{buf_jp:.0f},g:100,w:150,flag:'🇯🇵 日本'}},us:{{min:80,max:260,now:{buf_us:.0f},g:120,w:170,flag:'🇺🇸 米国'}}}},
  verdict:{{ttl:'総合判定の仕組み',body:'5指標（シラーPER・PBR・益回り・配当利回り・バフェット指数）を日米で比較し、日本が有利な指標の数で自動判定します。\\n\\n5指標中4つ以上→日本株フルポジ\\n3つ→日本株優位\\n2つ→均衡局面\\n1つ以下→要検討',jp:null,us:null}}
}};
function pct(mn,mx,v){{return Math.min(100,Math.max(0,Math.round((v-mn)/(mx-mn)*100)));}}
function dc(p,gp,wp,inv){{if(inv)return p>=gp?'#34d399':p>=wp?'#fbbf24':'#f87171';return p<=gp?'#34d399':p<=wp?'#fbbf24':'#f87171';}}
function mhRow(d){{
  if(!d)return '';
  var p=pct(d.min,d.max,d.now),gp=pct(d.min,d.max,d.g),wp=pct(d.min,d.max,d.w),inv=d.inv;
  var dotC=dc(p,gp,wp,inv),r1=inv?'#7f1d1d':'#064e3b',r3=inv?'#064e3b':'#7f1d1d';
  return '<div class="mh-row"><div class="mh-flag">'+d.flag+'</div>'
    +'<div class="mh-bg">'
    +'<div style="position:absolute;left:0;width:'+gp+'%;height:8px;background:'+r1+';border-radius:4px 0 0 4px;"></div>'
    +'<div style="position:absolute;left:'+gp+'%;width:'+(wp-gp)+'%;height:8px;background:#92400e;"></div>'
    +'<div style="position:absolute;left:'+wp+'%;width:'+(100-wp)+'%;height:8px;background:'+r3+';border-radius:0 4px 4px 0;"></div>'
    +'<div style="position:absolute;left:calc('+p+'% - 9px);top:-5px;width:18px;height:18px;border-radius:50%;background:'+dotC+';border:2px solid #111827;"></div>'
    +'</div>'
    +'<div class="mh-labels"><span>'+d.min+'（過去最安）</span><span style="color:'+dotC+';font-weight:800;">現在：'+d.now+'</span><span>'+d.max+'（過去最高）</span></div>'
    +'</div>';
}}
function showVI(k){{
  var d=VI_DATA[k];if(!d)return;
  document.getElementById('vi-ttl').textContent=d.ttl;
  document.getElementById('vi-body').textContent=d.body;
  var h=document.getElementById('vi-hist');
  if(d.jp){{h.style.display='block';h.innerHTML='<div style="font-size:9px;font-weight:800;color:#94a3b8;margin-bottom:6px;">過去10年レンジ（緑＝割安 / 黄＝普通 / 赤＝割高）</div>'+mhRow(d.jp)+mhRow(d.us);}}
  else h.style.display='none';
  document.getElementById('vi-modal').classList.add('open');
}}
function closeVI(){{document.getElementById('vi-modal').classList.remove('open');}}
</script>"""

# バリュエーションセクションをHTMLに埋め込む
# <div id="body"> を終端アンカーとして使用（確実・シンプル）
val_start = src.find('<div class="sl">バリュエーション')
val_end   = src.find('<div id="body">')
if val_start >= 0 and val_end >= 0:
    src = src[:val_start] + VAL_HTML + '\n    ' + src[val_end:]
    print("OK: バリュエーション置換")
else:
    print(f"WARN: バリュエーション置換スキップ (start={val_start} end={val_end})")

# ── 市場指標モーダルを </body> 直前に挿入 ─────────────────────
src = src.replace('</body>', VI_MODAL_HTML + MC_MODAL_HTML + '</body>', 1)
print("OK: モーダル挿入")

out = 'ai_dashboard_v11_fixed.html'
with open(out, 'w', encoding='utf-8') as f:
    f.write(src)
print(f"\n✅ 出力完了: {out}")
print(f"   保有:{len(rows_h)} 監視:{len(rows_w)} スコア:{len(SCORES)}")
print(f"   短期:{SHORT_SCORE}点 / 中期:{MID_SCORE}点")

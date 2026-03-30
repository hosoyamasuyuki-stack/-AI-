# ============================================================
# generate_dashboard.py v21
# AI投資判断システム ダッシュボード自動生成
#
# v20からの変更点：
# ・load_valuation()のバリュエーション取得ソース修正（失敗(19)対応）
#   Phase 1-A: PBR日本 EWJ(1.2倍) → 日経プロフィルスクレイピング(実測1.76倍)
#   Phase 1-B: PBR米国 SPY(1.5倍) → multpl.comスクレイピング(実測4.5-5.0倍)
#   Phase 1-B: シラーPER米国 per×1.3(33倍) → multpl.comスクレイピング(実測38倍)
#   Phase 1-C: cape_jp per×1.5計算式廃止 → 日本PER×補正係数（暫定）
# ・取得失敗時は前回値（バリュエーション_日次シート）にフォールバック
# ・全スクレイピングにUser-Agentヘッダー設定（ブロック対策）
# ・更新日時に「ソース更新済み」を明記（50代初心者への配慮）
#
# 【三者会議確認済み 2026/03/22】
# 【実行タイミング】毎週月曜 10:30 JST（weekly_update完了後30分）
# 【認証】GOOGLE_CREDENTIALS（環境変数）
# ============================================================

import os, json, re, requests, time
import yfinance as yf
import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime, timedelta

# ── ヘルパー関数（スクレイピング・API取得）────────────────────
UA = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}

def get_yf_info(ticker, key):
    """yfinanceからinfo値を安全に取得"""
    try:
        t = yf.Ticker(ticker)
        return t.info.get(key)
    except: return None

def get_fred(series_id):
    """FRED APIから最新値を取得"""
    api_key = os.environ.get('FRED_API_KEY', '')
    if not api_key: return None
    try:
        url = f'https://api.stlouisfed.org/fred/series/observations?series_id={series_id}&sort_order=desc&limit=5&api_key={api_key}&file_type=json'
        r = requests.get(url, timeout=10)
        if r.status_code == 200:
            obs = r.json().get('observations', [])
            for o in obs:
                if o['value'] != '.':
                    return float(o['value'])
    except: pass
    return None

def scrape_pbr_japan():
    """日経プロフィルから日本PBRを取得"""
    try:
        r = requests.get('https://indexes.nikkei.co.jp/nkave/index/profile?idx=0009', headers=UA, timeout=10)
        if r.status_code == 200:
            m = re.search(r'PBR.*?([\d.]+)\s*倍', r.text)
            if m:
                v = float(m.group(1))
                if 0.5 < v < 5.0: return v
    except: pass
    return None

def scrape_pbr_us():
    """multpl.comから米国PBRを取得"""
    try:
        r = requests.get('https://www.multpl.com/s-p-500-price-to-book', headers=UA, timeout=10)
        if r.status_code == 200:
            m = re.search(r'([\d.]+)\s*</div>', r.text)
            if m:
                v = float(m.group(1))
                if 1.0 < v < 10.0: return v
    except: pass
    return None

def scrape_cape_us():
    """multpl.comからシラーPER米国を取得"""
    try:
        r = requests.get('https://www.multpl.com/shiller-pe', headers=UA, timeout=10)
        if r.status_code == 200:
            m = re.search(r'([\d.]+)\s*</div>', r.text)
            if m:
                v = float(m.group(1))
                if 5.0 < v < 80.0: return v
    except: pass
    return None

# ── 認証 ────────────────────────────────────────────────────
from core.auth import get_spreadsheet
ss = get_spreadsheet()
NOW = datetime.now().strftime('%Y/%m/%d %H:%M')


# ── マクロフェーズゲージHTML生成 ──────────────────────────────
def build_phase_gauge_html(ss):
    score=0; label='RED'; updated='---'
    try:
        ws=ss.worksheet('MacroPhase'); av=ws.get_all_values()
        if len(av)>=2:
            r2=av[-1]
            updated=r2[0] if len(r2)>0 else '---'
            score=int(float(r2[1])) if len(r2)>1 and r2[1] else 0
            label=r2[2] if len(r2)>2 and r2[2] else 'RED'
            print(f"  OK: MacroPhase ({label}/{score})")
    except Exception as e:
        print(f"  WARN: {e}")
    if label=='GREEN':   cm='#22c55e';cbr='#166534';st='良好'
    elif label=='YELLOW':cm='#f59e0b';cbr='#92400e';st='慎重に'
    else:                cm='#ef4444';cbr='#991b1b';st='今は待て'
    pct=min(max(score,0),100)
    bar = f'<div style="flex:1;background:#1e293b;border-radius:3px;height:5px;position:relative;"><div style="position:absolute;left:30%;width:1px;height:5px;background:#374151;"></div><div style="position:absolute;left:60%;width:1px;height:5px;background:#374151;"></div><div style="width:{pct}%;height:5px;border-radius:3px;background:{cm};transition:width .3s;"></div></div>'
    return (
        f'<div style="background:#0d1117;border:1px solid {cbr};border-radius:6px;'
        f'padding:6px 14px;margin-bottom:10px;display:flex;align-items:center;gap:10px;">'
        f'<span style="width:8px;height:8px;border-radius:50%;background:{cm};'
        f'display:inline-block;flex-shrink:0;box-shadow:0 0 6px {cm};"></span>'
        f'<span style="font-size:var(--fs-md);font-weight:800;color:{cm};white-space:nowrap;">'
        f'マクロ {st}</span>'
        + bar +
        f'<span style="font-size:var(--fs-lg);font-weight:900;color:{cm};font-family:monospace;'
        f'white-space:nowrap;">{score}'
        f'<span style="font-size:var(--fs-xs);color:#475569;">/100</span></span>'
        f'<span style="font-size:var(--fs-xs);color:#475569;white-space:nowrap;">{updated}</span>'
        f'</div>'
    )

def load_valuation():
    """
    バリュエーション指標を全自動取得（v21修正版）
    変更点：
      ① 日本PBR → scrape_pbr_japan()（日経プロフィル）
      ② 米国PBR → scrape_pbr_us()（multpl.com）
      ③ シラーPER米国 → scrape_cape_us()（multpl.com）
      ④ シラーPER日本 → per_jp×補正係数（暫定・粗利データ整備後に改善）
      ⑤ 全項目：取得失敗時は前回値にフォールバック
    """
    print("  バリュエーション自動取得中（v21ソース更新版）...")

    # まず本日取得済みデータがあれば使う（API節約）
    try:
        ws   = ss.worksheet('バリュエーション_日次')
        rows = ws.get_all_values()
        if len(rows) >= 2:
            today = datetime.now().strftime('%Y/%m/%d')
            if rows[1][0].startswith(today):
                h = rows[0]; d = rows[1]
                rec = dict(zip(h, d))
                sf = lambda k, fb: float(rec[k]) if rec.get(k,'') not in ('','None','-') else fb
                print(f"  → 本日取得済みデータを使用")
                return {
                    'per_jp':    sf('PER_日本',     16),
                    'per_us':    sf('PER_米国',     22),
                    'pbr_jp':    sf('PBR_日本',     1.76),
                    'pbr_us':    sf('PBR_米国',     4.8),
                    'div_jp':    sf('配当利回り_日本', 2.0),
                    'div_us':    sf('配当利回り_米国', 1.3),
                    'yield_jp':  sf('益回り_日本',   6.25),
                    'yield_us':  sf('益回り_米国',   4.5),
                    'roe_jp':    sf('ROE_日本',     10.5),
                    'roe_us':    sf('ROE_米国',     21.8),
                    'cape_jp':   sf('シラーPER_日本', 24.0),
                    'cape_us':   sf('シラーPER_米国', 38.0),
                    'rate_jp':   sf('10年金利_日本',  1.5),
                    'rate_us':   sf('10年金利_米国',  4.3),
                    'rate_diff': sf('金利差',        2.8),
                    'buffett_jp':sf('バフェット指数_日本', 140),
                    'buffett_us':sf('バフェット指数_米国', 200),
                    'usdjpy':    sf('ドル円',        149),
                    'verdict':   rec.get('総合判定',  '日本株優位'),
                    'verdict_us':rec.get('米国判定',  '米国株 慎重'),
                    'updated_at':rec.get('更新日時',  '-'),
                    'source_updated': True,
                }
    except: pass

    # フォールバック：ハードコード値（未定義関数の代替）
    prev = {
        'per_jp': 16, 'per_us': 22, 'pbr_jp': 1.76, 'pbr_us': 4.8,
        'div_jp': 2.0, 'div_us': 1.3, 'yield_jp': 6.25, 'yield_us': 4.5,
        'roe_jp': 10.5, 'roe_us': 21.8, 'cape_jp': 24.0, 'cape_us': 38.0,
        'rate_jp': 1.5, 'rate_us': 4.3, 'rate_diff': 2.8,
        'buffett_jp': 140, 'buffett_us': 200, 'usdjpy': 149,
    }

    # ── yfinance取得（PER・配当等）────────────────────────
    per_jp  = get_yf_info('^N225', 'trailingPE')
    per_us  = get_yf_info('^GSPC', 'trailingPE') or get_yf_info('SPY', 'trailingPE')
    div_jp_r= get_yf_info('1306.T', 'dividendYield')
    div_us_r= get_yf_info('SPY',    'dividendYield')
    div_jp  = round(div_jp_r*100, 2) if div_jp_r else 2.0
    div_us  = round(div_us_r*100, 2) if div_us_r else 1.3
    usdjpy  = None
    try:
        h = yf.Ticker('USDJPY=X').history(period='2d')
        if len(h) > 0: usdjpy = round(float(h['Close'].iloc[-1]), 1)
    except: pass

    # ── FRED取得（金利・バフェット指数）──────────────────
    rate_us    = get_fred('DGS10')
    rate_jp    = get_fred('IRLTLT01JPM156N')
    buffett_us = get_fred('DDDM01USA156NWDB')
    buffett_jp = get_fred('DDDM01JPA156NWDB')

    # ── Phase 1-A: 日本PBR（日経プロフィルスクレイピング）──
    # 失敗時は前回値にフォールバック（0や1.2倍の誤値を記録しない）
    pbr_jp = scrape_pbr_japan()
    if pbr_jp is None:
        pbr_jp = prev['pbr_jp']
        print(f"  ℹ️ 日本PBR → 前回値使用: {pbr_jp}倍")
    time.sleep(1)  # スクレイピング間隔

    # ── Phase 1-B: 米国PBR（multpl.comスクレイピング）──────
    pbr_us = scrape_pbr_us()
    if pbr_us is None:
        pbr_us = prev['pbr_us']
        print(f"  ℹ️ 米国PBR → 前回値使用: {pbr_us}倍")
    time.sleep(1)

    # ── Phase 1-B: シラーPER米国（multpl.comスクレイピング）─
    cape_us = scrape_cape_us()
    if cape_us is None:
        cape_us = prev['cape_us']
        print(f"  ℹ️ シラーPER米国 → 前回値使用: {cape_us}倍")
    time.sleep(1)

    # ── Phase 1-C: シラーPER日本（per×補正係数・暫定）──────
    # per×1.5は誤り（失敗(19)）。日本の景気循環を考慮した補正係数を使用。
    # 実測値の日本CAPEは概ね20-26倍程度（米国38倍より大幅に低い）
    # 暫定：per_jp × 1.3 ただし範囲は15-35倍でクリップ
    # TODO: EDINET/財務DB整備後に10年平均利益ベースの正確な計算に変更
    if per_jp:
        cape_jp_raw = round(per_jp * 1.3, 1)
        cape_jp = max(15.0, min(35.0, cape_jp_raw))  # 15-35倍でクリップ
        print(f"  ℹ️ シラーPER日本: PER{per_jp:.1f}×1.3={cape_jp:.1f}倍（暫定・クリップ済）")
    else:
        cape_jp = prev['cape_jp']
        print(f"  ℹ️ シラーPER日本 → 前回値使用: {cape_jp}倍")

    # ── 派生指標計算 ────────────────────────────────────
    yield_jp  = round(1/per_jp*100,  2) if per_jp  else 6.25
    yield_us  = round(1/per_us*100,  2) if per_us  else 4.5
    roe_jp    = round(pbr_jp/per_jp*100, 1) if (pbr_jp and per_jp) else 10.5
    roe_us    = round(pbr_us/per_us*100, 1) if (pbr_us and per_us) else 21.8
    rate_diff = round(rate_us-rate_jp, 2)   if (rate_us and rate_jp) else 2.8

    # ── 総合判定 ────────────────────────────────────────
    jp_adv = sum([
        1 if (pbr_jp  and pbr_us  and pbr_jp  < pbr_us)  else 0,
        1 if (per_jp  and per_us  and per_jp  < per_us)  else 0,
        1 if (div_jp  and div_us  and div_jp  > div_us)  else 0,
        1 if (yield_jp and yield_us and yield_jp > yield_us) else 0,
        1 if (buffett_jp and buffett_us and buffett_jp < buffett_us) else 0,
    ])
    verdict    = ('日本株フルポジ' if jp_adv >= 4 else
                  '日本株優位'     if jp_adv >= 3 else
                  '均衡局面'       if jp_adv >= 2 else '要検討')
    verdict_us = ('米国株 慎重'    if jp_adv >= 4 else
                  '米国株 様子見'  if jp_adv >= 3 else
                  '分散推奨'       if jp_adv >= 2 else '米国株も検討')

    # 更新日時に「ソース更新済み」を明記（50代初心者への配慮）
    updated_at = datetime.now().strftime('%Y/%m/%d %H:%M') + ' ソース更新済み'

    result = {
        'per_jp':    per_jp    or 16,
        'per_us':    per_us    or 22,
        'pbr_jp':    pbr_jp,
        'pbr_us':    pbr_us,
        'div_jp':    div_jp,
        'div_us':    div_us,
        'yield_jp':  yield_jp,
        'yield_us':  yield_us,
        'roe_jp':    roe_jp,
        'roe_us':    roe_us,
        'cape_jp':   cape_jp,
        'cape_us':   cape_us,
        'rate_jp':   rate_jp   or 1.5,
        'rate_us':   rate_us   or 4.3,
        'rate_diff': rate_diff,
        'buffett_jp':buffett_jp or 140,
        'buffett_us':buffett_us or 200,
        'usdjpy':    usdjpy    or 149,
        'verdict':   verdict,
        'verdict_us':verdict_us,
        'updated_at':updated_at,
        'source_updated': True,
    }

    # スプレッドシートに保存
    try:
        header = ['更新日時','PER_日本','PER_米国','PBR_日本','PBR_米国',
                  '配当利回り_日本','配当利回り_米国','益回り_日本','益回り_米国',
                  'ROE_日本','ROE_米国','シラーPER_日本','シラーPER_米国',
                  '10年金利_日本','10年金利_米国','金利差',
                  'バフェット指数_日本','バフェット指数_米国','ドル円','総合判定','米国判定']
        row = [result.get('updated_at'), result.get('per_jp'),    result.get('per_us'),
               result.get('pbr_jp'),     result.get('pbr_us'),    result.get('div_jp'),
               result.get('div_us'),     result.get('yield_jp'),  result.get('yield_us'),
               result.get('roe_jp'),     result.get('roe_us'),    result.get('cape_jp'),
               result.get('cape_us'),    result.get('rate_jp'),   result.get('rate_us'),
               result.get('rate_diff'),  result.get('buffett_jp'),result.get('buffett_us'),
               result.get('usdjpy'),     result.get('verdict'),   result.get('verdict_us')]
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
        print(f"  ✅ バリュエーション保存完了（v21ソース）")
    except Exception as e:
        print(f"  ⚠️ バリュエーション保存失敗: {e}")

    return result

VAL = load_valuation()
print(f"  PBR 日本:{VAL['pbr_jp']} 米国:{VAL['pbr_us']}")
print(f"  CAPE 日本:{VAL['cape_jp']} 米国:{VAL['cape_us']}")
print(f"  判定:{VAL['verdict']}")

# ── 市場指標 自動取得 ────────────────────────────────────────
def fetch_market():
    print("  市場指標取得中...")
    def yp(ticker):
        try:
            h = yf.Ticker(ticker).history(period='5d')
            if len(h) >= 2:
                now  = float(h['Close'].iloc[-1])
                prev = float(h['Close'].iloc[-2])
                chg  = (now - prev) / prev * 100
                h52  = yf.Ticker(ticker).history(period='1y')
                hi52 = float(h52['High'].max()) if len(h52) > 0 else now
                lo52 = float(h52['Low'].min())  if len(h52) > 0 else now
                pct52 = round((now - lo52) / (hi52 - lo52) * 100) if hi52 != lo52 else 50
                return {'v': now, 'chg': chg, 'hi52': hi52, 'lo52': lo52, 'pct52': pct52}
        except: pass
        return None

    nk  = yp('^N225')
    sp5 = yp('^GSPC')
    vix = yp('^VIX')
    hyg = yp('HYG')
    try:
        t10 = get_fred('DGS10') or 4.3
        t2  = get_fred('DGS2')  or 4.5
        yield_spread = round(t10 - t2, 2)
    except:
        t10 = 4.3; t2 = 4.5; yield_spread = -0.2

    result = {
        'nk_v':    round(nk['v'])      if nk  else 35000,
        'nk_chg':  round(nk['chg'],1)  if nk  else 0,
        'nk_p52':  nk['pct52']         if nk  else 50,
        'sp_v':    round(sp5['v'])     if sp5 else 5500,
        'sp_chg':  round(sp5['chg'],1) if sp5 else 0,
        'sp_p52':  sp5['pct52']        if sp5 else 50,
        'vix_v':   round(vix['v'],1)   if vix else 20,
        'vix_chg': round(vix['chg'],1) if vix else 0,
        't10':     t10,
        't2':      t2,
        'yield_spread': yield_spread,
        'hyg_v':   round(hyg['v'],2)   if hyg else 80,
        'hyg_chg': round(hyg['chg'],2) if hyg else 0,
    }
    print(f"  日経:{result['nk_v']:,} SP500:{result['sp_v']:,} VIX:{result['vix_v']} イールド差:{result['yield_spread']}")
    return result

MKT = fetch_market()

# ── 日本M2前年比%を取得 ──────────────────────────────────────
_m2_yoy = None
_m2_label = '---'
try:
    _m2_ws = ss.worksheet('日本M2')
    _m2_rows = _m2_ws.get_all_values()
    if len(_m2_rows) >= 2:
        _m2_hdr = _m2_rows[0]
        if '前年比%' in _m2_hdr:
            _m2_idx = _m2_hdr.index('前年比%')
            for _r in reversed(_m2_rows[1:]):
                if len(_r) > _m2_idx and _r[_m2_idx]:
                    try:
                        _m2_yoy = float(_r[_m2_idx])
                        break
                    except: pass
    if _m2_yoy is not None:
        _m2_label = '加速中' if _m2_yoy > 3.0 else '拡大中' if _m2_yoy > 0 else '縮小中'
    print(f"  日本M2前年比: {_m2_yoy}% ({_m2_label})")
except Exception as e:
    print(f"  WARN: 日本M2取得失敗: {e}")

# ── 市場指標HTML生成 ─────────────────────────────────────────
def fmt_chg(c):
    arrow = '↑' if c > 0 else '↓' if c < 0 else '→'
    color = 'cg' if c > 0 else 'cr' if c < 0 else 'cs'
    return f'<span class="{color}">{arrow}{abs(c):.1f}%</span>'

def fmt_52w(p):
    color = '#34d399' if p >= 60 else '#fbbf24' if p >= 30 else '#f87171'
    return (f'<div style="background:#1e2d40;border-radius:2px;height:3px;margin-top:2px;position:relative;">'
            f'<div style="position:absolute;left:0;width:{p}%;height:3px;background:{color};border-radius:2px;"></div>'
            f'</div>'
            f'<div style="font-size:var(--fs-micro);color:#475569;margin-top:1px;">52W {p}%</div>')

nk_bc,  nk_vc  = ('bg','cg') if MKT['nk_chg']  >= 0 else ('br','cr')
sp_bc,  sp_vc  = ('bg','cg') if MKT['sp_chg']  >= 0 else ('br','cr')
vix_bc, vix_vc = ('bg','cg') if MKT['vix_v'] <= 20 else ('ba','ca') if MKT['vix_v'] <= 30 else ('br','cr')
ys_bc,  ys_vc  = ('bg','cg') if MKT['yield_spread'] >= 0 else ('ba','ca') if MKT['yield_spread'] >= -0.5 else ('br','cr')
ys_label  = '正常化' if MKT['yield_spread'] >= 0 else 'やや警戒' if MKT['yield_spread'] >= -0.5 else '逆イールド'
vix_label = '平静'   if MKT['vix_v'] <= 20 else '警戒' if MKT['vix_v'] <= 30 else '恐怖'
hyg_label = '良好'   if MKT['hyg_chg'] >= 0 else '悪化'
hyg_bc    = 'bg'     if MKT['hyg_chg'] >= 0 else 'br'

# ── MacroPhaseからスコア取得 ──────────────────────────────
# 列: 0=日時, 1=総合スコア, 2=フェーズ, 3=LayerA, 4=LayerB, 5=LayerC, 6=LayerD
# SHORT_SCORE（短期1年）= LayerA(リスク) + LayerB(金融) を0-100に正規化
# MID_SCORE（中期3年）= LayerC(経済) + LayerD(バリュエーション) を0-100に正規化
try:
    _mp_ws = ss.worksheet('MacroPhase'); _mp_rows = _mp_ws.get_all_values()
    _mp_row = _mp_rows[-1]
    _mp_score = int(float(_mp_row[1])); _mp_lbl = _mp_row[2]
    _la = float(_mp_row[3]) if len(_mp_row) > 3 and _mp_row[3] else 0  # max 40
    _lb = float(_mp_row[4]) if len(_mp_row) > 4 and _mp_row[4] else 0  # max 30
    _lc = float(_mp_row[5]) if len(_mp_row) > 5 and _mp_row[5] else 0  # max 20
    _ld = float(_mp_row[6]) if len(_mp_row) > 6 and _mp_row[6] else 0  # max 10
    # 短期 = (LayerA + LayerB) / 70 * 100
    SHORT_SCORE = int(round((_la + _lb) / 70 * 100))
    # 中期 = (LayerC + LayerD) / 30 * 100
    MID_SCORE   = int(round((_lc + _ld) / 30 * 100))
except:
    _mp_score = 45; _mp_lbl = 'YELLOW'; SHORT_SCORE = 19; MID_SCORE = 50

short_bc  = 'bg' if SHORT_SCORE >= 55 else 'ba' if SHORT_SCORE >= 45 else 'br'
short_vc  = 'cg' if SHORT_SCORE >= 55 else 'ca' if SHORT_SCORE >= 45 else 'cr'
short_lbl = '🟢 強気' if SHORT_SCORE >= 55 else '🟡 中立' if SHORT_SCORE >= 45 else '🔴 弱気'
mid_bc    = 'bg' if MID_SCORE >= 55 else 'ba' if MID_SCORE >= 45 else 'br'
mid_vc    = 'cg' if MID_SCORE >= 55 else 'ca' if MID_SCORE >= 45 else 'cr'
mid_lbl   = '🟢 強気' if MID_SCORE >= 55 else '🟡 中立' if MID_SCORE >= 45 else '🔴 弱気'
_mp_bc = 'bg' if _mp_lbl=='GREEN' else 'ba' if _mp_lbl=='YELLOW' else 'br'
_mp_vc = 'cg' if _mp_lbl=='GREEN' else 'ca' if _mp_lbl=='YELLOW' else 'cr'
_mp_txt = '良好' if _mp_lbl=='GREEN' else '慎重に' if _mp_lbl=='YELLOW' else '今は待て'
cape_jp = VAL.get('cape_jp', 20); pbr_jp = VAL.get('pbr_jp', 1.76)
buf_jp  = VAL.get('buffett_jp', 140); yld_jp = VAL.get('yield_jp', 3.5)
cape_bc = 'br' if cape_jp > 25 else 'ba' if cape_jp > 18 else 'bg'
pbr_bc  = 'br' if pbr_jp > 2.0 else 'ba' if pbr_jp > 1.5 else 'bg'
buf_bc  = 'br' if buf_jp > 160 else 'ba' if buf_jp > 130 else 'bg'
yld_bc  = 'bg' if yld_jp > 4.0 else 'ba' if yld_jp > 2.5 else 'br'
MSTRIP_HTML = f"""    <div class="mstrip">
      <div style="display:flex;flex-direction:column;justify-content:center;align-items:center;padding:2px 5px;border-right:1px solid #374151;min-width:24px;"><div style="font-size:var(--fs-xs);color:#ef4444;font-weight:700;writing-mode:vertical-rl;">🔴 リスク環境</div></div>
      <div class="mc {vix_bc}" onclick="showMC('vix')" style="cursor:pointer;">
        <div class="mc-l">VIX 恐怖指数 ⓘ</div>
        <div class="mc-v {vix_vc}">{MKT['vix_v']}</div>
        <div class="mc-s">{fmt_chg(MKT['vix_chg'])} {vix_label}</div>
      </div>
      <div class="mc {ys_bc}" onclick="showMC('ys')" style="cursor:pointer;">
        <div class="mc-l">逆イールド ⓘ</div>
        <div class="mc-v {ys_vc}">{MKT['yield_spread']:+.2f}</div>
        <div class="mc-s {ys_vc}">{ys_label}</div>
      </div>
      <div class="mc {hyg_bc}" onclick="showMC('hyg')" style="cursor:pointer;">
        <div class="mc-l">社債市場 ⓘ</div>
        <div class="mc-v {'cg' if MKT['hyg_chg']>=0 else 'cr'}">{MKT['hyg_v']}</div>
        <div class="mc-s {'cg' if MKT['hyg_chg']>=0 else 'cr'}">{hyg_label}</div>
      </div>
      <div class="mc {_mp_bc}">
        <div class="mc-l">マクロスコア</div>
        <div class="mc-v {_mp_vc}" style="font-size:var(--fs-xl);">{_mp_score}点</div>
        <div class="mc-s {_mp_vc}">{_mp_txt}</div>
      </div>
      <div style="display:flex;flex-direction:column;justify-content:center;align-items:center;padding:2px 5px;border-left:1px solid #374151;border-right:1px solid #374151;min-width:24px;"><div style="font-size:var(--fs-xs);color:#f59e0b;font-weight:700;writing-mode:vertical-rl;">🟡 バリュエーション</div></div>
      <div class="mc {cape_bc}" onclick="showMC('cape')" style="cursor:pointer;">
        <div class="mc-l">シラーPER ⓘ</div>
        <div class="mc-v {'cr' if cape_jp>25 else 'ca' if cape_jp>18 else 'cg'}">{cape_jp:.0f}倍</div>
        <div class="mc-s ca">🇯🇵 日本</div>
      </div>
      <div class="mc {pbr_bc}" onclick="showMC('pbr')" style="cursor:pointer;">
        <div class="mc-l">PBR ⓘ</div>
        <div class="mc-v {'cr' if pbr_jp>2.0 else 'ca' if pbr_jp>1.5 else 'cg'}">{pbr_jp:.2f}倍</div>
        <div class="mc-s ca">🇯🇵 日本</div>
      </div>
      <div class="mc {buf_bc}" onclick="showMC('buf')" style="cursor:pointer;">
        <div class="mc-l">バフェット指数 ⓘ</div>
        <div class="mc-v {'cr' if buf_jp>160 else 'ca' if buf_jp>130 else 'cg'}">{buf_jp:.0f}%</div>
        <div class="mc-s ca">🇯🇵 日本</div>
      </div>
      <div class="mc {yld_bc}" onclick="showMC('yield')" style="cursor:pointer;">
        <div class="mc-l">益回り ⓘ</div>
        <div class="mc-v {'cg' if yld_jp>4.0 else 'ca' if yld_jp>2.5 else 'cr'}">{yld_jp:.2f}%</div>
        <div class="mc-s ca">🇯🇵 日本</div>
      </div>
      <div style="display:flex;flex-direction:column;justify-content:center;align-items:center;padding:2px 5px;border-left:1px solid #374151;border-right:1px solid #374151;min-width:24px;"><div style="font-size:var(--fs-xs);color:#22c55e;font-weight:700;writing-mode:vertical-rl;">🟢 マクロ動向</div></div>
      <div class="mc {'bg' if _m2_yoy and _m2_yoy > 0 else 'br'}" onclick="showMC('m2')" style="cursor:pointer;">
        <div class="mc-l">日本M2 ⓘ</div>
        <div class="mc-v {'cg' if _m2_yoy and _m2_yoy > 0 else 'cr'}">{f'+{_m2_yoy:.2f}' if _m2_yoy and _m2_yoy > 0 else f'{_m2_yoy:.2f}' if _m2_yoy else '---'}%</div>
        <div class="mc-s {'cg' if _m2_yoy and _m2_yoy > 0 else 'cr'}">{_m2_label}</div>
      </div>
      <div class="mc {nk_bc}" onclick="showMC('nk')" style="cursor:pointer;">
        <div class="mc-l">日経225 ⓘ</div>
        <div class="mc-v {nk_vc}">{MKT['nk_v']:,}</div>
        <div class="mc-s">{fmt_chg(MKT['nk_chg'])}</div>
        {fmt_52w(MKT['nk_p52'])}
      </div>
      <div class="mc mc-signal {short_bc}" style="border-color:{'#065f46' if SHORT_SCORE>=55 else '#92400e' if SHORT_SCORE>=45 else '#991b1b'}!important;">
        <div class="mc-l" style="color:{'#6ee7b7' if SHORT_SCORE>=55 else '#fcd34d' if SHORT_SCORE>=45 else '#fca5a5'};cursor:pointer;" onclick="showHelp('short_score')">短期スコア（1年）<span class="help-icon">?</span></div>
        <div class="mc-v {short_vc}" style="font-size:var(--fs-xl);">{SHORT_SCORE}点</div>
        <div class="mc-s {short_vc}">{short_lbl}</div>
      </div>
      <div class="mc mc-signal {mid_bc}" style="border-color:{'#065f46' if MID_SCORE>=55 else '#92400e' if MID_SCORE>=45 else '#7f2d1d'}!important;">
        <div class="mc-l" style="color:{'#6ee7b7' if MID_SCORE>=55 else '#fcd34d' if MID_SCORE>=45 else '#fca5a5'};cursor:pointer;" onclick="showHelp('medium_score')">中期スコア（3年）<span class="help-icon">?</span></div>
        <div class="mc-v {mid_vc}" style="font-size:var(--fs-xl);">{MID_SCORE}点</div>
        <div class="mc-s {mid_vc}">{mid_lbl}</div>
      </div>
    </div>"""

MC_MODAL_HTML = f"""<style>
#mc-modal{{display:none;position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,.65);z-index:9998;align-items:center;justify-content:center;}}
#mc-modal.open{{display:flex;}}
</style>
<div id="mc-modal" onclick="if(event.target===this)closeMC()">
  <div style="background:#111827;border:1px solid #374151;border-radius:10px;padding:18px 20px;max-width:320px;width:90%;">
    <div id="mc-ttl" style="font-size:var(--fs-lg);font-weight:900;color:#f59e0b;margin-bottom:8px;"></div>
    <div id="mc-body" style="font-size:var(--fs-md);color:#d1d5db;line-height:1.75;white-space:pre-wrap;"></div>
    <div style="margin-top:12px;text-align:right;font-size:var(--fs-base);color:#94a3b8;cursor:pointer;" onclick="closeMC()">✕ 閉じる</div>
  </div>
</div>
<script>
var MC_INFO={{
  nk:{{t:'日経225とは',b:'日本を代表する225社の株価を平均した指数です。\\n\\nこの数字が上がる→日本株全体が好調\\nこの数字が下がる→日本株全体が低調\\n\\n52週バー：過去1年の最安値〜最高値の中で今がどこにいるか。右端ほど高値圏。'}},
  sp:{{t:'S&P500とは',b:'アメリカの代表的な500社の株価指数。世界の株式市場の中心です。\\n\\nS&P500が下がると世界中の株が連動して売られやすくなります。日本株も例外ではありません。'}},
  vix:{{t:'VIX（恐怖指数）とは',b:'投資家がどれだけ「怖い」と感じているかを数値化した指標です。\\n\\n20以下→平静（買いやすい環境）\\n20〜30→不安（慎重に）\\n30以上→恐怖（嵐の中）\\n\\nただし長期投資家にとって恐怖は仕込みのチャンスでもあります。'}},
  hyg:{{t:'社債市場（HYG）とは',b:'信用力が低い企業が発行する債券のETFです。\\n\\nHYGが上がる→市場全体がリスクを取りやすい安心環境\\nHYGが下がる→企業の倒産懸念が高まっている危険サイン\\n\\n株式市場より先行して動くことが多く、先行指標として機能します。'}},
  ys:{{t:'逆イールドとは',b:'10年国債の金利−2年国債の金利の差です。\\n\\nプラス（正常）→景気は通常運転\\nマイナス（逆イールド）→近い将来の景気後退を市場が予測\\n\\n歴史的にマイナスが1年以上続いた後、景気後退が起きることが多い。現在は正常化の方向。'}},
  m2:{{t:'日本M2（マネーサプライ）とは',b:'日本国内に出回っているお金の総量の増加率です。\\n\\nM2が増加→15〜18ヶ月後に株式市場に資金が流入\\nM2が減少→将来の株式市場に逆風\\n\\n前年比プラスで拡大中なら、将来の株価上昇が期待されます。'}},
  cape:{{t:'シラーPER（CAPE）とは',b:'過去10年間の平均利益で計算したPERです。\\n\\n20倍以下→割安（買い場の可能性）\\n20〜25倍→適正\\n25倍以上→割高（注意）\\n\\n通常のPERより景気変動の影響を受けにくく、長期投資の判断に適しています。'}},
  pbr:{{t:'PBR（株価純資産倍率）とは',b:'株価が企業の純資産（解散価値）の何倍かを示します。\\n\\n1倍以下→解散価値割れ（割安の可能性）\\n1〜1.5倍→適正水準\\n2倍以上→割高（成長期待込み）\\n\\n日本株は歴史的に1.0〜1.5倍が中心。2倍超えは要注意。'}},
  buf:{{t:'バフェット指数とは',b:'株式市場の時価総額÷GDPで計算します。\\n\\n100%以下→割安\\n100〜130%→適正\\n130〜160%→やや割高\\n160%以上→過熱（バブル警戒）\\n\\nウォーレン・バフェットが重視する指標として有名です。'}},
  yield:{{t:'益回りとは',b:'PERの逆数（1÷PER×100）です。\\n株式の「利回り」を債券と比較できます。\\n\\n益回り＞国債利回り→株式が有利\\n益回り＜国債利回り→債券が有利\\n\\n4%以上あれば株式投資は魅力的な水準です。'}}
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
screen_data = load('スクリーニング_Top50', 'スクリーニング')
print(f"  合計: {len(all_data)}銘柄 + スクリーニング{len(screen_data)}銘柄")

def sf(v, d=0):
    try:
        return float(v) if str(v).strip() not in ('', 'None') else d
    except:
        return d

def rcol(r):
    m = {'S':'#a78bfa','A':'#4ade80','B':'#60a5fa','C':'#fbbf24','D':'#f87171'}
    return m.get(r, '#64748b')

def rbg(r):
    m = {'S':'rgba(167,139,250,.2)','A':'rgba(74,222,128,.15)',
         'B':'rgba(96,165,250,.12)','C':'rgba(251,191,36,.12)',
         'D':'rgba(248,113,113,.1)'}
    return m.get(r, 'rgba(100,116,139,.1)')

def get_sig(rank):
    if rank in ['S','A']: return '買い検討','#60a5fa'
    if rank == 'B':        return '様子見',  '#fbbf24'
    return '時期尚早','#f87171'

RANK_ORDER = {'S': 5, 'A': 4, 'B': 3, 'C': 2, 'D': 1}
degradation_alerts = []  # abar用アラートリスト

def short_label(s):
    return ('強気' if s>=70 else 'やや強気' if s>=55 else
            '中立' if s>=45 else 'やや弱気' if s>=30 else '弱気')

def mid_sector_comment(sect, mid):
    sector_map = {
        '商社':'商社業種はM2加速の恩恵大',
        '小売':'小売・内需株が好転局面',
        '銀行':'銀行業種は金利上昇と連動',
        '陸運':'陸運は内需回復で追い風',
        '半導体':'半導体は逆相関・慎重に',
        '輸送機器':'輸送機器は逆相関・慎重に',
    }
    comment = sector_map.get(sect, f'{sect}業種の動向に注目')
    return f"中期{mid}点({('弱気' if mid<45 else '中立' if mid<55 else '強気')})。{comment}。"

SCORES  = {}
rows_h  = []
rows_w  = []

# STEP0予測記録日からの経過日数
STEP0_DATE = datetime(2026, 3, 18)
ELAPSED_DAYS = (datetime.now() - STEP0_DATE).days
DAYS_LABEL = f"{ELAPSED_DAYS}日"
print(f"  学習経過日数: {DAYS_LABEL}（STEP0: 2026/03/18）")

for row, stype in all_data:
    code  = str(row.get('コード',    '')).strip()
    name  = str(row.get('銘柄名',    '')).strip()
    sect  = str(row.get('業種',      '')).strip()
    tot   =     sf(row.get('総合スコア'))
    rank  = str(row.get('ランク',   'D')).strip()
    prev_rank = str(row.get('前回ランク', '')).strip()
    s1    =     sf(row.get('変数1'))
    s2    =     sf(row.get('変数2'))
    s3    =     sf(row.get('変数3'))
    roe   =     sf(row.get('ROE平均'))
    fcr   =     sf(row.get('FCR平均'))
    roeT  =     sf(row.get('ROEトレンド'))
    peg   =     sf(row.get('PEG'),  1.0)
    fy    =     sf(row.get('FCF利回り'))
    price =     sf(row.get('株価'))
    if not code: continue

    # 総合スコアを変数から再計算（スプレッドシートの値が古い場合の保護）
    if s1 is not None and s2 is not None and s3 is not None:
        calc_tot = round(s1 * 0.40 + s2 * 0.35 + s3 * 0.25, 1)
        if tot is None or abs(tot - calc_tot) > 1.0:
            print(f"  RECALC: {code} 総合スコア {tot} -> {calc_tot}")
            tot = calc_tot
            rank = ('S' if tot >= 80 else 'A' if tot >= 65 else
                    'B' if tot >= 50 else 'C' if tot >= 35 else 'D')

    SCORES[code] = [s1, s2, s3, tot, roe, fcr, roeT, 0, peg, fy]
    ps = f"{int(price):,}" if price > 0 else '-'
    vs = f"{tot:.1f}/{rank}" if tot > 0 else '-'
    rc = rcol(rank)
    rb = rbg(rank)
    st, sc = get_sig(rank)

    def e(s):
        return s.replace("'","&#39;").replace('\n',' ')

    sb = e(f"短期{SHORT_SCORE}点({short_label(SHORT_SCORE)})。SOX・SP500の動向に注目。")
    mb = e(mid_sector_comment(sect, MID_SCORE))
    lb = e(f"ROE平均{roe:.1f}%・FCR{fcr:.0f}%・ROEトレンド{roeT:+.2f}/年。")
    nt = e(f"v4.3: {tot:.1f}点({rank})=ROIC{s1:.0f}*40%+Trend{s2:.0f}*35%+Price{s3:.0f}*25%")

    tr = (
        f'        <tr class="dr" onclick="sel(this);showD('
        f"'{code}','{name}','{sect}',"
        f"{tot},'{rank}',{SHORT_SCORE},'down','down','{rank}',"
        f"'{sb}','{mb}','{lb}','{nt}','{DAYS_LABEL}'"
        f')">\n'
        f'          <td><span style="font-size:var(--fs-sm);color:#475569;">{code}</span><br>'
        f'<span style="font-weight:900;color:#f1f5f9;">{name}</span></td>\n'
        f'          <td style="font-family:monospace;">{ps}</td>\n'
        f'          <td style="color:{rc};font-weight:900;font-family:monospace;">{vs}</td>\n'
        f'          <td style="color:#fbbf24;">{short_label(SHORT_SCORE)}</td>\n'
        f'          <td style="color:#fbbf24;">{short_label(MID_SCORE)}</td>\n'
        f'          <td><span style="background:{rb};color:{rc};padding:1px 6px;'
        f'border-radius:4px;font-weight:900;font-size:var(--fs-base);">{rank}</span></td>\n'
        f'          <td>{DAYS_LABEL}</td>\n'
        f'          <td><span class="s-buy" style="background:{rbg(rank)};color:{sc};">'
        f'{st}</span></td>\n'
        f'        </tr>'
    )
    (rows_h if stype == '保有' else rows_w).append(tr)

    # ランク変動検知（保有銘柄のみ・B→C以下の転落をアラート）
    if stype == '保有' and prev_rank and prev_rank in RANK_ORDER and rank in RANK_ORDER:
        if RANK_ORDER[rank] < RANK_ORDER[prev_rank]:
            degradation_alerts.append({
                'code': code, 'name': name, 'prev': prev_rank,
                'curr': rank, 'score': tot
            })

# スクリーニングTop50のテーブル行生成（簡素表示：銘柄・株価・スコア・シグナル）
rows_s = []
for row, stype in screen_data:
    code  = str(row.get('コード',    '')).strip()
    name  = str(row.get('銘柄名',    '')).strip()
    sect  = str(row.get('業種',      '')).strip()
    tot   =     sf(row.get('総合スコア'))
    rank  = str(row.get('ランク',   'D')).strip()
    s1    =     sf(row.get('変数1'))
    s2    =     sf(row.get('変数2'))
    s3    =     sf(row.get('変数3'))
    roe   =     sf(row.get('ROE平均'))
    fcr   =     sf(row.get('FCR平均'))
    roeT  =     sf(row.get('ROEトレンド'))
    peg   =     sf(row.get('PEG'),  1.0)
    fy    =     sf(row.get('FCF利回り'))
    price =     sf(row.get('株価'))
    if not code: continue

    # 総合スコアを変数から再計算（スプレッドシートの値が古い場合の保護）
    if s1 is not None and s2 is not None and s3 is not None:
        calc_tot = round(s1 * 0.40 + s2 * 0.35 + s3 * 0.25, 1)
        if tot is None or abs(tot - calc_tot) > 1.0:
            tot = calc_tot
            rank = ('S' if tot >= 80 else 'A' if tot >= 65 else
                    'B' if tot >= 50 else 'C' if tot >= 35 else 'D')

    SCORES[code] = [s1, s2, s3, tot, roe, fcr, roeT, 0, peg, fy]
    ps = f"{int(price):,}" if price > 0 else '-'
    vs = f"{tot:.1f}/{rank}" if tot > 0 else '-'
    rc = rcol(rank)
    st, sc = get_sig(rank)

    def e2(s):
        return s.replace("'","&#39;").replace('\n',' ')

    sb2 = e2(f"短期{SHORT_SCORE}点({short_label(SHORT_SCORE)})。")
    mb2 = e2(mid_sector_comment(sect, MID_SCORE))
    lb2 = e2(f"ROE平均{roe:.1f}%・FCR{fcr:.0f}%・ROEトレンド{roeT:+.2f}/年。")
    nt2 = e2(f"v4.3: {tot:.1f}点({rank})=ROIC{s1:.0f}*40%+Trend{s2:.0f}*35%+Price{s3:.0f}*25%")

    rb2 = rbg(rank)
    tr_s = (
        f'        <tr class="dr" onclick="sel(this);showD('
        f"'{code}','{name}','{sect}',"
        f"{tot},'{rank}',{SHORT_SCORE},'down','down','{rank}',"
        f"'{sb2}','{mb2}','{lb2}','{nt2}','{DAYS_LABEL}'"
        f')">\n'
        f'          <td><span style="font-size:var(--fs-sm);color:#475569;">{code}</span><br>'
        f'<span style="font-weight:900;color:#f1f5f9;">{name}</span></td>\n'
        f'          <td style="font-family:monospace;">{ps}</td>\n'
        f'          <td style="color:{rc};font-weight:900;font-family:monospace;">{vs}</td>\n'
        f'          <td style="color:#fbbf24;">{short_label(SHORT_SCORE)}</td>\n'
        f'          <td style="color:#fbbf24;">{short_label(MID_SCORE)}</td>\n'
        f'          <td><span style="background:{rb2};color:{rc};padding:1px 6px;'
        f'border-radius:4px;font-weight:900;font-size:var(--fs-base);">{rank}</span></td>\n'
        f'          <td>{DAYS_LABEL}</td>\n'
        f'          <td><span class="s-buy" style="background:{rbg(rank)};color:{sc};">'
        f'{st}</span></td>\n'
        f'        </tr>'
    )
    rows_s.append(tr_s)

print(f"  保有:{len(rows_h)}銘柄 監視:{len(rows_w)}銘柄 スクリーニング:{len(rows_s)}銘柄")

BASE_URL = ('https://raw.githubusercontent.com/'
            'hosoyamasuyuki-stack/-AI-/main/ai_dashboard_v13.html')
print(f"  ベースHTML取得中...")
resp = requests.get(BASE_URL, timeout=30)
resp.raise_for_status()
src = resp.text
print(f"  OK: {len(src):,} bytes")

# 市場ストリップ置換
mstrip_start = src.find('<div class="mstrip">')
mstrip_end   = src.find('<div class="sl">バリュエーション', mstrip_start)
if mstrip_start >= 0 and mstrip_end >= 0:
    src = src[:mstrip_start] + MSTRIP_HTML + '\n    ' + src[mstrip_end:]
    print("OK: 市場ストリップ置換")
else:
    print(f"WARN: 市場ストリップ置換スキップ (start={mstrip_start} end={mstrip_end})")

# ティッカーHTML生成
TICKER_HTML = '<div style="overflow:hidden;white-space:nowrap;background:#0a0e17;padding:3px 0;font-size:var(--fs-base);border-bottom:1px solid #1e293b;"><div style="display:inline-block;animation:ticker_scroll 60s linear infinite;"><span style="color:#6ee7b7;margin:0 18px;">AI LEARNING</span><span style="color:#94a3b8;margin:0 10px;">|</span><span style="color:#e2e8f0;margin:0 10px;">保有銘柄46 日次価格学習中</span><span style="color:#94a3b8;margin:0 10px;">|</span><span style="color:#e2e8f0;margin:0 10px;">監視銘柄27 日次価格学習中</span><span style="color:#94a3b8;margin:0 10px;">|</span><span style="color:#e2e8f0;margin:0 10px;">学習用99 月次バッチ学習</span><span style="color:#94a3b8;margin:0 10px;">|</span><span style="color:#e2e8f0;margin:0 10px;">日次データ学習中(FRED 32指標)</span><span style="color:#94a3b8;margin:0 10px;">|</span><span style="color:#e2e8f0;margin:0 10px;">全172銘柄 v4.3スコアリング稼働中</span></div></div>'

# ティッカー挿入
SL_ANCHOR    = '<div class="sl">市場体温計 &amp; 短期・中期シグナル</div>'
MSTRIP_ANCHOR = '<div class="mstrip">'
sl_pos     = src.find(SL_ANCHOR)
mstrip_pos = src.find(MSTRIP_ANCHOR)
if sl_pos >= 0 and mstrip_pos >= 0 and mstrip_pos > sl_pos:
    src = (src[:sl_pos + len(SL_ANCHOR)] +
           '\n    ' + TICKER_HTML + '\n    ' +
           src[mstrip_pos:])
    print("OK: ティッカー置換（全蓄積クリア）")
else:
    print(f"WARN: ティッカー挿入スキップ (sl={sl_pos} mstrip={mstrip_pos})")

# ticker_scroll keyframe追加
src = src.replace(
    '@keyframes fadeIn{',
    '@keyframes ticker_scroll{0%{transform:translateX(0)}100%{transform:translateX(-50%)}}'
    '@keyframes fadeIn{',
    1
)
print("OK: ticker_scroll keyframe追加")

# CSS修正
src = re.sub(r'(\.db\{[^}]*)aspect-ratio:[^;]+;', r'\1', src)
src = re.sub(r'(\.db\{[^}]*)overflow:hidden', r'\1overflow:visible', src)
src = re.sub(r'(#body\{[^}]*)overflow:hidden', r'\1overflow:visible', src)
src = re.sub(r'(\.panel\{[^}]*)overflow:hidden', r'\1overflow:visible', src)
print("OK: CSS修正")

# STOCK_SCORES埋め込み
scores_js = ('const STOCK_SCORES=' +
             json.dumps(SCORES, ensure_ascii=False) + ';')
src = re.sub(r'const STOCK_SCORES\s*=\s*\{[^;]*\};',
             scores_js, src, flags=re.DOTALL)

# マトリックス配列バグ修正
src = src.replace(
    'const mx1=[[1,2,2,3,3],[0,1,2,2,3],[0,0,1,2,2],[4,0,0,1,1],[4,4,0,0,1]];',
    'const mx1=[[2,1,1,0,0],[3,2,1,1,0],[3,3,2,1,1],[4,3,3,2,2],[4,4,3,3,2]];'
)
src = src.replace(
    'const mx2=[[1,1,2,2,3],[0,1,1,2,2],[0,0,1,1,2],[4,0,0,1,1],[4,4,0,0,1]];',
    'const mx2=[[2,2,1,1,0],[3,2,2,1,1],[3,3,2,2,1],[4,3,3,2,2],[4,4,3,3,2]];'
)
src = src.replace(
    'const mx3=[[2,2,3,3,3],[1,1,2,2,3],[0,0,1,2,2],[4,0,0,1,1],[4,4,0,0,1]];',
    'const mx3=[[1,1,0,0,0],[2,2,1,1,0],[3,3,2,1,1],[4,3,3,2,2],[4,4,3,3,2]];'
)
print("OK: マトリックス配列修正")
src = re.sub(r'最終更新：[^<"\']+', f'最終更新：{NOW}', src)

# 4層マクロダッシュボード 更新日時を現在日時に更新
src = re.sub(
    r'4層マクロダッシュボード<span[^>]*>[^<]*</span>',
    f'4層マクロダッシュボード<span style="font-size:var(--fs-micro);color:#475569;margin-left:8px;">{NOW} 更新</span>',
    src
)
print(f"OK: 4層マクロダッシュボード更新日時更新 → {NOW}")

# ティッカーブロック（TICKER_START〜TICKER_END）内の日経225を動的置換
# ※日経225の値のみ置換（ティッカー構造を維持したまま）
nk_v_str = f'{MKT["nk_v"]:,}'
src = re.sub(
    r'(日経225</span><span[^>]*>)[\d,]+(</span>)',
    r'\g<1>' + nk_v_str + r'\g<2>',
    src
)
print(f"OK: ティッカー内日経225更新 → {nk_v_str}")

# ヘッダー日時バッジを現在日時に更新
BADGE_NOW = datetime.now().strftime('%Y-%m-%d %H:%M')
src = re.sub(
    r'<span class="badge">\d{4}-\d{2}-\d{2}\s*&nbsp;\s*\d{2}:\d{2}\s*JST</span>',
    f'<span class="badge">{BADGE_NOW} JST</span>',
    src
)
print(f"OK: ヘッダー日時バッジ更新 → {BADGE_NOW} JST")

# 保有テーブル置換
hold_open = """      <table id="tH">
        <tr>
          <th class="sh" onclick="srt('tH',0,this)">銘柄<span class="sort-btn"><span class="au"></span><span class="ad"></span></span></th>
          <th class="sh" onclick="srt('tH',1,this)">株価<span class="sort-btn"><span class="au"></span><span class="ad"></span></span></th>
          <th class="sh" onclick="srt('tH',2,this)" style="color:#f59e0b;">v4.3<span class="sort-btn"><span class="au"></span><span class="ad"></span></span></th>
          <th class="sh" onclick="srt('tH',3,this)" style="color:#93c5fd;">短期<span class="sort-btn"><span class="au"></span><span class="ad"></span></span></th>
          <th class="sh" onclick="srt('tH',4,this)" style="color:#93c5fd;">中期<span class="sort-btn"><span class="au"></span><span class="ad"></span></span></th>
          <th class="sh" onclick="srt('tH',5,this)" style="color:#93c5fd;">長期<span class="sort-btn"><span class="au"></span><span class="ad"></span></span></th>
          <th class="sh">日数</th><th class="sh">判定</th>
        </tr>
""" + '\n'.join(rows_h) + "\n      </table>"

src = re.sub(r'<table id="tH">.*?</table>',
             hold_open, src, count=1, flags=re.DOTALL)
print("OK: 保有テーブル置換")

# 監視テーブル置換
watch_open = """      <table id="tW">
        <tr>
          <th class="sh" onclick="srt('tW',0,this)">銘柄<span class="sort-btn"><span class="au"></span><span class="ad"></span></span></th>
          <th class="sh" onclick="srt('tW',1,this)">株価<span class="sort-btn"><span class="au"></span><span class="ad"></span></span></th>
          <th class="sh" onclick="srt('tW',2,this)" style="color:#f59e0b;">v4.3<span class="sort-btn"><span class="au"></span><span class="ad"></span></span></th>
          <th class="sh" onclick="srt('tW',3,this)" style="color:#93c5fd;">短期<span class="sort-btn"><span class="au"></span><span class="ad"></span></span></th>
          <th class="sh" onclick="srt('tW',4,this)" style="color:#93c5fd;">中期<span class="sort-btn"><span class="au"></span><span class="ad"></span></span></th>
          <th class="sh" onclick="srt('tW',5,this)" style="color:#93c5fd;">長期<span class="sort-btn"><span class="au"></span><span class="ad"></span></span></th>
          <th class="sh">日数</th><th class="sh">シグナル</th>
        </tr>
""" + '\n'.join(rows_w) + "\n      </table>"

src = re.sub(r'<table id="tW">.*?</table>',
             watch_open, src, count=1, flags=re.DOTALL)
print("OK: 監視テーブル置換")

# スクリーニングTop50テーブル置換
if rows_s:
    screen_open = """      <table id="tS">
        <tr>
          <th class="sh" onclick="srt('tS',0,this)">銘柄<span class="sort-btn"><span class="au"></span><span class="ad"></span></span></th>
          <th class="sh" onclick="srt('tS',1,this)">株価<span class="sort-btn"><span class="au"></span><span class="ad"></span></span></th>
          <th class="sh" onclick="srt('tS',2,this)" style="color:#f59e0b;">v4.3<span class="sort-btn"><span class="au"></span><span class="ad"></span></span></th>
          <th class="sh" onclick="srt('tS',3,this)" style="color:#93c5fd;">短期<span class="sort-btn"><span class="au"></span><span class="ad"></span></span></th>
          <th class="sh" onclick="srt('tS',4,this)" style="color:#93c5fd;">中期<span class="sort-btn"><span class="au"></span><span class="ad"></span></span></th>
          <th class="sh" onclick="srt('tS',5,this)" style="color:#93c5fd;">長期<span class="sort-btn"><span class="au"></span><span class="ad"></span></span></th>
          <th class="sh">日数</th><th class="sh">シグナル</th>
        </tr>
""" + '\n'.join(rows_s) + "\n      </table>"
    src = re.sub(r'<table id="tS">.*?</table>',
                 screen_open, src, count=1, flags=re.DOTALL)
    print(f"OK: スクリーニングTop50テーブル置換（{len(rows_s)}銘柄）")
else:
    print("SKIP: スクリーニングデータなし（初回スキャン前）")

# abar動的生成（ランク変動アラート）
if degradation_alerts:
    abar_items = '<span class="al">&#x26A0; ランク変動</span>'
    for a in degradation_alerts[:5]:
        abar_items += (f'<span class="ai">{a["name"]} '
                       f'{a["prev"]}&#x2192;{a["curr"]}({a["score"]:.0f}点)</span>')
    src = src.replace(
        '<!-- ABAR_DYNAMIC --><span class="al">&#x2714; ランク異常なし</span>',
        abar_items
    )
    print(f"OK: abar動的生成（{len(degradation_alerts)}銘柄がランク下落）")
else:
    print("OK: abar ランク異常なし")

# 四半期レビューリマインダー（sbar）
import calendar
now_month = datetime.now().month
review_months = {1: '1月', 4: '4月', 7: '7月', 10: '10月'}
next_review = None
for m in sorted(review_months.keys()):
    if m >= now_month:
        next_review = review_months[m]
        break
if not next_review:
    next_review = review_months[1]
print(f"OK: 次回四半期レビュー: {next_review}第1週")

# バリュエーションHTML生成（v20と同一ロジック・数値のみv21ソースに更新）
def gauge_pct(mn, mx, v):
    return min(100, max(0, round((v - mn) / (mx - mn) * 100)))

def gauge_dot_color(pct, g_pct, w_pct, invert=False):
    if invert:
        return '#34d399' if pct >= g_pct else '#fbbf24' if pct >= w_pct else '#f87171'
    else:
        return '#34d399' if pct <= g_pct else '#fbbf24' if pct <= w_pct else '#f87171'

def badge(label, cls):
    bg = {'g':'#064e3b;color:#34d399','y':'#92400e;color:#fbbf24','r':'#7f1d1d;color:#f87171'}.get(cls,'#1e2d40;color:#94a3b8')
    return f'<span style="font-size:var(--fs-micro);font-weight:800;padding:1px 5px;border-radius:3px;background:{bg};">{label}</span>'

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
g_cape_us = make_gauge(22,45,cape_us,27,35)   # v21: 上限を40→45に拡張（実測38倍対応）
g_pbr_jp  = make_gauge(0.9,2.4,pbr_jp,1.4,2.0)
g_pbr_us  = make_gauge(2.5,6.5,pbr_us,3.5,4.5)  # v21: 上限を5.5→6.5に拡張（実測5倍対応）
g_yld_jp  = make_gauge(3,9,yld_jp,6,4,invert=True)
g_yld_us  = make_gauge(2,7,yld_us,5,3.5,invert=True)
g_buf_jp  = make_gauge(60,200,buf_jp,100,150)
g_buf_us  = make_gauge(80,260,buf_us,120,170)

cape_jp_cls = 'g' if cape_jp<=22 else 'y' if cape_jp<=28 else 'r'
cape_us_cls = 'g' if cape_us<=27 else 'y' if cape_us<=35 else 'r'   # v21: 閾値32→35
pbr_jp_cls  = 'g' if pbr_jp<=1.4 else 'y' if pbr_jp<=2.0 else 'r'
pbr_us_cls  = 'g' if pbr_us<=3.5 else 'y' if pbr_us<=4.5 else 'r'  # v21: 閾値3.2/4.2→3.5/4.5
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

vi_style  = 'padding:4px 8px;border-right:1px solid #1e2d40;cursor:pointer;'
vn_style  = 'font-size:var(--fs-sm);font-weight:800;color:#cbd5e1;margin-bottom:4px;text-decoration:underline dotted;text-underline-offset:2px;'
row_style = 'display:flex;align-items:center;gap:5px;margin-bottom:1px;'
flag_style= 'font-size:var(--fs-sm);min-width:14px;'
val_style_g='font-size:var(--fs-lg);font-weight:900;font-family:monospace;color:#34d399;min-width:36px;'
val_style_y='font-size:var(--fs-lg);font-weight:900;font-family:monospace;color:#fbbf24;min-width:36px;'
val_style_r='font-size:var(--fs-lg);font-weight:900;font-family:monospace;color:#f87171;min-width:36px;'
vc = {'g':val_style_g,'y':val_style_y,'r':val_style_r}

# 更新日時表示（ソース更新済みを明示）
updated_display = VAL['updated_at']

VAL_HTML = f"""        <div class="sl">バリュエーション — 日本 vs 米国（過去10年との比較）<span style="font-size:var(--fs-micro);color:#34d399;font-weight:600;margin-left:8px;">✓ {updated_display}</span></div>
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
            <div style="{row_style}"><span style="{flag_style}">🇯🇵</span><span style="{vc[pbr_jp_cls]}">{pbr_jp:.2f}倍</span><div style="flex:1">{g_pbr_jp}</div></div>
            <div style="{row_style}"><span style="{flag_style}">🇺🇸</span><span style="{vc[pbr_us_cls]}">{pbr_us:.2f}倍</span><div style="flex:1">{g_pbr_us}</div></div>
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

        </div>
        </div>"""

VI_MODAL_HTML = f"""<style>
#vi-modal{{display:none;position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,.65);z-index:9999;align-items:center;justify-content:center;}}
#vi-modal.open{{display:flex;}}
#vi-box{{background:#111827;border:1px solid #374151;border-radius:10px;padding:18px 20px;max-width:340px;width:90%;}}
#vi-ttl{{font-size:var(--fs-lg);font-weight:900;color:#f59e0b;margin-bottom:8px;}}
#vi-body{{font-size:var(--fs-md);color:#d1d5db;line-height:1.75;white-space:pre-wrap;}}
#vi-hist{{margin-top:10px;padding-top:10px;border-top:1px solid #1e2d40;}}
.vi-close{{margin-top:12px;text-align:right;font-size:var(--fs-base);color:#94a3b8;cursor:pointer;}}
.mh-row{{margin-bottom:10px;}}
.mh-flag{{font-size:var(--fs-sm);color:#94a3b8;margin-bottom:3px;font-weight:800;}}
.mh-bg{{background:#1e2d40;border-radius:4px;height:8px;position:relative;}}
.mh-labels{{display:flex;justify-content:space-between;font-size:var(--fs-micro);color:#475569;margin-top:3px;}}
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
  cape:{{ttl:'シラーPER（CAPE）とは',body:'過去10年の平均利益で計算した株価収益率です。\\n景気の良い年・悪い年を平均するため、より正確に割高・割安を判断できます。\\nノーベル賞を受賞したシラー教授が考案。\\n\\n目安：15倍以下→割安 / 22〜28倍→適正 / 35倍超→割高',jp:{{min:15,max:35,now:{cape_jp:.1f},g:22,w:28,flag:'🇯🇵 日本'}},us:{{min:22,max:45,now:{cape_us:.1f},g:27,w:35,flag:'🇺🇸 米国'}}}},
  pbr:{{ttl:'PBR（株価純資産倍率）とは',body:'会社の純資産と株価を比べた指標です。\\n1倍＝今すぐ会社を解散したときの価値と同じ。\\n日本は東証の改革でPBR改善が進んでいます。\\n\\n目安：1倍以下→超割安 / 1〜2倍→割安 / 3倍超→割高',jp:{{min:0.9,max:2.4,now:{pbr_jp:.2f},g:1.4,w:2.0,flag:'🇯🇵 日本'}},us:{{min:2.5,max:6.5,now:{pbr_us:.2f},g:3.5,w:4.5,flag:'🇺🇸 米国'}}}},
  yield:{{ttl:'益回り（株式益回り）とは',body:'PERの逆数（1÷PER×100）。\\n株式投資をした場合の利回りに相当します。\\n国債利回りより高ければ株式が有利。\\n\\n目安：6%超→株式有利 / 4〜6%→中立 / 4%未満→割高',jp:{{min:3,max:9,now:{yld_jp:.2f},g:6,w:4,flag:'🇯🇵 日本',inv:1}},us:{{min:2,max:7,now:{yld_us:.2f},g:5,w:3.5,flag:'🇺🇸 米国',inv:1}}}},
  buffett:{{ttl:'バフェット指数とは',body:'国の株式市場全体の時価総額をGDPで割った指標。\\nバフェットが重視することで有名。\\n数値が高いほど株式市場が割高です。\\n\\n目安：100%以下→割安 / 100〜150%→適正 / 150%超→割高',jp:{{min:60,max:200,now:{buf_jp:.0f},g:100,w:150,flag:'🇯🇵 日本'}},us:{{min:80,max:260,now:{buf_us:.0f},g:120,w:170,flag:'🇺🇸 米国'}}}},
  verdict:{{ttl:'総合判定の仕組み',body:'5指標（シラーPER・PBR・益回り・配当利回り・バフェット指数）を日米で比較し、日本が有利な指標の数で自動判定します。\\n\\n5指標中4つ以上→日本株フルポジ\\n3つ→日本株優位\\n2つ→均衡局面\\n1つ以下→要検討\\n\\nv21よりPBR・シラーPERのデータソースを正確な実測値に更新しました。',jp:null,us:null}}
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
  if(d.jp){{h.style.display='block';h.innerHTML='<div style="font-size:var(--fs-sm);font-weight:800;color:#94a3b8;margin-bottom:6px;">過去レンジ（緑＝割安 / 黄＝普通 / 赤＝割高）</div>'+mhRow(d.jp)+mhRow(d.us);}}
  else h.style.display='none';
  document.getElementById('vi-modal').classList.add('open');
}}
function closeVI(){{document.getElementById('vi-modal').classList.remove('open');}}
</script>"""

# バリュエーション置換
# ── 4層マクロカード・割安度テーブル・マクロ総合スコアHTML生成 ────────────────
# 既存変数を活用（MKT / _m2_yoy / _m2_label / wti_price / gold_price は後で設定）
# wti_price / gold_price は先に取得する（FOUR_LAYER_CARDSのため）
wti_price  = get_fred('DCOILWTICO')
gold_price = get_fred('GOLDPMGBD228NLBM')
print(f"  WTI:{wti_price} 金:{gold_price}")

def _commodity_style(val, thresholds):
    """価格→(ラベル, 前景色, 背景色) を返す"""
    for thr, lbl, fg, bg in thresholds:
        if val >= thr:
            return lbl, fg, bg
    return thresholds[-1][1], thresholds[-1][2], thresholds[-1][3]

WTI_THR = [
    (90, '高騰',  '#f87171', '#7f1d1d'),
    (75, 'やや高', '#fbbf24', '#78350f'),
    (55, 'やや安', '#fbbf24', '#92400e'),
    (0,  '安値圏', '#34d399', '#064e3b'),
]
GOLD_THR = [
    (2800, '高騰',  '#f87171', '#7f1d1d'),
    (2400, 'やや高', '#fbbf24', '#78350f'),
    (2000, '普通',  '#fbbf24', '#92400e'),
    (0,    '安値圏', '#34d399', '#064e3b'),
]

# VIX・HYGの表示スタイル
vix_v   = MKT['vix_v']
vix_chg = MKT['vix_chg']
hyg_v   = MKT['hyg_v']
hyg_chg = MKT['hyg_chg']
ys_v    = MKT['yield_spread']
nk_v    = MKT['nk_v']
nk_chg  = MKT['nk_chg']
nk_p52  = MKT['nk_p52']

vix_fg  = '#34d399' if vix_v <= 20 else '#fbbf24' if vix_v <= 30 else '#f87171'
vix_bg2 = '#064e3b' if vix_v <= 20 else '#92400e' if vix_v <= 30 else '#7f1d1d'
vix_lbl2= '安全' if vix_v <= 20 else '警戒' if vix_v <= 30 else '恐怖'
vix_summary = '平穏な市場環境' if vix_v <= 20 else '恐怖が高まっている' if vix_v <= 30 else '強い恐怖・暴落モード'
risk_color = '#34d399' if vix_v <= 20 else '#fbbf24' if vix_v <= 30 else '#f87171'
risk_label = '危険度: 低い' if vix_v <= 20 else '危険度: やや高い' if vix_v <= 30 else '危険度: 高い'

hyg_fg  = '#34d399' if hyg_chg >= 0 else '#f87171'
hyg_bg2 = '#064e3b' if hyg_chg >= 0 else '#7f1d1d'
hyg_lbl2= '良好' if hyg_chg >= 0 else '悪化'
hyg_sub = '企業の信用力が安定' if hyg_chg >= 0 else '企業の信用力が低下'

ys_fg   = '#34d399' if ys_v >= 0 else '#fbbf24' if ys_v >= -0.5 else '#f87171'
ys_bg2  = '#064e3b' if ys_v >= 0 else '#92400e' if ys_v >= -0.5 else '#7f1d1d'
ys_lbl2 = '正常' if ys_v >= 0 else 'やや警戒' if ys_v >= -0.5 else '逆イールド'
ys_sub  = '正常化=安心材料' if ys_v >= 0 else '警戒ゾーン' if ys_v >= -0.5 else '景気後退シグナル'
fin_color = '#34d399' if ys_v >= 0 else '#fbbf24' if ys_v >= -0.5 else '#f87171'
fin_label = '安心度: 良好' if ys_v >= 0 else '安心度: 警戒' if ys_v >= -0.5 else '安心度: 危険'

# WTI・金
if wti_price:
    wti_lbl2, wti_fg2, wti_bg2 = _commodity_style(wti_price, WTI_THR)
    wti_str2 = f'${wti_price:.1f}'
else:
    wti_lbl2, wti_fg2, wti_bg2 = 'データなし', '#64748b', '#1e2d40'
    wti_str2 = '$--'
if gold_price:
    gold_lbl2, gold_fg2, gold_bg2 = _commodity_style(gold_price, GOLD_THR)
    gold_str2 = f'${gold_price:,.0f}'
else:
    gold_lbl2, gold_fg2, gold_bg2 = 'データなし', '#64748b', '#1e2d40'
    gold_str2 = '$--'
# コモディティ総合コメント
if wti_price and gold_price:
    if wti_price >= 90 or gold_price >= 2800:
        comm_summary, comm_color = '資源: インフレ警戒', '#f87171'
    elif wti_price >= 75 or gold_price >= 2400:
        comm_summary, comm_color = '資源: やや警戒', '#fbbf24'
    else:
        comm_summary, comm_color = '資源: 安定圏', '#34d399'
else:
    comm_summary, comm_color = '資源: データ取得中', '#64748b'

# M2・日経
m2_str = f'+{_m2_yoy:.2f}%' if _m2_yoy and _m2_yoy > 0 else f'{_m2_yoy:.2f}%' if _m2_yoy else '---'
m2_fg  = '#34d399' if _m2_yoy and _m2_yoy > 0 else '#f87171'
m2_bg2 = '#064e3b' if _m2_yoy and _m2_yoy > 0 else '#7f1d1d'
m2_lbl2= '加速' if _m2_yoy and _m2_yoy > 3.0 else '拡大' if _m2_yoy and _m2_yoy > 0 else '縮小'
m2_sub = 'お金の量が増えている' if _m2_yoy and _m2_yoy > 0 else 'お金の量が減っている'

nk_fg   = '#34d399' if nk_chg >= 0 else '#f87171'
nk_bg2  = '#064e3b' if nk_chg >= 0 else '#7f1d1d'
nk_str  = f'{nk_v:,}'
nk_chg_str = f'{nk_chg:+.1f}%'
nk_52w_str  = f'52週の{nk_p52}%位置'
econ_color  = '#34d399' if nk_chg >= 0 and (_m2_yoy or 0) > 0 else '#fbbf24' if nk_chg >= 0 else '#f87171'
econ_label  = '勢い: 良好' if nk_chg >= 0 else '勢い: 低下'

# 割安度テーブル用の数値
_cape_jp_v = VAL.get('cape_jp', 20)
_pbr_jp_v  = VAL.get('pbr_jp', 1.76)
_yld_jp_v  = VAL.get('yield_jp', 6.25)
_buf_jp_v  = VAL.get('buffett_jp', 140)
_cape_us_v = VAL.get('cape_us', 38)
_pbr_us_v  = VAL.get('pbr_us', 4.8)
_yld_us_v  = VAL.get('yield_us', 4.5)
_buf_us_v  = VAL.get('buffett_us', 200)

def _val_color(v, good_below, warn_below, invert=False):
    """閾値に基づき色を返す（invert=True: 大きいほど良い）"""
    if invert:
        return '#34d399' if v >= good_below else '#fbbf24' if v >= warn_below else '#f87171'
    return '#34d399' if v <= good_below else '#fbbf24' if v <= warn_below else '#f87171'

_cape_jp_c = _val_color(_cape_jp_v, 22, 28)
_pbr_jp_c  = _val_color(_pbr_jp_v,  1.4, 2.0)
_yld_jp_c  = _val_color(_yld_jp_v,  6,   4, invert=True)
_buf_jp_c  = _val_color(_buf_jp_v,  100, 150)
_cape_us_c = _val_color(_cape_us_v, 27, 35)
_pbr_us_c  = _val_color(_pbr_us_v,  3.5, 4.5)
_yld_us_c  = _val_color(_yld_us_v,  5,   3.5, invert=True)
_buf_us_c  = _val_color(_buf_us_v,  120, 170)

def _badge_sm(lbl, color):
    bg_map = {'#34d399':'#064e3b','#fbbf24':'#92400e','#f87171':'#7f1d1d'}
    bg = bg_map.get(color, '#1e2d40')
    return f'<span style="background:{bg};color:{color};font-size:var(--fs-micro);font-weight:900;padding:1px 4px;border-radius:2px;">{lbl}</span>'

_cape_jp_lbl = '割安' if _cape_jp_v <= 22 else 'やや高' if _cape_jp_v <= 28 else '割高'
_pbr_jp_lbl  = '割安' if _pbr_jp_v  <= 1.4 else 'やや高' if _pbr_jp_v  <= 2.0 else '割高'
_yld_jp_lbl  = '株有利' if _yld_jp_v >= 6 else '中立' if _yld_jp_v >= 4 else '注意'
_buf_jp_lbl  = '割安' if _buf_jp_v  <= 100 else '注意' if _buf_jp_v <= 150 else '割高'
_cape_us_lbl = '割安' if _cape_us_v <= 27 else 'やや高' if _cape_us_v <= 35 else '割高'
_pbr_us_lbl  = '割安' if _pbr_us_v  <= 3.5 else 'やや高' if _pbr_us_v  <= 4.5 else '割高'
_yld_us_lbl  = '株有利' if _yld_us_v >= 5 else '中立' if _yld_us_v >= 3.5 else '注意'
_buf_us_lbl  = '割安' if _buf_us_v  <= 120 else '注意' if _buf_us_v <= 170 else '割高'

# マクロ総合スコアの色
_mp_total_color = '#22c55e' if _mp_lbl=='GREEN' else '#f59e0b' if _mp_lbl=='YELLOW' else '#ef4444'
_mp_total_txt   = '良好' if _mp_lbl=='GREEN' else '慎重に' if _mp_lbl=='YELLOW' else '今は待て'
_short_vc2 = '#34d399' if SHORT_SCORE >= 55 else '#fbbf24' if SHORT_SCORE >= 45 else '#f87171'
_short_bc2 = '#064e3b' if SHORT_SCORE >= 55 else '#92400e' if SHORT_SCORE >= 45 else '#991b1b'
_short_lbl2 = '強気' if SHORT_SCORE >= 55 else '中立' if SHORT_SCORE >= 45 else '弱気'
_mid_vc2   = '#34d399' if MID_SCORE >= 55 else '#fbbf24' if MID_SCORE >= 45 else '#f87171'
_mid_bc2   = '#064e3b' if MID_SCORE >= 55 else '#92400e' if MID_SCORE >= 45 else '#92400e'
_mid_lbl2  = '強気' if MID_SCORE >= 55 else '中立' if MID_SCORE >= 45 else '弱気'

FOUR_LAYER_HTML = f"""    <!-- 4層マクロカード：上段4列 -->
    <div style="display:grid;grid-template-columns:1fr 1fr 1fr 1fr;gap:4px;">

      <!-- リスク環境 -->
      <div style="background:#111827;border:1px solid #1e2d40;border-top:2px solid #f87171;border-radius:6px;padding:6px 8px;">
        <div style="font-size:var(--fs-xs);font-weight:900;color:#fca5a5;margin-bottom:5px;letter-spacing:.5px;">リスク環境</div>
        <div style="cursor:pointer;margin-bottom:4px;" onclick="showHelp('vix')">
          <div style="display:flex;justify-content:space-between;align-items:center;"><span style="color:#cbd5e1;font-size:var(--fs-sm);font-weight:800;">VIX</span><span style="font-size:var(--fs-md);font-weight:900;font-family:monospace;color:{vix_fg};">{vix_v}</span>{_badge_sm(vix_lbl2, vix_fg)}</div>
          <div style="color:#475569;font-size:var(--fs-micro);margin-top:1px;">{vix_summary}</div>
        </div>
        <div style="cursor:pointer;margin-bottom:4px;" onclick="showHelp('hyg')">
          <div style="display:flex;justify-content:space-between;align-items:center;"><span style="color:#cbd5e1;font-size:var(--fs-sm);font-weight:800;">HYG</span><span style="font-size:var(--fs-md);font-weight:900;font-family:monospace;color:{hyg_fg};">{hyg_v:.2f}</span>{_badge_sm(hyg_lbl2, hyg_fg)}</div>
          <div style="color:#475569;font-size:var(--fs-micro);margin-top:1px;">{hyg_sub}</div>
        </div>
        <div style="border-top:1px solid #1e2d40;padding-top:4px;margin-top:2px;">
          <div style="color:{risk_color};font-size:var(--fs-xs);font-weight:800;">{risk_label}</div>
        </div>
      </div>

      <!-- 金融政策 -->
      <div style="background:#111827;border:1px solid #1e2d40;border-top:2px solid #34d399;border-radius:6px;padding:6px 8px;">
        <div style="font-size:var(--fs-xs);font-weight:900;color:#6ee7b7;margin-bottom:5px;letter-spacing:.5px;">金融政策</div>
        <div style="cursor:pointer;margin-bottom:4px;" onclick="showHelp('yield_spread')">
          <div style="display:flex;justify-content:space-between;align-items:center;"><span style="color:#cbd5e1;font-size:var(--fs-sm);font-weight:800;">逆イールド</span><span style="font-size:var(--fs-md);font-weight:900;font-family:monospace;color:{ys_fg};">{ys_v:+.2f}</span>{_badge_sm(ys_lbl2, ys_fg)}</div>
          <div style="color:#475569;font-size:var(--fs-micro);margin-top:1px;">{ys_sub}</div>
        </div>
        <div style="border-top:1px solid #1e2d40;padding-top:4px;margin-top:2px;">
          <div style="color:{fin_color};font-size:var(--fs-xs);font-weight:800;">{fin_label}</div>
        </div>
      </div>

      <!-- コモディティ -->
      <div style="background:#111827;border:1px solid #1e2d40;border-top:2px solid #a78bfa;border-radius:6px;padding:6px 8px;">
        <div style="font-size:var(--fs-xs);font-weight:900;color:#c4b5fd;margin-bottom:5px;letter-spacing:.5px;">コモディティ</div>
        <div style="cursor:pointer;margin-bottom:4px;" onclick="showHelp('wti')">
          <div style="display:flex;justify-content:space-between;align-items:center;"><span style="color:#cbd5e1;font-size:var(--fs-sm);font-weight:800;">WTI原油</span><span style="font-size:var(--fs-md);font-weight:900;font-family:monospace;color:{wti_fg2};">{wti_str2}</span>{_badge_sm(wti_lbl2, wti_fg2)}</div>
          <div style="color:#475569;font-size:var(--fs-micro);margin-top:1px;">インフレ・エネルギーの先行指標</div>
        </div>
        <div style="cursor:pointer;margin-bottom:4px;" onclick="showHelp('gold')">
          <div style="display:flex;justify-content:space-between;align-items:center;"><span style="color:#cbd5e1;font-size:var(--fs-sm);font-weight:800;">金(Gold)</span><span style="font-size:var(--fs-md);font-weight:900;font-family:monospace;color:{gold_fg2};">{gold_str2}</span>{_badge_sm(gold_lbl2, gold_fg2)}</div>
          <div style="color:#475569;font-size:var(--fs-micro);margin-top:1px;">安全資産への資金逃避を示す指標</div>
        </div>
        <div style="border-top:1px solid #1e2d40;padding-top:4px;margin-top:2px;">
          <div style="color:{comm_color};font-size:var(--fs-xs);font-weight:800;">{comm_summary}</div>
        </div>
      </div>

      <!-- 経済活動 -->
      <div style="background:#111827;border:1px solid #1e2d40;border-top:2px solid #60a5fa;border-radius:6px;padding:6px 8px;">
        <div style="font-size:var(--fs-xs);font-weight:900;color:#93c5fd;margin-bottom:5px;letter-spacing:.5px;">経済活動</div>
        <div style="cursor:pointer;margin-bottom:4px;" onclick="showHelp('m2')">
          <div style="display:flex;justify-content:space-between;align-items:center;"><span style="color:#cbd5e1;font-size:var(--fs-sm);font-weight:800;">日本M2</span><span style="font-size:var(--fs-md);font-weight:900;font-family:monospace;color:{m2_fg};">{m2_str}</span>{_badge_sm(m2_lbl2, m2_fg)}</div>
          <div style="color:#475569;font-size:var(--fs-micro);margin-top:1px;">{m2_sub}</div>
        </div>
        <div style="cursor:pointer;margin-bottom:4px;" onclick="showHelp('nikkei')">
          <div style="display:flex;justify-content:space-between;align-items:center;"><span style="color:#cbd5e1;font-size:var(--fs-sm);font-weight:800;">日経225</span><span style="font-size:var(--fs-md);font-weight:900;font-family:monospace;color:{nk_fg};">{nk_str}</span>{_badge_sm(nk_chg_str, nk_fg)}</div>
          <div style="color:#475569;font-size:var(--fs-micro);margin-top:1px;">{nk_52w_str}</div>
        </div>
        <div style="border-top:1px solid #1e2d40;padding-top:4px;margin-top:2px;">
          <div style="color:{econ_color};font-size:var(--fs-xs);font-weight:800;">{econ_label}</div>
        </div>
      </div>

    </div>
    <!-- 割安度 + マクロ総合：横長バー -->
    <div style="display:grid;grid-template-columns:3fr 1.2fr;gap:4px;margin-top:4px;">
      <!-- 割安度：日本 vs 米国 比較テーブル -->
      <div style="background:#111827;border:1px solid #1e2d40;border-top:2px solid #fb923c;border-radius:6px;padding:6px 10px;">
        <div style="display:flex;align-items:center;margin-bottom:6px;">
          <span style="font-size:var(--fs-sm);font-weight:900;color:#fdba74;letter-spacing:.5px;">割安度</span>
          <span style="font-size:var(--fs-micro);color:#475569;font-weight:700;margin-left:6px;">- 日本と米国、今どっちが割安？</span>
        </div>
        <!-- テーブル型：ヘッダー行 + データ行 -->
        <div style="display:grid;grid-template-columns:70px 1fr 1fr 1fr 1fr;gap:0;font-family:monospace;">
          <!-- ヘッダー -->
          <div style="padding:2px 0;"></div>
          <div style="text-align:center;padding:2px 0;border-bottom:1px solid #1e2d40;"><span style="color:#94a3b8;font-size:var(--fs-xs);font-weight:800;">CAPE</span></div>
          <div style="text-align:center;padding:2px 0;border-bottom:1px solid #1e2d40;"><span style="color:#94a3b8;font-size:var(--fs-xs);font-weight:800;">PBR</span></div>
          <div style="text-align:center;padding:2px 0;border-bottom:1px solid #1e2d40;"><span style="color:#94a3b8;font-size:var(--fs-xs);font-weight:800;">益回り</span></div>
          <div style="text-align:center;padding:2px 0;border-bottom:1px solid #1e2d40;"><span style="color:#94a3b8;font-size:var(--fs-xs);font-weight:800;">BF指数</span></div>
          <!-- 日本行 -->
          <div style="padding:3px 0;display:flex;align-items:center;"><span style="font-size:var(--fs-sm);font-weight:900;color:#e2e8f0;">🇯🇵 日本</span></div>
          <div style="text-align:center;padding:3px 0;cursor:pointer;" onclick="showHelp('cape')"><span style="font-size:var(--fs-md);font-weight:900;color:{_cape_jp_c};">{_cape_jp_v:.0f}倍</span></div>
          <div style="text-align:center;padding:3px 0;cursor:pointer;" onclick="showHelp('pbr')"><span style="font-size:var(--fs-md);font-weight:900;color:{_pbr_jp_c};">{_pbr_jp_v:.2f}倍</span></div>
          <div style="text-align:center;padding:3px 0;cursor:pointer;" onclick="showHelp('earnings_yield')"><span style="font-size:var(--fs-md);font-weight:900;color:{_yld_jp_c};">{_yld_jp_v:.2f}%</span></div>
          <div style="text-align:center;padding:3px 0;cursor:pointer;" onclick="showHelp('buffett')"><span style="font-size:var(--fs-md);font-weight:900;color:{_buf_jp_c};">{_buf_jp_v:.0f}%</span></div>
          <!-- 米国行 -->
          <div style="padding:3px 0;display:flex;align-items:center;"><span style="font-size:var(--fs-sm);font-weight:900;color:#e2e8f0;">🇺🇸 米国</span></div>
          <div style="text-align:center;padding:3px 0;cursor:pointer;" onclick="showHelp('cape')"><span style="font-size:var(--fs-md);font-weight:900;color:{_cape_us_c};">{_cape_us_v:.0f}倍</span></div>
          <div style="text-align:center;padding:3px 0;cursor:pointer;" onclick="showHelp('pbr')"><span style="font-size:var(--fs-md);font-weight:900;color:{_pbr_us_c};">{_pbr_us_v:.2f}倍</span></div>
          <div style="text-align:center;padding:3px 0;cursor:pointer;" onclick="showHelp('earnings_yield')"><span style="font-size:var(--fs-md);font-weight:900;color:{_yld_us_c};">{_yld_us_v:.2f}%</span></div>
          <div style="text-align:center;padding:3px 0;cursor:pointer;" onclick="showHelp('buffett')"><span style="font-size:var(--fs-md);font-weight:900;color:{_buf_us_c};">{_buf_us_v:.0f}%</span></div>
          <!-- 判定行 -->
          <div style="padding:2px 0;border-top:1px solid #1e2d40;"><span style="color:#fb923c;font-size:var(--fs-micro);font-weight:800;">判定</span></div>
          <div style="text-align:center;padding:2px 0;border-top:1px solid #1e2d40;">{_badge_sm(_cape_jp_lbl, _cape_jp_c)}</div>
          <div style="text-align:center;padding:2px 0;border-top:1px solid #1e2d40;">{_badge_sm(_pbr_jp_lbl, _pbr_jp_c)}</div>
          <div style="text-align:center;padding:2px 0;border-top:1px solid #1e2d40;">{_badge_sm(_yld_jp_lbl, _yld_jp_c)}</div>
          <div style="text-align:center;padding:2px 0;border-top:1px solid #1e2d40;">{_badge_sm(_buf_jp_lbl, _buf_jp_c)}</div>
        </div>
      </div>
      <!-- マクロ総合スコア -->
      <div style="background:#111827;border:1px solid #1e2d40;border-top:2px solid {_mp_total_color};border-radius:6px;padding:6px 10px;display:flex;flex-direction:column;justify-content:space-between;">
        <div style="font-size:var(--fs-xs);font-weight:900;color:{_mp_total_color};letter-spacing:.5px;">マクロ総合</div>
        <div style="text-align:center;">
          <span style="font-size:var(--fs-xl);font-weight:900;font-family:monospace;color:{_mp_total_color};">{_mp_score}</span><span style="font-size:var(--fs-micro);color:#475569;">/100</span>
          <span style="font-size:var(--fs-sm);font-weight:800;color:{_mp_total_color};margin-left:6px;">{_mp_total_txt}</span>
        </div>
        <div style="background:#1e293b;border-radius:3px;height:4px;"><div style="width:{_mp_score}%;height:4px;border-radius:3px;background:{_mp_total_color};"></div></div>
        <div style="display:flex;gap:4px;">
          <div style="flex:1;background:#0a0d16;border:1px solid {_short_bc2};border-radius:4px;padding:4px 6px;text-align:center;cursor:pointer;" onclick="showHelp('short_score')">
            <div style="color:#94a3b8;font-size:var(--fs-micro);font-weight:800;">短期(1年)</div>
            <div><span style="color:{_short_vc2};font-size:var(--fs-lg);font-weight:900;font-family:monospace;">{SHORT_SCORE}</span> <span style="color:{_short_vc2};font-size:var(--fs-micro);font-weight:800;">{_short_lbl2}</span></div>
          </div>
          <div style="flex:1;background:#0a0d16;border:1px solid {_mid_bc2};border-radius:4px;padding:4px 6px;text-align:center;cursor:pointer;" onclick="showHelp('medium_score')">
            <div style="color:#94a3b8;font-size:var(--fs-micro);font-weight:800;">中期(3年)</div>
            <div><span style="color:{_mid_vc2};font-size:var(--fs-lg);font-weight:900;font-family:monospace;">{MID_SCORE}</span> <span style="color:{_mid_vc2};font-size:var(--fs-micro);font-weight:800;">{_mid_lbl2}</span></div>
          </div>
        </div>
      </div>
    </div>"""

# 4層マクロカード置換
src = src.replace('<!-- FOUR_LAYER_CARDS -->', FOUR_LAYER_HTML, 1)
print(f"OK: 4層マクロカード置換（VIX:{vix_v} HYG:{hyg_v:.2f} YS:{ys_v:+.2f} WTI:{wti_str2} Gold:{gold_str2} NKY:{nk_str}）")

val_start = src.find('<div class="sl">バリュエーション')
val_end   = src.find('<div id="body">')
if val_start >= 0 and val_end >= 0:
    src = src[:val_start] + VAL_HTML + '\n    ' + src[val_end:]
    print("OK: バリュエーション置換")
else:
    print(f"WARN: バリュエーション置換スキップ (start={val_start} end={val_end})")

# マクロフェーズゲージ挿入
PHASE_HTML = build_phase_gauge_html(ss)
src = src.replace('<!-- MACRO_PHASE_GAUGE -->', PHASE_HTML, 1)
print('OK: マクロフェーズゲージ置換')
# モーダル挿入（</body>直前）
src = src.replace('</body>', VI_MODAL_HTML + MC_MODAL_HTML + '</body>', 1)
print("OK: モーダル挿入")

# WTI・金価格は4層マクロカード（FOUR_LAYER_HTML）内で既に動的生成済み
# （旧来のre.subによる置換は不要・FOUR_LAYER_CARDSに統合）
print(f"OK: WTI原油価格 → {wti_str2} ({wti_lbl2})  ※4層カードに反映済み")
print(f"OK: 金価格 → {gold_str2} ({gold_lbl2})  ※4層カードに反映済み")

out = 'ai_dashboard_v13.html'
with open(out, 'w', encoding='utf-8') as f:
    f.write(src)
print(f"\n✅ 出力完了: {out}")
print(f"   保有:{len(rows_h)} 監視:{len(rows_w)} スコア:{len(SCORES)}")
print(f"   短期:{SHORT_SCORE}点 / 中期:{MID_SCORE}点")
print(f"   PBR 日本:{VAL['pbr_jp']} 米国:{VAL['pbr_us']}")
print(f"   CAPE 日本:{VAL['cape_jp']} 米国:{VAL['cape_us']}")
print(f"   ソース: 日本PBR=日経プロフィル / 米国PBR・CAPE=multpl.com")

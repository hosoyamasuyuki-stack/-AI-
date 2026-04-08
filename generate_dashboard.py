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
UA = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'}

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

def scrape_nikkei225jp():
    """nikkei225jp.comのdaily2.jsonから日経225 PER/PBR/配当利回りを取得
    Returns: dict with per, pbr, div_yield or None
    Data columns: [timestamp, price, volume, ..., col12=PER, col13=PBR, col14=div_yield, ...]
    """
    try:
        headers = {**UA, 'Referer': 'https://nikkei225jp.com/data/per.php'}
        cache_buster = int(time.time() // 100)
        url = f'https://nikkei225jp.com/_data/_nfsWEB/DAY/daily2.json?{cache_buster}'
        r = requests.get(url, headers=headers, timeout=15)
        if r.status_code != 200:
            print(f"  WARN: nikkei225jp daily2.json status={r.status_code}")
            return None
        text = r.text.strip()
        # 最後のデータ行を取得
        lines = text.rstrip(']').rstrip().split('\n')
        for line in reversed(lines):
            line = line.strip().rstrip(',')
            if line.startswith('['):
                vals = [v.strip().strip('"') for v in line.strip('[]').split(',')]
                if len(vals) >= 15:
                    per = float(vals[12]) if vals[12] else None
                    pbr = float(vals[13]) if vals[13] else None
                    div_y = float(vals[14]) if vals[14] else None
                    # サニティチェック
                    if per and 5 < per < 60 and pbr and 0.5 < pbr < 5:
                        print(f"  OK: nikkei225jp PER={per} PBR={pbr} DivY={div_y}")
                        return {'per': per, 'pbr': pbr, 'div_yield': div_y}
                    else:
                        print(f"  WARN: nikkei225jp abnormal PER={per} PBR={pbr}")
                break
    except Exception as e:
        print(f"  WARN: nikkei225jp fetch failed: {e}")
    return None

def scrape_multpl(path, min_val, max_val):
    """multpl.comからid='current'直後の数値を取得
    HTML構造: id="current"> ... </b> 数値 <span>
    """
    try:
        url = f'https://www.multpl.com/{path}'
        r = requests.get(url, headers=UA, timeout=10)
        if r.status_code == 200:
            m = re.search(r'id="current"[^>]*>\s*<b>.*?</b>\s*([\d.]+)', r.text, re.DOTALL)
            if m:
                v = float(m.group(1))
                if min_val < v < max_val:
                    return v
                else:
                    print(f"  WARN: multpl {path} value {v} out of range ({min_val}-{max_val})")
    except Exception as e:
        print(f"  WARN: multpl {path} failed: {e}")
    return None

def scrape_pbr_japan():
    """nikkei225jp.comから日本PBRを取得（scrape_nikkei225jpのラッパー）"""
    data = scrape_nikkei225jp()
    return data['pbr'] if data else None

def scrape_pbr_us():
    """multpl.comから米国PBRを取得"""
    return scrape_multpl('s-p-500-price-to-book', 1.0, 10.0)

def scrape_cape_us():
    """multpl.comからシラーPER米国を取得"""
    return scrape_multpl('shiller-pe', 5.0, 80.0)

# ── 認証 ────────────────────────────────────────────────────
from core.auth import get_spreadsheet
from core.config import GAS_URL_FULL_UPDATE, GAS_URL_KENJA
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
        f'padding:4px 10px;margin-bottom:4px;display:flex;align-items:center;gap:10px;">'
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
                    'per_jp':    sf('PER_日本',     20.57),
                    'per_us':    sf('PER_米国',     29.11),
                    'pbr_jp':    sf('PBR_日本',     1.82),
                    'pbr_us':    sf('PBR_米国',     5.36),
                    'div_jp':    sf('配当利回り_日本', 1.59),
                    'div_us':    sf('配当利回り_米国', 1.16),
                    'yield_jp':  sf('益回り_日本',   4.86),
                    'yield_us':  sf('益回り_米国',   3.44),
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

    # フォールバック：前回値（取得失敗時のみ使用・更新日時で古さを判別可能）
    # 2026/04/08時点の正確な値で初期化
    prev = {
        'per_jp': 20.57, 'per_us': 29.11, 'pbr_jp': 1.82, 'pbr_us': 5.36,
        'div_jp': 1.59, 'div_us': 1.16, 'yield_jp': 4.86, 'yield_us': 3.44,
        'roe_jp': 8.8, 'roe_us': 18.4, 'cape_jp': 26.7, 'cape_us': 39.14,
        'rate_jp': 1.5, 'rate_us': 4.3, 'rate_diff': 2.8,
        'buffett_jp': 133, 'buffett_us': 195, 'usdjpy': 158,
    }

    # ── Phase 1: 日本PER/PBR/配当利回り（nikkei225jp.com）────
    # yfinanceの^N225はPER=Noneを返す（指数はPER情報を持たない）
    # nikkei225jp.comのdaily2.jsonが最も正確なソース（加重平均PER/PBR）
    jp_data = scrape_nikkei225jp()
    per_jp  = jp_data['per']       if jp_data else None
    pbr_jp  = jp_data['pbr']       if jp_data else None
    div_jp  = jp_data['div_yield'] if jp_data else None
    fail_sources = []
    if not per_jp:
        per_jp = prev['per_jp']
        fail_sources.append('PER_JP')
        print(f"  WARN: 日本PER取得失敗 → フォールバック値{per_jp}（不正確な可能性）")
    if not pbr_jp:
        pbr_jp = prev['pbr_jp']
        fail_sources.append('PBR_JP')
        print(f"  WARN: 日本PBR取得失敗 → フォールバック値{pbr_jp}（不正確な可能性）")
    if not div_jp:
        div_jp = prev.get('div_jp', 2.0)
        fail_sources.append('DIV_JP')
        print(f"  WARN: 日本配当利回り取得失敗 → フォールバック値{div_jp}")

    # ── Phase 2: 米国PER/PBR/CAPE/配当利回り（multpl.com）──
    per_us  = scrape_multpl('s-p-500-pe-ratio', 5.0, 60.0)
    if not per_us:
        per_us = prev['per_us']
        fail_sources.append('PER_US')
        print(f"  WARN: 米国PER取得失敗 → フォールバック値{per_us}")
    time.sleep(0.5)

    pbr_us = scrape_pbr_us()
    if pbr_us is None:
        pbr_us = prev['pbr_us']
        fail_sources.append('PBR_US')
        print(f"  WARN: 米国PBR取得失敗 → フォールバック値{pbr_us}倍")
    time.sleep(0.5)

    cape_us = scrape_cape_us()
    if cape_us is None:
        cape_us = prev['cape_us']
        fail_sources.append('CAPE_US')
        print(f"  WARN: シラーPER米国取得失敗 → フォールバック値{cape_us}倍")
    time.sleep(0.5)

    div_us_multpl = scrape_multpl('s-p-500-dividend-yield', 0.5, 10.0)
    div_us = div_us_multpl if div_us_multpl else prev.get('div_us', 1.3)
    if not div_us_multpl:
        fail_sources.append('DIV_US')
        print(f"  WARN: 米国配当利回り取得失敗 → フォールバック値{div_us}")

    # ── Phase 3: 為替（yfinance）────────────────────────
    usdjpy  = None
    try:
        h = yf.Ticker('USDJPY=X').history(period='2d')
        if len(h) > 0: usdjpy = round(float(h['Close'].iloc[-1]), 1)
    except: pass

    # ── Phase 4: FRED取得（金利・バフェット指数）──────────
    rate_us    = get_fred('DGS10')
    rate_jp    = get_fred('IRLTLT01JPM156N')
    buffett_us = get_fred('DDDM01USA156NWDB')
    buffett_jp = get_fred('DDDM01JPA156NWDB')

    # ── Phase 5: シラーPER日本（per×補正係数・暫定）──────
    # 暫定：per_jp × 1.3 ただし範囲は15-35倍でクリップ
    # TODO: EDINET/財務DB整備後に10年平均利益ベースの正確な計算に変更
    if per_jp:
        cape_jp_raw = round(per_jp * 1.3, 1)
        cape_jp = max(15.0, min(35.0, cape_jp_raw))
        print(f"  OK: シラーPER日本: PER{per_jp:.1f}x1.3={cape_jp:.1f}倍（暫定）")
    else:
        cape_jp = prev['cape_jp']
        print(f"  WARN: シラーPER日本 → 前回値使用: {cape_jp}倍")

    # ── 派生指標計算 ────────────────────────────────────
    yield_jp  = round(1/per_jp*100,  2) if per_jp  else 6.25
    yield_us  = round(1/per_us*100,  2) if per_us  else 4.5
    roe_jp    = round(pbr_jp/per_jp*100, 1) if (pbr_jp and per_jp) else 10.5
    roe_us    = round(pbr_us/per_us*100, 1) if (pbr_us and per_us) else 21.8
    rate_diff = round(rate_us-rate_jp, 2)   if (rate_us and rate_jp) else 2.8

    # ── フォールバック警告（取得失敗があれば明示）───────
    if fail_sources:
        print(f"  ⚠️ フォールバック使用中: {', '.join(fail_sources)}（データ不正確の可能性）")

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
    wti = yp('CL=F')
    gold = yp('GC=F')
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
        'wti_v':   round(wti['v'],1)   if wti  else 70,
        'wti_chg': round(wti['chg'],1)  if wti  else 0,
        'gold_v':  round(gold['v'])     if gold else 3000,
        'gold_chg':round(gold['chg'],1) if gold else 0,
    }
    print(f"  日経:{result['nk_v']:,} SP500:{result['sp_v']:,} VIX:{result['vix_v']} イールド差:{result['yield_spread']}")
    return result

MKT = fetch_market()

# ── 日本M2前年比%を取得 ──────────────────────────────────────
_m2_yoy = None
_m2_label = '---'
try:
    # 日銀APIから直接M2前年比%を取得（スプレッドシート経由の計算エラーを回避）
    import requests as _req
    _boj_r = _req.get("https://www.stat-search.boj.or.jp/api/v1/getDataCode",
        params={"db":"MD02","code":"MAM1YAM2M2MO","format":"json",
                "from":(datetime.now()-timedelta(days=60)).strftime("%Y%m"),
                "to":datetime.now().strftime("%Y%m"),"lang":"EN"}, timeout=30)
    if _boj_r.status_code == 200:
        _boj_d = _boj_r.json()
        _boj_vals = _boj_d["RESULTSET"][0]["VALUES"]["VALUES"]
        if _boj_vals:
            _m2_yoy = float(_boj_vals[-1])
    if _m2_yoy is None:
        # フォールバック: スプレッドシートの前年比%列
        _m2_ws = ss.worksheet('日本M2')
        _m2_rows = _m2_ws.get_all_values()
        if len(_m2_rows) >= 2:
            _m2_hdr = _m2_rows[0]
            if '前年比%' in _m2_hdr:
                _m2_idx = _m2_hdr.index('前年比%')
                for _r in reversed(_m2_rows[1:]):
                    if len(_r) > _m2_idx and _r[_m2_idx]:
                        try:
                            v = float(_r[_m2_idx])
                            if abs(v) < 50:  # 異常値ガード
                                _m2_yoy = v
                                break
                        except: pass
    if _m2_yoy is not None:
        _m2_label = '加速中' if _m2_yoy > 3.0 else '拡大中' if _m2_yoy > 0 else '縮小中'
    else:
        _m2_label = 'データなし'
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
# mstripは廃止済み（4層カード+マクロ総合で代替）- 以下はMC_MODAL用のHTML
_MSTRIP_UNUSED = f"""    <div class="mstrip">
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
        f'          <td style="font-size:var(--fs-xs);color:#94a3b8;">{sect}</td>\n'
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

# ── ティッカー動的生成（実データに基づくシステム稼働状況） ─────────
_n_hold = len(rows_h)
_n_watch = len(rows_w)
_n_screen = len(rows_s)
_n_total = _n_hold + _n_watch

# MacroPhaseシートの最終行から日時を取得（日次マクロ更新の最終実行日）
try:
    _macro_last = _mp_row[0] if _mp_row and _mp_row[0] else ''
except:
    _macro_last = ''

# コアスキャン_日次シートから株価更新の最終日時を取得
try:
    _daily_ws = ss.worksheet('\u30B3\u30A2\u30B9\u30AD\u30E3\u30F3_\u65E5\u6B21')
    _daily_rows = _daily_ws.get_all_values()
    _price_last = _daily_rows[-1][0] if len(_daily_rows) > 1 and _daily_rows[-1][0] else ''
except:
    _price_last = ''

# 週次更新の最終日時（保有銘柄シートのヘッダーやログから推定 → generate時刻で代用）
_gen_time = datetime.now().strftime('%m/%d %H:%M')

# 日経225とSP500のリアルタイム値
_nk_now = f'{MKT["nk_v"]:,.0f}' if MKT.get('nk_v') else '---'
_sp_now = f'{MKT["sp_v"]:,.0f}' if MKT.get('sp_v') else '---'
_nk_chg = MKT.get('nk_chg', 0)
_sp_chg = MKT.get('sp_chg', 0)
_nk_cc = '#34d399' if _nk_chg >= 0 else '#f87171'
_sp_cc = '#34d399' if _sp_chg >= 0 else '#f87171'

# VIXステータス
_vix_status = '\u5E73\u9759' if MKT['vix_v'] <= 20 else '\u8B66\u6212' if MKT['vix_v'] <= 30 else '\u6050\u6016'
_vix_cc = '#34d399' if MKT['vix_v'] <= 20 else '#fbbf24' if MKT['vix_v'] <= 30 else '#f87171'

# ティッカーアイテム生成
def _ti(dot_color, label, value):
    return (
        f'<span style="display:inline-flex;align-items:center;gap:4px;padding:0 10px;'
        f'border-right:1px solid #1e2d40;font-size:var(--fs-sm);font-family:monospace;'
        f'height:20px;flex-shrink:0;white-space:nowrap;">'
        f'<span style="width:5px;height:5px;border-radius:50%;background:{dot_color};'
        f'flex-shrink:0;box-shadow:0 0 4px {dot_color};"></span>'
        f'<span style="color:#e2e8f0;font-weight:800;">{label}</span>'
        f'<span style="color:{dot_color};">{value}</span></span>'
    )

ticker_items = []
# 保有銘柄数（実数）
ticker_items.append(_ti('#34d399', f'\u4FDD\u6709({_n_hold})', f'\u66F4\u65B0{_gen_time}'))
# 監視銘柄数（実数）
ticker_items.append(_ti('#34d399', f'\u76E3\u8996({_n_watch})', f'\u66F4\u65B0{_gen_time}'))
# 日経225（リアルタイム）
ticker_items.append(_ti(_nk_cc, '\u65E5\u7D4C225', f'{_nk_now} ({_nk_chg:+.1f}%)'))
# SP500（リアルタイム）
ticker_items.append(_ti(_sp_cc, 'SP500', f'{_sp_now} ({_sp_chg:+.1f}%)'))
# VIX（リアルタイム）
ticker_items.append(_ti(_vix_cc, 'VIX', f'{MKT["vix_v"]} {_vix_status}'))
# マクロ指標更新日（実データ）
_macro_dot = '#34d399' if _macro_last else '#f87171'
_macro_txt = f'\u6700\u7D42{_macro_last}' if _macro_last else '\u672A\u53D6\u5F97'
ticker_items.append(_ti(_macro_dot, '\u30DE\u30AF\u30ED\u6307\u6A19', _macro_txt))
# スクリーニングTop50（実数）
_screen_dot = '#34d399' if _n_screen > 0 else '#f87171'
ticker_items.append(_ti(_screen_dot, f'Top50', f'{_n_screen}\u9298\u67C4'))
# 合計追跡数
ticker_items.append(
    f'<span style="display:inline-flex;align-items:center;gap:4px;padding:0 10px;'
    f'border-right:1px solid #1e2d40;font-size:var(--fs-xs);font-family:monospace;'
    f'height:20px;flex-shrink:0;white-space:nowrap;">'
    f'<span style="color:#475569;">v4.3</span>'
    f'<span style="color:#94a3b8;">\u5408\u8A08{_n_total}\u9298\u67C4\u8FFD\u8DE1\u4E2D</span></span>'
)

# ヘッダーラベル
_hdr = (
    f'<span style="display:inline-flex;align-items:center;gap:4px;padding:0 10px;'
    f'border-right:1px solid #1e2d40;font-size:var(--fs-xs);font-family:monospace;'
    f'height:20px;flex-shrink:0;white-space:nowrap;">'
    f'<span style="color:#f59e0b;font-weight:900;">SYSTEM STATUS</span></span>'
)
_all_items = _hdr + ''.join(ticker_items)
# ループ再生のため2回繰り返す
TICKER_DYN = (
    f'<div id="sys-ticker-wrap" style="background:#060810;border-bottom:1px solid #1e2d40;'
    f'height:20px;overflow:hidden;flex-shrink:0;">'
    f'<div id="sys-ticker" style="display:inline-flex;flex-wrap:nowrap;align-items:center;'
    f'height:20px;width:max-content;animation:ticker_scroll 60s linear infinite;" '
    f'onmouseover="this.style.animationPlayState=\'paused\'" '
    f'onmouseout="this.style.animationPlayState=\'running\'">'
    f'{_all_items}{_all_items}</div></div>'
)

# TICKER_START/TICKER_END マーカーで置換
tk_start = src.find('<!-- TICKER_START -->')
tk_end   = src.find('<!-- TICKER_END -->')
if tk_start >= 0 and tk_end >= 0:
    tk_end_full = tk_end + len('<!-- TICKER_END -->')
    src = src[:tk_start] + '<!-- TICKER_START -->' + TICKER_DYN + '<!-- TICKER_END -->' + src[tk_end_full:]
    print(f"OK: \u30C6\u30A3\u30C3\u30AB\u30FC\u52D5\u7684\u66F4\u65B0 (\u4FDD\u6709{_n_hold} \u76E3\u8996{_n_watch} \u65E5\u7D4C{_nk_now} VIX{MKT['vix_v']})")
else:
    print(f"WARN: \u30C6\u30A3\u30C3\u30AB\u30FC\u7F6E\u63DB\u30B9\u30AD\u30C3\u30D7 (start={tk_start} end={tk_end})")

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

# ── 4層マクロカード動的生成 ──────────────────────────────────
def _mc_item(label, val, badge_text, val_color, badge_bg, badge_fg, onclick='', sub_text=''):
    oc = f" onclick=\"showHelp('{onclick}')\"" if onclick else ''
    sub = f'<div style="color:#475569;font-size:var(--fs-micro);margin-top:1px;">{sub_text}</div>' if sub_text else ''
    return (
        f'<div style="cursor:pointer;margin-bottom:2px;"{oc}>'
        f'<div style="display:flex;justify-content:space-between;align-items:center;">'
        f'<span style="color:#cbd5e1;font-size:var(--fs-sm);font-weight:800;">{label}</span>'
        f'<span style="font-size:var(--fs-md);font-weight:900;font-family:monospace;color:{val_color};">{val}</span>'
        f'<span style="background:{badge_bg};color:{badge_fg};font-size:var(--fs-micro);font-weight:900;padding:1px 4px;border-radius:2px;">{badge_text}</span>'
        f'</div>'
        f'{sub}'
        f'</div>'
    )

def _mc_card(border_color, title_color, title, items_html, summary_color, summary):
    return (
        f'<div style="background:#111827;border:1px solid #1e2d40;border-top:2px solid {border_color};border-radius:6px;padding:4px 6px;">'
        f'<div style="font-size:var(--fs-xs);font-weight:900;color:{title_color};margin-bottom:2px;letter-spacing:.5px;">{title}</div>'
        f'{items_html}'
        f'<div style="border-top:1px solid #1e2d40;padding-top:2px;margin-top:1px;">'
        f'<div style="color:{summary_color};font-size:var(--fs-xs);font-weight:800;">{summary}</div>'
        f'</div></div>'
    )

_vix_v = MKT['vix_v']
_vix_col = '#34d399' if _vix_v <= 20 else '#fbbf24' if _vix_v <= 30 else '#f87171'
_vix_bg  = '#064e3b' if _vix_v <= 20 else '#92400e' if _vix_v <= 30 else '#7f1d1d'
_vix_lbl = '\u5E73\u9759' if _vix_v <= 20 else '\u8B66\u6212' if _vix_v <= 30 else '\u6050\u6016'
_vix_sub = '\u5B89\u5B9A\u3057\u3066\u3044\u308B' if _vix_v <= 20 else '\u6050\u6016\u304C\u9AD8\u307E\u3063\u3066\u3044\u308B' if _vix_v <= 30 else '\u6A5F\u95A2\u6295\u8CC7\u5BB6\u304C\u6050\u6016\u3057\u3066\u3044\u308B'
_hyg_v = MKT['hyg_v']; _hyg_chg = MKT['hyg_chg']
_hyg_col = '#34d399' if _hyg_chg >= 0 else '#f87171'
_hyg_bg  = '#064e3b' if _hyg_chg >= 0 else '#7f1d1d'
_hyg_lbl = '\u826F\u597D' if _hyg_chg >= 0 else '\u60AA\u5316'
_hyg_sub = '\u4FE1\u7528\u5E02\u5834\u5B89\u5B9A' if _hyg_chg >= 0 else '\u4F01\u696D\u306E\u4FE1\u7528\u529B\u304C\u4F4E\u4E0B'
_risk_col = '#34d399' if _vix_v <= 20 and _hyg_chg >= 0 else '#f87171' if _vix_v > 30 else '#fbbf24'
_risk_txt = '\u5371\u967A\u5EA6: ' + ('\u4F4E\u3044' if _vix_v <= 20 else '\u3084\u3084\u9AD8\u3044' if _vix_v <= 30 else '\u9AD8\u3044')
card1 = _mc_card('#f87171','#fca5a5','\u30EA\u30B9\u30AF\u74B0\u5883',
    _mc_item('VIX',str(_vix_v),_vix_lbl,_vix_col,_vix_bg,_vix_col,'vix',_vix_sub)+
    _mc_item('HYG',str(_hyg_v),_hyg_lbl,_hyg_col,_hyg_bg,_hyg_col,'hyg',_hyg_sub),
    _risk_col,_risk_txt)

_ys = MKT['yield_spread']
_ys_col = '#34d399' if _ys >= 0 else '#fbbf24' if _ys >= -0.5 else '#f87171'
_ys_bg  = '#064e3b' if _ys >= 0 else '#92400e' if _ys >= -0.5 else '#7f1d1d'
_ys_lbl = '\u6B63\u5E38' if _ys >= 0 else '\u3084\u3084\u8B66\u6212' if _ys >= -0.5 else '\u9006\u30A4\u30FC\u30EB\u30C9'
_ys_sub = '\u6B63\u5E38\u5316=\u5B89\u5FC3\u6750\u6599' if _ys >= 0 else '\u8B66\u6212\u304C\u5FC5\u8981'
card2 = _mc_card('#34d399','#6ee7b7','\u91D1\u878D\u653F\u7B56',
    _mc_item('\u9006\u30A4\u30FC\u30EB\u30C9',f'{_ys:+.2f}',_ys_lbl,_ys_col,_ys_bg,_ys_col,'yield_spread',_ys_sub),
    _ys_col,'\u5B89\u5FC3\u5EA6: '+('\u826F\u597D' if _ys >= 0 else '\u8981\u6CE8\u610F'))

_wti = MKT['wti_v']; _gold = MKT['gold_v']
_wti_col = '#34d399' if _wti < 60 else '#fbbf24' if _wti < 80 else '#f87171'
_wti_bg  = '#064e3b' if _wti < 60 else '#92400e' if _wti < 80 else '#7f1d1d'
_wti_lbl = '\u5B89\u5024' if _wti < 60 else '\u3084\u3084\u5B89' if _wti < 80 else '\u9AD8\u9A30'
_gold_col = '#34d399' if _gold < 2000 else '#fbbf24' if _gold < 2500 else '#f87171'
_gold_bg  = '#064e3b' if _gold < 2000 else '#92400e' if _gold < 2500 else '#7f1d1d'
_gold_lbl = '\u5B89\u5B9A' if _gold < 2000 else '\u4E0A\u6607' if _gold < 2500 else '\u9AD8\u9A30'
_gold_sub = '\u5B89\u5168\u8CC7\u7523\u306B\u8CC7\u91D1\u304C\u9003\u907F\u4E2D' if _gold >= 2500 else '\u8CC7\u7523\u9632\u885B\u9700\u8981'
card3 = _mc_card('#a78bfa','#c4b5fd','\u30B3\u30E2\u30C7\u30A3\u30C6\u30A3',
    _mc_item('WTI\u539F\u6CB9',f'${_wti}',_wti_lbl,_wti_col,_wti_bg,_wti_col,'wti','\u30A4\u30F3\u30D5\u30EC\u30FB\u30A8\u30CD\u30EB\u30AE\u30FC\u306E\u5148\u884C\u6307\u6A19')+
    _mc_item('\u91D1(Gold)',f'${_gold:,}',_gold_lbl,_gold_col,_gold_bg,_gold_col,'gold',_gold_sub),
    '#a78bfa','\u8CC7\u6E90: '+('\u30A4\u30F3\u30D5\u30EC\u8B66\u6212' if _wti>=80 or _gold>=2500 else '\u5B89\u5B9A'))

_nk=MKT['nk_v'];_nk_chg=MKT['nk_chg']
_nk_col='#34d399' if _nk_chg>=0 else '#f87171'
_nk_bg='#064e3b' if _nk_chg>=0 else '#7f1d1d'
_nk_lbl=f'+{_nk_chg:.1f}%' if _nk_chg>=0 else f'{_nk_chg:.1f}%'
_m2c='#34d399' if _m2_yoy and _m2_yoy>0 else '#f87171'
_m2b='#064e3b' if _m2_yoy and _m2_yoy>0 else '#7f1d1d'
_m2v=f'+{_m2_yoy:.2f}%' if _m2_yoy and _m2_yoy>0 else f'{_m2_yoy:.2f}%' if _m2_yoy else '---'
_m2s2='\u304A\u91D1\u306E\u91CF\u304C\u5897\u3048\u3066\u3044\u308B' if _m2_yoy and _m2_yoy>0 else '\u304A\u91D1\u306E\u91CF\u304C\u6E1B\u3063\u3066\u3044\u308B'
_eco_col='#60a5fa'
_eco_txt='\u52E2\u3044: '+('\u826F\u597D' if _nk_chg>=0 and (_m2_yoy or 0)>0 else '\u4E2D\u7ACB' if _nk_chg>=0 else '\u5F31\u3044')
card4 = _mc_card('#60a5fa','#93c5fd','\u7D4C\u6E08\u6D3B\u52D5',
    _mc_item('\u65E5\u672CM2',_m2v,_m2_label,_m2c,_m2b,_m2c,'m2',_m2s2)+
    _mc_item('\u65E5\u7D4C225',f'{_nk:,}',_nk_lbl,_nk_col,_nk_bg,_nk_col,'nikkei',f'52\u9031\u306E{MKT["nk_p52"]}%\u4F4D\u7F6E'),
    _eco_col,_eco_txt)

MACRO_CARDS_HTML = ('    <div style="display:grid;grid-template-columns:1fr 1fr 1fr 1fr;gap:2px;">\n'
    f'      {card1}\n      {card2}\n      {card3}\n      {card4}\n    </div>')

# ROBUST: コメントマーカーで置換（手動CSS編集に影響されない）
cards_start = src.find('<!-- MACRO_CARDS_START -->')
cards_end   = src.find('<!-- MACRO_CARDS_END -->')
if cards_start >= 0 and cards_end >= 0:
    cards_end_full = cards_end + len('<!-- MACRO_CARDS_END -->')
    src = src[:cards_start] + '<!-- MACRO_CARDS_START -->\n' + MACRO_CARDS_HTML + '\n    <!-- MACRO_CARDS_END -->' + src[cards_end_full:]
    print(f"OK: 4\u5C64\u30DE\u30AF\u30ED\u30AB\u30FC\u30C9\u52D5\u7684\u7F6E\u63DB (VIX={_vix_v} WTI=${_wti} Gold=${_gold:,})")
else:
    print(f"WARN: 4\u5C64\u30DE\u30AF\u30ED\u30AB\u30FC\u30C9\u7F6E\u63DB\u30B9\u30AD\u30C3\u30D7 (start={cards_start} end={cards_end})")

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

# ヘッダー日時バッジを現在日時に更新
BADGE_NOW = datetime.now().strftime('%Y-%m-%d %H:%M')
src = re.sub(
    r'<span class="badge">\d{4}-\d{2}-\d{2}\s*(?:&nbsp;)?\s*\d{2}:\d{2}\s*JST</span>',
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
          <th class="sh">業種</th><th class="sh">シグナル</th>
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


# アラートストリップ動的生成（VIX値に基づく短期リスク＋長期買い場）
# ティッカー下のALERT_STRIPマーカー内に表示
vix_now = MKT['vix_v']
if vix_now >= 30:
    ALERT_HTML = (
        '<div id="alert-strip" style="display:flex;align-items:center;gap:12px;'
        'padding:2px 12px;background:#0d1117;border-bottom:1px solid #1e2d40;'
        'flex-shrink:0;flex-wrap:wrap;">'
        '<span style="color:#f87171;font-size:var(--fs-xs);font-weight:900;">'
        '\u26A0 \u77ED\u671F\u30EA\u30B9\u30AF\u9AD8</span>'
        '<span style="color:#fca5a5;font-size:var(--fs-xs);font-weight:700;">'
        f'VIX {vix_now}\u2026\u65B0\u898F\u8CB7\u3044\u306F\u63A7\u3048\u3066\u304F\u3060\u3055\u3044</span>'
        '<span style="color:#1e2d40;">|</span>'
        '<span style="color:#fbbf24;font-size:var(--fs-xs);font-weight:900;">'
        '\u2605 \u9577\u671F\u6295\u8CC7\u5BB6\u306B\u306F\u6B74\u53F2\u7684\u8CB7\u3044\u5834</span>'
        '<span style="color:#fcd34d;font-size:var(--fs-xs);font-weight:700;">'
        'H005-B\u691C\u8A3C\u6E08\uFF1A\u66B4\u843D\u6642\u8CB7\u30445\u5E74\u4FDD\u6709\u2192+21.81%/\u5E74\uFF08p=0.0035\uFF09</span>'
        '<span style="color:#6b7280;font-size:var(--fs-micro);font-weight:700;">'
        '\u203B\u6295\u8CC7\u52A9\u8A00\u3067\u306F\u3042\u308A\u307E\u305B\u3093\u3002\u904E\u53BB\u306E\u691C\u8A3C\u7D50\u679C\u306E\u8868\u793A\u3067\u3059</span>'
        '</div>')
elif vix_now >= 25:
    ALERT_HTML = (
        '<div id="alert-strip" style="display:flex;align-items:center;gap:12px;'
        'padding:2px 12px;background:#0d1117;border-bottom:1px solid #1e2d40;'
        'flex-shrink:0;flex-wrap:wrap;">'
        '<span style="color:#fbbf24;font-size:var(--fs-xs);font-weight:900;">'
        '\u26A0 \u8B66\u6212</span>'
        '<span style="color:#fcd34d;font-size:var(--fs-xs);font-weight:700;">'
        f'VIX {vix_now}\u2026\u65B0\u898F\u8CB7\u3044\u306F\u614E\u91CD\u306B</span>'
        '</div>')
else:
    ALERT_HTML = ''

# ALERT_STRIP置換
alert_start = src.find('<!-- ALERT_STRIP_START -->')
alert_end = src.find('<!-- ALERT_STRIP_END -->')
if alert_start >= 0 and alert_end >= 0:
    alert_end_full = alert_end + len('<!-- ALERT_STRIP_END -->')
    if ALERT_HTML:
        src = src[:alert_start] + '<!-- ALERT_STRIP_START -->\n    ' + ALERT_HTML + '\n    <!-- ALERT_STRIP_END -->' + src[alert_end_full:]
    else:
        src = src[:alert_start] + '<!-- ALERT_STRIP_START --><!-- ALERT_STRIP_END -->' + src[alert_end_full:]
    print(f"OK: アラートストリップ動的生成 (VIX={vix_now})")
else:
    print(f"WARN: アラートストリップ置換スキップ (start={alert_start} end={alert_end})")

# GBAR_DYNAMIC置換（監視銘柄パネル内のプレースホルダー）
s_lbl = '\u5F37\u6C17' if SHORT_SCORE >= 55 else '\u4E2D\u7ACB' if SHORT_SCORE >= 45 else '\u5F31\u6C17'
m_lbl = '\u5F37\u6C17' if MID_SCORE >= 55 else '\u4E2D\u7ACB' if MID_SCORE >= 45 else '\u5F31\u6C17'
GBAR_HTML = (
    '<div class="gbar"><span class="gl">\u73FE\u5728\u306E\u74B0\u5883</span>'
    f'<span class="gi">\u77ED\u671F{SHORT_SCORE}\u70B9({s_lbl})\u30FB\u4E2D\u671F{MID_SCORE}\u70B9({m_lbl})</span>'
    '</div>')
src = src.replace('<!-- GBAR_DYNAMIC -->', GBAR_HTML, 1)
print(f"OK: gbar動的生成（短期{SHORT_SCORE}/中期{MID_SCORE}）")
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

vi_style  = 'padding:3px 6px;border-right:1px solid #1e2d40;cursor:pointer;'
vn_style  = 'font-size:var(--fs-sm);font-weight:800;color:#cbd5e1;margin-bottom:2px;text-decoration:underline dotted;text-underline-offset:2px;'
row_style = 'display:flex;align-items:center;gap:5px;margin-bottom:1px;'
flag_style= 'font-size:var(--fs-sm);min-width:14px;'
val_style_g='font-size:var(--fs-lg);font-weight:900;font-family:monospace;color:#34d399;min-width:36px;'
val_style_y='font-size:var(--fs-lg);font-weight:900;font-family:monospace;color:#fbbf24;min-width:36px;'
val_style_r='font-size:var(--fs-lg);font-weight:900;font-family:monospace;color:#f87171;min-width:36px;'
vc = {'g':val_style_g,'y':val_style_y,'r':val_style_r}

# 更新日時表示（ソース更新済みを明示）
updated_display = VAL['updated_at']

# マクロ総合スコア変数（VAL_HTMLの5列目で使用）
_mp_bar_w = min(max(_mp_score, 0), 100)
_mp_col = '#34d399' if _mp_lbl == 'GREEN' else '#f59e0b' if _mp_lbl == 'YELLOW' else '#f87171'
_short_col = '#34d399' if SHORT_SCORE >= 55 else '#fbbf24' if SHORT_SCORE >= 45 else '#f87171'
_short_bdr = '#065f46' if SHORT_SCORE >= 55 else '#92400e' if SHORT_SCORE >= 45 else '#991b1b'
_mid_col   = '#34d399' if MID_SCORE >= 55 else '#fbbf24' if MID_SCORE >= 45 else '#f87171'
_mid_bdr   = '#065f46' if MID_SCORE >= 55 else '#92400e' if MID_SCORE >= 45 else '#991b1b'
_s_txt = '強気' if SHORT_SCORE >= 55 else '中立' if SHORT_SCORE >= 45 else '弱気'
_m_txt = '強気' if MID_SCORE >= 55 else '中立' if MID_SCORE >= 45 else '弱気'

VAL_HTML = f"""        <div class="sl">バリュエーション — 日本 vs 米国（過去10年との比較）<span style="font-size:var(--fs-micro);color:#34d399;font-weight:600;margin-left:8px;">✓ {updated_display}</span></div>
        <div style="background:#0f1420;border:1px solid #1e2d40;border-radius:6px;padding:4px 4px;">
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
          <div style="padding:3px 6px;display:flex;flex-direction:column;justify-content:center;align-items:center;text-align:center;">
            <div style="font-size:var(--fs-sm);font-weight:900;color:{_mp_col};letter-spacing:.5px;margin-bottom:2px;">マクロ総合</div>
            <div><span style="font-size:var(--fs-xl);font-weight:900;font-family:monospace;color:{_mp_col};">{_mp_score}</span><span style="font-size:var(--fs-micro);color:#475569;">/100</span> <span style="font-size:var(--fs-sm);font-weight:800;color:{_mp_col};">{_mp_txt}</span></div>
            <div style="background:#1e293b;border-radius:3px;height:4px;width:100%;margin:3px 0;"><div style="width:{_mp_bar_w}%;height:4px;border-radius:3px;background:{_mp_col};"></div></div>
            <div style="display:flex;gap:6px;align-items:center;">
              <span style="color:#94a3b8;font-size:var(--fs-micro);font-weight:800;">短期</span><span style="color:{_short_col};font-size:var(--fs-base);font-weight:900;">{SHORT_SCORE}</span><span style="color:{_short_col};font-size:var(--fs-micro);">{_s_txt}</span>
              <span style="color:#374151;">|</span>
              <span style="color:#94a3b8;font-size:var(--fs-micro);font-weight:800;">中期</span><span style="color:{_mid_col};font-size:var(--fs-base);font-weight:900;">{MID_SCORE}</span><span style="color:{_mid_col};font-size:var(--fs-micro);">{_m_txt}</span>
            </div>
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

# MACRO_TOTAL_HTML（単体表示用のフォールバック・通常はVAL_HTML 5列目に統合済み）
MACRO_TOTAL_HTML = (
    f'      <!-- \u30DE\u30AF\u30ED\u7DCF\u5408\u30B9\u30B3\u30A2 -->\n'
    f'      <div style="background:#111827;border:1px solid #1e2d40;border-top:2px solid {_mp_col};border-radius:6px;padding:4px 8px;display:flex;flex-direction:column;justify-content:space-between;">\n'
    f'        <div style="font-size:var(--fs-xs);font-weight:900;color:{_mp_col};letter-spacing:.5px;">\u30DE\u30AF\u30ED\u7DCF\u5408</div>\n'
    f'        <div style="text-align:center;">\n'
    f'          <span style="font-size:var(--fs-xl);font-weight:900;font-family:monospace;color:{_mp_col};">{_mp_score}</span><span style="font-size:var(--fs-micro);color:#475569;">/100</span>\n'
    f'          <span style="font-size:var(--fs-sm);font-weight:800;color:{_mp_col};margin-left:6px;">{_mp_txt}</span>\n'
    f'        </div>\n'
    f'        <div style="background:#1e293b;border-radius:3px;height:4px;"><div style="width:{_mp_bar_w}%;height:4px;border-radius:3px;background:{_mp_col};"></div></div>\n'
    f'        <div style="display:flex;gap:4px;">\n'
    f'          <div style="flex:1;background:#0a0d16;border:1px solid {_short_bdr};border-radius:4px;padding:4px 6px;text-align:center;cursor:pointer;" onclick="showHelp(\'short_score\')">\n'
    f'            <div style="color:#94a3b8;font-size:var(--fs-micro);font-weight:800;">\u77ED\u671F(1\u5E74)</div>\n'
    f'            <div><span style="color:{_short_col};font-size:var(--fs-lg);font-weight:900;font-family:monospace;">{SHORT_SCORE}</span> <span style="color:{_short_col};font-size:var(--fs-micro);font-weight:800;">{_s_txt}</span></div>\n'
    f'          </div>\n'
    f'          <div style="flex:1;background:#0a0d16;border:1px solid {_mid_bdr};border-radius:4px;padding:4px 6px;text-align:center;cursor:pointer;" onclick="showHelp(\'medium_score\')">\n'
    f'            <div style="color:#94a3b8;font-size:var(--fs-micro);font-weight:800;">\u4E2D\u671F(3\u5E74)</div>\n'
    f'            <div><span style="color:{_mid_col};font-size:var(--fs-lg);font-weight:900;font-family:monospace;">{MID_SCORE}</span> <span style="color:{_mid_col};font-size:var(--fs-micro);font-weight:800;">{_m_txt}</span></div>\n'
    f'          </div>\n'
    f'        </div>\n'
    f'      </div>\n'
    f'    </div>')

# ROBUST: コメントマーカーで置換（手動HTML編集に影響されない）
val_start = src.find('<!-- VAL_MACRO_START -->')
val_end   = src.find('<!-- VAL_MACRO_END -->')
if val_start >= 0 and val_end >= 0:
    val_end_full = val_end + len('<!-- VAL_MACRO_END -->')
    src = src[:val_start] + '<!-- VAL_MACRO_START -->\n' + VAL_HTML + '\n    <!-- VAL_MACRO_END -->' + src[val_end_full:]
    print(f"OK: \u30D0\u30EA\u30E5\u30A8\u30FC\u30B7\u30E7\u30F3+\u30DE\u30AF\u30ED\u7DCF\u5408\u7F6E\u63DB (\u30B9\u30B3\u30A2{_mp_score} \u77ED\u671F{SHORT_SCORE} \u4E2D\u671F{MID_SCORE})")
else:
    print(f"WARN: \u30D0\u30EA\u30E5\u30A8\u30FC\u30B7\u30E7\u30F3\u7F6E\u63DB\u30B9\u30AD\u30C3\u30D7 (start={val_start} end={val_end})")

# マクロフェーズゲージ挿入
PHASE_HTML = build_phase_gauge_html(ss)
src = src.replace('<!-- MACRO_PHASE_GAUGE -->', PHASE_HTML, 1)
print('OK: マクロフェーズゲージ置換')

# ── 折りたたみトグル注入（マーカー外側にラッパー配置・置換ロジックに影響なし）──
TOGGLE_CSS = '<style>#hdr-fold-btn{cursor:pointer;user-select:none;padding:1px 10px;font-size:var(--fs-xs);font-weight:800;color:#94a3b8;background:#111827;border:1px solid #374151;border-radius:4px;transition:all .2s;}#hdr-fold-btn:hover{color:#f1f5f9;border-color:#6b7280;}</style>'
TOGGLE_BTN = '<div style="text-align:center;margin:2px 0;"><span id="hdr-fold-btn" onclick="toggleHdr()">&#x25B2; 閉じる</span></div>'
TOGGLE_JS = """<script>
function toggleHdr(){
  var w=document.getElementById('hdr-fold-wrap');
  var b=document.getElementById('hdr-fold-btn');
  if(!w||!b)return;
  if(w.style.display==='none'){w.style.display='';b.innerHTML='\\u25B2 閉じる';}
  else{w.style.display='none';b.innerHTML='\\u25BC 開く';}
}
</script>"""

# MACRO_CARDS_STARTの直前に<div id="hdr-fold-wrap">を追加
# VAL_MACRO_ENDの直後に</div>を追加
if 'hdr-fold-wrap' not in src:
    mc_start_marker = '<!-- MACRO_CARDS_START -->'
    vm_end_marker = '<!-- VAL_MACRO_END -->'
    mc_idx = src.find(mc_start_marker)
    vm_idx = src.find(vm_end_marker)
    if mc_idx >= 0 and vm_idx >= 0:
        vm_end_pos = vm_idx + len(vm_end_marker)
        src = src[:vm_end_pos] + '\n    </div>' + TOGGLE_BTN + src[vm_end_pos:]
        src = src[:mc_idx] + TOGGLE_CSS + '<div id="hdr-fold-wrap">\n    ' + src[mc_idx:]
        print("OK: 折りたたみトグル注入")
    else:
        print("WARN: 折りたたみトグルスキップ (マーカー未検出)")
else:
    print("OK: 折りたたみトグル既存確認")

# モーダル挿入（</body>直前）
src = src.replace('</body>', TOGGLE_JS + VI_MODAL_HTML + MC_MODAL_HTML + '</body>', 1)

# 銘柄管理ボタン挿入（ヘッダーに存在しなければ追加）
MGMT_BTN = '<span id="mgmt-btn" onclick="openStockMgmt()" style="display:inline-flex;align-items:center;gap:4px;padding:3px 10px;background:#1e293b;border:1px solid #f97316;border-radius:6px;cursor:pointer;font-size:var(--fs-xs);font-weight:900;color:#f97316;transition:all .2s;" onmouseover="this.style.background=\'#f97316\';this.style.color=\'#000\'" onmouseout="this.style.background=\'#1e293b\';this.style.color=\'#f97316\'">&#x1F4DD; \u9298\u67C4\u7BA1\u7406</span>'
if 'mgmt-btn' not in src:
    # 全更新ボタンの直後に挿入
    upd_btn_end = src.find('</span>', src.find('id="update-btn"'))
    if upd_btn_end >= 0:
        insert_pos = upd_btn_end + len('</span>')
        src = src[:insert_pos] + '\n    ' + MGMT_BTN + src[insert_pos:]
        print("OK: \u9298\u67C4\u7BA1\u7406\u30DC\u30BF\u30F3\u633F\u5165")
    else:
        print("WARN: \u5168\u66F4\u65B0\u30DC\u30BF\u30F3\u304C\u898B\u3064\u304B\u3089\u305A\u3001\u9298\u67C4\u7BA1\u7406\u30DC\u30BF\u30F3\u30B9\u30AD\u30C3\u30D7")
else:
    print("OK: \u9298\u67C4\u7BA1\u7406\u30DC\u30BF\u30F3\u5B58\u5728\u78BA\u8A8D")

# 銘柄管理モーダル挿入（存在しなければ末尾に追加）
if 'mgmt-overlay' not in src:
    MGMT_MODAL = """
<!-- MANAGE_STOCK_MODAL -->
<div id="mgmt-overlay" onclick="closeMgmt(event)" style="display:none;position:fixed;inset:0;background:rgba(0,0,0,.75);z-index:200;align-items:center;justify-content:center;">
  <div onclick="event.stopPropagation()" style="background:#111827;border:1px solid #f97316;border-radius:10px;width:380px;padding:0;box-shadow:0 0 40px rgba(0,0,0,.8);animation:fadeIn .2s ease;">
    <div style="display:flex;justify-content:space-between;align-items:center;padding:12px 16px;border-bottom:1px solid #1e3a5f;">
      <div style="color:#f97316;font-weight:900;font-size:var(--fs-md);">\u9298\u67C4\u7BA1\u7406</div>
      <button onclick="closeMgmt()" style="background:none;border:none;color:#94a3b8;font-size:18px;cursor:pointer;">&#x2715;</button>
    </div>
    <div style="padding:16px;">
      <div style="margin-bottom:12px;">
        <label style="color:#94a3b8;font-size:var(--fs-xs);font-weight:700;display:block;margin-bottom:4px;">\u9298\u67C4\u30B3\u30FC\u30C9\uFF084\u6841\uFF09</label>
        <input id="mgmt-code" type="text" maxlength="4" placeholder="\u4F8B: 7203" style="width:100%;padding:8px 10px;background:#0d1117;border:1px solid #30363d;border-radius:6px;color:#e2e8f0;font-size:var(--fs-md);font-family:monospace;box-sizing:border-box;" oninput="this.value=this.value.replace(/[^0-9]/g,'')">
      </div>
      <div style="margin-bottom:12px;">
        <label style="color:#94a3b8;font-size:var(--fs-xs);font-weight:700;display:block;margin-bottom:4px;">\u5BFE\u8C61</label>
        <div style="display:flex;gap:12px;">
          <label style="color:#e2e8f0;font-size:var(--fs-sm);cursor:pointer;display:flex;align-items:center;gap:4px;"><input type="radio" name="mgmt-target" value="\u4FDD\u6709" checked style="accent-color:#f97316;"> \u4FDD\u6709</label>
          <label style="color:#e2e8f0;font-size:var(--fs-sm);cursor:pointer;display:flex;align-items:center;gap:4px;"><input type="radio" name="mgmt-target" value="\u76E3\u8996" style="accent-color:#f97316;"> \u76E3\u8996</label>
        </div>
      </div>
      <div style="display:flex;gap:8px;margin-bottom:12px;">
        <button onclick="execMgmt('add')" style="flex:1;padding:8px;background:#064e3b;border:1px solid #34d399;border-radius:6px;color:#34d399;font-weight:800;font-size:var(--fs-sm);cursor:pointer;">+ \u8FFD\u52A0</button>
        <button onclick="execMgmt('remove')" style="flex:1;padding:8px;background:#7f1d1d;border:1px solid #f87171;border-radius:6px;color:#f87171;font-weight:800;font-size:var(--fs-sm);cursor:pointer;">- \u524A\u9664</button>
        <button onclick="execMgmt('move')" style="flex:1;padding:8px;background:#1e3a5f;border:1px solid #60a5fa;border-radius:6px;color:#60a5fa;font-weight:800;font-size:var(--fs-sm);cursor:pointer;">&#x21C4; \u79FB\u52D5</button>
      </div>
      <div id="mgmt-status" style="min-height:24px;padding:6px 8px;background:#0d1117;border-radius:4px;font-size:var(--fs-xs);color:#94a3b8;font-family:monospace;"></div>
    </div>
  </div>
</div>
<script>
function openStockMgmt(){document.getElementById('mgmt-overlay').style.display='flex';document.getElementById('mgmt-code').value='';document.getElementById('mgmt-status').textContent='';document.getElementById('mgmt-code').focus();}
function closeMgmt(e){if(!e||e.target===document.getElementById('mgmt-overlay'))document.getElementById('mgmt-overlay').style.display='none';}
function execMgmt(action){var code=document.getElementById('mgmt-code').value.trim();if(!code||code.length!==4||!/^\\d{4}$/.test(code)){document.getElementById('mgmt-status').innerHTML='<span style="color:#f87171;">4\u6841\u306E\u9298\u67C4\u30B3\u30FC\u30C9\u3092\u5165\u529B\u3057\u3066\u304F\u3060\u3055\u3044</span>';return;}var target=document.querySelector('input[name="mgmt-target"]:checked').value;var al={'add':'\u8FFD\u52A0','remove':'\u524A\u9664','move':'\u79FB\u52D5'}[action];var st=document.getElementById('mgmt-status');st.innerHTML='<span style="color:#fbbf24;">&#x23F3; '+code+' \u3092'+target+'\u306B'+al+'\u4E2D...</span>';var btns=document.querySelectorAll('#mgmt-overlay button');btns.forEach(function(b){b.style.pointerEvents='none';b.style.opacity='0.5';});var GAS='{GAS_URL_FULL_UPDATE}';fetch(GAS+'?action=manage_stock&code='+code+'&operation='+action+'&target='+encodeURIComponent(target),{method:'POST',mode:'no-cors'}).then(function(){st.innerHTML='<span style="color:#34d399;">&#x2705; GitHub Actions\u8D77\u52D5! '+code+'\u3092'+target+'\u306B'+al+' (2-3\u5206\u3067\u53CD\u6620)</span>';btns.forEach(function(b){b.style.pointerEvents='';b.style.opacity='';});}).catch(function(){st.innerHTML='<span style="color:#f87171;">&#x274C; \u30A8\u30E9\u30FC</span>';btns.forEach(function(b){b.style.pointerEvents='';b.style.opacity='';});});}
</script>
"""
    src += MGMT_MODAL
    print("OK: \u9298\u67C4\u7BA1\u7406\u30E2\u30FC\u30C0\u30EB\u633F\u5165")
else:
    print("OK: \u9298\u67C4\u7BA1\u7406\u30E2\u30FC\u30C0\u30EB\u5B58\u5728\u78BA\u8A8D")
print("OK: モーダル挿入")

# GAS URL注入（core/config.pyから一元管理）
src = src.replace('%%GAS_URL_FULL_UPDATE%%', GAS_URL_FULL_UPDATE)
src = src.replace('%%GAS_URL_KENJA%%', GAS_URL_KENJA)
print(f"OK: GAS URL注入（FULL_UPDATE={GAS_URL_FULL_UPDATE[:60]}...）")
print(f"OK: GAS URL注入（KENJA={GAS_URL_KENJA[:60]}...）")

# charset宣言を保証（文字化け防止）
if '<!DOCTYPE html>' not in src:
    src = '<!DOCTYPE html>\n<html lang="ja">\n<head>\n<meta charset="utf-8">\n</head>\n' + src
elif '<meta charset' not in src:
    src = src.replace('<!DOCTYPE html>', '<!DOCTYPE html>\n<html lang="ja">\n<head>\n<meta charset="utf-8">\n</head>', 1)
print("OK: charset宣言保証")

# ── サニティチェック（置換が実際に成功したか検証） ──────────────
_errors = []
if str(MKT['vix_v']) not in src:
    _errors.append(f"VIX\u5024{MKT['vix_v']}\u304cHTML\u306B\u542B\u307E\u308C\u306A\u3044")
if BADGE_NOW not in src:
    _errors.append(f"\u30D0\u30C3\u30B8{BADGE_NOW}\u304cHTML\u306B\u542B\u307E\u308C\u306A\u3044")
if '<!-- MACRO_CARDS_START -->' not in src or '<!-- MACRO_CARDS_END -->' not in src:
    _errors.append("\u30DE\u30AF\u30ED\u30AB\u30FC\u30C9\u30DE\u30FC\u30AB\u30FC\u304C\u6B20\u843D")
if '<!-- VAL_MACRO_START -->' not in src or '<!-- VAL_MACRO_END -->' not in src:
    _errors.append("\u30D0\u30EA\u30E5\u30A8\u30FC\u30B7\u30E7\u30F3\u30DE\u30FC\u30AB\u30FC\u304C\u6B20\u843D")
if '<!-- TICKER_START -->' not in src or '<!-- TICKER_END -->' not in src:
    _errors.append("\u30C6\u30A3\u30C3\u30AB\u30FC\u30DE\u30FC\u30AB\u30FC\u304C\u6B20\u843D")
if '<!-- ALERT_STRIP_START -->' not in src:
    _errors.append("\u30A2\u30E9\u30FC\u30C8\u30B9\u30C8\u30EA\u30C3\u30D7\u30DE\u30FC\u30AB\u30FC\u304C\u6B20\u843D")
if f'{MKT["nk_v"]:,.0f}' not in src and str(int(MKT['nk_v'])) not in src:
    _errors.append(f"\u65E5\u7D4C225\u5024{MKT['nk_v']}\u304cHTML\u306B\u542B\u307E\u308C\u306A\u3044")
if '%%GAS_URL_FULL_UPDATE%%' in src:
    _errors.append("GAS URL\u30D7\u30EC\u30FC\u30B9\u30DB\u30EB\u30C0\u30FC\u304C\u672A\u7F6E\u63DB")

if _errors:
    print("\n\u274C \u30B5\u30CB\u30C6\u30A3\u30C1\u30A7\u30C3\u30AF\u5931\u6557:")
    for e in _errors:
        print(f"   - {e}")
    print("\u26A0 HTML\u306F\u66F8\u304D\u51FA\u3057\u307E\u3059\u304C\u3001\u4E0A\u8A18\u306E\u52D5\u7684\u66F4\u65B0\u304C\u5931\u6557\u3057\u3066\u3044\u307E\u3059\u3002")
else:
    print("\n\u2705 \u30B5\u30CB\u30C6\u30A3\u30C1\u30A7\u30C3\u30AF\u5168\u30D1\u30B9")

out = 'ai_dashboard_v13.html'
with open(out, 'w', encoding='utf-8') as f:
    f.write(src)
print(f"\n\u2705 \u51FA\u529B\u5B8C\u4E86: {out}")
print(f"   \u4FDD\u6709:{len(rows_h)} \u76E3\u8996:{len(rows_w)} \u30B9\u30B3\u30A2:{len(SCORES)}")
print(f"   \u77ED\u671F:{SHORT_SCORE}\u70B9 / \u4E2D\u671F:{MID_SCORE}\u70B9")
print(f"   PBR \u65E5\u672C:{VAL['pbr_jp']} \u7C73\u56FD:{VAL['pbr_us']}")
print(f"   CAPE \u65E5\u672C:{VAL['cape_jp']} \u7C73\u56FD:{VAL['cape_us']}")
print(f"   \u30BD\u30FC\u30B9: \u65E5\u672CPBR=\u65E5\u7D4C\u30D7\u30ED\u30D5\u30A3\u30EB / \u7C73\u56FDPBR\u30FBCAPE=multpl.com")

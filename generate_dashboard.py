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
print(f"$2705 接続完了: {ss.title}  ({NOW})")

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
        print(f"  $26A0$FE0F 週次シグナル取得失敗: {e} → デフォルト値使用")
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
        print(f"  $2705 バリュエーション保存完了")
    except Exception as e:
        print(f"  $26A0$FE0F バリュエーション保存失敗: {e}")
    return result

VAL = load_valuation()
print(f"  PBR 日本:{VAL['pbr_jp']} 米国:{VAL['pbr_us']} / 判定:{VAL['verdict']}")

# ── スプレッドシートから銘柄データ読み込み ────────────────────
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

# ── 出力 ──────────────────────────────────────────────────────
def cmp(jp, us, lower_is_better=True):
    if lower_is_better:
        return ('cg','日本割安') if jp < us else ('cr','米国割安')
    else:
        return ('cg','日本有利') if jp > us else ('cr','米国有利')

pbr_cls,   pbr_lbl   = cmp(VAL['pbr_jp'],    VAL['pbr_us'],   True)
cape_cls,  cape_lbl  = cmp(VAL['cape_jp'],   VAL['cape_us'],  True)
div_cls,   div_lbl   = cmp(VAL['div_jp'],    VAL['div_us'],   False)
yield_cls, yield_lbl = cmp(VAL['yield_jp'],  VAL['yield_us'], False)
buf_cls,   buf_lbl   = cmp(VAL['buffett_jp'],VAL['buffett_us'],True)
vd_cls = 'cg' if '日本' in VAL['verdict'] else 'ca' if '均衡' in VAL['verdict'] else 'cr'

VAL_HTML = f"""        <div class="sl">バリュエーション $2014 日本 vs 米国<span style="font-size:7px;color:#475569;font-weight:400;margin-left:8px;">自動更新 {VAL['updated_at']}</span></div>
        <div class="vg" style="display:grid;grid-template-columns:repeat(6,1fr);gap:0;">
          <div class="vi"><div class="vi-l">シラーPER</div><div class="vi-r"><span class="vi-c">日本</span><span class="vi-n {cape_cls}">{VAL['cape_jp']:.0f}倍</span></div><div class="vi-r"><span class="vi-c">米国</span><span class="vi-n cr">{VAL['cape_us']:.0f}倍</span></div><span class="vi-j {cape_cls}">{cape_lbl}</span></div>
          <div class="vi"><div class="vi-l">PBR</div><div class="vi-r"><span class="vi-c">日本</span><span class="vi-n {pbr_cls}">{VAL['pbr_jp']:.1f}倍</span></div><div class="vi-r"><span class="vi-c">米国</span><span class="vi-n cr">{VAL['pbr_us']:.1f}倍</span></div><span class="vi-j {pbr_cls}">{pbr_lbl}</span></div>
          <div class="vi"><div class="vi-l">益回り</div><div class="vi-r"><span class="vi-c">日本</span><span class="vi-n {yield_cls}">{VAL['yield_jp']:.2f}%</span></div><div class="vi-r"><span class="vi-c">米国</span><span class="vi-n ca">{VAL['yield_us']:.2f}%</span></div><span class="vi-j {yield_cls}">{yield_lbl}</span></div>
          <div class="vi"><div class="vi-l">配当利回り</div><div class="vi-r"><span class="vi-c">日本</span><span class="vi-n {div_cls}">{VAL['div_jp']:.1f}%</span></div><div class="vi-r"><span class="vi-c">米国</span><span class="vi-n ca">{VAL['div_us']:.1f}%</span></div><span class="vi-j {div_cls}">{div_lbl}</span></div>
          <div class="vi"><div class="vi-l">バフェット指数</div><div class="vi-r"><span class="vi-c">日本</span><span class="vi-n {buf_cls}">{VAL['buffett_jp']:.0f}%</span></div><div class="vi-r"><span class="vi-c">米国</span><span class="vi-n cr">{VAL['buffett_us']:.0f}%</span></div><span class="vi-j {buf_cls}">{buf_lbl}</span></div>
          <div class="vi"><div class="vi-l">総合判定</div><div class="{vd_cls}" style="font-size:11px;font-weight:900;margin-top:3px;">{VAL['verdict']}</div><div class="cr" style="font-size:8px;font-weight:800;margin-top:2px;">{VAL['verdict_us']}</div><span style="font-size:7px;color:#475569;margin-top:2px;display:block;">$00A5{VAL['usdjpy']:.1f} 金利差{VAL['rate_diff']:.1f}%</span></div>
        </div>"""

# バリュエーションセクションをHTMLに埋め込む
src = re.sub(
    r'<div class="sl">バリュエーション.*?</div>\s*<div[^>]*class="vg"[^>]*>.*?</div>',
    VAL_HTML, src, count=1, flags=re.DOTALL
)
print("OK: バリュエーション置換")

out = 'ai_dashboard_v11_fixed.html'
with open(out, 'w', encoding='utf-8') as f:
    f.write(src)
print(f"\n$2705 出力完了: {out}")
print(f"   保有:{len(rows_h)} 監視:{len(rows_w)} スコア:{len(SCORES)}")
print(f"   短期:{SHORT_SCORE}点 / 中期:{MID_SCORE}点")

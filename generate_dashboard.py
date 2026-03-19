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

import os, json, re, requests
import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime

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
out = 'ai_dashboard_v11_fixed.html'
with open(out, 'w', encoding='utf-8') as f:
    f.write(src)
print(f"\n✅ 出力完了: {out}")
print(f"   保有:{len(rows_h)} 監視:{len(rows_w)} スコア:{len(SCORES)}")
print(f"   短期:{SHORT_SCORE}点 / 中期:{MID_SCORE}点")

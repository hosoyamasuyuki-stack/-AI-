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
import yfinance as yf
from datetime import datetime, timedelta
import gspread
from google.oauth2.service_account import Credentials
from core.config import (SPREADSHEET_ID, JQUANTS_API_KEY, JQUANTS_HEADERS,
                          JQUANTS_BASE, PEG_THR, FCY_THR)
from core.auth import get_spreadsheet
from core.scoring import safe, thr_high, thr_low
warnings.filterwarnings('ignore')

# ── 認証・設定 ─────────────────────────────────────────────
# 株価取得ソース切替：jquants（自動更新・前日終値）/ yfinance（手動更新・リアルタイム）
PRICE_SOURCE = os.environ.get('PRICE_SOURCE', 'jquants')

ss = get_spreadsheet()

NOW   = datetime.now().strftime('%Y/%m/%d %H:%M')
TODAY = datetime.now()

print(f"$2705 接続完了: {ss.title}")
print(f"実行日時: {NOW}")
print(f"\n{'='*60}")
print(f"日次 変数3（価格）更新スクリプト")
print(f"株価ソース: {PRICE_SOURCE}" + (" (リアルタイム)" if PRICE_SOURCE == 'yfinance' else " (前日終値)"))
print('='*60)

# ── 銘柄マスタ（v4.3シートから動的取得）──────────────────────
# 保有+監視の全銘柄を自動取得（ハードコード廃止）
STOCKS = []
_seen = set()
for _sheet_name in ['保有銘柄_v4.3スコア', '監視銘柄_v4.3スコア']:
    try:
        _ws = ss.worksheet(_sheet_name)
        _rows = _ws.get_all_values()
        if len(_rows) < 2: continue
        _header = _rows[0]
        _code_idx = _header.index('コード') if 'コード' in _header else 0
        _name_idx = _header.index('銘柄名') if '銘柄名' in _header else 1
        for _row in _rows[1:]:
            _c = str(_row[_code_idx]).strip()
            _n = str(_row[_name_idx]).strip()
            if _c and _c not in _seen:
                STOCKS.append({'code': _c, 'name': _n})
                _seen.add(_c)
    except Exception as _e:
        print(f"  WARN: {_sheet_name} 読み込みエラー: {_e}")
print(f"銘柄マスタ: {len(STOCKS)}銘柄（v4.3シートから自動取得）")

# ── ヘルパー関数・閾値はcore/scoring.py, core/config.pyからimport済み ──

# ── 株価取得（2営業日分：当日と前日）───────────────────────
def get_price_jquants(code):
    """J-Quants: 前日終値を取得（自動更新用・正確）"""
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

def get_price_yfinance(code):
    """yfinance: リアルタイム株価を取得（手動更新用・15分遅延）"""
    ticker = f"{code}.T"
    prices = {}
    try:
        t = yf.Ticker(ticker)
        h = t.history(period='5d')
        if len(h) >= 2:
            prices['today'] = {
                'price': round(float(h['Close'].iloc[-1]), 1),
                'date':  str(h.index[-1].date()),
                'volume': int(h['Volume'].iloc[-1]) if h['Volume'].iloc[-1] else 0,
            }
            prices['yesterday'] = {
                'price': round(float(h['Close'].iloc[-2]), 1),
                'date':  str(h.index[-2].date()),
                'volume': int(h['Volume'].iloc[-2]) if h['Volume'].iloc[-2] else 0,
            }
        elif len(h) == 1:
            prices['today'] = {
                'price': round(float(h['Close'].iloc[-1]), 1),
                'date':  str(h.index[-1].date()),
                'volume': int(h['Volume'].iloc[-1]) if h['Volume'].iloc[-1] else 0,
            }
    except:
        pass
    return prices

def get_price_2days(code):
    """株価取得（PRICE_SOURCEに応じて切替・失敗時フォールバック）"""
    if PRICE_SOURCE == 'yfinance':
        prices = get_price_yfinance(code)
        if prices.get('today'):
            return prices
        # yfinance失敗→J-Quantsにフォールバック
        return get_price_jquants(code)
    else:
        return get_price_jquants(code)

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

    # FCF利回り（時価総額ベース）— マイナスFCFはそのまま負の値にする
    fy = None
    if fcf is not None and shares and price and shares > 0:
        market_cap = float(price) * float(shares)
        if market_cap > 0:
            fy = float(fcf) / market_cap * 100
    elif fcf is not None and ta and ta > 0:
        fy = float(fcf) / float(ta) * 100

    s3 = round(thr_low(peg, PEG_THR) * 0.50 +
               thr_high(fy, FCY_THR) * 0.50)
    return s3, peg, fy

# ── メイン処理 ───────────────────────────────────────────────
print(f"\n【{len(STOCKS)}銘柄の変数3（価格）を日次更新】")
print(f"FCF利回りの計算：時価総額ベース（株価連動）")

# 既存のv4.3スコアシートを読み込む（変数1・2を再利用）
# 優先順位: 保有銘柄_v4.3スコア > 監視銘柄_v4.3スコア > コアスキャン_v4.3
# 理由: manage_stock.py の最新書き込みが確実に反映されているのは
#       保有/監視シート。コアスキャン_v4.3 は過去のバグ版で書かれた
#       行が残っている可能性があるためフォールバック。
has_existing = False
df_v43 = None
try:
    dfs = []
    for sh in ['保有銘柄_v4.3スコア', '監視銘柄_v4.3スコア']:
        try:
            ws_p = ss.worksheet(sh)
            d = pd.DataFrame(ws_p.get_all_records())
            if len(d) > 0:
                d['コード'] = d['コード'].astype(str)
                dfs.append(d[['コード', '変数1', '変数2', 'ランク', '総合スコア']])
        except Exception as e:
            print(f"  WARNING: {sh}読込失敗 {e}")
    if dfs:
        df_v43 = pd.concat(dfs, ignore_index=True)
        df_v43 = df_v43.drop_duplicates(subset='コード', keep='first')
        has_existing = True
        print(f"$2705 変数1・2ソース読込（保有+監視）: {len(df_v43)}銘柄")
    else:
        # フォールバック: コアスキャン_v4.3
        ws_v43 = ss.worksheet('コアスキャン_v4.3')
        df_v43 = pd.DataFrame(ws_v43.get_all_records())
        df_v43['コード'] = df_v43['コード'].astype(str)
        has_existing = True
        print(f"$2705 変数1・2ソース読込（コアスキャン_v4.3フォールバック）: {len(df_v43)}銘柄")
except Exception as e:
    has_existing = False
    print(f"$26A0$FE0F 既存v4.3スコアが見つかりません。変数1・2はデフォルト値を使用: {e}")

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

    # 既存の変数1・2を取得（サニティチェック付き）
    # スコアは通常 0〜100 の整数。0〜1 の小数値が入っていれば「壊れた行」とみなしデフォルト
    s1, s2, rank_prev, total_prev = 50, 50, 'C', 50.0
    if has_existing:
        row = df_v43[df_v43['コード'] == code]
        if len(row) > 0:
            try:
                _s1 = float(row.iloc[0].get('変数1', 50) or 50)
                _s2 = float(row.iloc[0].get('変数2', 50) or 50)
            except (ValueError, TypeError):
                _s1, _s2 = 50.0, 50.0
            # サニティチェック: 絶対値 1 未満はスコア値としては異常（過去バグ書き込み）
            if abs(_s1) < 1.0 and abs(_s2) < 1.0:
                print(f"[WARN {code} 変数1={_s1}・変数2={_s2} は異常値・デフォルト使用] ", end='')
                s1, s2 = 50, 50
            else:
                s1 = int(round(_s1))
                s2 = int(round(_s2))
            rank_prev  = str(row.iloc[0].get('ランク', 'C'))
            try:
                total_prev = float(row.iloc[0].get('総合スコア', 50) or 50)
            except: total_prev = 50.0

    # 統合スコア再計算
    total_new = round(s1 * 0.40 + s2 * 0.35 + s3 * 0.25, 1)
    rank_new  = ('S' if total_new >= 80 else 'A' if total_new >= 65 else
                 'B' if total_new >= 50 else 'C' if total_new >= 35 else 'D')
    score_diff = round(total_new - total_prev, 1)

    # 暴落・急騰検知（±5%以上）
    alert_msg = ''
    if change_pct is not None and abs(change_pct) >= 5.0:
        direction = '$D83D$DCC8急騰' if change_pct > 0 else '$D83D$DCC9急落'
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
        status += " $26A0$FE0F"
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
     for v in list(r)]
    for _, r in df_daily.iterrows()
]
ws_daily.update('A1', rows_d)
print(f"\n$2705 日次スコア保存：'{SHEET_DAILY}'（{len(df_daily)}銘柄）")

# ── 暴落・急騰アラートの記録 ─────────────────────────────────
if alerts:
    print(f"\n$26A0$FE0F  暴落・急騰アラート（{len(alerts)}件）")
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
        print(f"$2705 アラート記録完了")
    except Exception as e:
        print(f"$26A0$FE0F アラート記録エラー: {e}")
else:
    print(f"\n$2705 暴落・急騰なし（全銘柄±5%以内）")

# ── 作業ログ ─────────────────────────────────────────────────
try:
    wl   = ss.worksheet('作業ログ')
    last = len(wl.get_all_values()) + 1
    wl.update(f'A{last}', [[NOW, '日次価格更新',
                             f'変数3を最新株価で再計算・時価総額ベース',
                             f'アラート{len(alerts)}件', '$2705完了']])
except: pass

# ── 最終サマリー ─────────────────────────────────────────────
print(f"\n{'='*60}")
print(f"日次変数3更新 完了サマリー")
print(f"{'='*60}")
print(f"  更新銘柄数：{len(df_daily)}銘柄")
print(f"  暴落急騰アラート：{len(alerts)}件")
print(f"  FCF利回り計算：時価総額ベース（株価連動）")
print(f"  暴落時動作：株価下落→PER低下→PEG低下→変数3上昇→スコア上昇→割安度増加")
print(f"\n$2705 日次スコア計算完了：{NOW}")

# ── v4.3スコアシートに最新株価・スコアを反映 ──────────────────
# generate_dashboard.py は「保有銘柄_v4.3スコア」「監視銘柄_v4.3スコア」から
# 読み込むため、日次更新結果をこれらのシートに反映する必要がある
print(f"\n{'='*60}")
print("v4.3スコアシートに日次結果を反映")
print('='*60)

# 日次結果をコード→データのdictに変換
daily_map = {}
for _, r in df_daily.iterrows():
    daily_map[str(r['コード'])] = r

SYNC_SHEETS = ['保有銘柄_v4.3スコア', '監視銘柄_v4.3スコア']
SYNC_COLS   = ['株価', '変数3', '総合スコア', 'ランク', 'PEG', 'FCF利回り']

for sheet_name in SYNC_SHEETS:
    try:
        ws = ss.worksheet(sheet_name)
        all_vals = ws.get_all_values()
        if len(all_vals) < 2:
            print(f"  {sheet_name}: データなし（スキップ）")
            continue

        header = all_vals[0]
        # 列インデックスを特定
        col_idx = {}
        for col_name in ['コード'] + SYNC_COLS:
            if col_name in header:
                col_idx[col_name] = header.index(col_name)

        if 'コード' not in col_idx:
            print(f"  {sheet_name}: コード列なし（スキップ）")
            continue

        updates = 0
        batch_updates = []

        for row_num in range(1, len(all_vals)):
            row = all_vals[row_num]
            code = str(row[col_idx['コード']]).strip()
            if code not in daily_map:
                continue

            dr = daily_map[code]
            for col_name in SYNC_COLS:
                if col_name not in col_idx:
                    continue
                ci = col_idx[col_name]
                # 日次結果の対応する列名
                src_map = {
                    '株価': '株価',
                    '変数3': '変数3(日次)',
                    '総合スコア': '総合スコア_日次',
                    'ランク': 'ランク',
                    'PEG': 'PEG',
                    'FCF利回り': 'FCF利回り(時価総額)',
                }
                src_key = src_map.get(col_name, col_name)
                new_val = dr.get(src_key)
                if new_val is not None and str(new_val) not in ('', 'nan', 'None'):
                    # gspread: row_num+1 (1-indexed, header=row1)
                    cell_label = gspread.utils.rowcol_to_a1(row_num + 1, ci + 1)
                    batch_updates.append({
                        'range': cell_label,
                        'values': [[float(new_val) if isinstance(new_val, (int, float, np.integer, np.floating)) else str(new_val)]]
                    })
            updates += 1

        if batch_updates:
            ws.batch_update(batch_updates)
            print(f"  {sheet_name}: {updates}銘柄を更新（{len(batch_updates)}セル）")
        else:
            print(f"  {sheet_name}: 更新対象なし")

    except Exception as e:
        print(f"  {sheet_name}: エラー {e}")

print(f"\n$2705 全処理完了：{NOW}")

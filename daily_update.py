"""
daily_update.py v1
AI投資判断システム 日次マクロ指標更新

【実行タイミング】毎日 7:00 JST（平日のみ・GitHub Actions）
【依存API】FRED API（25指標）/ Google Sheets API
【入力】FRED_API_KEY / GOOGLE_CREDENTIALS / SPREADSHEET_ID（環境変数）
【出力】スプレッドシート各指標シートに最新値を書き込み
       MacroPhase 4層スコア（Layer A〜D 合計100点）を計算・保存
【注意】レート制限対策：各書き込み後に3秒ウェイト（2026/03/29修正）
"""

import os
import json
import requests
import time
import numpy as np
import pandas as pd
import yfinance as yf
from datetime import datetime, timedelta
import gspread
from google.oauth2.service_account import Credentials

# ============================================================
# 認証
# ============================================================
FRED_API_KEY   = os.environ["FRED_API_KEY"]
SPREADSHEET_ID = os.environ["SPREADSHEET_ID"]
creds_json     = os.environ["GOOGLE_CREDENTIALS"]
creds_dict     = json.loads(creds_json)
scopes = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive"
]
creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
gc    = gspread.authorize(creds)
ss    = gc.open_by_key(SPREADSHEET_ID)
print(f"$2705 認証完了 ({datetime.now().strftime('%Y-%m-%d %H:%M')})")

# ============================================================
# 指標定義
# ============================================================
FRED_DAILY = {
    "VIX":             "VIXCLS",
    "HYスプレッド":    "BAMLH0A0HYM2",
    "TEDスプレッド":   "TEDRATE",
    "ドル円":          "DEXJPUS",
    "ドルインデックス":"DTWEXBGS",
    "長短金利差":      "T10Y2Y",
    "米10年債利回り":  "DGS10",
    "信用スプレッドIG":"BAMLC0A0CM",
    "WTI原油":         "DCOILWTICO",
    "金価格":          "GOLDPMGBD228NLBM",
}

FRED_MONTHLY = {
    "米M2":             "M2SL",
    "日本M2":           "MYAGM2JPM189S",
    "ユーロM3":         "MABMM301EZM189S",
    "FRBバランスシート":"WALCL",
    "米CPI":            "CPIAUCSL",
    "米PCEインフレ":    "PCEPI",
    "米失業率":         "UNRATE",
    "米小売売上高":     "RSXFS",
    "米鉱工業生産":     "INDPRO",
    "米設備稼働率":     "TCU",
    "米住宅着工件数":   "HOUST",
    "米耐久財受注":     "DGORDER",
    "米消費者信頼感":   "UMCSENT",
    "ISM製造業PMI":    "MANEMP",
    "米マネタリーベース":"BOGMBASE",
}

YF_DAILY = {
    "日経225":     "^N225",
    "TOPIX":      "1306.T",
    "SP500":      "^GSPC",
    "SOX指数":    "^SOX",
    "ラッセル2000":"^RUT",
}

# ============================================================
# ユーティリティ
# ============================================================
def clean_val(v):
    """NaN・infを空文字に変換"""
    if v is None: return ""
    try:
        f = float(v)
        if np.isnan(f) or np.isinf(f): return ""
        return round(f, 6)
    except: return ""

def fetch_fred_latest(series_id, days=400):
    """FREDから最新データを取得"""
    try:
        res = requests.get(
            "https://api.stlouisfed.org/fred/series/observations",
            params={
                "series_id": series_id,
                "api_key": FRED_API_KEY,
                "file_type": "json",
                "sort_order": "asc",
                "observation_start": (datetime.today()-timedelta(days=days)).strftime("%Y-%m-%d")
            },
            timeout=10
        )
        if res.status_code == 200:
            obs = res.json().get("observations", [])
            df = pd.DataFrame(obs)[["date","value"]]
            df["value"] = pd.to_numeric(df["value"], errors="coerce")
            return df.dropna().reset_index(drop=True)
    except: pass
    return None

def fetch_yf_latest(ticker, days=400):
    """yfinanceから最新データを取得"""
    try:
        df = yf.download(ticker,
                         start=(datetime.today()-timedelta(days=days)).strftime("%Y-%m-%d"),
                         end=datetime.today().strftime("%Y-%m-%d"),
                         progress=False, auto_adjust=True)
        if df.empty: return None
        df.columns = [c[0] if isinstance(c,tuple) else c for c in df.columns]
        df = df[["Close"]].reset_index()
        df.columns = ["date","value"]
        df["date"]  = df["date"].astype(str)
        df["value"] = pd.to_numeric(df["value"], errors="coerce")
        return df.dropna().reset_index(drop=True)
    except: return None

def append_new_rows(ws_name, new_df):
    """既存シートに新しい行を追記（重複スキップ・変化値計算）"""
    try:
        ws       = ss.worksheet(ws_name)
        existing = ws.get_all_values()
        if len(existing) < 2: return 0

        header   = existing[0]
        date_col = header[0]
        val_col  = header[1]

        ex_df = pd.DataFrame(existing[1:], columns=header)
        ex_df[date_col] = pd.to_datetime(ex_df[date_col], errors="coerce")
        ex_df[val_col]  = pd.to_numeric(ex_df[val_col],  errors="coerce")
        ex_df = ex_df.dropna(subset=[date_col]).sort_values(date_col)

        last_date = ex_df[date_col].max()

        new_df["date"] = pd.to_datetime(new_df["date"], errors="coerce")
        add_df = new_df[new_df["date"] > last_date].copy()
        if add_df.empty: return 0

        combined = pd.concat([
            ex_df[[date_col, val_col]].rename(columns={date_col:"date", val_col:"value"}),
            add_df[["date","value"]]
        ], ignore_index=True).sort_values("date").reset_index(drop=True)

        v = combined["value"]
        combined["前日比"]  = v.diff(1).round(4)
        combined["前週比"]  = v.diff(5).round(4)
        combined["前月比"]  = v.diff(21).round(4)
        combined["前年比"]  = v.diff(252).round(4)
        combined["前年比%"] = ((v / v.shift(252) - 1) * 100).round(2)
        combined["3M平均"]  = v.rolling(63).mean().round(4)
        combined["乖離率%"] = ((v / v.rolling(63).mean() - 1) * 100).round(2)
        combined["加速度"]  = combined["前月比"].diff(21).round(4)

        new_rows_df = combined[combined["date"] > last_date]
        new_cols    = ["date","value","前日比","前週比","前月比",
                       "前年比","前年比%","3M平均","乖離率%","加速度"]

        rows_to_add = []
        for _, row in new_rows_df.iterrows():
            r = [str(row["date"])[:10]]
            for c in new_cols[1:]:
                r.append(clean_val(row.get(c, "")))
            rows_to_add.append(r)

        if rows_to_add:
            ws.append_rows(rows_to_add)
        return len(rows_to_add)

    except Exception as e:
        print(f"    $26A0$FE0F {ws_name} 追記エラー: {e}")
        return 0

# ============================================================
# メイン処理
# ============================================================
print(f"\n{'='*55}")
print(f"$D83D$DCE1 毎日自動更新開始: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
print(f"{'='*55}\n")

total_added = 0

# ── FRED 日次指標 ──
print("【FRED 日次指標】")
for name, sid in FRED_DAILY.items():
    df = fetch_fred_latest(sid, days=30)
    if df is not None:
        added = append_new_rows(name, df)
        print(f"  $2705 {name}: +{added}行")
        total_added += added
    else:
        print(f"  $26A0$FE0F {name}: 取得失敗")
    time.sleep(3)

# ── FRED 月次指標 ──
print("\n【FRED 月次指標】")
for name, sid in FRED_MONTHLY.items():
    df = fetch_fred_latest(sid, days=90)
    if df is not None:
        added = append_new_rows(name, df)
        print(f"  $2705 {name}: +{added}行")
        total_added += added
    else:
        print(f"  $26A0$FE0F {name}: 取得失敗")
    time.sleep(3)

# ── yfinance 日次 ──
print("\n【yfinance 日次指標】")
for name, ticker in YF_DAILY.items():
    df = fetch_yf_latest(ticker, days=30)
    if df is not None:
        added = append_new_rows(name, df)
        print(f"  $2705 {name}: +{added}行")
        total_added += added
    else:
        print(f"  $26A0$FE0F {name}: 取得失敗")
    time.sleep(3)

# ── シラーPER近似値（SP500株価÷10年移動平均×20） ──
print("\n【シラーPER近似値更新】")
try:
    sp = yf.download("^GSPC",
                     start=(datetime.today()-timedelta(days=40*365)).strftime("%Y-%m-%d"),
                     end=datetime.today().strftime("%Y-%m-%d"),
                     progress=False, auto_adjust=True)
    if not sp.empty:
        sp.columns    = [c[0] if isinstance(c,tuple) else c for c in sp.columns]
        monthly       = sp["Close"].resample("ME").last()
        ma10y         = monthly.rolling(120).mean()
        cape          = (monthly / ma10y * 20).round(2)
        df_cape       = pd.DataFrame({
            "date":  cape.index.strftime("%Y-%m-%d"),
            "value": cape.values
        }).dropna()

        v = df_cape["value"]
        df_cape["前月比"]  = v.diff(1).round(4)
        df_cape["前年比%"] = ((v / v.shift(12) - 1) * 100).round(2)
        df_cape["3M平均"]  = v.rolling(3).mean().round(2)
        df_cape["乖離率%"] = ((v / v.rolling(36).mean() - 1) * 100).round(2)

        try:
            ws_cape = ss.worksheet("シラーPER")
            ws_cape.clear()
            ws_cape.resize(rows=len(df_cape)+5, cols=6)
        except gspread.exceptions.WorksheetNotFound:
            ws_cape = ss.add_worksheet(title="シラーPER", rows=len(df_cape)+5, cols=6)
        except Exception:
            time.sleep(5)
            ws_cape = ss.worksheet("シラーPER")
            ws_cape.clear()
        header  = ["date","value","前月比","前年比%","3M平均","乖離率%"]
        rows    = [header] + [
            [clean_val(row[c]) if c != "date" else str(row[c])
             for c in header]
            for _, row in df_cape.iterrows()
        ]
        ws_cape.update(range_name="A1", values=rows)
        latest = float(df_cape["value"].iloc[-1])
        print(f"  $2705 シラーPER近似値: {len(df_cape)}行 / 最新:{latest:.1f}倍")
        print(f"  ※ SP500株価÷10年移動平均×20で近似（参考値）")
except Exception as e:
    print(f"  $274C シラーPER: {e}")

# ── 異常値スコア更新 ──
print("\n【異常値スコア更新】")
try:
    anomaly_data  = []
    check_sheets  = list(FRED_DAILY.keys()) + list(YF_DAILY.keys()) + ["シラーPER"]

    for name in check_sheets:
        try:
            time.sleep(1)
            ws   = ss.worksheet(name)
            rows = ws.get_all_values()
            if len(rows) < 10: continue
            header = rows[0]
            df = pd.DataFrame(rows[1:], columns=header)
            if "乖離率%" not in df.columns: continue
            df["乖離率%"] = pd.to_numeric(df["乖離率%"], errors="coerce")
            latest_dev   = df["乖離率%"].dropna().iloc[-1] if not df["乖離率%"].dropna().empty else 0
            anomaly      = abs(latest_dev) > 20
            anomaly_data.append({
                "指標":       name,
                "最新乖離率%": round(latest_dev, 2),
                "異常値":     "$26A0$FE0F 異常" if anomaly else "$2705 正常",
                "更新日":     datetime.now().strftime("%Y-%m-%d")
            })
        except: continue

    if anomaly_data:
        try:
            ws_a = ss.worksheet("異常値スコア")
            ws_a.clear()
        except gspread.exceptions.WorksheetNotFound:
            ws_a = ss.add_worksheet(title="異常値スコア", rows=100, cols=4)
        except Exception:
            time.sleep(5)
            ws_a = ss.worksheet("異常値スコア")
            ws_a.clear()
        header_a = ["指標","最新乖離率%","異常値判定","更新日"]
        rows_a   = [[d["指標"],d["最新乖離率%"],d["異常値"],d["更新日"]] for d in anomaly_data]
        ws_a.update(range_name="A1", values=[header_a]+rows_a)
        anomaly_count = sum(1 for d in anomaly_data if "異常" in d["異常値"])
        print(f"  $2705 異常値スコア更新: {len(anomaly_data)}指標 / 異常{anomaly_count}件")
except Exception as e:
    print(f"  $274C 異常値スコア: {e}")



# ============================================================
# マクロフェーズ判定（4層100点）
# ============================================================

def get_latest_val(ss, sheet_name, col=1):
    try:
        time.sleep(1)
        ws = ss.worksheet(sheet_name)
        vals = ws.col_values(col + 1)
        for v in reversed(vals):
            if v and str(v).strip():
                try:
                    return float(str(v).replace(',', ''))
                except:
                    pass
    except Exception as e:
        print(f"  WARN: {sheet_name} 取得失敗 -> {e}")
    return None

def get_row_val(ss, sheet_name, col_name):
    """指定列名の最新値を取得"""
    try:
        time.sleep(1)
        ws = ss.worksheet(sheet_name)
        rows = ws.get_all_values()
        if not rows: return None
        header = rows[0]
        if col_name not in header: return None
        idx = header.index(col_name)
        for r in reversed(rows[1:]):
            if len(r) > idx and r[idx]:
                try: return float(str(r[idx]).replace(',',''))
                except: pass
    except Exception as e:
        print(f"  WARN {sheet_name}[{col_name}]: {e}")
    return None

def calc_macro_phase(ss):
    # 修正版 v2: 正しいシート名・列名・判定ロジック (2026/03/25)
    detail = {}
    total = 0

    # Layer A: リスク指標 (40点)
    layer_a = 0
    vix = get_latest_val(ss, 'VIX')
    if vix is not None:
        pts = 15 if vix < 15 else 10 if vix < 20 else 5 if vix < 25 else 0
        layer_a += pts
        detail['VIX'] = {'value': vix, 'pts': pts, 'max': 15}

    hyg = get_latest_val(ss, 'HYスプレッド')
    if hyg is not None:
        pts = 15 if hyg < 3 else 10 if hyg < 4 else 5 if hyg < 5 else 0
        layer_a += pts
        detail['HYG'] = {'value': hyg, 'pts': pts, 'max': 15}

    ted = get_latest_val(ss, 'TEDスプレッド')
    if ted is not None:
        pts = 10 if ted < 0.3 else 5 if ted < 0.5 else 0
        layer_a += pts
        detail['TED'] = {'value': ted, 'pts': pts, 'max': 10}

    total += layer_a
    detail['LayerA'] = {'score': layer_a, 'max': 40, 'name': 'リスク指標'}
    print(f"  Layer A (リスク指標): {layer_a}/40点")

    # Layer B: 金融政策 (30点)
    # M2:前月比% / FRB:前月比(符号)
    layer_b = 0
    m2_mom = get_row_val(ss, '日本M2', '前月比%')
    if m2_mom is not None:
        pts = 15 if m2_mom > 0.3 else 8 if m2_mom > 0 else 0
        layer_b += pts
        detail['JapanM2'] = {'value': m2_mom, 'pts': pts, 'max': 15, 'unit': '前月比%'}

    frb_mom = get_row_val(ss, 'FRBバランスシート', '前月比')
    if frb_mom is not None:
        pts = 15 if frb_mom > 0 else 8 if frb_mom > -50000 else 0
        layer_b += pts
        detail['FRB'] = {'value': frb_mom, 'pts': pts, 'max': 15, 'unit': '前月比'}

    total += layer_b
    detail['LayerB'] = {'score': layer_b, 'max': 30, 'name': '金融政策'}
    print(f"  Layer B (金融政策): {layer_b}/30点")

    # Layer C: 経済活動 (20点)
    # ISM:乖離率%と前月比の組み合わせ / 失業率:絶対値
    layer_c = 0
    ism_dev = get_row_val(ss, 'ISM製造業PMI', '乖離率%')
    ism_mom = get_row_val(ss, 'ISM製造業PMI', '前月比')
    if ism_dev is not None and ism_mom is not None:
        if ism_dev > 0 and ism_mom > 0:
            pts = 10
        elif ism_dev > -1 or ism_mom > 0:
            pts = 5
        else:
            pts = 0
        layer_c += pts
        detail['ISM'] = {'value': ism_dev, 'pts': pts, 'max': 10, 'unit': '乖離率%'}

    unemp = get_latest_val(ss, '米失業率')
    if unemp is not None:
        pts = 10 if unemp < 4.0 else 5 if unemp < 5.0 else 0
        layer_c += pts
        detail['UNEMP'] = {'value': unemp, 'pts': pts, 'max': 10}

    total += layer_c
    detail['LayerC'] = {'score': layer_c, 'max': 20, 'name': '経済活動'}
    print(f"  Layer C (経済活動): {layer_c}/20点")

    # Layer D: バリュエーション (10点)
    layer_d = 0
    cape = get_latest_val(ss, 'シラーPER')
    if cape is not None:
        pts = 10 if cape < 20 else 5 if cape < 28 else 0
        layer_d += pts
        detail['CAPE'] = {'value': cape, 'pts': pts, 'max': 10}

    total += layer_d
    detail['LayerD'] = {'score': layer_d, 'max': 10, 'name': 'バリュエーション'}
    print(f"  Layer D (バリュエーション): {layer_d}/10点")

    label = 'GREEN' if total >= 60 else 'YELLOW' if total >= 30 else 'RED'
    print(f"  総合: {total}/100 -> {label}")
    return total, label, detail


def save_macro_phase(ss, score, label, detail):
    import datetime
    now = datetime.datetime.now().strftime('%Y/%m/%d %H:%M')
    try:
        ws = ss.worksheet('MacroPhase')
    except gspread.exceptions.WorksheetNotFound:
        ws = ss.add_worksheet(title='MacroPhase', rows=500, cols=16)
        ws.update('A1', [['日時','スコア','フェーズ','LayerA','LayerB','LayerC','LayerD',
                          'VIX','HYspread','TEDspread','LongShortSpread',
                          'JapanM2','FRBbalance','ISMPMI','失業率','ShillerPER']])
        print("  OK: MacroPhase シート作成")
    except Exception as e:
        print(f"  WARN: MacroPhase取得リトライ: {e}")
        import time; time.sleep(10)
        ws = ss.worksheet('MacroPhase')
    row = [
        now, score, label,
        detail.get('LayerA',{}).get('score',''),
        detail.get('LayerB',{}).get('score',''),
        detail.get('LayerC',{}).get('score',''),
        detail.get('LayerD',{}).get('score',''),
        detail.get('VIX',{}).get('value',''),
        detail.get('HYG',{}).get('value',''),
        detail.get('TED',{}).get('value',''),
        '',  # LongShortSpread（未実装）
        detail.get('JapanM2',{}).get('value',''),
        detail.get('FRB',{}).get('value',''),
        detail.get('ISM',{}).get('value',''),
        detail.get('UNEMP',{}).get('value',''),
        detail.get('CAPE',{}).get('value',''),
    ]
    all_vals = ws.get_all_values()
    next_row = len(all_vals) + 1
    ws.update(f'A{next_row}', [row])
    print(f"  OK: MacroPhase 保存 ({now} / {label} / {score}点)")

# ── マクロフェーズ判定実行 ──
print("\n【マクロフェーズ判定】")
phase_score, phase_label, phase_detail = calc_macro_phase(ss)
save_macro_phase(ss, phase_score, phase_label, phase_detail)
# ── 完了 ──
print(f"\n{'='*55}")
print(f"$2705 毎日自動更新完了")
print(f"   追記行数合計: {total_added}行")
print(f"   シラーPER:    自動計算済み")
print(f"   実行時刻:     {datetime.now().strftime('%Y-%m-%d %H:%M')}")
print(f"{'='*55}")

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
print(f"✅ 認証完了 ({datetime.now().strftime('%Y-%m-%d %H:%M')})")

# ============================================================
# 指標定義
# ============================================================
FRED_DAILY = {
    "VIX":            "VIXCLS",
    "HYスプレッド":   "BAMLH0A0HYM2",
    "TEDスプレッド":  "TEDRATE",
    "ドル円":         "DEXJPUS",
    "ドルインデックス":"DTWEXBGS",
    "長短金利差":     "T10Y2Y",
    "米10年債利回り": "DGS10",
    "信用スプレッドIG":"BAMLC0A0CM",
    "WTI原油":        "DCOILWTICO",
    "金価格":         "GOLDPMGBD228NLBM",
}

FRED_MONTHLY = {
    "米M2":           "M2SL",
    "日本M2":         "MYAGM2JPM189S",
    "ユーロM3":       "MABMM301EZM189S",
    "FRBバランスシート":"WALCL",
    "米CPI":          "CPIAUCSL",
    "米PCEインフレ":  "PCEPI",
    "米失業率":       "UNRATE",
    "米小売売上高":   "RSXFS",
    "米鉱工業生産":   "INDPRO",
    "米設備稼働率":   "TCU",
    "米住宅着工件数": "HOUST",
    "米耐久財受注":   "DGORDER",
    "米消費者信頼感": "UMCSENT",
    "ISM製造業PMI":  "MANEMP",
    "米マネタリーベース":"BOGMBASE",
}

YF_DAILY = {
    "日経225":  "^N225",
    "TOPIX":   "1306.T",
    "SP500":   "^GSPC",
    "SOX指数": "^SOX",
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
    """
    既存シートに新しい行を追記
    重複日付はスキップ・変化値を計算して追記
    """
    try:
        ws       = ss.worksheet(ws_name)
        existing = ws.get_all_values()

        if len(existing) < 2:
            return 0

        header   = existing[0]
        date_col = header[0]
        val_col  = header[1]

        # 既存データをDataFrameに
        ex_df = pd.DataFrame(existing[1:], columns=header)
        ex_df[date_col] = pd.to_datetime(ex_df[date_col], errors="coerce")
        ex_df[val_col]  = pd.to_numeric(ex_df[val_col],  errors="coerce")
        ex_df = ex_df.dropna(subset=[date_col]).sort_values(date_col)

        # 既存の最新日付
        last_date = ex_df[date_col].max()

        # 新しい行のみ抽出
        new_df["date"] = pd.to_datetime(new_df["date"], errors="coerce")
        add_df = new_df[new_df["date"] > last_date].copy()

        if add_df.empty:
            return 0

        # 全データを結合して変化値を計算
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

        # 追記する行のみ
        new_rows_df = combined[combined["date"] > last_date]

        new_cols = ["date","value","前日比","前週比","前月比",
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
        print(f"    ⚠️ {ws_name} 追記エラー: {e}")
        return 0

# ============================================================
# メイン処理
# ============================================================
print(f"\n{'='*55}")
print(f"📡 毎日自動更新開始: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
print(f"{'='*55}\n")

total_added = 0

# ── FRED 日次指標 ──
print("【FRED 日次指標】")
for name, sid in FRED_DAILY.items():
    df = fetch_fred_latest(sid, days=30)
    if df is not None:
        added = append_new_rows(name, df)
        print(f"  {'✅' if added>=0 else '❌'} {name}: +{added}行")
        total_added += added
    else:
        print(f"  ⚠️ {name}: 取得失敗")
    time.sleep(0.3)

# ── FRED 月次指標 ──
print("\n【FRED 月次指標】")
for name, sid in FRED_MONTHLY.items():
    df = fetch_fred_latest(sid, days=90)
    if df is not None:
        added = append_new_rows(name, df)
        print(f"  {'✅' if added>=0 else '❌'} {name}: +{added}行")
        total_added += added
    else:
        print(f"  ⚠️ {name}: 取得失敗")
    time.sleep(0.3)

# ── yfinance 日次 ──
print("\n【yfinance 日次指標】")
for name, ticker in YF_DAILY.items():
    df = fetch_yf_latest(ticker, days=30)
    if df is not None:
        added = append_new_rows(name, df)
        print(f"  {'✅' if added>=0 else '❌'} {name}: +{added}行")
        total_added += added
    else:
        print(f"  ⚠️ {name}: 取得失敗")
    time.sleep(0.3)

# ── 異常値スコア更新 ──
print("\n【異常値スコア更新】")
try:
    anomaly_data = []
    check_sheets = list(FRED_DAILY.keys()) + list(YF_DAILY.keys())

    for name in check_sheets:
        try:
            ws   = ss.worksheet(name)
            rows = ws.get_all_values()
            if len(rows) < 10: continue
            header = rows[0]
            df = pd.DataFrame(rows[1:], columns=header)
            if "乖離率%" not in df.columns: continue
            df["乖離率%"] = pd.to_numeric(df["乖離率%"], errors="coerce")
            latest_dev = df["乖離率%"].dropna().iloc[-1] if not df["乖離率%"].dropna().empty else 0
            anomaly = abs(latest_dev) > 20
            anomaly_data.append({
                "指標": name,
                "最新乖離率%": round(latest_dev, 2),
                "異常値": "⚠️ 異常" if anomaly else "✅ 正常",
                "更新日": datetime.now().strftime("%Y-%m-%d")
            })
        except: continue

    if anomaly_data:
        try:
            ws_a = ss.worksheet("異常値スコア")
            ss.del_worksheet(ws_a)
        except: pass
        ws_a = ss.add_worksheet(title="異常値スコア", rows=100, cols=4)
        header_a = ["指標","最新乖離率%","異常値判定","更新日"]
        rows_a   = [[d["指標"],d["最新乖離率%"],d["異常値"],d["更新日"]] for d in anomaly_data]
        ws_a.update(range_name="A1", values=[header_a]+rows_a)
        anomaly_count = sum(1 for d in anomaly_data if "異常" in d["異常値"])
        print(f"  ✅ 異常値スコア更新: {len(anomaly_data)}指標 / 異常{anomaly_count}件")
except Exception as e:
    print(f"  ❌ 異常値スコア: {e}")

# ── 完了 ──
print(f"\n{'='*55}")
print(f"✅ 毎日自動更新完了")
print(f"   追記行数合計: {total_added}行")
print(f"   実行時刻: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
print(f"{'='*55}")

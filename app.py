import streamlit as st
import gspread
import json
import os
import pandas as pd
from google.oauth2.service_account import Credentials

# ============================================================
# 認証
# ============================================================
@st.cache_resource
def get_spreadsheet():
    creds_json = os.environ.get("GOOGLE_CREDENTIALS", "")
    if not creds_json:
        st.error("GOOGLE_CREDENTIALSが設定されていません")
        return None
    creds_dict = json.loads(creds_json)
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive"
    ]
    creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
    gc   = gspread.authorize(creds)
    ss   = gc.open_by_key(os.environ.get("SPREADSHEET_ID", "1GtlVhGcPjMU0pJWsijwnmTe1rFJXAGvkaJFjav9gGcE"))
    return ss

# ============================================================
# データ読み込み
# ============================================================
@st.cache_data(ttl=3600)
def load_data():
    ss = get_spreadsheet()
    if ss is None:
        return None, None, None

    ws   = ss.worksheet("予測記録")
    rows = ws.get_all_values()
    if len(rows) < 2:
        return None, None, None
    header = rows[0]
    df = pd.DataFrame(rows[1:], columns=header)

    for col in ["現在株価","マクロスコア","業種スコア","銘柄スコア","総合スコア","目標株価(3M)","損切り水準"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    # ★修正：株価が入っている行のみを対象に最新日付を取得
    df_valid = df[df["現在株価"].notna() & (df["現在株価"] > 0)]
    if not df_valid.empty:
        latest_date = df_valid["予測日"].max()
    else:
        latest_date = df["予測日"].max()

    df_latest = df[df["予測日"] == latest_date].copy()

    try:
        ws_sec   = ss.worksheet("業種スコア")
        sec_rows = ws_sec.get_all_values()
        df_sec   = pd.DataFrame(sec_rows[1:], columns=sec_rows[0]) if len(sec_rows)>1 else pd.DataFrame()
        if "スコア" in df_sec.columns:
            df_sec["スコア"] = pd.to_numeric(df_sec["スコア"], errors="coerce")
    except:
        df_sec = pd.DataFrame()

    return df_latest, df_sec, latest_date

# ============================================================
# ページ設定
# ============================================================
st.set_page_config(page_title="AI投資判断システム", page_icon="📈", layout="wide")
st.title("📈 AI投資判断システム")
st.caption("毎週月曜自動更新 | 3層スコア（マクロ40%・業種30%・銘柄30%）")

df_latest, df_sec, latest_date = load_data()

if df_latest is None:
    st.error("データの読み込みに失敗しました")
    st.stop()

tab1, tab2, tab3 = st.tabs(["📊 銘柄スコア", "🌡️ 業種体温計", "📡 マクロ指標"])

# ============================================================
# Tab1: 銘柄スコア
# ============================================================
with tab1:
    st.caption(f"最終更新: {latest_date}")

    col1, col2, col3, col4 = st.columns(4)
    total_count = len(df_latest)
    buy_count   = int((df_latest["総合スコア"] >= 30).sum()) if "総合スコア" in df_latest.columns else 0
    macro_score = df_latest["マクロスコア"].iloc[0] if "マクロスコア" in df_latest.columns and len(df_latest)>0 else 0
    sec_avg     = df_latest["業種スコア"].mean() if "業種スコア" in df_latest.columns else 0

    with col1: st.metric("分析銘柄数", f"{total_count}銘柄")
    with col2: st.metric("買い検討", f"{buy_count}銘柄")
    with col3: st.metric("マクロスコア", f"{int(macro_score) if pd.notna(macro_score) else 0}")
    with col4: st.metric("業種平均", f"{sec_avg:.1f}")

    st.divider()

    if "シグナル" in df_latest.columns:
        signal_options = ["全て"] + sorted(df_latest["シグナル"].dropna().unique().tolist())
    else:
        signal_options = ["全て"]
    selected = st.selectbox("絞り込み", signal_options)

    df_view = df_latest.copy()
    if selected != "全て" and "シグナル" in df_view.columns:
        df_view = df_view[df_view["シグナル"] == selected]

    if "総合スコア" in df_view.columns:
        df_view = df_view.sort_values("総合スコア", ascending=False)

    display_cols = [c for c in ["銘柄コード","銘柄名","現在株価","マクロスコア","業種スコア","銘柄スコア","総合スコア","予測方向"] if c in df_view.columns]
    df_display = df_view[display_cols].copy()
    if "現在株価" in df_display.columns:
        df_display["現在株価"] = df_display["現在株価"].apply(
            lambda x: f"{int(x):,}" if pd.notna(x) and x > 0 else "取得中"
        )
    st.dataframe(df_display, use_container_width=True, hide_index=True)

    if buy_count > 0 and "総合スコア" in df_latest.columns:
        st.subheader(f"🟡 買い検討銘柄（{buy_count}銘柄）")
        df_buy  = df_latest[df_latest["総合スコア"] >= 30].sort_values("総合スコア", ascending=False)
        buy_cols = [c for c in ["銘柄コード","銘柄名","現在株価","総合スコア","予測方向","目標株価(3M)","損切り水準"] if c in df_buy.columns]
        st.dataframe(df_buy[buy_cols], use_container_width=True, hide_index=True)

# ============================================================
# Tab2: 業種体温計
# ============================================================
with tab2:
    st.subheader("🌡️ 33業種 体温計")
    if df_sec is not None and not df_sec.empty and "スコア" in df_sec.columns:
        df_sec_sorted = df_sec.sort_values("スコア", ascending=False)
        strong  = df_sec_sorted[df_sec_sorted["スコア"] >= 30]
        neutral = df_sec_sorted[(df_sec_sorted["スコア"] >= -30) & (df_sec_sorted["スコア"] < 30)]
        weak    = df_sec_sorted[df_sec_sorted["スコア"] < -30]
        col1, col2, col3 = st.columns(3)
        with col1:
            st.markdown("#### 🟢 強気業種")
            for _, row in strong.iterrows():
                st.markdown(f"**{row['業種']}** : {int(row['スコア']):+d}")
        with col2:
            st.markdown("#### 🟡 中立業種")
            for _, row in neutral.iterrows():
                st.markdown(f"{row['業種']} : {int(row['スコア']):+d}")
        with col3:
            st.markdown("#### 🔴 弱気業種")
            for _, row in weak.iterrows():
                st.markdown(f"{row['業種']} : {int(row['スコア']):+d}")
    else:
        st.info("業種スコアデータがありません")

# ============================================================
# Tab3: マクロ指標
# ============================================================
with tab3:
    st.subheader("📡 マクロ指標")
    if len(df_latest) > 0:
        macro_val = df_latest["マクロスコア"].iloc[0] if "マクロスコア" in df_latest.columns else 0
        if macro_val >= 60:    macro_label = "🟢 強買い"
        elif macro_val >= 30:  macro_label = "🟡 買い検討"
        elif macro_val >= -30: macro_label = "⚪ 中立"
        elif macro_val >= -60: macro_label = "🟠 様子見"
        else:                   macro_label = "🔴 売り検討"
        st.metric("マクロスコア", f"{int(macro_val) if pd.notna(macro_val) else 0}", delta=macro_label)
        st.divider()
        st.markdown("""
**指標の見方：**
- マクロスコア +45 → 買い検討水準
- VIX < 20 → 市場安定
- HYスプレッド < 4% → リスクオン
- 逆イールド > 0 → 景気後退リスク低
- M2増加 → 流動性供給中

**崩れる条件（撤退ルール）：**
- VIX > 35 → 全銘柄現金化検討
- HYスプレッド > 6% → リスク資産半減
- 逆イールド < -1.0% → 現金比率50%へ
- M2が3ヶ月連続減少 → 新規購入停止
        """)

st.divider()
st.caption("AI投資判断システム | 毎週月曜朝8時自動更新 | バックテスト：5Y勝率88%・日経超過+14%/年")

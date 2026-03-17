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
    ss   = gc.open_by_key(os.environ.get("SPREADSHEET_ID",
           "1GtlVhGcPjMU0pJWsijwnmTe1rFJXAGvkaJFjav9gGcE"))
    return ss

# ============================================================
# データ読み込み
# ============================================================
@st.cache_data(ttl=3600)
def load_data():
    ss = get_spreadsheet()
    if ss is None:
        return None, None, None

    # 予測記録
    ws   = ss.worksheet("予測記録")
    rows = ws.get_all_values()
    if len(rows) < 2:
        return None, None, None
    header = rows[0]
    df = pd.DataFrame(rows[1:], columns=header)

    for col in ["現在株価","マクロスコア","業種スコア","銘柄スコア","総合スコア","目標株価(3M)","損切り水準"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    # 株価が入っている行のみで最新日付を取得
    df_valid = df[df["現在株価"].notna() & (df["現在株価"] > 0)]
    latest_date = df_valid["予測日"].max() if not df_valid.empty else df["予測日"].max()
    df_latest   = df[df["予測日"] == latest_date].copy()

    # 重複銘柄を除去（同日付で最新1行のみ）
    if "銘柄コード" in df_latest.columns:
        df_latest = df_latest.drop_duplicates(subset=["銘柄コード"], keep="last")

    # 業種スコア
    try:
        ws_sec   = ss.worksheet("業種スコア")
        sec_rows = ws_sec.get_all_values()
        df_sec   = pd.DataFrame(sec_rows[1:], columns=sec_rows[0]) if len(sec_rows)>1 else pd.DataFrame()
        if "スコア" in df_sec.columns:
            df_sec["スコア"] = pd.to_numeric(df_sec["スコア"], errors="coerce")
    except:
        df_sec = pd.DataFrame()

    # 経営品質スコアv2
    try:
        ws_mq   = ss.worksheet("経営品質スコアv2")
        mq_rows = ws_mq.get_all_values()
        df_mq   = pd.DataFrame(mq_rows[1:], columns=mq_rows[0]) if len(mq_rows)>1 else pd.DataFrame()
        if "経営品質スコア" in df_mq.columns:
            df_mq["経営品質スコア"] = pd.to_numeric(df_mq["経営品質スコア"], errors="coerce")
    except:
        df_mq = pd.DataFrame()

    # 統合スコア
    try:
        ws_int   = ss.worksheet("統合スコア")
        int_rows = ws_int.get_all_values()
        df_int   = pd.DataFrame(int_rows[1:], columns=int_rows[0]) if len(int_rows)>1 else pd.DataFrame()
        for col in ["旧スコア","新スコア","経営品質スコア"]:
            if col in df_int.columns:
                df_int[col] = pd.to_numeric(df_int[col], errors="coerce")
    except:
        df_int = pd.DataFrame()

    return df_latest, df_sec, latest_date, df_mq, df_int

# ============================================================
# ページ設定
# ============================================================
st.set_page_config(page_title="AI投資判断システム", page_icon="📈", layout="wide")
st.title("📈 AI投資判断システム")
st.caption("毎週月曜自動更新 | 統合スコア（マクロ30%・業種25%・銘柄25%・経営品質20%）")

result = load_data()
if result is None or result[0] is None:
    st.error("データの読み込みに失敗しました")
    st.stop()

df_latest, df_sec, latest_date, df_mq, df_int = result

tab1, tab2, tab3, tab4 = st.tabs(["📊 統合スコア", "🌡️ 業種体温計", "💹 経営品質", "📡 マクロ指標"])

# ============================================================
# Tab1: 統合スコア
# ============================================================
with tab1:
    st.caption(f"最終更新: {latest_date}")

    col1, col2, col3, col4 = st.columns(4)
    total_count = len(df_latest)
    macro_score = df_latest["マクロスコア"].iloc[0] if "マクロスコア" in df_latest.columns and len(df_latest)>0 else 0
    sec_avg     = df_latest["業種スコア"].mean() if "業種スコア" in df_latest.columns else 0

    # 統合スコアから買い検討を計算
    if not df_int.empty and "新スコア" in df_int.columns:
        buy_count = int((df_int["新スコア"] >= 30).sum())
    else:
        buy_count = int((df_latest["総合スコア"] >= 30).sum()) if "総合スコア" in df_latest.columns else 0

    with col1: st.metric("分析銘柄数", f"{total_count}銘柄")
    with col2: st.metric("買い検討（統合）", f"{buy_count}銘柄")
    with col3: st.metric("マクロスコア", f"{int(macro_score) if pd.notna(macro_score) else 0}")
    with col4: st.metric("業種平均", f"{sec_avg:.1f}")

    st.divider()

    # 統合スコアテーブル
    if not df_int.empty:
        st.subheader("🔮 統合スコア（マクロ30%・業種25%・銘柄25%・経営品質20%）")
        df_int_view = df_int.sort_values("新スコア", ascending=False) if "新スコア" in df_int.columns else df_int

        # 買い検討ハイライト
        if "新スコア" in df_int_view.columns:
            buy_df = df_int_view[df_int_view["新スコア"] >= 30]
            if not buy_df.empty:
                st.markdown(f"#### 🟡 買い検討銘柄（{len(buy_df)}銘柄）")
                show_cols = [c for c in ["コード","銘柄名","業種","旧スコア","新スコア","差","経営品質スコア","経営品質判定"] if c in buy_df.columns]
                st.dataframe(buy_df[show_cols], use_container_width=True, hide_index=True)
                st.divider()

        st.markdown("#### 全銘柄スコア一覧")
        show_cols = [c for c in ["コード","銘柄名","業種","旧スコア","新スコア","差","経営品質スコア","経営品質判定"] if c in df_int_view.columns]
        st.dataframe(df_int_view[show_cols], use_container_width=True, hide_index=True)
    else:
        # フォールバック：予測記録から表示
        display_cols = [c for c in ["銘柄コード","銘柄名","現在株価","マクロスコア","業種スコア","銘柄スコア","総合スコア","予測方向"] if c in df_latest.columns]
        df_view = df_latest.sort_values("総合スコア", ascending=False) if "総合スコア" in df_latest.columns else df_latest
        df_display = df_view[display_cols].copy()
        if "現在株価" in df_display.columns:
            df_display["現在株価"] = df_display["現在株価"].apply(
                lambda x: f"{int(x):,}" if pd.notna(x) and x>0 else "取得中"
            )
        st.dataframe(df_display, use_container_width=True, hide_index=True)

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
# Tab3: 経営品質スコア
# ============================================================
with tab3:
    st.subheader("💹 経営品質スコア（業種別基準）")
    if df_mq is not None and not df_mq.empty:
        df_mq_sorted = df_mq.sort_values("経営品質スコア", ascending=False) if "経営品質スコア" in df_mq.columns else df_mq

        col1, col2 = st.columns(2)
        with col1:
            st.markdown("#### 🟢 成長加速（上位）")
            top5 = df_mq_sorted.head(5)
            for _, row in top5.iterrows():
                score = row.get("経営品質スコア","")
                label = row.get("判定","")
                name  = row.get("銘柄名","")
                st.markdown(f"{label} **{name}** : {int(score):+d}点")
        with col2:
            st.markdown("#### 🔴 要注意（下位）")
            bot5 = df_mq_sorted.tail(5).iloc[::-1]
            for _, row in bot5.iterrows():
                score = row.get("経営品質スコア","")
                label = row.get("判定","")
                name  = row.get("銘柄名","")
                st.markdown(f"{label} **{name}** : {int(score):+d}点")

        st.divider()
        show_cols = [c for c in ["証券コード","銘柄名","業種","経営品質スコア","判定",
                                  "売上高成長率%","営業利益率%","EPS成長率%","主な根拠"] if c in df_mq_sorted.columns]
        st.dataframe(df_mq_sorted[show_cols], use_container_width=True, hide_index=True)
    else:
        st.info("経営品質スコアデータがありません")

# ============================================================
# Tab4: マクロ指標
# ============================================================
with tab4:
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
**現在の市場環境：**
- マクロスコア +45 → 買い検討水準
- 3シナリオ：🟢 強気65% / 中立23% / 弱気12%
- 現在フェーズ：減速期（VIX=27.3・HY=3.17%）

**指標の見方：**
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
st.caption("AI投資判断システム | daily自動更新（平日朝7時）+ weekly自動更新（月曜10時）| バックテスト：5Y勝率88%・日経超過+14%/年")

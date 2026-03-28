"""
app.py - Streamlit dashboard for local development

A lightweight Streamlit interface for viewing spreadsheet data locally.
Not used in production (GitHub Pages serves ai_dashboard_v13.html).

Usage: streamlit run app.py
"""
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
        return None, None, None, None, None, None

    # 予測記録
    ws   = ss.worksheet("予測記録")
    rows = ws.get_all_values()
    if len(rows) < 2:
        return None, None, None, None, None, None
    df = pd.DataFrame(rows[1:], columns=rows[0])
    for col in ["現在株価","マクロスコア","業種スコア","銘柄スコア","総合スコア","目標株価(3M)","損切り水準"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    df_valid  = df[df["現在株価"].notna() & (df["現在株価"] > 0)]
    latest_dt = df_valid["予測日"].max() if not df_valid.empty else df["予測日"].max()
    df_latest = df[df["予測日"] == latest_dt].copy()
    if "銘柄コード" in df_latest.columns:
        df_latest = df_latest.drop_duplicates(subset=["銘柄コード"], keep="last")

    # 業種スコア
    try:
        r = ss.worksheet("業種スコア").get_all_values()
        df_sec = pd.DataFrame(r[1:], columns=r[0]) if len(r)>1 else pd.DataFrame()
        if "スコア" in df_sec.columns:
            df_sec["スコア"] = pd.to_numeric(df_sec["スコア"], errors="coerce")
    except: df_sec = pd.DataFrame()

    # 経営品質スコアv2
    try:
        r = ss.worksheet("経営品質スコアv2").get_all_values()
        df_mq = pd.DataFrame(r[1:], columns=r[0]) if len(r)>1 else pd.DataFrame()
        if "経営品質スコア" in df_mq.columns:
            df_mq["経営品質スコア"] = pd.to_numeric(df_mq["経営品質スコア"], errors="coerce")
    except: df_mq = pd.DataFrame()

    # 統合スコア
    try:
        r = ss.worksheet("統合スコア").get_all_values()
        df_int = pd.DataFrame(r[1:], columns=r[0]) if len(r)>1 else pd.DataFrame()
        for col in ["旧スコア","新スコア","経営品質スコア"]:
            if col in df_int.columns:
                df_int[col] = pd.to_numeric(df_int[col], errors="coerce")
    except: df_int = pd.DataFrame()

    # バリュー成長スコア
    try:
        r = ss.worksheet("バリュー成長スコア").get_all_values()
        df_vg = pd.DataFrame(r[1:], columns=r[0]) if len(r)>1 else pd.DataFrame()
        for col in ["PER","EPS成長率%","PEG","統合スコア","PBR","ROE%"]:
            if col in df_vg.columns:
                df_vg[col] = pd.to_numeric(df_vg[col], errors="coerce")
    except: df_vg = pd.DataFrame()

    return df_latest, df_sec, latest_dt, df_mq, df_int, df_vg

# ============================================================
# ページ設定
# ============================================================
st.set_page_config(page_title="AI投資判断システム", page_icon="$D83D$DCC8", layout="wide")
st.title("$D83D$DCC8 AI投資判断システム")
st.caption("2軸分析：統合スコア（マクロ35%・業種30%・テクニカル25%・経営品質10%）× バリュー成長（PEGレシオ）")

result = load_data()
if result is None or result[0] is None:
    st.error("データの読み込みに失敗しました")
    st.stop()

df_latest, df_sec, latest_dt, df_mq, df_int, df_vg = result

tab1, tab2, tab3, tab4, tab5 = st.tabs([
    "$D83D$DCCA 統合スコア", "$D83C$DF21$FE0F 業種体温計", "$D83D$DCB9 経営品質",
    "$D83D$DCE1 マクロ指標", "$D83C$DFAF 2軸分析"
])

# ============================================================
# Tab1: 統合スコア
# ============================================================
with tab1:
    st.caption(f"最終更新: {latest_dt}")
    col1, col2, col3, col4 = st.columns(4)
    macro_score = df_latest["マクロスコア"].iloc[0] if "マクロスコア" in df_latest.columns and len(df_latest)>0 else 0
    sec_avg     = df_latest["業種スコア"].mean() if "業種スコア" in df_latest.columns else 0
    buy_count   = int((df_int["新スコア"] >= 30).sum()) if not df_int.empty and "新スコア" in df_int.columns else 0

    with col1: st.metric("分析銘柄数", f"{len(df_latest)}銘柄")
    with col2: st.metric("統合買い検討", f"{buy_count}銘柄")
    with col3: st.metric("マクロスコア", f"{int(macro_score) if pd.notna(macro_score) else 0}")
    with col4: st.metric("業種平均", f"{sec_avg:.1f}")
    st.divider()

    if not df_int.empty:
        st.subheader("$D83D$DD2E 統合スコア（マクロ35%・業種30%・テクニカル25%・経営品質10%）")
        df_int_view = df_int.sort_values("新スコア", ascending=False) if "新スコア" in df_int.columns else df_int
        buy_df = df_int_view[df_int_view["新スコア"] >= 30] if "新スコア" in df_int_view.columns else pd.DataFrame()
        if not buy_df.empty:
            st.markdown(f"#### $D83D$DFE1 買い検討銘柄（{len(buy_df)}銘柄）")
            show_cols = [c for c in ["コード","銘柄名","業種","旧スコア","新スコア","差","経営品質スコア","経営品質判定"] if c in buy_df.columns]
            st.dataframe(buy_df[show_cols], use_container_width=True, hide_index=True)
            st.divider()
        st.markdown("#### 全銘柄スコア一覧")
        show_cols = [c for c in ["コード","銘柄名","業種","旧スコア","新スコア","差","経営品質スコア","経営品質判定"] if c in df_int_view.columns]
        st.dataframe(df_int_view[show_cols], use_container_width=True, hide_index=True)
    else:
        df_view = df_latest.sort_values("総合スコア", ascending=False) if "総合スコア" in df_latest.columns else df_latest
        st.dataframe(df_view, use_container_width=True, hide_index=True)

# ============================================================
# Tab2: 業種体温計
# ============================================================
with tab2:
    st.subheader("$D83C$DF21$FE0F 33業種 体温計")
    if df_sec is not None and not df_sec.empty and "スコア" in df_sec.columns:
        df_s = df_sec.sort_values("スコア", ascending=False)
        strong  = df_s[df_s["スコア"] >= 30]
        neutral = df_s[(df_s["スコア"] >= -30) & (df_s["スコア"] < 30)]
        weak    = df_s[df_s["スコア"] < -30]
        c1,c2,c3 = st.columns(3)
        with c1:
            st.markdown("#### $D83D$DFE2 強気業種")
            for _,r in strong.iterrows(): st.markdown(f"**{r['業種']}** : {int(r['スコア']):+d}")
        with c2:
            st.markdown("#### $D83D$DFE1 中立業種")
            for _,r in neutral.iterrows(): st.markdown(f"{r['業種']} : {int(r['スコア']):+d}")
        with c3:
            st.markdown("#### $D83D$DD34 弱気業種")
            for _,r in weak.iterrows(): st.markdown(f"{r['業種']} : {int(r['スコア']):+d}")
    else:
        st.info("業種スコアデータがありません")

# ============================================================
# Tab3: 経営品質スコア
# ============================================================
with tab3:
    st.subheader("$D83D$DCB9 経営品質スコア（業種別基準）")
    if df_mq is not None and not df_mq.empty:
        df_mq_s = df_mq.sort_values("経営品質スコア", ascending=False) if "経営品質スコア" in df_mq.columns else df_mq
        c1,c2 = st.columns(2)
        with c1:
            st.markdown("#### $D83D$DFE2 成長加速（上位5）")
            for _,r in df_mq_s.head(5).iterrows():
                st.markdown(f"{r.get('判定','')} **{r.get('銘柄名','')}** : {int(r.get('経営品質スコア',0)):+d}点")
        with c2:
            st.markdown("#### $D83D$DD34 要注意（下位5）")
            for _,r in df_mq_s.tail(5).iloc[::-1].iterrows():
                st.markdown(f"{r.get('判定','')} **{r.get('銘柄名','')}** : {int(r.get('経営品質スコア',0)):+d}点")
        st.divider()
        show_cols = [c for c in ["証券コード","銘柄名","業種","経営品質スコア","判定",
                                  "売上高成長率%","営業利益率%","EPS成長率%","主な根拠"] if c in df_mq_s.columns]
        st.dataframe(df_mq_s[show_cols], use_container_width=True, hide_index=True)
    else:
        st.info("経営品質スコアデータがありません")

# ============================================================
# Tab4: マクロ指標
# ============================================================
with tab4:
    st.subheader("$D83D$DCE1 マクロ指標")
    if len(df_latest) > 0:
        macro_val = df_latest["マクロスコア"].iloc[0] if "マクロスコア" in df_latest.columns else 0
        if macro_val >= 60:    ml = "$D83D$DFE2 強買い"
        elif macro_val >= 30:  ml = "$D83D$DFE1 買い検討"
        elif macro_val >= -30: ml = "$26AA 中立"
        elif macro_val >= -60: ml = "$D83D$DFE0 様子見"
        else:                   ml = "$D83D$DD34 売り検討"
        st.metric("マクロスコア", f"{int(macro_val) if pd.notna(macro_val) else 0}", delta=ml)
        st.divider()
        st.markdown("""
**現在の市場環境（2026/3/17）：**
- マクロスコア +45 → 買い検討水準
- 3シナリオ：$D83D$DFE2 強気65% / 中立23% / 弱気12%
- 現在フェーズ：減速期（VIX=27.3・HY=3.17%）
- シラーPER：34.3倍（割高警戒）

**崩れる条件（撤退ルール）：**
- VIX > 35 → 全銘柄現金化検討
- HYスプレッド > 6% → リスク資産半減
- 逆イールド < -1.0% → 現金比率50%へ
- M2が3ヶ月連続減少 → 新規購入停止
        """)

# ============================================================
# Tab5: 2軸分析（メイン判断画面）
# ============================================================
with tab5:
    st.subheader("$D83C$DFAF 2軸分析：最終投資判断")
    st.caption("統合スコア（市場タイミング）× バリュー成長（PEGレシオ）の2軸で判断")

    if df_vg is not None and not df_vg.empty:

        # サマリーカード
        strong_buy = df_vg[df_vg["最終判定"] == "$D83D$DFE2 強買い推奨"]
        buy_rec    = df_vg[df_vg["最終判定"] == "$D83D$DFE1 買い推奨"]
        timing     = df_vg[df_vg["最終判定"] == "$D83D$DFE0 タイミング待ち"]
        hidden     = df_vg[(df_vg["最終判定"] == "$26AA 割安だが時期尚早") &
                           (df_vg["PEG"].notna()) & (df_vg["PEG"] < 1.0)]

        c1,c2,c3,c4 = st.columns(4)
        with c1: st.metric("$D83D$DFE2 強買い推奨", f"{len(strong_buy)}銘柄")
        with c2: st.metric("$D83D$DFE1 買い推奨",   f"{len(buy_rec)}銘柄")
        with c3: st.metric("$D83D$DFE0 押し目待ち", f"{len(timing)}銘柄")
        with c4: st.metric("$26AA 隠れ割安",   f"{len(hidden)}銘柄")

        st.divider()

        # 強買い推奨
        if not strong_buy.empty:
            st.markdown("### $D83D$DFE2 強買い推奨（統合+30以上 × PEG<1.0）")
            show = [c for c in ["コード","銘柄名","業種","統合スコア","PEG","PEG判定","PER","EPS成長率%","ROE%","テーマ"] if c in strong_buy.columns]
            st.dataframe(strong_buy[show], use_container_width=True, hide_index=True)
            st.divider()

        # 買い推奨
        if not buy_rec.empty:
            st.markdown("### $D83D$DFE1 買い推奨（統合+20以上 × PEG<1.0）")
            show = [c for c in ["コード","銘柄名","業種","統合スコア","PEG","PEG判定","PER","EPS成長率%","ROE%","テーマ"] if c in buy_rec.columns]
            st.dataframe(buy_rec[show], use_container_width=True, hide_index=True)
            st.divider()

        # タイミング待ち
        if not timing.empty:
            st.markdown("### $D83D$DFE0 タイミング待ち（統合+30以上 × PEG>1.0）")
            st.caption("トレンドは良好だが割高→押し目で買い検討")
            show = [c for c in ["コード","銘柄名","業種","統合スコア","PEG","PEG判定","PER","EPS成長率%","テーマ"] if c in timing.columns]
            st.dataframe(timing[show], use_container_width=True, hide_index=True)
            st.divider()

        # 隠れ割安
        if not hidden.empty:
            st.markdown("### $26AA 隠れ割安（PEG<1.0 × 統合+20未満）")
            st.caption("業種逆風だが本質的割安→業種回復時の候補")
            show = [c for c in ["コード","銘柄名","業種","統合スコア","PEG","PEG判定","PER","EPS成長率%","ROE%","テーマ"] if c in hidden.columns]
            st.dataframe(hidden[show], use_container_width=True, hide_index=True)
            st.divider()

        # 全銘柄一覧
        st.markdown("### $D83D$DCCB 全銘柄 2軸分析一覧")
        show = [c for c in ["コード","銘柄名","業種","統合スコア","PEG","PEG判定","最終判定","PER","EPS成長率%","PBR","ROE%"] if c in df_vg.columns]
        st.dataframe(df_vg[show], use_container_width=True, hide_index=True)

        st.divider()
        st.markdown("""
**判定基準：**
- $D83D$DFE2 強買い推奨：統合スコア+30以上 × PEG<1.0
- $D83D$DFE1 買い推奨：統合スコア+20以上 × PEG<1.0
- $D83D$DFE0 タイミング待ち：統合スコア+30以上 × PEG>1.0（割高・押し目待ち）
- $26AA 隠れ割安：PEG<1.0 × 統合スコア+20未満（業種回復待ち）

**PEG = PER ÷ EPS成長率**
- PEG < 0.5 → 超割安成長
- PEG < 1.0 → 割安成長（推奨水準）
- PEG > 2.0 → 割高警戒
        """)
    else:
        st.info("バリュー成長スコアデータがありません")

# ============================================================
# フッター
# ============================================================
st.divider()
st.caption("AI投資判断システム | daily自動更新（平日朝7時）+ weekly自動更新（月曜10時）| バックテスト：5Y勝率100%・超過+287%")

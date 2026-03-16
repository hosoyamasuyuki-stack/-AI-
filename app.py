import streamlit as st
import gspread
from google.oauth2.service_account import Credentials
import pandas as pd
import json

# ── ページ設定 ──
st.set_page_config(
    page_title="AI投資判断システム",
    page_icon="📊",
    layout="wide"
)

# ── 認証 ──
def get_gspread_client():
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive"
    ]
    creds_dict = json.loads(st.secrets["GOOGLE_CREDENTIALS"])
    creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
    return gspread.authorize(creds)

# ── データ取得 ──
@st.cache_data(ttl=3600)
def load_data():
    try:
        gc = get_gspread_client()
        ss = gc.open_by_key("1GtlVhGcPjMU0pJWsijwnmTe1rFJXAGvkaJFjav9gGcE")

        # 予測記録
        ws_pred = ss.worksheet("予測記録")
        pred_data = ws_pred.get_all_values()
        df_pred = pd.DataFrame(pred_data[1:], columns=pred_data[0]) if len(pred_data) > 1 else pd.DataFrame()

        # マクロ指標DB
        ws_macro = ss.worksheet("マクロ指標DB")
        macro_data = ws_macro.get_all_values()
        df_macro = pd.DataFrame(macro_data[1:], columns=macro_data[0]) if len(macro_data) > 1 else pd.DataFrame()

        # 業種スコア
        ws_sector = ss.worksheet("業種スコア")
        sector_data = ws_sector.get_all_values()
        df_sector = pd.DataFrame(sector_data[1:], columns=sector_data[0]) if len(sector_data) > 1 else pd.DataFrame()

        return df_pred, df_macro, df_sector

    except Exception as e:
        st.error(f"データ取得エラー: {e}")
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

# ── スコアカラー ──
def score_color(score):
    try:
        s = float(score)
        if s >= 40:   return "🟢"
        elif s >= 20: return "🟡"
        elif s >= -20: return "⚪"
        elif s >= -40: return "🟠"
        else:         return "🔴"
    except:
        return "⚪"

# ── メイン ──
def main():
    st.title("📊 AI投資判断システム")
    st.caption("毎週月曜自動更新 | 3層スコア（マクロ40%・業種30%・銘柄30%）")

    df_pred, df_macro, df_sector = load_data()

    # ── タブ ──
    tab1, tab2, tab3 = st.tabs(["📈 銘柄スコア", "🌡️ 業種体温計", "📡 マクロ指標"])

    # ── タブ1：銘柄スコア ──
    with tab1:
        if df_pred.empty:
            st.warning("データがありません")
        else:
            # 最新日付のデータだけ表示
            if "予測日" in df_pred.columns:
                latest_date = df_pred["予測日"].max()
                df_latest = df_pred[df_pred["予測日"] == latest_date].copy()
                st.caption(f"最終更新: {latest_date}")
            else:
                df_latest = df_pred.copy()

            # 総合スコアでソート
            if "総合スコア" in df_latest.columns:
                df_latest["総合スコア_num"] = pd.to_numeric(df_latest["総合スコア"], errors="coerce")
                df_latest = df_latest.sort_values("総合スコア_num", ascending=False)

            # スコアカード
            col1, col2, col3, col4 = st.columns(4)
            buy_count = len(df_latest[df_latest.get("判定", pd.Series()).str.contains("買い検討", na=False)]) if "判定" in df_latest.columns else 0

            with col1:
                st.metric("分析銘柄数", f"{len(df_latest)}銘柄")
            with col2:
                st.metric("買い検討", f"{buy_count}銘柄")
            with col3:
                if "マクロスコア" in df_latest.columns:
                    macro_score = df_latest["マクロスコア"].iloc[0] if len(df_latest) > 0 else "-"
                    st.metric("マクロスコア", macro_score)
            with col4:
                if "業種スコア" in df_latest.columns:
                    try:
                        avg_sector = pd.to_numeric(df_latest["業種スコア"], errors="coerce").mean()
                        st.metric("業種平均", f"{avg_sector:.1f}")
                    except:
                        pass

            st.divider()

            # 銘柄テーブル
            display_cols = ["銘柄コード", "銘柄名", "現在株価", "マクロスコア", "業種スコア", "銘柄スコア", "総合スコア", "判定", "予測方向"]
            show_cols = [c for c in display_cols if c in df_latest.columns]

            if show_cols:
                # 判定でフィルター
                filter_opt = st.selectbox("絞り込み", ["全て", "買い検討のみ", "中立以上"])
                df_show = df_latest[show_cols].copy()

                if filter_opt == "買い検討のみ" and "判定" in df_show.columns:
                    df_show = df_show[df_show["判定"].str.contains("買い検討", na=False)]
                elif filter_opt == "中立以上" and "総合スコア" in df_show.columns:
                    df_show = df_show[pd.to_numeric(df_show["総合スコア"], errors="coerce") >= 0]

                st.dataframe(df_show, use_container_width=True, hide_index=True)

    # ── タブ2：業種体温計 ──
    with tab2:
        if df_sector.empty:
            st.warning("データがありません")
        else:
            if "スコア" in df_sector.columns:
                df_sector["スコア_num"] = pd.to_numeric(df_sector["スコア"], errors="coerce")
                df_sector = df_sector.sort_values("スコア_num", ascending=False)

            # ヒートマップ表示
            cols = st.columns(4)
            for i, row in df_sector.iterrows():
                col_idx = (list(df_sector.index).index(i)) % 4
                with cols[col_idx]:
                    score = row.get("スコア", 0)
                    icon = score_color(score)
                    sector = row.get("業種", "")
                    st.metric(f"{icon} {sector}", score)

    # ── タブ3：マクロ指標 ──
    with tab3:
        if df_macro.empty:
            st.warning("データがありません")
        else:
            # カテゴリでフィルター
            if "カテゴリ" in df_macro.columns:
                categories = ["全て"] + sorted(df_macro["カテゴリ"].unique().tolist())
                cat = st.selectbox("カテゴリ", categories)
                if cat != "全て":
                    df_macro = df_macro[df_macro["カテゴリ"] == cat]

            display_cols = ["指標名", "カテゴリ", "最新値", "前回値", "変化量", "最新日付"]
            show_cols = [c for c in display_cols if c in df_macro.columns]
            st.dataframe(df_macro[show_cols] if show_cols else df_macro,
                        use_container_width=True, hide_index=True)

if __name__ == "__main__":
    main()

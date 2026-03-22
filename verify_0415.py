# ============================================================
# verify_0415.py
# AI投資判断システム STEP0 目先予測 初回検証準備スクリプト
#
# 【実行タイミング】2026/04/15 9:00 JST（1回限り）
# 【目的】
#   STEP0（2026/03/18記録）の目先3ヶ月予測を検証するための
#   準備シートを自動生成する
#   ・予測記録シートから15銘柄の予測値を抽出
#   ・検証日時点の株価欄を空欄で用意（手入力用）
#   ・判定基準（80%/60%/50%）を自動表示
#
# 【認証】GOOGLE_CREDENTIALS（環境変数）
# ============================================================

import os, json, warnings
from datetime import datetime
import gspread
from google.oauth2.service_account import Credentials
warnings.filterwarnings('ignore')

# ── 認証 ────────────────────────────────────────────────────
SPREADSHEET_ID = '1GtlVhGcPjMU0pJWsijwnmTe1rFJXAGvkaJFjav9gGcE'
scope = ['https://spreadsheets.google.com/feeds',
         'https://www.googleapis.com/auth/drive']
creds_dict = json.loads(os.environ.get('GOOGLE_CREDENTIALS', '{}'))
creds = Credentials.from_service_account_info(creds_dict, scopes=scope)
gc = gspread.authorize(creds)
ss = gc.open_by_key(SPREADSHEET_ID)

NOW = datetime.now().strftime('%Y/%m/%d %H:%M')
print(f"✅ 接続完了: {ss.title}")
print(f"実行日時: {NOW}")
print(f"\n{'='*60}")
print(f"STEP0 目先予測 初回検証準備スクリプト（4/15）")
print(f"{'='*60}")

# ── 予測記録シートから目先予測を抽出 ────────────────────────
try:
    ws_pred = ss.worksheet('予測記録')
    rows    = ws_pred.get_all_values()
    if len(rows) < 2:
        print("⚠️ 予測記録シートにデータなし")
        exit()

    header = rows[0]
    data   = rows[1:]

    # 目先予測（3ヶ月）の列を特定
    col_names = [h.strip() for h in header]
    print(f"  列名: {col_names[:10]}")

    # STEP0記録分（2026/03/18前後）を抽出
    step0_rows = []
    for row in data:
        if len(row) > 0:
            # 記録日が2026/03/18前後の行を対象
            rec_date = row[0] if row[0] else ''
            if '2026/03' in rec_date or '2026-03' in rec_date:
                step0_rows.append(row)

    if not step0_rows:
        # 全行を対象にする（日付フィルタが効かない場合）
        step0_rows = data[:20]  # 最初の20行を対象

    print(f"  対象行数: {len(step0_rows)}行")

    # ── 検証準備シートを作成 ────────────────────────────────
    VERIFY_SHEET = 'STEP0_目先検証_0415'
    try:
        ss.del_worksheet(ss.worksheet(VERIFY_SHEET))
        print(f"  既存シート削除: {VERIFY_SHEET}")
    except: pass

    ws_v = ss.add_worksheet(title=VERIFY_SHEET, rows=50, cols=12)

    # ヘッダー
    header_row = [
        '銘柄コード', '銘柄名', '業種',
        '予測時スコア', '予測時ランク', '目先予測方向',
        '予測時株価', '検証時株価（手入力）',
        '騰落率%（自動）', '日経比（手入力）',
        '勝敗', '備考'
    ]

    # 判定基準を先頭に記載
    meta_rows = [
        ['STEP0 目先予測 初回検証シート', '', '', '', '', '', '', '', '', '', '', ''],
        ['検証日', '2026/04/15', '', '', '', '', '', '', '', '', '', ''],
        ['予測記録日', '2026/03/18', '', '', '', '', '', '', '', '', '', ''],
        ['', '', '', '', '', '', '', '', '', '', '', ''],
        ['■ 判定基準', '', '', '', '', '', '', '', '', '', '', ''],
        ['勝率80%以上', '→ ウェイト据え置き（v4.3は機能している）', '', '', '', '', '', '', '', '', '', ''],
        ['勝率60-80%', '→ 継続観察（パラメータ微調整検討）', '', '', '', '', '', '', '', '', '', ''],
        ['勝率50%以下', '→ 設計見直し（スコアリング根本再検討）', '', '', '', '', '', '', '', '', '', ''],
        ['', '', '', '', '', '', '', '', '', '', '', ''],
        ['■ 入力手順', '', '', '', '', '', '', '', '', '', '', ''],
        ['①「検証時株価」列に2026/04/15時点の株価を手入力', '', '', '', '', '', '', '', '', '', '', ''],
        ['②「日経比」列に同日の日経225騰落率を手入力', '', '', '', '', '', '', '', '', '', '', ''],
        ['③「勝敗」列は騰落率>0なら◎、<0なら✕を入力', '', '', '', '', '', '', '', '', '', '', ''],
        ['', '', '', '', '', '', '', '', '', '', '', ''],
        [header_row[0], header_row[1], header_row[2], header_row[3], header_row[4],
         header_row[5], header_row[6], header_row[7], header_row[8], header_row[9],
         header_row[10], header_row[11]],
    ]

    # 銘柄データ行を追加
    data_rows = []
    for row in step0_rows:
        # 列インデックスを安全に取得
        def gc(idx, default=''):
            return row[idx] if len(row) > idx else default

        data_row = [
            gc(0),  # コード or 日付
            gc(1),  # 銘柄名
            gc(2),  # 業種
            gc(3),  # スコア
            gc(4),  # ランク
            gc(5),  # 目先予測方向
            gc(6),  # 予測時株価
            '',     # 検証時株価（手入力）
            '',     # 騰落率（自動計算用・空欄）
            '',     # 日経比
            '',     # 勝敗
            '',     # 備考
        ]
        data_rows.append(data_row)

    all_rows = meta_rows + data_rows

    # 一括書き込み
    ws_v.update('A1', all_rows)

    # 書式設定（ヘッダー行を太字に）
    ws_v.format('A15:L15', {'textFormat': {'bold': True}, 'backgroundColor': {'red': 0.1, 'green': 0.15, 'blue': 0.25}})
    ws_v.format('A1:L1',   {'textFormat': {'bold': True, 'fontSize': 12}})

    print(f"\n✅ 検証準備シート作成完了: '{VERIFY_SHEET}'")
    print(f"   対象銘柄: {len(data_rows)}銘柄")
    print(f"   次のアクション: 検証時株価・日経比・勝敗を手入力してください")

except Exception as e:
    print(f"⚠️ 検証準備シート作成失敗: {e}")
    import traceback
    traceback.print_exc()

# ── 作業ログに記録 ───────────────────────────────────────────
try:
    wl   = ss.worksheet('作業ログ')
    last = len(wl.get_all_values()) + 1
    wl.update(f'A{last}', [[
        NOW, 'verify_0415.py',
        f'STEP0目先予測検証準備完了。「{VERIFY_SHEET}」シートに検証フォームを生成。',
        '検証時株価・日経比・勝敗を手入力してください', '✅完了'
    ]])
    print(f"✅ 作業ログ記録完了")
except Exception as e:
    print(f"⚠️ 作業ログ記録失敗: {e}")

# ── リマインダーメッセージ ───────────────────────────────────
print(f"\n{'='*60}")
print(f"【本日のアクション】")
print(f"{'='*60}")
print(f"1. スプレッドシートの「{VERIFY_SHEET}」シートを開く")
print(f"2. 各銘柄の2026/04/15時点の株価を「検証時株価」列に入力")
print(f"3. 2026/04/15の日経225騰落率を「日経比」列に入力")
print(f"4. 騰落率が+なら◎、-なら✕を「勝敗」列に入力")
print(f"5. 勝率を計算して判定基準と照合")
print(f"   80%以上 → ✅ウェイト据え置き")
print(f"   60-80%  → ⚠️継続観察")
print(f"   50%以下 → 🔴設計見直し")
print(f"\n✅ verify_0415.py 完了: {NOW}")

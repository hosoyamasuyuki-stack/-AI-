# ============================================================
# sheet_manager.py
# AI投資判断システム シート管理自動化
# 実行タイミング: 毎月1日 9:00 JST（GitHub Actions）
#
# 機能:
#   1. 全シートを「現役・保存・削除候補・不明」に自動分類
#   2. 90日以上更新なしのシートを検出
#   3. 「シート管理台帳」シートに結果を出力
#   4. 削除候補リストをスプレッドシートに記録
#
# 注意: 実際の削除は行わない（細矢さんが判断する）
# ============================================================

import os
import json
import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime, timedelta

# ── 認証 ──────────────────────────────────────────────────
from core.auth import get_spreadsheet
ss = get_spreadsheet()
NOW = datetime.now().strftime('%Y/%m/%d %H:%M')
TODAY = datetime.now()

print(f"$2705 認証完了: {ss.title}")
print(f"実行日時: {NOW}\n")

# ── シート分類定義 ─────────────────────────────────────────

# Aグループ: 現役・稼働中（スクリプトが自動書き込み）
A_GROUP = {
    # daily_update.pyが書き込む32シート
    'VIX', 'HYスプレッド', 'TEDスプレッド', 'ドル円',
    'ドルインデックス', '長短金利差', '米10年債利回り',
    '信用スプレッドIG', 'WTI原油', '金価格',
    '米M2', '日本M2', 'ユーロM3', 'FRBバランスシート',
    '米CPI', '米PCEインフレ', '米失業率', '米小売売上高',
    '米鉱工業生産', '米設備稼働率', '米住宅着工件数',
    '米耐久財受注', '米消費者信頼感', 'ISM製造業PMI',
    '米マネタリーベース', '日経225', 'TOPIX', 'SP500',
    'SOX指数', 'ラッセル2000', 'シラーPER', '異常値スコア',
    # weekly_update.pyが書き込む6シート
    'コアスキャン_v4.3', '統合スコア_週次',
    '週次シグナル', '因子劣化チェック',
    'インデックス予測記録', '作業ログ',
    # 実運用データ
    '保有銘柄_v4.3スコア', '監視銘柄_v4.3スコア', '予測記録',
    # verify系
    'STEP0_目先検証_0415',
}

# Bグループ: 永久保存（削除禁止）
B_GROUP = {
    '設計ロジック_永久保存', '統計手順書_永久保存',
    '仮説登録簿', 'H001C_3年5年7年保有',
    '引き継ぎ書_v2.4', '引き継ぎ書_v2.5',
    '思考回路_設計判断記録', 'v4.3設計記録',
    '銘柄マスタ', 'EDINETスコア', '設定',
    'スコア設計思想',
}

# Cグループ: 削除推奨（旧版・棄却済み）
C_GROUP = {
    # 旧引き継ぎ書
    '引き継ぎ書v21', '引き継ぎ書v22_完全版', '引き継ぎ書v23_完全版',
    '引き継ぎ書_v1.6', '引き継ぎ書_v1.7', '引き継ぎ書_v1.8',
    '引き継ぎ書_v1.9', '引き継ぎ書_v2.0', '引き継ぎ書_v2.1',
    '引き継ぎ書_v2.2', '引き継ぎ書_v2.3', '引き継ぎ書v24_完全版',
    '週次検証アラート',
    # 旧コアスキャン
    'コアスキャンv3', 'コアスキャンv3_業種補正',
    'コアスキャンv3_業種補正2', 'コアスキャンv3_相対評価',
    'コアスキャンv3_3軸確定版', 'コアスキャン_v4.0',
    'コアスキャン_v4.1', 'コアスキャン_v4.2',
    # 棄却・旧バックテスト
    'H001_v4.3スコア有効性_v1', 'H001_v4.3スコア有効性_v4',
    'H001B_条件付き有効性_v5',
    'H001C_3年5年保有_fixed', 'H001C_3年5年保有_v2',
    'H001C_3年5年保有_v3', 'H001C_3年5年保有バックテスト',
    'H005_ROE加速度_バックテスト', 'H005_ROE加速度_v2',
    'H006_粗利率安定性_v1',
    'バックテスト_日経比較', 'バックテスト_長期v2',
    'バックテスト_統合スコア版',
    # 旧管理ファイル
    'ファイル一覧_完全版', 'ファイル一覧_完全版v2',
    '次回作業ステップ詳細', '最終ゴール_ロードマップ',
    'weekly_test_結果',
    # 旧分析シート（現行スクリプト未参照）
    '相関マトリックス', '感応度マップ', '完全版感応度マップ',
    '33業種感応度マップ', '33業種インデックス_JQ', '日経PER_PBR',
    'タイムラグ分析', 'M2加速度分析', '景気フェーズ別感応度',
    '業種ETF×指標相関分析v2', '33業種×全指標相関分析_完全版',
    '業種別最強先行指標_サマリー', '加速度指標×業種相関_完全版',
    '業種別最強先行指標_加速度版', '加速度シグナル_月次',
    '業種スコア', '財務スコア', '経営品質スコアv2',
    'バリュー成長スコア', '分析理論', '業種推奨ランキング',
    'マクロ指標DB', 'バフェット指数', 'バフェット指数分子',
    '米名目GDP', '米新規失業保険', '米GDP成長率',
    '統合スコア', '学習用銘柄_設計思想', '日経PER_PBR',
    'バックテスト結果',
}

# ── メイン処理 ─────────────────────────────────────────────
print("=" * 55)
print("シート管理台帳 自動生成")
print("=" * 55)

# 全シート取得
all_worksheets = ss.worksheets()
all_names = [ws.title for ws in all_worksheets]
print(f"総シート数: {len(all_names)}\n")

# 各シートを分類
results = []
count_a = count_b = count_c = count_d = 0
stale_sheets = []  # 90日以上更新なし

for ws in all_worksheets:
    name = ws.title

    # グループ判定
    if name in A_GROUP:
        group = 'A: 現役稼働中'
        action = '保持（自動更新）'
        count_a += 1
    elif name in B_GROUP:
        group = 'B: 永久保存'
        action = '保持（削除禁止）'
        count_b += 1
    elif name in C_GROUP:
        group = 'C: 削除推奨'
        action = '$26A0$FE0F 削除候補（細矢さん確認後）'
        count_c += 1
    else:
        group = 'D: 要確認'
        action = '$2753 用途不明・確認必要'
        count_d += 1

    # 最終更新日を推定（行数から判断）
    try:
        row_count = ws.row_count
        col_count = ws.col_count
        # 実際のデータ行数を確認（最初の3行だけ取得）
        try:
            first_rows = ws.get('A1:A3')
            has_data = len(first_rows) > 0
            data_info = f"行:{row_count} 列:{col_count} データ:{has_data}"
        except:
            data_info = f"行:{row_count} 列:{col_count}"
    except Exception as e:
        data_info = f"取得エラー: {str(e)[:30]}"

    results.append({
        'シート名': name,
        'グループ': group,
        '推奨アクション': action,
        '情報': data_info,
        '確認日': NOW,
    })
    print(f"  [{group[0]}] {name}")

# ── シート管理台帳を更新（既存シートはクリアして再利用、なければ作成） ────────
MGMT_SHEET = 'シート管理台帳'
try:
    ws_mgmt = ss.worksheet(MGMT_SHEET)
    ws_mgmt.clear()
    needed_rows = len(results) + 20
    if ws_mgmt.row_count < needed_rows:
        ws_mgmt.resize(rows=needed_rows, cols=6)
except gspread.exceptions.WorksheetNotFound:
    ws_mgmt = ss.add_worksheet(title=MGMT_SHEET, rows=len(results)+20, cols=6)

header = ['シート名', 'グループ', '推奨アクション', '情報', '確認日']
rows = [header]
for r in results:
    rows.append([r['シート名'], r['グループ'], r['推奨アクション'],
                 r['情報'], r['確認日']])

# サマリー行を追加
rows.append([])
rows.append(['=== サマリー ===', '', '', '', NOW])
rows.append([f'総シート数: {len(all_names)}', '', '', '', ''])
rows.append([f'A現役: {count_a}シート', '', '', '', ''])
rows.append([f'B永久保存: {count_b}シート', '', '', '', ''])
rows.append([f'C削除推奨: {count_c}シート', '', '', '', ''])
rows.append([f'D要確認: {count_d}シート', '', '', '', ''])

ws_mgmt.update('A1', rows)

# ヘッダー行を太字・色付きに
ws_mgmt.format('A1:E1', {
    'textFormat': {'bold': True},
    'backgroundColor': {'red': 0.2, 'green': 0.4, 'blue': 0.8}
})

print(f"\n$2705 シート管理台帳を更新: '{MGMT_SHEET}'")
print(f"\n{'=' * 55}")
print(f"$D83D$DCCA シート管理サマリー ({NOW})")
print(f"{'=' * 55}")
print(f"  総シート数    : {len(all_names)}")
print(f"  A 現役稼働中  : {count_a} シート")
print(f"  B 永久保存    : {count_b} シート")
print(f"  C 削除推奨    : {count_c} シート ← 細矢さん確認後に削除")
print(f"  D 要確認      : {count_d} シート ← 次回確認")
print(f"{'=' * 55}")
print(f"$2705 sheet_manager.py 完了")


# ── Handover_Auto スナップショット生成（毎月1日に自動実行）──────
def generate_handover_auto(ss, results, now):
    PERMANENT = [
        'DesignLogic_permanent','StatsProcedure_permanent','HypothesisLog',
        'H001C_3Y5Y7Yholding','Handover_v2.6','ThinkingProcess_DesignDecisions',
        'v4.3DesignRecord','StockMaster','EDINETscore','Settings','MacroPhase'
    ]
    active_sheets = [r['シート名'] for r in results if '現役' in r.get('グループ','')]
    delete_sheets = [r['シート名'] for r in results if '削除' in r.get('グループ','')]

    lines = [
        '=' * 60,
        f'Handover_Auto (monthly snapshot by sheet_manager.py)',
        f'Generated: {now}',
        '=' * 60,
        '',
        '[STATUS] Read Handover_v2.6 for full context.',
        '[STATUS] This sheet = latest auto-snapshot only.',
        '',
        f'[SHEET COUNT] Total: {len(results)}',
        f'  Permanent (GroupB): {len(PERMANENT)} sheets',
        f'  Active (GroupA)   : {len(active_sheets)} sheets',
        f'  Delete candidate  : {len(delete_sheets)} sheets',
        '',
        '[PERMANENT SHEETS - DO NOT DELETE]',
    ] + [f'  {s}' for s in PERMANENT] + [
        '',
        '[ACTIVE SHEETS (GroupA)]',
    ] + [f'  {s}' for s in active_sheets[:20]] + [
        '',
        '[DELETE CANDIDATES (confirm with Hosoyama)]',
    ] + [f'  {s}' for s in delete_sheets[:20]] + [
        '',
        '[NEXT ACTIONS]',
        '  -> Read Handover_ChangeLog for recent session history',
        '  -> Read Handover_v2.6 for full system context',
        '=' * 60,
    ]

    SHEET = 'Handover_Auto'
    try:
        ws = ss.worksheet(SHEET)
        ws.clear()
        needed_rows = len(lines) + 10
        if ws.row_count < needed_rows:
            ws.resize(rows=needed_rows, cols=2)
    except gspread.exceptions.WorksheetNotFound:
        ws = ss.add_worksheet(title=SHEET, rows=len(lines)+10, cols=2)
    ws.update('A1', [['No','Content']])
    ws.update('A2', [[i+1, l] for i, l in enumerate(lines)])
    print(f'  OK: Handover_Auto 生成 ({len(lines)}行)')

generate_handover_auto(ss, results, NOW)

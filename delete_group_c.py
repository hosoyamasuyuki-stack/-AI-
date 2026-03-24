# delete_group_c.py
# Cグループ（削除候補）シートを一括削除する
# Colabで実行:
#   from google.colab import auth
#   auth.authenticate_user()

import gspread
from google.auth import default

creds, _ = default()
gc = gspread.authorize(creds)
SPREADSHEET_ID = '1GtlVhGcPjMU0pJWsijwnmTe1rFJXAGvkaJFjav9gGcE'
ss = gc.open_by_key(SPREADSHEET_ID)
print('OK: ' + ss.title)

DELETE_TARGETS = [
    '引き継ぎ書v21','引き継ぎ書v22_完全版','引き継ぎ書v23_完全版','引き継ぎ書v24_完全版',
    '引き継ぎ書_v1.6','引き継ぎ書_v1.7','引き継ぎ書_v1.8','引き継ぎ書_v1.9',
    '引き継ぎ書_v2.0','引き継ぎ書_v2.1','引き継ぎ書_v2.2','引き継ぎ書_v2.3','引き継ぎ書_v2.4',
    '最終ゴール_ロードマップ','ファイル一覧_完全版','ファイル一覧_完全版v2',
    '思考回路_設計判断記録','次回作業ステップ詳細',
    'コアスキャンv3','コアスキャンv3_業種補正','コアスキャンv3_業種補正2',
    'コアスキャンv3_相対評価','コアスキャンv3_3軸確定版',
    'コアスキャン_v4.0','コアスキャン_v4.1','コアスキャン_v4.2',
    'バックテスト_日経比較','バックテスト_長期v2','バックテスト_統合スコア版','バックテスト結果',
    'H005_ROE加速度_バックテスト','H005_ROE加速度_v2','H006_粗利率安定性_v1',
    'H001_v4.3スコア有効性_v1','H001_v4.3スコア有効性_v4','H001B_条件付き有効性_v5',
    'H001C_3年5年保有バックテスト','H001C_3年5年保有_fixed','H001C_3年5年保有_v2','H001C_3年5年保有_v3',
    '相関マトリックス','感応度マップ','完全版感応度マップ',
    '33業種インデックス_JQ','33業種感応度マップ','33業種×全指標相関分析_完全版',
    '業種ETF×指標相関分析v2','業種別最強先行指標_サマリー','加速度指標×業種相関_完全版',
    '業種別最強先行指標_加速度版','景気フェーズ別感応度',
    'タイムラグ分析','M2加速度分析','業種推奨ランキング',
    'バフェット指数','バフェット指数分子','日経PER_PBR',
    '経営品質スコアv2','バリュー成長スコア','スコア設計思想',
    'weekly_test_結果','米名目GDP','現在のシグナル_最新','加速度シグナル_月次',
]

existing = {ws.title: ws for ws in ss.worksheets()}
deleted, skipped = [], []
print(f'\n削除対象: {len(DELETE_TARGETS)}シート')
print('=' * 50)
for name in DELETE_TARGETS:
    if name in existing:
        try:
            ss.del_worksheet(existing[name])
            deleted.append(name)
            print(f'  OK 削除: {name}')
        except Exception as e:
            skipped.append(name)
            print(f'  ERR: {name} -> {e}')
    else:
        skipped.append(name)
        print(f'  SKIP(未発見): {name}')
print('=' * 50)
print(f'\n削除完了: {len(deleted)}シート')
print(f'スキップ: {len(skipped)}シート')
print(f'残りシート数: {len(ss.worksheets())}')

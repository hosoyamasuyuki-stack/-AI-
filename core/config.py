"""
core/config.py - Centralized configuration and constants

All threshold constants, spreadsheet IDs, and API endpoints
are defined here. Import from this module instead of
hardcoding values in individual scripts.

J-Quants V2 API Authentication:
  - APIキーはダッシュボード（https://jpx-jquants.com/）から発行
  - キー自体に有効期限なし（再発行すると旧キーは即無効）
  - 再発行時は .env + GitHub Secrets の両方を更新すること
  - ヘッダー: x-api-key: {api_key}
  - プラン: スタンダード（120リクエスト/分）
"""

import os

# ── Spreadsheet ──────────────────────────────────────────────
SPREADSHEET_ID = os.environ.get(
    'SPREADSHEET_ID',
    '1GtlVhGcPjMU0pJWsijwnmTe1rFJXAGvkaJFjav9gGcE'
)

# ── J-Quants V2 API ─────────────────────────────────────────
JQUANTS_API_KEY = os.environ.get('JQUANTS_API_KEY', '')
JQUANTS_HEADERS = {'x-api-key': JQUANTS_API_KEY}
JQUANTS_BASE    = 'https://api.jquants.com'

# ── Google Sheets Scope ──────────────────────────────────────
GSHEETS_SCOPE = [
    'https://spreadsheets.google.com/feeds',
    'https://www.googleapis.com/auth/drive',
]

# ── GAS (Google Apps Script) URLs ───────────────────────────
# GAS再デプロイ時はここだけ更新すれば全スクリプトに反映される
# 取得元: GASプロジェクト → デプロイ → ウェブアプリ → URL
GAS_URL_FULL_UPDATE = os.environ.get(
    'GAS_URL_FULL_UPDATE',
    'https://script.google.com/macros/s/AKfycbzS5b6XPlrkI_toQssXQQ3ivBeWXD-uL_4aXFZnZW-wWO4TgRbNOObpf3XRVJu_M8vF/exec'
)
GAS_URL_KENJA = os.environ.get(
    'GAS_URL_KENJA',
    'https://script.google.com/macros/s/AKfycbxDEN69psev29NQUJ3qhiPzA-mgT3uYpFXITW4bRRoc49VHxDhBW24Io4HbEizeuLo_/exec'
)

# ── v4.3 Scoring Thresholds ─────────────────────────────────
# Variable 1: Real ROIC
ROE_THR = [(25,100),(20,85),(15,70),(12,58),(10,46),(8,35),(5,20),(0,8)]
FCR_THR = [(120,100),(100,90),(80,78),(60,62),(40,44),(20,26),(0,10)]

# Variable 2: Trend
RS_THR  = [(4.0,100),(2.0,82),(0.5,64),(-0.5,46),(-2.0,28),(-999,12)]
FS_THR  = [(8.0,100),(4.0,80),(0.0,60),(-4.0,40),(-8.0,20),(-999,8)]

# Variable 3: Price
PEG_THR = [(0.5,100),(0.8,85),(1.0,72),(1.2,58),(1.5,42),(2.0,26),(999,12)]
FCY_THR = [(8,100),(6,85),(4,70),(3,55),(2,38),(1,22),(0,8)]

# ── Sheet Schema Definitions（教訓16遵守）──────────────────
# 全スクリプトは各シートのヘッダー順をここから参照する。
# manage_stock.py / weekly_update.py / daily_price_update.py / full_scan.py
# が書き込む際は SHEET_SCHEMA[シート名] の順序で書くのが原則。
# 実際のシートヘッダーとの整合性は weekly_update.py 末尾の整合性チェックで検証。
SHEET_SCHEMA = {
    '保有銘柄_v4.3スコア': [
        'コード', '銘柄名', '業種', '種別', '総合スコア', 'ランク',
        'ROE平均', 'FCR平均', 'ROEトレンド', 'PEG', 'FCF利回り',
        '変数1', '変数2', '変数3', '取得期数', '株価', '算出日時', '前回ランク',
    ],
    '監視銘柄_v4.3スコア': [
        'コード', '銘柄名', '業種', '種別', '総合スコア', 'ランク',
        'ROE平均', 'FCR平均', 'ROEトレンド', 'PEG', 'FCF利回り',
        '変数1', '変数2', '変数3', '取得期数', '株価', '算出日時', '前回ランク',
    ],
    'コアスキャン_v4.3': [
        'コード', '銘柄名', '業種', '総合スコア', 'ランク',
        'ROE平均', 'FCR平均', 'ROEトレンド', 'PEG', 'FCF利回り',
        '変数1', '変数2', '変数3', '株価', '時価総額', 'データ期数', '算出日時',
    ],
    'コアスキャン_日次': [
        'コード', '銘柄名', '総合スコア_日次', 'ランク', 'スコア変化',
        '変数1(週次)', '変数2(週次)', '変数3(日次)',
        '株価', '前日比(%)', 'PEG', 'FCF利回り(時価総額)', '更新日時',
    ],
    'スクリーニング_Top50': [
        'コード', '銘柄名', '業種', '総合スコア', 'ランク',
        '変数1', '変数2', '変数3',
        'ROE平均', 'FCR平均', 'ROEトレンド',
        'PEG', 'FCF利回り', '株価', '算出日時',
    ],
    # 予測記録は 40列構成（行0=グループヘッダー、行1=サブヘッダー）
    # 0-7: メタ情報 / 8-15: 目先 / 16-23: 短期 / 24-31: 中期 / 32-39: 長期
    # 各時間軸8列: 予測方向, 目標株価, 根拠, 検証予定日, 実績株価, 騰落率, 日経比超過, 勝敗
    '予測記録': {
        'meta': ['記録日', '銘柄コード', '銘柄名', '業種',
                 '記録時株価', '総合スコア', 'ランク', '推奨アクション'],
        'axes': ['目先', '短期', '中期', '長期'],
        'axis_cols': ['予測方向', '目標株価', '根拠', '検証予定日',
                      '実績株価', '騰落率', '日経比超過', '勝敗'],
        'axis_starts': {'目先': 8, '短期': 16, '中期': 24, '長期': 32},
    },
}

# ── データ健全性の判定閾値（整合性ガード用）──────────────
SCORE_RANGE        = (-20, 120)   # 変数1/2/3 の正常範囲
SCORE_ABS_MIN      = 1.0          # 絶対値がこれ未満は「生データ混入」疑い
TOTAL_DEVIATION    = 1.5          # 総合スコアと変数計算値の許容乖離
CELL_SAME_RATIO    = 0.80         # ダッシュボードで同値セルが占める許容上限
INTEGRITY_MIN_ROWS = 10           # 整合性チェックの最小対象行数

# ── Source of Truth 定義（教訓16）────────────────────────
# 各データの真実シート（他スクリプトはここを読む・派生シートから読まない）
SOURCE_OF_TRUTH = {
    '保有変数スコア':   ['保有銘柄_v4.3スコア'],
    '監視変数スコア':   ['監視銘柄_v4.3スコア'],
    '予測方向':         ['予測記録'],
    '市場マクロ指標':   ['MacroPhase', 'バリュエーション_日次'],
}

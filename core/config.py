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
    'https://script.google.com/macros/s/AKfycbyt3zG6eqUlYa3Yhq6hYitsv9tWTBv9uv2NxWRbWpgTFhmWI4ezRYgeJcginVp6dMg/exec'
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

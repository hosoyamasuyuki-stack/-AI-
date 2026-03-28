"""
core/config.py - Centralized configuration and constants

All threshold constants, spreadsheet IDs, and API endpoints
are defined here. Import from this module instead of
hardcoding values in individual scripts.
"""

import os

# ── Spreadsheet ──────────────────────────────────────────────
SPREADSHEET_ID = os.environ.get(
    'SPREADSHEET_ID',
    '1GtlVhGcPjMU0pJWsijwnmTe1rFJXAGvkaJFjav9gGcE'
)

# ── J-Quants API ─────────────────────────────────────────────
JQUANTS_API_KEY = os.environ.get('JQUANTS_API_KEY', '')
JQUANTS_HEADERS = {'x-api-key': JQUANTS_API_KEY}
JQUANTS_BASE    = 'https://api.jquants.com'

# ── Google Sheets Scope ──────────────────────────────────────
GSHEETS_SCOPE = [
    'https://spreadsheets.google.com/feeds',
    'https://www.googleapis.com/auth/drive',
]

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

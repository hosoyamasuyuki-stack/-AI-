"""
core/config.py - Centralized configuration and constants

All threshold constants, spreadsheet IDs, and API endpoints
are defined here. Import from this module instead of
hardcoding values in individual scripts.

J-Quants API Authentication:
  1. JQUANTS_MAIL + JQUANTS_PASS -> /v1/token/auth_user -> refresh_token (7 days)
  2. refresh_token -> /v1/token/auth_refresh -> id_token (24 hours)
  3. id_token -> x-api-key header -> data API calls

  If JQUANTS_API_KEY (id_token) is expired or missing,
  this module automatically refreshes it using mail/password.
"""

import os
import requests as _requests

# ── Spreadsheet ──────────────────────────────────────────────
SPREADSHEET_ID = os.environ.get(
    'SPREADSHEET_ID',
    '1GtlVhGcPjMU0pJWsijwnmTe1rFJXAGvkaJFjav9gGcE'
)

# ── J-Quants API ─────────────────────────────────────────────
JQUANTS_BASE = 'https://api.jquants.com'

def _get_jquants_token():
    """
    Get a valid J-Quants ID token (x-api-key).

    Priority:
      1. JQUANTS_API_KEY env var (if set and not empty)
      2. Auto-refresh using JQUANTS_MAIL + JQUANTS_PASS env vars

    Returns the token string, or empty string on failure.
    """
    # Try existing token first
    token = os.environ.get('JQUANTS_API_KEY', '').strip()
    if token:
        return token

    # Auto-refresh: mail + password -> refresh_token -> id_token
    mail = os.environ.get('JQUANTS_MAIL', '').strip()
    passwd = os.environ.get('JQUANTS_PASS', '').strip()
    if not mail or not passwd:
        print("  WARN: JQUANTS_API_KEY not set and JQUANTS_MAIL/JQUANTS_PASS not available")
        return ''

    try:
        # Step 1: Get refresh token
        r1 = _requests.post(
            f"{JQUANTS_BASE}/v1/token/auth_user",
            json={"mailaddress": mail, "password": passwd},
            timeout=15,
        )
        if r1.status_code != 200:
            print(f"  WARN: J-Quants auth_user failed: {r1.status_code} {r1.text[:200]}")
            return ''
        refresh_token = r1.json().get('refreshToken', '')
        if not refresh_token:
            print("  WARN: J-Quants auth_user returned no refreshToken")
            return ''

        # Step 2: Get ID token
        r2 = _requests.post(
            f"{JQUANTS_BASE}/v1/token/auth_refresh?refreshtoken={refresh_token}",
            timeout=15,
        )
        if r2.status_code != 200:
            print(f"  WARN: J-Quants auth_refresh failed: {r2.status_code} {r2.text[:200]}")
            return ''
        id_token = r2.json().get('idToken', '')
        if id_token:
            print(f"  J-Quants: ID token auto-refreshed successfully")
            return id_token
        else:
            print("  WARN: J-Quants auth_refresh returned no idToken")
            return ''
    except Exception as e:
        print(f"  WARN: J-Quants token refresh failed: {e}")
        return ''


JQUANTS_API_KEY = _get_jquants_token()
JQUANTS_HEADERS = {'x-api-key': JQUANTS_API_KEY}

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

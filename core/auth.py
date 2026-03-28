"""
core/auth.py - Centralized authentication for Google Sheets and J-Quants

Usage:
    from core.auth import get_spreadsheet
    ss = get_spreadsheet()
    ws = ss.worksheet('sheet_name')
"""

import os
import json
import gspread
from google.oauth2.service_account import Credentials
from core.config import SPREADSHEET_ID, GSHEETS_SCOPE


def get_spreadsheet(spreadsheet_id=None):
    """
    Authenticate with Google Sheets and return the spreadsheet object.

    Args:
        spreadsheet_id: Override the default SPREADSHEET_ID if needed.

    Returns:
        gspread.Spreadsheet object
    """
    sid = spreadsheet_id or SPREADSHEET_ID
    creds_dict = json.loads(os.environ.get('GOOGLE_CREDENTIALS', '{}'))
    creds = Credentials.from_service_account_info(creds_dict, scopes=GSHEETS_SCOPE)
    gc = gspread.authorize(creds)
    return gc.open_by_key(sid)

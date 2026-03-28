"""
core/api.py - J-Quants API helper functions

Provides get_price_jq() and get_fin_jq() for fetching
stock price and financial data from J-Quants V2 API.

Used by: weekly_update.py, full_scan.py, manage_stock.py
"""

import requests
import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from core.config import JQUANTS_BASE, JQUANTS_HEADERS


def get_price_jq(code, today=None):
    """
    Fetch the latest stock price from J-Quants V2 API.

    Tries the last 7 days to find a trading day with data.

    Args:
        code: Stock code (4 or 5 digits)
        today: Reference date (default: now)

    Returns:
        dict with 'price', 'market_cap', 'date' keys, or empty dict on failure
    """
    if today is None:
        today = datetime.now()
    try:
        code5 = code + '0' if len(code) == 4 else code
        for days_ago in range(1, 8):
            date_str = (today - timedelta(days=days_ago)).strftime('%Y-%m-%d')
            r = requests.get(
                f"{JQUANTS_BASE}/v2/equities/bars/daily",
                headers=JQUANTS_HEADERS,
                params={"code": code5, "date": date_str},
                timeout=10,
            )
            if r.status_code == 200:
                data = r.json().get('data', [])
                if data:
                    d = data[0]
                    price = d.get('AdjC') or d.get('C')
                    shares = get_shares_jq(code5)
                    market_cap = (
                        float(price) * shares if price and shares else None
                    )
                    return {
                        'price': price,
                        'market_cap': market_cap,
                        'date': date_str,
                    }
        return {}
    except Exception:
        return {}


def get_shares_jq(code5):
    """
    Fetch TotalMarketValue from J-Quants V2 equities master.

    Args:
        code5: 5-digit stock code

    Returns:
        float or None
    """
    try:
        r = requests.get(
            f"{JQUANTS_BASE}/v2/equities/master",
            headers=JQUANTS_HEADERS,
            params={"code": code5},
            timeout=10,
        )
        if r.status_code == 200:
            data = r.json().get('data', [])
            if data:
                shares = data[0].get('TotalMarketValue')
                if shares:
                    return float(shares)
        return None
    except Exception:
        return None


def get_fin_jq(code, cutoff_date=None, today=None):
    """
    Fetch financial summary data from J-Quants V2 API.

    Retrieves fiscal year data, filters by cutoff date,
    calculates ROE, FCF, FCR, and fetches current price.

    Args:
        code: Stock code (4 or 5 digits)
        cutoff_date: Earliest date string 'YYYY-MM-DD' for data filtering
        today: Reference date for price lookup (default: now)

    Returns:
        tuple: (DataFrame of financial data, dict of price info)
               Returns (None, {}) on failure
    """
    if today is None:
        today = datetime.now()
    if cutoff_date is None:
        cutoff_date = (today - timedelta(days=365 * 10)).strftime('%Y-%m-%d')
    try:
        code5 = code + '0' if len(code) == 4 else code
        r = requests.get(
            f"{JQUANTS_BASE}/v2/fins/summary",
            headers=JQUANTS_HEADERS,
            params={"code": code5},
            timeout=15,
        )
        if r.status_code != 200:
            return None, {}
        data = r.json().get('data', [])
        if not data:
            return None, {}

        df = pd.DataFrame(data)
        if 'CurPerEn' in df.columns:
            df['CurPerEn'] = pd.to_datetime(df['CurPerEn'], errors='coerce')
            df = df[df['CurPerEn'] >= pd.Timestamp(cutoff_date)].copy()
            df = df.sort_values('CurPerEn').reset_index(drop=True)
        if len(df) < 2:
            return None, {}

        if 'DocType' in df.columns:
            annual = df[
                df['DocType'].str.contains('FinancialStatements', na=False) &
                ~df['DocType'].str.contains(
                    '2Q|3Q|1Q|HalfYear|Quarter', na=False
                )
            ].copy()
            if len(annual) >= 2:
                df = annual

        numeric_cols = [
            'Sales', 'OP', 'NP', 'EPS', 'DEPS', 'TA', 'Eq', 'EqAR',
            'CFO', 'CFI', 'FEPS', 'FOP', 'FNP', 'ShOutFY',
        ]
        for col in numeric_cols:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors='coerce')

        if 'NP' in df.columns and 'Eq' in df.columns:
            df['ROE'] = df['NP'] / df['Eq'].replace(0, np.nan) * 100
        if 'CFO' in df.columns and 'CFI' in df.columns:
            df['FCF'] = df['CFO'] + df['CFI']
        if 'FCF' in df.columns and 'NP' in df.columns:
            df['FCR'] = df['FCF'] / df['NP'].replace(0, np.nan) * 100

        price_info = get_price_jq(code, today=today)
        if 'ShOutFY' in df.columns:
            shares_latest = df['ShOutFY'].dropna()
            if len(shares_latest) > 0:
                price_info['shares'] = float(shares_latest.iloc[-1])
                if price_info.get('price'):
                    price_info['market_cap'] = (
                        float(price_info['price'])
                        * float(shares_latest.iloc[-1])
                    )

        return (
            df.replace([np.inf, -np.inf], np.nan).dropna(how='all'),
            price_info,
        )
    except Exception:
        return None, {}

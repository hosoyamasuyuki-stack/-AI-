"""
core/scoring.py - Shared scoring helper functions

These functions are used by weekly_update.py, daily_price_update.py,
full_scan.py, manage_stock.py, and learning_batch_monthly.py.
"""

import numpy as np
import pandas as pd


def safe(val, d=1):
    """Safely convert a value to a rounded float, returning None on failure."""
    if val is None:
        return None
    try:
        f = float(val)
        return None if (np.isnan(f) or np.isinf(f)) else round(f, d)
    except Exception:
        return None


def safe_list(lst):
    """Replace None/NaN/Inf values in a list with empty strings."""
    return [
        '' if (v is None or (isinstance(v, float) and
               (np.isnan(v) or np.isinf(v)))) else v
        for v in lst
    ]


def thr_high(val, thresholds):
    """
    Score a value using thresholds where higher is better.

    Iterates through (threshold, score) pairs from highest to lowest.
    Returns the score for the first threshold the value meets or exceeds.

    Args:
        val: The value to score
        thresholds: List of (threshold, score) tuples, sorted descending

    Returns:
        int: The score (default 50 for None/NaN, 10 if below all thresholds)
    """
    if val is None or (isinstance(val, float) and
       (np.isnan(val) or np.isinf(val))):
        return 50
    for t, s in thresholds:
        if val >= t:
            return s
    return 10


def thr_low(val, thresholds):
    """
    Score a value using thresholds where lower is better (e.g., PEG ratio).

    Iterates through (threshold, score) pairs from lowest to highest.
    Returns the score for the first threshold the value is at or below.

    Args:
        val: The value to score
        thresholds: List of (threshold, score) tuples, sorted ascending

    Returns:
        int: The score (default 50 for None/NaN, 10 if above all thresholds)
    """
    if val is None or (isinstance(val, float) and
       (np.isnan(val) or np.isinf(val))):
        return 50
    for t, s in thresholds:
        if val <= t:
            return s
    return 10


def slope_fn(series):
    """
    Calculate the linear regression slope of a numeric series.

    Used to determine trend direction for ROE and FCR over 3-4 years.

    Args:
        series: List or array of numeric values

    Returns:
        float: The slope (change per period), 0.0 if insufficient data
    """
    v = pd.Series(series).replace([np.inf, -np.inf], np.nan).dropna().values
    if len(v) < 2:
        return 0.0
    return float(np.polyfit(range(len(v)), v, 1)[0])

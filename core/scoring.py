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


# ── per-stock 短期/中期 予測スコア（2026-06-07 CEO指示・自己学習の仮説）──────────
# 旧方式は市場値(週次シグナルの短期/中期スコア)を全銘柄に貼付し、短期/中期が全銘柄同一
# になっていた（CEO指摘「Top75全部一緒」）。各銘柄の因子で算出して銘柄差を出す。
# 重み w_market の根拠・検証方法は verify/HYPOTHESES.md (H-perstock-0607)。
# これは決め打ちでなく開始仮説であり、ic_report の IC で定期検証して調整する（1度に1パラメータ）。
PERSTOCK_W_MARKET_SHORT = 0.4   # 短期(1年): 市場0.4 + 銘柄割安度(s3)0.6
PERSTOCK_W_MARKET_MID = 0.4     # 中期(3年): 市場0.4 + 銘柄トレンド(s2)0.6


def perstock_short(market_short, s3, w_market=PERSTOCK_W_MARKET_SHORT):
    """短期(1年)の銘柄別予測スコア = 市場短期 * w + 銘柄割安度(s3) * (1-w)。

    根拠と検証方法は verify/HYPOTHESES.md (H-perstock-0607)。None/NaN は中立50。
    """
    m = safe(market_short)
    v = safe(s3)
    m = 50.0 if m is None else m
    v = 50.0 if v is None else v
    return max(0, min(100, round(m * w_market + v * (1 - w_market))))


def perstock_mid(market_mid, s2, w_market=PERSTOCK_W_MARKET_MID):
    """中期(3年)の銘柄別予測スコア = 市場中期 * w + 銘柄トレンド(s2) * (1-w)。

    根拠と検証方法は verify/HYPOTHESES.md (H-perstock-0607)。None/NaN は中立50。
    """
    m = safe(market_mid)
    v = safe(s2)
    m = 50.0 if m is None else m
    v = 50.0 if v is None else v
    return max(0, min(100, round(m * w_market + v * (1 - w_market))))

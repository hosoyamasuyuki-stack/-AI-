"""指数/株価の yfinance 取得 確定終値ガード + sanity。

2026-06-05 日経225 誤値事故（68,402・実値67,470.69）の根治。
原因: generate_dashboard.py の yp() が history の最終行 Close.iloc[-1] を無検証採用し、
寄付前の「未確定の当日バー（先物/プレ気配）」を確定終値と取り違えた。
68,402 は実値と僅か+1.4%差で「範囲チェック」では検知不能 → 本体は確定終値ガード。

本モジュールの主要関数（pick_confirmed / sane_index）は外部依存ゼロの純関数で、
cred 無しのローカル単体テストが可能（tests/test_market_guard.py）。
"""
from datetime import datetime

try:
    from zoneinfo import ZoneInfo
    _HAS_TZ = True
except Exception:  # zoneinfo/tzdata 不在環境
    _HAS_TZ = False

# 市場セッションの締め時刻: ticker -> (市場TZ名, 締め時, 締め分)
# JST 系: 東証 15:30 締め。米系/先物: NY 16:00（先物は 17:00 近似）。
MKT_INFO = {
    '^N225':    ('Asia/Tokyo',       15, 30),
    '^GSPC':    ('America/New_York', 16,  0),
    '^VIX':     ('America/New_York', 16,  0),
    'HYG':      ('America/New_York', 16,  0),
    'CL=F':     ('America/New_York', 17,  0),
    'GC=F':     ('America/New_York', 17,  0),
    'USDJPY=X': ('Asia/Tokyo',       15, 30),
}

# 緩い sanity: ticker -> (下限, 上限, 日次変化上限%)。
# 「市場崩壊級」だけを弾く緩い固定値（場中の正常な急騰急落を殺さない）。
# 現水準に十分広く取る（例: 日経は数万円台 → hi=90000）。
MKT_SANITY = {
    '^N225':    (30000, 90000, 15),
    '^GSPC':    (3000,  12000, 15),
    '^VIX':     (5,     150,   90),
    'HYG':      (50,    130,   12),
    'CL=F':     (10,    250,   25),
    'GC=F':     (1000,  8000,  15),
    'USDJPY=X': (80,    250,   10),
}


def market_now(tzname):
    """市場TZの現在を (today_date, (hour, minute)) で返す。tz 解決不可ならローカル時刻。"""
    if _HAS_TZ:
        try:
            n = datetime.now(ZoneInfo(tzname))
            return n.date(), (n.hour, n.minute)
        except Exception:
            pass
    n = datetime.now()
    return n.date(), (n.hour, n.minute)


def pick_confirmed(bar_dates, closes, now_date, now_hm, close_hm):
    """未確定の当日バーを除外し、確定済みの (now, prev) を返す純関数。

    bar_dates : list[date]  日足バーの日付（昇順）
    closes    : list[float] 各バーの終値（NaN 除去済み・bar_dates と同長）
    now_date  : date        市場TZの今日
    now_hm    : (h, m)      市場TZの現在時刻
    close_hm  : (h, m)      その市場の引け時刻

    返り値: (now_close, prev_close) または取得不能なら None。
    最終バーが「市場の今日」かつ「まだ引けていない」=未確定なら除外して
    1本前の確定終値を採用する（寄付前/場中の気配混入を排除）。
    """
    if not closes or len(closes) < 2 or len(closes) != len(bar_dates):
        return None
    session_closed = tuple(now_hm) >= tuple(close_hm)
    if bar_dates[-1] == now_date and not session_closed and len(closes) >= 3:
        closes = closes[:-1]
    if len(closes) < 2:
        return None
    return closes[-1], closes[-2]


def sane_index(ticker, now_v, prev_v):
    """指数値の緩い sanity（崩壊級のみ False）。範囲外 or 日次変化過大なら False。"""
    rng = MKT_SANITY.get(ticker)
    if not rng:
        return True
    lo, hi, maxchg = rng
    if not (lo < now_v < hi):
        return False
    if prev_v and abs((now_v - prev_v) / prev_v * 100.0) > maxchg:
        return False
    return True

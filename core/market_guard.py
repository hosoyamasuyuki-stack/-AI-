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


# 個別株の日次変化 sanity 上限（%）。
# 東証の値幅制限（ストップ高安）は対象ユニバース（保有/監視/Top75 の中〜大型株・
# 概ね数百円〜数千円台）では日次 ±30% 未満に収まる。55% はその現実的上限を十分
# 上回る緩い値で、正常な急騰急落は殺さず「データ破損級の偽暴落/偽急騰」だけを弾く。
STOCK_MAX_CHANGE_PCT = 55.0


def index_change_pct(now_v, prev_v):
    """指数の日次変化率（%）。prev<=0 / now=None なら None。"""
    if now_v is None or not prev_v or prev_v <= 0:
        return None
    return (now_v - prev_v) / prev_v * 100.0


# 暴落トリガ（X-2・2026-06-05）の閾値。
# threshold: これ以下で暴落とみなす。floor: これ未満は「1日の指数変動としてあり得ない＝
# データ破損」として除外（取引所のサーキットブレーカーで実際の下落はこの手前で止まる）。
CRASH_THRESHOLD_PCT = -5.0
CRASH_FLOOR_PCT = -60.0


def is_crash(ticker, now_v, prev_v, threshold_pct=CRASH_THRESHOLD_PCT, floor_pct=CRASH_FLOOR_PCT):
    """指数の暴落判定（info 由来の確定値前提）。

    range 健全（MKT_SANITY の lo<now<hi）かつ `floor_pct < 変化率 <= threshold_pct`
    なら True。
    - sane_index の日次変化上限（^N225 なら 15%）は **本物の暴落（2024-08-05 の -12% 等）も
      弾いてしまう**ため、暴落判定には使わず range のみ流用する。
    - floor_pct（-60%）未満や range 外は「データ破損」として False（誤発火防止・68,402 教訓）。
    - prev<=0 / now=None（取得不能）も False。
    """
    rng = MKT_SANITY.get(ticker)
    if rng:
        lo, hi, _ = rng
        if now_v is None or not (lo < now_v < hi):
            return False
    pct = index_change_pct(now_v, prev_v)
    if pct is None:
        return False
    return floor_pct < pct <= threshold_pct


def sane_price(now_v, prev_v, max_change_pct=STOCK_MAX_CHANGE_PCT):
    """個別株価の緩い sanity（データ破損のみ False）。

    2026-06-05 の日経 68,402 事故と同根: yfinance の日足が壊れると個別株でも
    `Close.iloc[-1]` が誤値となり偽暴落を表示しうる。本関数で破損を検知し、
    呼出側は権威ソース（J-Quants）へフォールバックする。

    now_v / prev_v : 当日・前日の終値。
    - now_v が None / <=0（明白な破損）→ False。
    - prev_v が正のとき、日次変化が max_change_pct を超える（崩壊級）→ False。
    - prev_v が無い/0 のときは変化率判定をスキップ（now_v>0 のみ要求）。
    """
    if now_v is None or now_v <= 0:
        return False
    if prev_v and prev_v > 0:
        if abs((now_v - prev_v) / prev_v * 100.0) > max_change_pct:
            return False
    return True

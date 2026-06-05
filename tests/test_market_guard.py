"""core.market_guard の単体テスト（cred 不要・純関数）。

2026-06-05 日経225 誤値事故（68,402・実値67,470.69）の再現と再発防止を検証。
"""
import os
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.market_guard import (  # noqa: E402
    pick_confirmed, sane_index, sane_price, is_crash, index_change_pct,
)


# 事故再現用バー: 6/03=68,401 / 6/04=67,470.69（実 確定終値） / 6/05=68,402（寄付前 未確定）
_BARS_DATES = [date(2026, 6, 3), date(2026, 6, 4), date(2026, 6, 5)]
_BARS_CLOSE = [68401.0, 67470.69, 68402.0]


def test_premarket_drops_unconfirmed_today_bar():
    # 6/05 08:23（寄付前・締め15:30前）→ 未確定の当日バー68,402を除外し確定6/04終値を採用
    r = pick_confirmed(_BARS_DATES, _BARS_CLOSE, date(2026, 6, 5), (8, 23), (15, 30))
    assert r is not None
    now, prev = r
    assert now == 67470.69 and prev == 68401.0
    chg = (now - prev) / prev * 100
    assert abs(chg - (-1.36)) < 0.05  # -1.36% 復元


def test_intraday_drops_unconfirmed_today_bar():
    # 10:30（場中・締め前）→ 進行中の当日バーは未確定 → 確定終値を採用（誤気配を出さない）
    r = pick_confirmed(_BARS_DATES, _BARS_CLOSE, date(2026, 6, 5), (10, 30), (15, 30))
    assert r == (67470.69, 68401.0)


def test_after_close_keeps_today_bar():
    # 引け後（16:00 > 15:30）→ 当日バーは確定 → 当日終値を採用
    bars = [68401.0, 67470.69, 67900.0]
    r = pick_confirmed(_BARS_DATES, bars, date(2026, 6, 5), (16, 0), (15, 30))
    assert r == (67900.0, 67470.69)


def test_no_today_bar_uses_latest_two():
    # 当日バーがまだ無い（直近=6/04）→ そのまま採用
    r = pick_confirmed(_BARS_DATES[:2], _BARS_CLOSE[:2], date(2026, 6, 5), (8, 23), (15, 30))
    assert r == (67470.69, 68401.0)


def test_too_few_bars_returns_none():
    assert pick_confirmed([date(2026, 6, 4)], [67470.69], date(2026, 6, 5), (8, 0), (15, 30)) is None
    assert pick_confirmed([], [], date(2026, 6, 5), (8, 0), (15, 30)) is None


def test_sane_index_accepts_current_level():
    # 本世界の日経 67k 台は正常（範囲内・日次-1.36%）
    assert sane_index('^N225', 67470.69, 68401.0) is True
    assert sane_index('^GSPC', 7554.0, 7600.0) is True


def test_sane_index_rejects_out_of_range_and_spikes():
    assert sane_index('^N225', 5000, 67000) is False          # 範囲外（下限割れ）
    assert sane_index('^N225', 120000, 67000) is False         # 範囲外（上限超）
    assert sane_index('^N225', 80000, 40000) is False          # 日次変化 +100% > 15%
    assert sane_index('^VIX', 16.1, 16.3) is True              # VIX は変動大でも範囲内OK


def test_sane_price_accepts_normal_moves():
    # 値幅制限内の正常な急騰急落は通す（対象ユニバースの現実的上限は ±30% 未満）
    assert sane_price(1000.0, 1000.0) is True
    assert sane_price(1300.0, 1000.0) is True   # +30%
    assert sane_price(700.0, 1000.0) is True     # -30%
    assert sane_price(500.0, None) is True       # 前日不明でも正値は OK


def test_sane_price_rejects_broken_data():
    # データ破損級（<=0 / 崩壊級の変化）は弾く → 呼出側で J-Quants フォールバック
    assert sane_price(0, 1000.0) is False
    assert sane_price(-5.0, 1000.0) is False
    assert sane_price(None, 1000.0) is False
    assert sane_price(400.0, 1000.0) is False     # -60% > 55%（偽暴落級）
    assert sane_price(1600.0, 1000.0) is False    # +60% > 55%（偽急騰級）


def test_sane_price_skips_change_check_without_prev():
    # 前日 0/None のときは変化率判定をスキップ（正値なら True）
    assert sane_price(1000.0, 0) is True
    assert sane_price(1000.0, None) is True


def test_is_crash_fires_on_real_crash():
    # -5% 以下の本物の暴落は発火（sane_index の 15% 上限では弾かれる -12% 級も拾う）
    assert is_crash('^N225', 63000, 67000) is True       # -5.97%
    assert is_crash('^N225', 58000, 67000) is True       # -13.4%（2024-08-05 級）


def test_is_crash_no_fire_on_normal():
    assert is_crash('^N225', 66000, 67000) is False      # -1.49%
    assert is_crash('^N225', 67000, 67000) is False      # 0%
    assert is_crash('^N225', 70000, 67000) is False      # 上昇


def test_is_crash_rejects_broken_data():
    assert is_crash('^N225', 5000, 67000) is False        # range 外（下限割れ・garbage）
    assert is_crash('^N225', 200000, 67000) is False      # range 外（上限超）
    assert is_crash('^N225', 31000, 85000) is False       # -63.5% < floor(-60%)＝破損級
    assert is_crash('^N225', None, 67000) is False        # 取得不能
    assert is_crash('^N225', 63000, 0) is False           # prev 不正


def test_index_change_pct():
    assert abs(index_change_pct(63000, 67000) - (-5.970)) < 0.01
    assert index_change_pct(63000, 0) is None
    assert index_change_pct(None, 67000) is None


if __name__ == '__main__':
    fns = [v for k, v in sorted(globals().items()) if k.startswith('test_') and callable(v)]
    passed = 0
    for fn in fns:
        fn()
        print(f"  PASS {fn.__name__}")
        passed += 1
    print(f"=== {passed}/{len(fns)} PASS ===")

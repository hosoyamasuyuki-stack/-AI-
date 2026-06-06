"""per-stock 短期/中期 予測スコアの単体テスト（2026-06-07・H-perstock-0607）。

銘柄ごとに値が分散すること＝市場値の全銘柄貼付（短期/中期が全銘柄同一バグ）が
解消されたことを検証する。根拠・仮説は verify/HYPOTHESES.md を参照。
"""
from core.scoring import perstock_short, perstock_mid


def test_short_varies_by_stock():
    market = 29
    cheap = perstock_short(market, 90)   # 割安度 高
    rich = perstock_short(market, 20)    # 割安度 低
    assert cheap != rich, "短期が銘柄(s3)で変わらない＝全銘柄同一バグ再発"
    assert cheap > rich


def test_mid_varies_by_stock():
    market = 25
    up = perstock_mid(market, 80)
    down = perstock_mid(market, 30)
    assert up != down, "中期が銘柄(s2)で変わらない＝全銘柄同一バグ再発"
    assert up > down


def test_blend_formula():
    assert perstock_short(29, 90, w_market=0.4) == round(29 * 0.4 + 90 * 0.6)
    assert perstock_mid(25, 80, w_market=0.4) == round(25 * 0.4 + 80 * 0.6)


def test_none_and_clamp_safe():
    # None/NaN は中立50で安全・常に 0..100 に収まる
    assert 0 <= perstock_short(29, None) <= 100
    assert 0 <= perstock_mid(25, None) <= 100
    assert 0 <= perstock_short(0, 0) <= 100
    assert 0 <= perstock_short(100, 100) <= 100

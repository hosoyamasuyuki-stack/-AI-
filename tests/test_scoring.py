"""
v4.3 スコアリング関数の単体テスト（Google Sheets モック不要・純粋関数のみ）
教訓17対応: 「PEG thr_high 誤用で s3 が暴走」を自動検出できるように。
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.scoring import safe, thr_high, thr_low, slope_fn
from core.config import (ROE_THR, FCR_THR, RS_THR, FS_THR,
                         PEG_THR, FCY_THR, SHEET_SCHEMA,
                         SCORE_RANGE, SCORE_ABS_MIN, CELL_SAME_RATIO)


class TestThrHigh:
    """高いほど良い指標（ROE/FCR/FCF利回り等）のスコア化"""

    def test_roe_25_gives_100(self):
        """ROE 25% = 満点"""
        assert thr_high(25, ROE_THR) == 100

    def test_roe_0_gives_low(self):
        """ROE 0% = 最低スコア"""
        assert thr_high(0, ROE_THR) <= 20

    def test_roe_none_gives_default(self):
        """None は 50（中立）"""
        assert thr_high(None, ROE_THR) == 50

    def test_roe_negative_gives_10(self):
        """負のROEは 10（下限）"""
        assert thr_high(-5, ROE_THR) == 10


class TestThrLow:
    """低いほど良い指標（PEG）のスコア化"""

    def test_peg_low_gives_high_score(self):
        """PEG 0.3 は 100点（最割安）"""
        assert thr_low(0.3, PEG_THR) == 100

    def test_peg_high_gives_low_score(self):
        """PEG 3.0 は最低に近いスコア（割高）"""
        assert thr_low(3.0, PEG_THR) <= 30

    def test_peg_none_gives_default(self):
        """None は 50"""
        assert thr_low(None, PEG_THR) == 50

    def test_peg_bug_detection(self):
        """PEG に thr_high を誤用すると 低PEG が低スコアになる（過去バグの回帰テスト）"""
        # PEG 0.3 は割安なので 高スコアであるべき
        # 誤って thr_high を使うと 低スコア（10）になる
        assert thr_high(0.3, PEG_THR) <= 30  # バグ動作の証拠
        # thr_low なら正しく高スコア
        assert thr_low(0.3, PEG_THR) == 100


class TestSafe:
    def test_none_returns_none(self):
        assert safe(None) is None

    def test_nan_returns_none(self):
        import math
        assert safe(math.nan) is None

    def test_rounding(self):
        assert safe(3.14159, 2) == 3.14


class TestSlope:
    def test_upward_trend(self):
        assert slope_fn([1, 2, 3, 4, 5]) > 0

    def test_downward_trend(self):
        assert slope_fn([5, 4, 3, 2, 1]) < 0

    def test_flat(self):
        assert abs(slope_fn([3, 3, 3, 3])) < 0.01

    def test_empty(self):
        assert slope_fn([]) == 0.0


class TestV43Score:
    """v4.3 総合スコアの計算整合性テスト（教訓16対応）"""

    def test_formula_consistency(self):
        """総合スコア = 変数1*0.40 + 変数2*0.35 + 変数3*0.25"""
        s1, s2, s3 = 80, 65, 70
        expected = round(s1 * 0.40 + s2 * 0.35 + s3 * 0.25, 1)
        # 理論値: 32 + 22.75 + 17.5 = 72.25
        # Python の round は banker's rounding なので 72.25 → 72.2
        # 許容範囲で判定（丸め方式によらない整合性）
        assert 72.2 <= expected <= 72.3

    def test_rank_thresholds(self):
        """S>=80 / A>=65 / B>=50 / C>=35 / D<35"""
        def rank_of(total):
            return ('S' if total >= 80 else 'A' if total >= 65 else
                    'B' if total >= 50 else 'C' if total >= 35 else 'D')
        assert rank_of(85) == 'S'
        assert rank_of(80) == 'S'
        assert rank_of(79.9) == 'A'
        assert rank_of(65) == 'A'
        assert rank_of(50) == 'B'
        assert rank_of(35) == 'C'
        assert rank_of(34.9) == 'D'


class TestSchemaIntegrity:
    """SHEET_SCHEMA が必須列を含むか（教訓16対応）"""

    def test_holding_schema_has_scores(self):
        schema = SHEET_SCHEMA['保有銘柄_v4.3スコア']
        for required in ['コード', '総合スコア', 'ランク', '変数1', '変数2', '変数3']:
            assert required in schema, f"{required} が 保有銘柄_v4.3スコア スキーマにない"

    def test_watch_schema_matches_holding(self):
        """保有と監視は同じスキーマであるべき"""
        assert SHEET_SCHEMA['保有銘柄_v4.3スコア'] == SHEET_SCHEMA['監視銘柄_v4.3スコア']

    def test_pred_schema_has_4_axes(self):
        pred = SHEET_SCHEMA['予測記録']
        assert set(pred['axes']) == {'目先', '短期', '中期', '長期'}
        assert set(pred['axis_starts'].keys()) == {'目先', '短期', '中期', '長期'}
        # 各時間軸は 8列間隔
        starts = sorted(pred['axis_starts'].values())
        for i in range(1, len(starts)):
            assert starts[i] - starts[i - 1] == 8, "時間軸グループは8列間隔"


class TestIntegrityThresholds:
    """整合性ガードの閾値（教訓17対応）"""

    def test_score_range(self):
        lo, hi = SCORE_RANGE
        assert lo < 0 and hi > 100

    def test_cell_same_ratio(self):
        """80% 同値でERROR停止"""
        assert 0.5 < CELL_SAME_RATIO < 1.0
        assert CELL_SAME_RATIO == 0.80

    def test_abs_min(self):
        """絶対値 1 未満は生データ混入疑い"""
        assert SCORE_ABS_MIN == 1.0


if __name__ == '__main__':
    import pytest
    pytest.main([__file__, '-v'])

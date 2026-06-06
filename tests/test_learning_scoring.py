"""
学習(v4.2)スコアの PEG 方向が本番(v4.3)と整合していることを検証する。

2026-06-06: learning_batch_monthly.py が独自 thr()(高良固定)で PEG(低良)を処理し、
割高株も割安株も一律100点になる逆向きバグ（v4.3 は thr_low で修正済）の再発防止。
verify_axis は v4.2/v4.3 行を分離しないため、この汚染は閾値補正提案(propose)に到達する。

注: learning_batch_monthly は import 時にモジュール本体(認証/99銘柄スキャン)が走るため
    calc() を直接 import できない。よってスコア関数の方向(core.scoring)と、
    calc() が thr_low(peg) を使っていることのソース保証 の両輪で検証する。
"""
import os
import re

from core.config import PEG_THR, FCY_THR, ROE_THR
from core.scoring import thr_low, thr_high

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LEARNING_SRC = os.path.join(REPO_ROOT, 'learning_batch_monthly.py')


def test_thr_low_peg_direction():
    """割安(低PEG)は割高(高PEG)より高スコアでなければならない（逆向きバグの本質）。"""
    cheap = thr_low(0.6, PEG_THR)   # 割安
    rich2 = thr_low(2.0, PEG_THR)   # 割高
    rich3 = thr_low(3.0, PEG_THR)   # さらに割高
    assert cheap > rich2, f"割安(PEG0.6={cheap})は割高(PEG2.0={rich2})より高くあるべき"
    assert rich2 >= rich3, f"PEGが高いほど低スコア({rich2} >= {rich3})"


def test_thr_high_fy_direction():
    """FCF利回り(高良)は高いほど高スコア。"""
    assert thr_high(10.0, FCY_THR) >= thr_high(1.0, FCY_THR)


def test_learning_batch_uses_thr_low_for_peg():
    """learning_batch.calc() が PEG に thr_low(低良) を使い、高良 thr() を撤去済みであること。"""
    src = open(LEARNING_SRC, encoding='utf-8').read()
    assert 'thr_low(peg' in src, "PEG は thr_low(低良)で評価すること"
    # 高良 thr() を PEG に使っていない（逆向きバグの再発防止）
    assert re.search(r'(?<![_a-z])thr\(peg', src) is None, "PEG に高良 thr() を使ってはいけない"
    # 独自 thr()(高良固定・既定0)の定義が撤去されていること
    assert re.search(r'^\s*def thr\(', src, re.M) is None, "独自 thr() は撤去し core.scoring を使うこと"
    # core.scoring の共通ヘルパーを import していること
    assert 'from core.scoring import' in src and 'thr_low' in src

"""core.sector_benchmark の単体テスト（cred 不要・純関数・コアスキャン v2.1 B）。

業種別ベンチマーク集計の正しさ（グルーピング/外れ値除外/中央値・四分位/全市場）を検証。
JS版 corescan_v21_sector_benchmark.test.mjs（19/19）と同じ判定基準。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.sector_benchmark import (  # noqa: E402
    compute_sector_benchmarks, to_sheet_rows, robust_stats, MIN_PEERS, METRICS,
)


def _fixture():
    """輸送用機器に Exedy(ROE6.57) を含む30社（外れ値1200混入）＋情報通信25社＋鉱業5社。"""
    rows = []
    trans_roe = [18, 16, 15, 14, 13, 12, 12, 11, 11, 10, 10, 9.5, 9, 8.8, 8.5,
                 8, 7.5, 7.2, 6.9, 6.57, 6.2, 6, 5.5, 5, 4.5, 4, 3.5, 3, 2.5, 1200]
    for i, roe in enumerate(trans_roe):
        rows.append({'code': f'T{i}', 'sector': '輸送用機器', 'roe': roe,
                     'fcf_yield': 4 + i % 7, 'total': 40 + (0 if roe > 100 else roe)})
    for i in range(25):
        rows.append({'code': f'I{i}', 'sector': '情報・通信業', 'roe': 10 + i * 0.8, 'total': 50 + i})
    for i in range(5):
        rows.append({'code': f'M{i}', 'sector': '鉱業', 'roe': 8 + i, 'total': 55})
    return rows


def test_grouping_counts():
    bm = compute_sector_benchmarks(_fixture(), as_of='2026-06-06')
    assert bm['sectors']['輸送用機器']['n'] == 30
    assert bm['sectors']['情報・通信業']['n'] == 25
    assert bm['sectors']['鉱業']['n'] == 5
    assert bm['sector_count'] == 3


def test_outlier_excluded_from_quartiles():
    bm = compute_sector_benchmarks(_fixture())
    t = bm['sectors']['輸送用機器']['metrics']['roe']
    assert t['n'] == 29          # ROE 外れ値 1200 を四分位計算から除外
    assert t['max'] <= 18
    assert 6 <= t['median'] <= 10


def test_quartile_values_reasonable():
    bm = compute_sector_benchmarks(_fixture())
    t = bm['sectors']['輸送用機器']['metrics']['roe']
    assert t['q1'] < t['median'] < t['q3']
    info = bm['sectors']['情報・通信業']['metrics']['roe']
    assert info['median'] > t['median']   # 情報通信は輸送より ROE 高い


def test_small_sector_under_min_peers():
    bm = compute_sector_benchmarks(_fixture())
    assert bm['sectors']['鉱業']['n'] < MIN_PEERS   # 参考表示の対象（判定は呼出側）


def test_all_market_aggregate():
    bm = compute_sector_benchmarks(_fixture())
    assert bm['all']['n'] == 60
    assert bm['all']['metrics']['roe']['median'] is not None


def test_missing_and_blank_values_ignored():
    rows = [
        {'sector': 'X業', 'roe': 10}, {'sector': 'X業', 'roe': None},
        {'sector': 'X業', 'roe': ''}, {'sector': 'X業', 'roe': 'NaN'},
        {'sector': 'X業', 'roe': 20},
    ]
    bm = compute_sector_benchmarks(rows)
    assert bm['sectors']['X業']['metrics']['roe']['n'] == 2   # 有効値は 10, 20 のみ


def test_blank_sector_skipped():
    rows = [{'sector': '', 'roe': 5}, {'sector': None, 'roe': 6}, {'sector': 'Y業', 'roe': 7}]
    bm = compute_sector_benchmarks(rows)
    assert bm['sector_count'] == 1 and 'Y業' in bm['sectors']


def test_robust_stats_empty_returns_none():
    assert robust_stats([], (-100, 150)) is None
    assert robust_stats([None, '', 'x'], (-100, 150)) is None


def test_to_sheet_rows_shape():
    bm = compute_sector_benchmarks(_fixture(), as_of='2026-06-06')
    rows = to_sheet_rows(bm)
    assert rows[0][0] == '業種' and len(rows[0]) == 10   # ヘッダー10列
    assert any(r[0] == '（全市場）' for r in rows[1:])    # 全市場行あり
    # 全データ行は10列
    for r in rows[1:]:
        assert len(r) == 10


if __name__ == '__main__':
    fns = [v for k, v in sorted(globals().items()) if k.startswith('test_') and callable(v)]
    passed = 0
    for fn in fns:
        fn()
        print(f"  PASS {fn.__name__}")
        passed += 1
    print(f"=== {passed}/{len(fns)} PASS ===")

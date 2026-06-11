"""業種別ベンチマーク集計（コアスキャン v2.1 B・業種内順位）。

full_scan.py が週次で算出する全社 results から、業種×指標の中央値・四分位を
集計する純関数群。外部依存は numpy のみ・cred 不要でローカル単体テスト可能
（tests/test_sector_benchmark.py）。

設計方針:
- 業種内順位は採点エンジンのスコア版（v4.3 / コアスキャン v2.1）に依存しないよう、
  生メトリクス（ROE/FCF利回り/PEG/総合スコア）の分布で判定する。
- 健全域クリップ＋IQRフェンスで外れ値（赤字ROE等）を四分位計算から除外する。
- full_scan は Phase 5c で本モジュールを呼び、新タブ「業種ベンチマーク」へ書き出す。
  既存スキャン・既存タブ・週次cron は無変更。失敗しても本スキャンを止めない（呼出側 try/except）。
- JS版 corescan_v21_sector_benchmark.mjs と同一ロジック（順位ルックアップは JS 側）。
"""
import numpy as np

# 業種内 peer がこれ未満の業種は「参考」表示（小業種・新規上場の歪み回避）。
MIN_PEERS = 20

# 集計対象の指標と健全域（外れ値除外）。full_scan の results 行のフィールド名に整合。
METRICS = {
    'roe':       {'label': 'ROE',        'sane': (-100, 150)},
    'fcr':       {'label': 'FCR',        'sane': (-300, 300)},
    'peg':       {'label': 'PEG',        'sane': (0.0001, 20)},
    'fcf_yield': {'label': 'FCF利回り',  'sane': (-50, 50)},
    'total':     {'label': '総合スコア', 'sane': (0, 100)},
}


def _finite_in_sane(values, sane):
    """有限値かつ健全域 [lo, hi] 内のみを昇順で返す（None/''/NaN/範囲外を除外）。"""
    out = []
    for v in values:
        if v is None or v == '':
            continue
        try:
            x = float(v)
        except (TypeError, ValueError):
            continue
        if x != x:  # NaN
            continue
        if x < sane[0] or x > sane[1]:
            continue
        out.append(x)
    out.sort()
    return out


def robust_stats(values, sane):
    """健全域クリップ＋IQRフェンスで外れ値除外 → 中央値/四分位を安定化。

    n>=4 のとき Q1-1.5*IQR 〜 Q3+1.5*IQR の外側を除外（除外後も n>=4 のときのみ採用）。
    値が無ければ None。
    """
    arr = _finite_in_sane(values, sane)
    if not arr:
        return None
    if len(arr) >= 4:
        q1 = float(np.percentile(arr, 25))
        q3 = float(np.percentile(arr, 75))
        iqr = q3 - q1
        lo, hi = q1 - 1.5 * iqr, q3 + 1.5 * iqr
        clean = [v for v in arr if lo <= v <= hi]
        if len(clean) >= 4:
            arr = clean
    return {
        'n': len(arr),
        'median': round(float(np.percentile(arr, 50)), 2),
        'q1': round(float(np.percentile(arr, 25)), 2),
        'q3': round(float(np.percentile(arr, 75)), 2),
        'min': round(arr[0], 2),
        'max': round(arr[-1], 2),
    }


def compute_sector_benchmarks(results, as_of=None):
    """results（full_scan の全社 dict 配列）→ 業種別×指標別ベンチマーク。

    返り値: {as_of, total_rows, sector_count, sectors:{sec:{n, metrics:{m:{...}}}}, all:{n, metrics}}
    """
    by = {}
    for r in results:
        sec = (r.get('sector') or '').strip()
        if not sec:
            continue
        by.setdefault(sec, []).append(r)
    sectors = {}
    for sec, lst in by.items():
        metrics = {}
        for mk, mc in METRICS.items():
            st = robust_stats([r.get(mk) for r in lst], mc['sane'])
            if st:
                metrics[mk] = st
        sectors[sec] = {'n': len(lst), 'metrics': metrics}
    flat = [r for lst in by.values() for r in lst]
    allm = {}
    for mk, mc in METRICS.items():
        st = robust_stats([r.get(mk) for r in flat], mc['sane'])
        if st:
            allm[mk] = st
    return {
        'as_of': as_of,
        'total_rows': len(flat),
        'sector_count': len(sectors),
        'sectors': sectors,
        'all': {'n': len(flat), 'metrics': allm},
    }


def to_sheet_rows(bm):
    """業種ベンチマーク を Sheet 書き出し用の2次元配列（ヘッダー込み）に平坦化。

    業種は peer 数の多い順。末尾に「（全市場）」行（業種不明フォールバック用）。
    """
    header = ['業種', 'peer数', '指標', '有効n', '中央値', '第1四分位', '第3四分位', '最小', '最大', '算出日時']
    rows = [header]
    for sec, s in sorted(bm['sectors'].items(), key=lambda kv: -kv[1]['n']):
        for mk, mc in METRICS.items():
            m = s['metrics'].get(mk)
            if not m:
                continue
            rows.append([sec, s['n'], mc['label'], m['n'], m['median'],
                         m['q1'], m['q3'], m['min'], m['max'], bm['as_of'] or ''])
    for mk, mc in METRICS.items():
        m = bm['all']['metrics'].get(mk)
        if not m:
            continue
        rows.append(['（全市場）', bm['all']['n'], mc['label'], m['n'], m['median'],
                     m['q1'], m['q3'], m['min'], m['max'], bm['as_of'] or ''])
    return rows

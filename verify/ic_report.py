"""
verify/ic_report.py
自己学習ループの「評価段」: IC（情報係数 = スコア順位 vs 実現リターン順位の Spearman 相関）を計測。

2026-06-06: "勝率"でなく IC を物差しにする（過剰適合の温床を断つ／100%級の高勝率は赤信号）。
軸別(目先/短期/中期/長期)に IC・ICIR・分位スプレッド(Q5-Q1)・単調性を「IC_レポート」シートへ出力。

【設計原則】threshold_advisor.py / snapshot_scores.py と同じ:
- 既存シートに書込しない（読込のみ）。「IC_レポート」へのみ出力（最新リプレース）。
- 失敗しても他に影響しない（独立・例外隔離）。末尾に機械可読 IC_MONITOR_SUMMARY を出力。
- look-ahead 回避: リターンは verify_axis が確定させた「騰落率/日経比超過」列（記録時株価起点）を使い、
  ic_report 内で現在株価を再取得しない。
- 列オフセットは core.config の SHEET_SCHEMA から取得（config.py / verify_axis.py の二重管理を増やさない）。

【実行】monthly_learning.yml に相乗り（scipy 利用可）。手動: python verify/ic_report.py
"""
import warnings
from datetime import datetime
from collections import defaultdict

import gspread
import numpy as np
from scipy.stats import spearmanr

from core.config import SHEET_SCHEMA
from core.auth import get_spreadsheet

warnings.filterwarnings('ignore')

PRED_SHEET = '予測記録'
OUT_SHEET = 'IC_レポート'
MIN_SAMPLES = 20            # 軸ごとの最小標本（これ未満はスキップ＝安全停止）
AXIS_STARTS = SHEET_SCHEMA['予測記録']['axis_starts']  # {'目先':8,...} 二重管理回避

SCORE_COL = 5  # 総合スコア "67.5点"
OFF_CHG = 5    # 軸内オフセット: 騰落率
OFF_VSNK = 6   # 軸内オフセット: 日経比超過
OFF_WL = 7     # 軸内オフセット: 勝敗


def _num(v):
    try:
        s = str(v).replace('点', '').replace('%', '').replace(',', '').strip()
        if s == '' or s in ('-', '—'):
            return None
        return float(s)
    except Exception:
        return None


def _ic(scores, rets):
    if len(scores) < 3:
        return None
    try:
        r = spearmanr(scores, rets).correlation
        return None if (r is None or np.isnan(r)) else round(float(r), 4)
    except Exception:
        return None


def _quintile(scores, rets):
    if len(scores) < 5:
        return '', '', '', ''
    order = np.argsort(scores)
    rs = np.array(rets, dtype=float)[order]
    q = len(rs) // 5
    if q < 1:
        return '', '', '', ''
    means = [float(np.mean(rs[i * q:(i + 1) * q])) for i in range(5)]
    mono = sum(1 for i in range(4) if means[i] < means[i + 1]) / 4.0
    return round(means[4], 2), round(means[0], 2), round(means[4] - means[0], 2), round(mono, 2)


def main():
    now = datetime.now()
    now_str = now.strftime('%Y/%m/%d %H:%M')
    ss = get_spreadsheet()
    print(f"接続完了: {ss.title}  {now_str}")

    data = ss.worksheet(PRED_SHEET).get_all_values()
    rows_data = data[2:] if len(data) >= 3 else []

    results = []
    total_samples = 0
    min_ic = None

    for axis, start in AXIS_STARTS.items():
        scores, chg, vsnk = [], [], []
        cohorts = defaultdict(list)
        for r in rows_data:
            if len(r) <= start + OFF_WL:
                continue
            if str(r[start + OFF_WL]).strip() not in ('勝', '負'):  # 検証済(満期到来)のみ
                continue
            sc = _num(r[SCORE_COL]) if len(r) > SCORE_COL else None
            rc = _num(r[start + OFF_CHG])
            if sc is None or rc is None:
                continue
            rv = _num(r[start + OFF_VSNK])
            scores.append(sc)
            chg.append(rc)
            vsnk.append(rv if rv is not None else rc)
            cohorts[str(r[0]).strip()].append((sc, rc))

        n = len(scores)
        if n < MIN_SAMPLES:
            results.append([axis, n, '標本不足', '', '', '', '', '', '', ''])
            continue

        total_samples += n
        ic_chg = _ic(scores, chg)
        ic_vsnk = _ic(scores, vsnk)
        q5, q1, spread, mono = _quintile(scores, chg)

        # ICIR = コホート別 IC の 平均/標準偏差（コホート>=3 かつ 各>=5 銘柄）
        cic = []
        for _d, pairs in cohorts.items():
            if len(pairs) >= 5:
                v = _ic([p[0] for p in pairs], [p[1] for p in pairs])
                if v is not None:
                    cic.append(v)
        icir = round(float(np.mean(cic) / np.std(cic)), 2) if (len(cic) >= 3 and np.std(cic) > 0) else ''

        if ic_chg is not None:
            min_ic = ic_chg if min_ic is None else min(min_ic, ic_chg)
        verdict = ('逆相関・要レビュー' if (ic_chg is not None and ic_chg < 0)
                   else '有効' if (ic_chg is not None and ic_chg >= 0.05)
                   else '弱い/観察')
        results.append([axis, n, ic_chg, ic_vsnk, icir, q5, q1, spread, mono, verdict])

    # 出力（最新リプレース・append しない＝レポートは最新1枚で十分）
    try:
        ws = ss.worksheet(OUT_SHEET)
        ws.clear()
    except gspread.exceptions.WorksheetNotFound:
        ws = ss.add_worksheet(title=OUT_SHEET, rows=50, cols=12)

    out = [
        ['最終実行日', now_str] + [''] * 8,
        ['指標', 'IC = スコア順位 vs 実現リターン順位の Spearman 相関（横断面）'] + [''] * 8,
        ['注記', 'PIT近似(J-Quants最新版財務・残存改訂バイアスあり)。短中長期は満期到来分のみ・標本不足は集計せず'] + [''] * 8,
        ['仮説', '現行の予測仮説と重みの根拠は verify/HYPOTHESES.md (H-perstock-0607)。IC と突合して当否判定・1度に1パラメータ調整(CEO指示2026-06-07)'] + [''] * 8,
        [''] * 10,
        ['軸', '標本数', 'IC(騰落率)', 'IC(日経比超過)', 'ICIR', 'Q5平均%', 'Q1平均%', 'Q5-Q1', '単調性', '判定'],
    ]
    for r in results:
        out.append((list(r) + [''] * 10)[:10])
    ws.update(values=out, range_name='A1')

    axes_ok = sum(1 for r in results if isinstance(r[1], int) and r[1] >= MIN_SAMPLES)
    mic = min_ic if min_ic is not None else 'NA'
    print(f"✅ {OUT_SHEET} 出力: 全{len(results)}軸 / 集計{axes_ok}軸 / 標本{total_samples}")
    print("📋 現行仮説は verify/HYPOTHESES.md (H-perstock-0607) 参照。IC と突合して当否判定・1度に1パラメータ調整")
    print(f"IC_MONITOR_SUMMARY ok=true axes={axes_ok} samples={total_samples} min_ic={mic}")


if __name__ == '__main__':
    try:
        main()
    except Exception as e:
        print(f"IC_MONITOR_SUMMARY ok=false axes=0 samples=0 reason={type(e).__name__}")
        raise

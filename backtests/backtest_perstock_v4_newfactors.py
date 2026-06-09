"""
backtests/backtest_perstock_v4_newfactors.py
  — 新因子探索 MVP (CEO 承認 Option C・2026-06-09)。

F1修正で現行3因子(s1/s2/s3)は過去ICが0と区別できないと確定(v3)。
本スクリプトは F1修正済クリーン harness を再利用し、新候補因子の過去IC を測る:
  (1) momentum 12-1 : P(t-1m)/P(t-12m)-1 (AdjC=分割相殺・過去価格のみ=look-ahead無し・harness検出力サニティ兼)
  (2) clean E/P     : 当時開示EPS / 当時生終値C (=F1修正の earnings yield・分母にAdjCを使わない)

★READ-ONLY: master(キャッシュ済)+ .cache_perstock/ のみ。本番SS/予測記録/cron/スコア経路に一切書かない。
  v3 の cached_master/fwd_ret_surv/neutral_ic と v1 の price_asof/block_bootstrap_ci を import 再利用。
  出力=ローカルCSV+標準出力のみ。観測値のみ・本番反映は三重ゲート。
"""
import sys
import math
from pathlib import Path
from datetime import timedelta, datetime

import numpy as np
import pandas as pd
from scipy import stats

ROOT = Path(r"C:/AI-investment/-AI-")
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backtests"))
import backtest_perstock_v1 as v1                # noqa: E402  price_asof/block_bootstrap_ci/build_fins_df/load_*
import backtest_perstock_v2_survivorship as v2   # noqa: E402  is_large_mid/code_field/ASOF
import backtest_perstock_v3_corrected as v3       # noqa: E402  cached_master/cached_master_current/fwd_ret_surv/neutral_ic

OUT = ROOT / "backtests" / "output"
OUT.mkdir(exist_ok=True)
HOR = {"6m": 182, "1y": 365, "3y": 365 * 3}
NEWF = ["mom", "ep"]


def eps_asof(fdf, t):
    if fdf is None or len(fdf) == 0:
        return None
    av = fdf[fdf["DiscDate"] <= t]
    if len(av) < 1:
        return None
    e = av.iloc[-1].get("EPS")
    return e if (e is not None and not (isinstance(e, float) and math.isnan(e))) else None


def main():
    print("=" * 80)
    print("backtest_perstock_v4_newfactors : momentum + clean E/P  READ-ONLY", datetime.now().strftime("%H:%M"))
    print("=" * 80)

    cur_rows = v3.cached_master_current()
    cur_codes = {v2.code_field(r) for r in cur_rows if v2.code_field(r)}
    print("[0] 現在master %d社" % len(cur_rows))

    print("[1] 当時母集団復元(master cached)")
    universe = {}
    for t in v2.ASOF:
        rows, used = v3.cached_master(t)
        uni = {}
        for r in rows:
            c = v2.code_field(r)
            if c and v2.is_large_mid(r):
                uni[c] = (r.get("S33Nm", ""), str(r.get("ScaleCat", "")))
        universe[t] = uni
    union = sorted({c for uni in universe.values() for c in uni})
    print("  union=%d" % len(union))

    print("[2] fins + 価格マップ(adj/raw)読込")
    fins, padj, praw = {}, {}, {}
    for i, c in enumerate(union):
        try:
            fins[c] = v1.build_fins_df(v1.load_fins(c))
            prows = v1.load_prices(c)
            ma, mr = {}, {}
            for r in prows:
                dd = r.get("Date")
                if not dd:
                    continue
                ts = pd.Timestamp(dd)
                a = r.get("AdjC") if r.get("AdjC") is not None else r.get("C")
                rw = r.get("C")
                if a is not None:
                    ma[ts] = float(a)
                if rw is not None:
                    mr[ts] = float(rw)
            padj[c] = (ma, sorted(ma.keys()))
            praw[c] = (mr, sorted(mr.keys()))
        except Exception as e:
            fins[c] = pd.DataFrame()
            padj[c] = ({}, [])
            praw[c] = ({}, [])
            print("    WARN %s %r" % (c, e))
        if (i + 1) % 200 == 0:
            print("    loaded %d/%d" % (i + 1, len(union)))
    all_last = [ds[-1] for (pm, ds) in padj.values() if ds]
    data_end = max(all_last) if all_last else pd.Timestamp("2026-06-30")
    print("  data_end=%s" % data_end.date())

    modes = ["full", "surv"]
    cic = {(f, h, m): [] for f in NEWF for h in HOR for m in modes}
    cic_neut = {(f, h, g): [] for f in NEWF for h in HOR for g in ("sec", "siz")}

    for t in v2.ASOF:
        recs = []
        for c, (sec, siz) in universe[t].items():
            ma, da = padj.get(c, ({}, []))
            mr, dr = praw.get(c, ({}, []))
            pt_adj = v1.price_asof(ma, da, t)
            if pt_adj is None:
                continue
            # momentum 12-1 (両端 <= t)
            p_1m = v1.price_asof(ma, da, t - timedelta(days=30))
            p_12m = v1.price_asof(ma, da, t - timedelta(days=365))
            mom = (p_1m / p_12m - 1) if (p_1m and p_12m and p_12m > 0) else None
            # clean E/P (分母=当時生終値C)
            pt_raw = v1.price_asof(mr, dr, t)
            e = eps_asof(fins.get(c, pd.DataFrame()), t)
            ep = (e / pt_raw) if (e is not None and pt_raw and pt_raw > 0) else None
            if mom is None and ep is None:
                continue
            row = {"code": c, "surv": (c in cur_codes), "sec": sec, "siz": siz, "mom": mom, "ep": ep}
            ok = False
            for h, days in HOR.items():
                r, kind = v3.fwd_ret_surv(ma, da, t, days, data_end)
                row["ret_%s" % h] = r
                if r is not None:
                    ok = True
            if ok:
                recs.append(row)
        if len(recs) < 20:
            continue
        rdf = pd.DataFrame(recs)
        for h in HOR:
            rcol = "ret_%s" % h
            for f in NEWF:
                for m in modes:
                    sub0 = rdf if m == "full" else rdf[rdf["surv"]]
                    sub = sub0[[f, rcol]].dropna()
                    if len(sub) < 20:
                        continue
                    ic, _p = stats.spearmanr(sub[f], sub[rcol])
                    if ic is not None and not math.isnan(ic):
                        cic[(f, h, m)].append(float(ic))
                ic_s = v3.neutral_ic(rdf, f, rcol, "sec")
                if ic_s is not None:
                    cic_neut[(f, h, "sec")].append(ic_s)
                ic_z = v3.neutral_ic(rdf, f, rcol, "siz")
                if ic_z is not None:
                    cic_neut[(f, h, "siz")].append(ic_z)

    def agg(ics, h):
        if not ics:
            return None
        m = float(np.mean(ics))
        pos = float(np.mean([1 if v > 0 else 0 for v in ics]))
        nC = len(ics)
        nI = nC // (2 if h == "6m" else (4 if h == "1y" else 12))
        ci = v1.block_bootstrap_ci(ics, block=(2 if h == "6m" else (4 if h == "1y" else 12)))
        return (m, pos, nC, nI, ci)

    label = {"mom": "momentum12-1", "ep": "clean E/P"}
    print("\n=== 新因子 過去IC (survivorship 母集団) ===")
    print("factor        hor mode |  meanIC   %pos nCoh nInd | bootCI95          | 0除外?")
    rows_out = []
    for f in NEWF:
        for h in HOR:
            for m in modes:
                a = agg(cic[(f, h, m)], h)
                if not a:
                    continue
                mic, pos, nC, nI, ci = a
                exq = (ci[0] is not None and ((ci[0] > 0) or (ci[1] < 0)))
                print("  %-12s %3s %-4s | %+.4f  %3.0f%% %4d %3d | %s..%s | %s" %
                      (label[f], h, m, mic, pos * 100, nC, nI, ci[0], ci[1], "YES" if exq else "no"))
                rows_out.append({"factor": f, "label": label[f], "horizon": h, "mode": m,
                                 "mean_ic": round(mic, 4), "pct_pos": round(pos, 3),
                                 "n_cohort": nC, "n_indep": nI, "ci_lo": ci[0], "ci_hi": ci[1],
                                 "ci_excl_zero": exq})
        print()

    print("=== 新因子 中立化IC [full] ===")
    for f in NEWF:
        for h in HOR:
            for g, gn in (("sec", "業種内"), ("siz", "サイズ内")):
                a = agg(cic_neut[(f, h, g)], h)
                if not a:
                    continue
                mic, pos, nC, nI, ci = a
                exq = (ci[0] is not None and ((ci[0] > 0) or (ci[1] < 0)))
                print("  %-12s %3s %-8s | %+.4f  %3.0f%% nCoh %d | %s..%s | %s" %
                      (label[f], h, gn, mic, pos * 100, nC, ci[0], ci[1], "YES" if exq else "no"))
                rows_out.append({"factor": "%s_neutral_%s" % (f, g), "label": "%s %s" % (label[f], gn),
                                 "horizon": h, "mode": "full", "mean_ic": round(mic, 4),
                                 "pct_pos": round(pos, 3), "n_cohort": nC, "n_indep": None,
                                 "ci_lo": ci[0], "ci_hi": ci[1], "ci_excl_zero": exq})
        print()

    out_csv = OUT / "perstock_ic_v4_newfactors.csv"
    pd.DataFrame(rows_out).to_csv(out_csv, index=False, encoding="utf-8-sig")
    print("出力:", out_csv)
    print("注: 多重比較=因子探索で検定数増加。有意性は全因子横断の補正後のみ・観測値のみ・本番反映は三重ゲート。")
    print("PERSTOCK_V4_SUMMARY ok=true union=%d cells=%d" % (len(union), len(rows_out)))
    print("DONE_V4")


if __name__ == "__main__":
    main()

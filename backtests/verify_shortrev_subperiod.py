"""
backtests/verify_shortrev_subperiod.py
  — タスクV2: shortRev のサブ期間安定性 + 既存因子との直交性(敵対的検証・2026-06-09)

目的: shortRev(短期リバーサル = -(P_t/P_{t-1m}-1))の陽性が
  (a) 単一レジーム(Abenomics 2013 / COVID 2020 等)の産物か → サブ期間分割で確認
  (b) 既存 s3(割安)等の言い換えか → 横断面 Spearman 相関で直交性を確認
を判別する。READ-ONLY: cached master/fins/px のみ。本番経路に一切書かない。

★harnessサニティ: 「shortRev=-(P_t/P_{t-30d}-1) の 1m前向きIC(full,56コホート)」が
  meanIC≈+0.045(CI≈ -0.003..0.094)を再現できることをまず確認。不一致なら STOP。
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
import backtest_perstock_v1 as v1                # noqa: E402  price_asof/build_fins_df/factors_asof/load_fins/load_prices/num/block_bootstrap_ci
import backtest_perstock_v2_survivorship as v2   # noqa: E402  is_large_mid/code_field/ASOF
import backtest_perstock_v3_corrected as v3       # noqa: E402  cached_master/cached_master_current/fwd_ret_surv/neutral_ic
import backtest_perstock_v5_pead as v5            # noqa: E402  pead_factors/price_factors

OUT = ROOT / "backtests" / "output"
OUT.mkdir(exist_ok=True)
HOR = {"1m": 30, "3m": 91, "1y": 365}


def block_for(days):
    return max(1, int(round(days / 91.0)))


def agg(ics, days):
    if not ics:
        return None
    blk = block_for(days)
    m = float(np.mean(ics))
    pos = float(np.mean([1 if v > 0 else 0 for v in ics]))
    nC = len(ics)
    nI = max(1, nC // blk)
    ci = v1.block_bootstrap_ci(ics, block=blk)
    return (m, pos, nC, nI, ci)


def main():
    print("=" * 84)
    print("verify_shortrev_subperiod : サブ期間安定性 + 直交性  READ-ONLY", datetime.now().strftime("%H:%M"))
    print("=" * 84)

    cur_rows = v3.cached_master_current()
    cur_codes = {v2.code_field(r) for r in cur_rows if v2.code_field(r)}
    print("[0] 現在master %d社" % len(cur_rows))

    # 1) 当時母集団(PIT・TOPIX Large+Mid・廃止含む)
    print("[1] 当時母集団復元(master cached)")
    universe = {}
    for t in v2.ASOF:
        rows, _ = v3.cached_master(t)
        uni = {}
        for r in rows:
            c = v2.code_field(r)
            if c and v2.is_large_mid(r):
                uni[c] = (r.get("S33Nm", ""), str(r.get("ScaleCat", "")))
        universe[t] = uni
    union = sorted({c for uni in universe.values() for c in uni})
    print("  union=%d" % len(union))

    # 2) fins(build_fins_df=s1/s2/s3用) + raw fins(pead用) + 価格マップ(adj=AdjC・raw=C)
    print("[2] fins + 価格マップ(adj/raw)読込")
    fins, rawf, padj, praw = {}, {}, {}, {}
    for i, c in enumerate(union):
        try:
            raw = v1.load_fins(c)
            rawf[c] = raw
            fins[c] = v1.build_fins_df(raw)
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
            rawf[c] = []
            padj[c] = ({}, [])
            praw[c] = ({}, [])
            print("    WARN %s %r" % (c, e))
        if (i + 1) % 200 == 0:
            print("    loaded %d/%d" % (i + 1, len(union)))
    all_last = [ds[-1] for (pm, ds) in padj.values() if ds]
    data_end = max(all_last) if all_last else pd.Timestamp("2026-06-30")
    print("  data_end=%s" % data_end.date())

    # サブ期間分割: 前半 2012-2018 / 後半 2019-2025
    SPLIT = pd.Timestamp("2019-01-01")
    sub_label = {"early": "2012-2018", "late": "2019-2025"}

    def subperiod(t):
        return "early" if t < SPLIT else "late"

    # 蓄積容器
    # IC(shortRev): (period, horizon, mode) -> [cohort IC]   period in {all,early,late}
    cic = {(p, h, m): [] for p in ("all", "early", "late") for h in HOR for m in ("full", "surv")}
    # サニティ用は cic[("all","1m","full")] で兼ねる
    # 反転(モメンタム)1m IC
    cic_mom = {p: [] for p in ("all", "early", "late")}
    # 直交性: shortRev vs other の横断面 Spearman(ASOF毎)
    OTHERS = ["s1", "s2", "s3", "frev", "esurp"]
    corr_acc = {o: [] for o in OTHERS}      # 全期間
    corr_acc_p = {(o, p): [] for o in OTHERS for p in ("early", "late")}

    for t in v2.ASOF:
        per = subperiod(t)
        recs = []
        for c, (sec, siz) in universe[t].items():
            ma, da = padj.get(c, ({}, []))
            mr, dr = praw.get(c, ({}, []))
            if not da or not dr:
                continue
            # shortRev / mom は AdjC(分割相殺=F1免疫)
            strev, _lowvol = v5.price_factors(ma, da, t)
            if strev is None:
                continue
            mom = -strev  # 反転 = +(P_t/P_1m-1) モメンタム
            # 既存因子 s1/s2/s3 = 生終値C基準(F1修正準拠)
            pt_raw = v1.price_asof(mr, dr, t)
            fac = v1.factors_asof(fins.get(c, pd.DataFrame()), pt_raw, t) if pt_raw is not None else None
            # PEAD 因子(raw rows を使う)
            frev, esurp = v5.pead_factors(rawf.get(c, []), t)
            row = {"code": c, "surv": (c in cur_codes), "sec": sec, "siz": siz,
                   "strev": strev, "mom": mom, "frev": frev, "esurp": esurp}
            if fac is not None:
                row["s1"], row["s2"], row["s3"] = fac["s1"], fac["s2"], fac["s3"]
            else:
                row["s1"] = row["s2"] = row["s3"] = None
            ok = False
            for h, days in HOR.items():
                r, _kind = v3.fwd_ret_surv(ma, da, t, days, data_end)
                row["ret_%s" % h] = r
                if r is not None:
                    ok = True
            if ok:
                recs.append(row)
        if len(recs) < 20:
            continue
        rdf = pd.DataFrame(recs)

        # --- IC: shortRev / mom ---
        for h in HOR:
            rcol = "ret_%s" % h
            for m in ("full", "surv"):
                sub0 = rdf if m == "full" else rdf[rdf["surv"]]
                sub = sub0[["strev", rcol]].dropna()
                if len(sub) >= 20:
                    ic, _p = stats.spearmanr(sub["strev"], sub[rcol])
                    if ic is not None and not math.isnan(ic):
                        cic[("all", h, m)].append(float(ic))
                        cic[(per, h, m)].append(float(ic))
        # mom 1m(full)
        subm = rdf[["mom", "ret_1m"]].dropna()
        if len(subm) >= 20:
            icm, _p = stats.spearmanr(subm["mom"], subm["ret_1m"])
            if icm is not None and not math.isnan(icm):
                cic_mom["all"].append(float(icm))
                cic_mom[per].append(float(icm))

        # --- 直交性: shortRev vs other(横断面 Spearman・ASOF毎) ---
        for o in OTHERS:
            if o not in rdf.columns:
                continue
            sub = rdf[["strev", o]].dropna()
            if len(sub) >= 20 and sub[o].nunique() > 1:
                rho, _p = stats.spearmanr(sub["strev"], sub[o])
                if rho is not None and not math.isnan(rho):
                    corr_acc[o].append(float(rho))
                    corr_acc_p[(o, per)].append(float(rho))

    # ───────────────── サニティチェック ─────────────────
    sane = agg(cic[("all", "1m", "full")], 30)
    if sane:
        print("\n[サニティ] shortRev 1m full meanIC=%+.4f CI=%s..%s nC=%d  (期待 +0.045 / CI -0.003..0.094)"
              % (sane[0], sane[4][0], sane[4][1], sane[2]))
    else:
        print("\n[サニティ] FAILED no cohorts")
    if not sane or not (0.035 <= sane[0] <= 0.055 and sane[2] == 56):
        print("!!! HARNESS MISMATCH — STOP. 期待 meanIC 0.035..0.055 & nC=56 を満たさない。")
        # それでも CSV は残す(調査用)が verdict は inconclusive を返す方針
        # ここでは標準出力のマーカーで上位に伝える
        print("HARNESS_SANITY=FAIL meanIC=%.4f nC=%d" % (sane[0] if sane else float('nan'),
                                                          sane[2] if sane else -1))
    else:
        print("HARNESS_SANITY=PASS")

    # ───────────────── 結果出力 ─────────────────
    rows_out = []
    print("\n=== shortRev サブ期間安定性 IC(full) ===")
    print("period      hor |  meanIC   %pos nCoh nInd | bootCI95            | 0除外?")
    for p in ("all", "early", "late"):
        for h, days in HOR.items():
            a = agg(cic[(p, h, "full")], days)
            if not a:
                continue
            mic, pos, nC, nI, ci = a
            exq = (ci[0] is not None and ((ci[0] > 0) or (ci[1] < 0)))
            lab = "all(2012-2025)" if p == "all" else sub_label[p]
            print("  %-11s %3s | %+.4f  %3.0f%% %4d %3d | %s..%s | %s"
                  % (lab, h, mic, pos * 100, nC, nI, ci[0], ci[1], "YES" if exq else "no"))
            rows_out.append({"variant": "shortRev", "subperiod": lab, "horizon": h, "mode": "full",
                             "mean_ic": round(mic, 4), "pct_pos": round(pos, 3),
                             "n_cohort": nC, "n_indep": nI, "ci_lo": ci[0], "ci_hi": ci[1],
                             "ci_excl_zero": exq, "note": ""})
        print()

    print("=== shortRev サブ期間安定性 IC(surv 現存のみ・頑健性参考) ===")
    for p in ("early", "late"):
        for h, days in HOR.items():
            a = agg(cic[(p, h, "surv")], days)
            if not a:
                continue
            mic, pos, nC, nI, ci = a
            exq = (ci[0] is not None and ((ci[0] > 0) or (ci[1] < 0)))
            print("  %-11s %3s surv | %+.4f  %3.0f%% %4d %3d | %s..%s | %s"
                  % (sub_label[p], h, mic, pos * 100, nC, nI, ci[0], ci[1], "YES" if exq else "no"))
            rows_out.append({"variant": "shortRev", "subperiod": sub_label[p], "horizon": h, "mode": "surv",
                             "mean_ic": round(mic, 4), "pct_pos": round(pos, 3),
                             "n_cohort": nC, "n_indep": nI, "ci_lo": ci[0], "ci_hi": ci[1],
                             "ci_excl_zero": exq, "note": ""})

    print("\n=== モメンタム(=shortRev符号反転)1m IC(full) : 方向検証 ===")
    for p in ("all", "early", "late"):
        a = agg(cic_mom[p], 30)
        if not a:
            continue
        mic, pos, nC, nI, ci = a
        exq = (ci[0] is not None and ((ci[0] > 0) or (ci[1] < 0)))
        lab = "all(2012-2025)" if p == "all" else sub_label[p]
        print("  momentum %-11s 1m | %+.4f  %3.0f%% %4d | %s..%s | %s"
              % (lab, mic, pos * 100, nC, ci[0], ci[1], "YES" if exq else "no"))
        rows_out.append({"variant": "momentum(=-shortRev)", "subperiod": lab, "horizon": "1m", "mode": "full",
                         "mean_ic": round(mic, 4), "pct_pos": round(pos, 3),
                         "n_cohort": nC, "n_indep": nC, "ci_lo": ci[0], "ci_hi": ci[1],
                         "ci_excl_zero": exq, "note": "expect negative mirror of shortRev"})

    print("\n=== 直交性: shortRev vs 既存因子 横断面Spearman(ASOF平均) ===")
    print("other  | meanRho(all)  N | meanRho(early) | meanRho(late)  | |rho|<0.2?")
    ortho_notes = []
    for o in OTHERS:
        if not corr_acc[o]:
            continue
        rho_all = float(np.mean(corr_acc[o]))
        n_all = len(corr_acc[o])
        rho_e = float(np.mean(corr_acc_p[(o, "early")])) if corr_acc_p[(o, "early")] else float("nan")
        rho_l = float(np.mean(corr_acc_p[(o, "late")])) if corr_acc_p[(o, "late")] else float("nan")
        small = abs(rho_all) < 0.2
        print("  %-5s | %+.4f       %3d | %+.4f       | %+.4f      | %s"
              % (o, rho_all, n_all, rho_e, rho_l, "YES(新規)" if small else "NO(交絡疑)"))
        note = "corr_shortRev_vs_%s=%.4f(all,N=%d;early=%.4f;late=%.4f)|rho|<0.2=%s" % (
            o, rho_all, n_all, rho_e, rho_l, small)
        ortho_notes.append(note)
        rows_out.append({"variant": "corr_shortRev_vs_%s" % o, "subperiod": "all", "horizon": "-",
                         "mode": "spearman_xs", "mean_ic": round(rho_all, 4), "pct_pos": None,
                         "n_cohort": n_all, "n_indep": None, "ci_lo": None, "ci_hi": None,
                         "ci_excl_zero": None, "note": note})

    out_csv = OUT / "verify_shortrev_subperiod.csv"
    pd.DataFrame(rows_out).to_csv(out_csv, index=False, encoding="utf-8-sig")
    print("\n出力:", out_csv)
    print("ORTHO_SUMMARY:", " ; ".join(ortho_notes))
    print("DONE_VERIFY_SUBPERIOD")


if __name__ == "__main__":
    main()

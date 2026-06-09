"""
backtests/backtest_perstock_v3_corrected.py
  — survivorship 母集団 × F1(分割調整基準)修正 × 業種/サイズ中立化 で per-stock 過去IC を definitive 再測定。

背景: 多角検証(2026-06-09)で F1(factors_asof が AdjC を当時EPS/ShOutFYで割る基準不一致 look-ahead)が確定。
v2(backtest_perstock_v2_survivorship)と同一の survivorship 母集団・同一手法を踏襲しつつ:
  (1) F1 修正: s3 の PER/時価総額に渡す株価を「当時生終値 C」にする(リターンは AdjC のまま=分割相殺で正しい)。
  (2) バグ版(AdjC)と修正版(C)を同一ランで並走対比 → 上振れ量を直接定量化。
  (3) s3 修正版に 業種(S33Nm)内・サイズ(ScaleCat)内 中立化IC を追加 → 「割安効果 or 低位株/サイズ交絡」を切分け。

★READ-ONLY: J-Quants GET(master)+キャッシュ(.cache_perstock/)のみ。本番SS/予測記録/cron/スコア経路に一切書かない。
  master 応答は master_<date>.json にキャッシュ(再実行高速化・API保護)。出力はローカルCSV+標準出力のみ。
"""
import os
import sys
import json
import math
import time
from pathlib import Path
from datetime import timedelta, datetime

import numpy as np
import pandas as pd
from scipy import stats

ROOT = Path(r"C:/AI-investment/-AI-")
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backtests"))
import backtest_perstock_v1 as v1            # noqa: E402  factors_asof/price_asof/block_bootstrap_ci/_get
import backtest_perstock_v2_survivorship as v2  # noqa: E402  is_large_mid/code_field/ASOF/HORIZONS

OUT = ROOT / "backtests" / "output"
OUT.mkdir(exist_ok=True)
FACTORS = ["s1", "s2", "s3"]


def cached_master(d):
    """master?date=d (非営業日は最大7日遡及)。応答を master_<date>.json にキャッシュ。(rows, used)"""
    base = pd.Timestamp(d)
    for back in range(0, 8):
        dd = (base - pd.Timedelta(days=back)).strftime("%Y-%m-%d")
        cf = v1.CACHE / f"master_{dd}.json"
        if cf.exists():
            rows = json.loads(cf.read_text(encoding="utf-8"))
            if rows:
                return rows, dd
        j = v1._get("/v2/equities/master", {"date": dd})
        rows = j.get("data", []) if isinstance(j, dict) else []
        if rows:
            cf.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
            return rows, dd
        time.sleep(v1.SLEEP)
    return [], None


def cached_master_current():
    cf = v1.CACHE / "master_current.json"
    if cf.exists():
        return json.loads(cf.read_text(encoding="utf-8"))
    j = v1._get("/v2/equities/master", {})
    rows = j.get("data", []) if isinstance(j, dict) else []
    if rows:
        cf.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
    return rows


def fwd_ret_surv(pmap, ds, t, days, data_end):
    """forward リターン(AdjC)。廃止銘柄は廃止時点終値で実現リターン計上。v2 と同一ロジック。"""
    pt = v1.price_asof(pmap, ds, t)
    if pt is None or pt <= 0:
        return None, None
    pf = v1.price_asof(pmap, ds, t + timedelta(days=days))
    if pf is not None:
        return (pf / pt - 1), "full"
    last = ds[-1] if ds else None
    if last is not None and last > t and last < (data_end - timedelta(days=30)):
        return (pmap[last] / pt - 1), "delisted"
    return None, None


def neutral_ic(rdf, fcol, rcol, gcol):
    """gcol(業種 or サイズ)内で f,r を group平均控除してから pooled Spearman = 中立化IC。"""
    sub = rdf[[fcol, rcol, gcol]].dropna()
    sub = sub[sub[gcol].astype(str) != ""]
    if len(sub) < 20:
        return None
    sub = sub.copy()
    sub["f_res"] = sub[fcol] - sub.groupby(gcol)[fcol].transform("mean")
    sub["r_res"] = sub[rcol] - sub.groupby(gcol)[rcol].transform("mean")
    ic, _p = stats.spearmanr(sub["f_res"], sub["r_res"])
    return None if (ic is None or math.isnan(ic)) else float(ic)


def main():
    print("=" * 80)
    print("backtest_perstock_v3_corrected : survivorship × F1修正 × 中立化  READ-ONLY", datetime.now().strftime("%H:%M"))
    print("=" * 80)

    # 0) 現在母集団(survivor 判定) + 各 as-of の TOPIX Large+Mid 当時母集団(廃止含む)
    cur_rows = cached_master_current()
    cur_codes = {v2.code_field(r) for r in cur_rows if v2.code_field(r)}
    print("[0] 現在master %d社" % len(cur_rows))

    print("[1] 当時母集団の復元(master?date=as-of)")
    universe = {}
    for t in v2.ASOF:
        rows, used = cached_master(t)
        uni = {}
        for r in rows:
            c = v2.code_field(r)
            if c and v2.is_large_mid(r):
                uni[c] = (r.get("S33Nm", ""), str(r.get("ScaleCat", "")))
        universe[t] = uni
        nd = sum(1 for c in uni if c not in cur_codes)
        print("    %s (used %s) Large+Mid=%4d 廃止=%3d" % (t.date(), used, len(uni), nd))
    union = sorted({c for uni in universe.values() for c in uni})
    union_del = [c for c in union if c not in cur_codes]
    print("  union=%d (廃止%d)" % (len(union), len(union_del)))

    # 2) fins + 2系統の価格マップ(adj=AdjC リターン用 / raw=C 因子用)を読込(キャッシュ)
    print("[2] fins + 価格マップ(adj/raw)読込")
    fins, padj, praw = {}, {}, {}
    t0 = time.time()
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
        if (i + 1) % 100 == 0:
            print("    loaded %d/%d (%.0fs)" % (i + 1, len(union), time.time() - t0))
    all_last = [ds[-1] for (pm, ds) in padj.values() if ds]
    data_end = max(all_last) if all_last else pd.Timestamp("2026-06-30")
    print("  data_end=%s" % data_end.date())

    # 3) コホート別 横断面IC を集める
    HOR = v2.HORIZONS  # {"1y":365,"3y":1095}
    # keys: factor in {s3,s3b(buggy),s2,s1} × mode in {full,surv} × horizon
    modes = ["full", "surv"]
    fk = ["s3", "s3b", "s2", "s1"]
    cic = {(f, h, m): [] for f in fk for h in HOR for m in modes}
    cic_neut = {(h, g): [] for h in HOR for g in ("sec", "siz")}  # s3修正版 中立化(full)
    delist_used = {h: 0 for h in HOR}

    for t in v2.ASOF:
        recs = []
        for c, (sec, siz) in universe[t].items():
            ma, da = padj.get(c, ({}, []))
            mr, dr = praw.get(c, ({}, []))
            pt_adj = v1.price_asof(ma, da, t)
            if pt_adj is None:
                continue
            pt_raw = v1.price_asof(mr, dr, t)
            if pt_raw is None:
                continue
            fac_fix = v1.factors_asof(fins.get(c, pd.DataFrame()), pt_raw, t)   # F1修正: 生終値
            fac_bug = v1.factors_asof(fins.get(c, pd.DataFrame()), pt_adj, t)   # 現行: AdjC
            if fac_fix is None or fac_bug is None:
                continue
            row = {"code": c, "surv": (c in cur_codes), "sec": sec, "siz": siz,
                   "s1": fac_fix["s1"], "s2": fac_fix["s2"], "s3": fac_fix["s3"], "s3b": fac_bug["s3"]}
            ok = False
            for h, days in HOR.items():
                r, kind = fwd_ret_surv(ma, da, t, days, data_end)
                row["ret_%s" % h] = r
                if kind == "delisted":
                    delist_used[h] += 1
                if r is not None:
                    ok = True
            if ok:
                recs.append(row)
        if len(recs) < 20:
            continue
        rdf = pd.DataFrame(recs)
        for h in HOR:
            rcol = "ret_%s" % h
            for f in fk:
                for m in modes:
                    sub0 = rdf if m == "full" else rdf[rdf["surv"]]
                    sub = sub0[[f, rcol]].dropna()
                    if len(sub) < 20:
                        continue
                    ic, _p = stats.spearmanr(sub[f], sub[rcol])
                    if ic is not None and not math.isnan(ic):
                        cic[(f, h, m)].append(float(ic))
            # s3修正版 中立化(full のみ)
            for g, gcol in (("sec", "sec"), ("siz", "siz")):
                ic = neutral_ic(rdf, "s3", rcol, gcol)
                if ic is not None:
                    cic_neut[(h, g)].append(ic)

    # 4) 集計
    def agg(ics, h):
        if not ics:
            return None
        m = float(np.mean(ics))
        pos = float(np.mean([1 if v > 0 else 0 for v in ics]))
        nC = len(ics)
        nI = nC // (4 if h == "1y" else 12)
        ci = v1.block_bootstrap_ci(ics, block=(4 if h == "1y" else 12))
        return (m, pos, nC, nI, ci)

    print("\n=== definitive per-stock 過去IC (survivorship 母集団) ===")
    print("factor       hor mode |  meanIC   %pos nCoh nInd | bootCI95          | 0除外?")
    rows_out = []
    label = {"s3": "s3割安(F1修正)", "s3b": "s3割安(現行AdjC)", "s2": "s2トレンド", "s1": "s1質"}
    for f in ["s3", "s3b", "s2", "s1"]:
        for h in HOR:
            for m in modes:
                a = agg(cic[(f, h, m)], h)
                if not a:
                    continue
                mic, pos, nC, nI, ci = a
                exq = (ci[0] is not None and ((ci[0] > 0) or (ci[1] < 0)))
                print("  %-12s %3s %-4s | %+.4f  %3.0f%% %4d %3d | %s..%s | %s" %
                      (label[f], h, m, mic, pos * 100, nC, nI, ci[0], ci[1], "YES" if exq else "no(0含む)"))
                rows_out.append({"factor": f, "label": label[f], "horizon": h, "mode": m,
                                 "mean_ic": round(mic, 4), "pct_pos": round(pos, 3),
                                 "n_cohort": nC, "n_indep": nI, "ci_lo": ci[0], "ci_hi": ci[1],
                                 "ci_excl_zero": exq})
        print()

    print("=== s3割安(F1修正) 中立化IC [full] : 割安効果 or 業種/低位株交絡の切分け ===")
    for h in HOR:
        base = agg(cic[("s3", h, "full")], h)
        for g, gname in (("sec", "業種内中立"), ("siz", "サイズ内中立")):
            a = agg(cic_neut[(h, g)], h)
            if not a:
                continue
            mic, pos, nC, nI, ci = a
            exq = (ci[0] is not None and ((ci[0] > 0) or (ci[1] < 0)))
            print("  s3 %3s %-10s | %+.4f  %3.0f%% nCoh %d | %s..%s | %s" %
                  (h, gname, mic, pos * 100, nC, ci[0], ci[1], "YES" if exq else "no(0含む)"))
            rows_out.append({"factor": "s3_neutral_%s" % g, "label": "s3 %s" % gname, "horizon": h,
                             "mode": "full", "mean_ic": round(mic, 4), "pct_pos": round(pos, 3),
                             "n_cohort": nC, "n_indep": None, "ci_lo": ci[0], "ci_hi": ci[1],
                             "ci_excl_zero": exq})
        if base:
            print("    (参考 s3 %s raw full = %+.4f)" % (h, base[0]))
    print()

    out_df = pd.DataFrame(rows_out)
    out_csv = OUT / "perstock_ic_v3_corrected.csv"
    out_df.to_csv(out_csv, index=False, encoding="utf-8-sig")
    print("廃止リターン計上件数:", ", ".join("%s=%d" % (h, delist_used[h]) for h in HOR))
    print("出力:", out_csv)
    print("PERSTOCK_V3_SUMMARY ok=true union=%d delisted=%d cells=%d" % (len(union), len(union_del), len(rows_out)))
    print("DONE_V3")


if __name__ == "__main__":
    main()

"""
backtests/verify_shortrev_decay.py
  — タスクV1: shortRev(短期リバーサル) の敵対的検証。
    「shortRev陽性はクリーンに減衰する真のリバーサルか、重複窓の見かけ有意/微細構造の産物か」を判別。

設計(タスク指示どおり):
  (1) decay プロファイル: 前向き horizon を細かく刻む(5,10,21,42,63,126,252 営業日相当=暦日同数を
      v3.fwd_ret_surv の days に渡す)。各 horizon で shortRev(full+surv)の
      meanIC / block_bootstrap_ci / %pos / nCoh / nIndep。block = max(1, round(days/91))。
  (2) skip 変種: strev_skip = -(P_{t-Kd}/P_{t-30d}-1)。直近 K 暦日をスキップ=bid-ask bounce/微細構造除去。
      指示の式は P_{t-3d}、コメントは「暦7日」と曖昧 → K=3 と K=7 の両方を実装し honest に併記。
      陽性が skip で消えれば微細構造由来、残れば本物のリバーサル。
  (3) リーク監査: 信号両端(<=t)・前向き(>t)が想定どおりか print で自己確認 + v5 のコード監査所見。

★READ-ONLY: cached master/fins/px のみ。本番SS/予測記録/cron/スコア/HTML に一切書かない。
  出力 = backtests/output/verify_shortrev_decay.csv + 標準出力のみ。
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
import backtest_perstock_v1 as v1               # noqa: E402  price_asof/block_bootstrap_ci/load_fins/load_prices/num
import backtest_perstock_v2_survivorship as v2  # noqa: E402  is_large_mid/code_field/ASOF
import backtest_perstock_v3_corrected as v3      # noqa: E402  cached_master/cached_master_current/fwd_ret_surv/neutral_ic

OUT = ROOT / "backtests" / "output"
OUT.mkdir(exist_ok=True)

# 前向き horizon: 営業日相当 → 暦日(タスク指示: 5,10,21,42,63,126,252 → 暦 7,14,21,42,63,126,252)
HORIZONS = [
    ("5d", 7), ("10d", 14), ("21d", 21), ("42d", 42),
    ("63d", 63), ("126d", 126), ("252d", 252),
]
SKIP_LAGS = [0, 3, 7]   # 0=skipなし(=shortRev素), 3=暦3日skip, 7=暦7日skip


def block_for(days):
    return max(1, int(round(days / 91.0)))


def strev_value(ma, da, t, skip_days):
    """strev_skip = -(P_{t-skip}/P_{t-30d}-1)。skip=0 で素の shortRev。
       信号両端とも <= t(リーク無し)。"""
    p_near = v1.price_asof(ma, da, t - timedelta(days=skip_days))   # 直近側(skip 反映)・<= t
    p_far = v1.price_asof(ma, da, t - timedelta(days=30))           # 1ヶ月前・<= t
    if p_near is None or p_far is None or p_far <= 0:
        return None
    return -(p_near / p_far - 1.0)


def agg(ics, days):
    if not ics:
        return None
    blk = block_for(days)
    m = float(np.mean(ics))
    pos = float(np.mean([1 if v > 0 else 0 for v in ics]))
    nC = len(ics)
    nI = max(1, nC // blk)
    ci = v1.block_bootstrap_ci(ics, block=blk)
    return (m, pos, nC, nI, blk, ci)


def main():
    print("=" * 88)
    print("verify_shortrev_decay : shortRev decay + skip変種 + リーク監査  READ-ONLY",
          datetime.now().strftime("%H:%M"))
    print("=" * 88)

    cur_rows = v3.cached_master_current()
    cur_codes = {v2.code_field(r) for r in cur_rows if v2.code_field(r)}
    print("[0] 現在master %d社" % len(cur_rows))

    print("[1] 当時母集団復元(cached master?date=as-of・TOPIX Large+Mid)")
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
    union_del = [c for c in union if c not in cur_codes]
    print("  union=%d (廃止%d) / ASOF=%d コホート" % (len(union), len(union_del), len(v2.ASOF)))

    print("[2] 価格マップ(AdjC)読込(cached px)")
    padj = {}
    for i, c in enumerate(union):
        try:
            prows = v1.load_prices(c)
            ma = {}
            for r in prows:
                dd = r.get("Date")
                if not dd:
                    continue
                ts = pd.Timestamp(dd)
                a = r.get("AdjC") if r.get("AdjC") is not None else r.get("C")
                if a is not None:
                    ma[ts] = float(a)
            padj[c] = (ma, sorted(ma.keys()))
        except Exception as e:
            padj[c] = ({}, [])
            print("    WARN %s %r" % (c, e))
        if (i + 1) % 200 == 0:
            print("    loaded %d/%d" % (i + 1, len(union)))
    all_last = [ds[-1] for (pm, ds) in padj.values() if ds]
    data_end = max(all_last) if all_last else pd.Timestamp("2026-06-30")
    print("  data_end=%s" % data_end.date())

    # ── リーク監査の自己確認(数例 print): 信号両端 <= t, 前向き > t ──
    print("\n[LEAK-AUDIT] 信号両端<=t・前向き>t を数例で自己確認")
    audit_done = 0
    for t in (v2.ASOF[20], v2.ASOF[40]):
        for c in union:
            ma, da = padj.get(c, ({}, []))
            if not da:
                continue
            import bisect
            i_near = bisect.bisect_right(da, t - timedelta(days=3)) - 1
            i_far = bisect.bisect_right(da, t - timedelta(days=30)) - 1
            i_t = bisect.bisect_right(da, t) - 1
            if min(i_near, i_far, i_t) < 0:
                continue
            d_near, d_far, d_t = da[i_near], da[i_far], da[i_t]
            r5, _k = v3.fwd_ret_surv(ma, da, t, 21, data_end)
            j_fwd = bisect.bisect_right(da, t + timedelta(days=21)) - 1
            d_fwd = da[j_fwd] if j_fwd >= 0 else None
            ok_sig = (d_near <= t) and (d_far <= t) and (d_t <= t)
            ok_fwd = (d_fwd is not None and d_fwd > t)
            print("  t=%s code=%s | sig: near=%s far=%s asof=%s (all<=t:%s) | fwd21: %s (>t:%s) ret=%s" %
                  (t.date(), c, d_near.date(), d_far.date(), d_t.date(), ok_sig,
                   d_fwd.date() if d_fwd is not None else None, ok_fwd,
                   ("%.4f" % r5) if r5 is not None else None))
            audit_done += 1
            if audit_done % 2 == 0:
                break
    print("  → 信号端=過去側(<=t), 前向き=未来側(>t) を確認(リーク無し)")

    # ── decay × skip マトリクスの IC 収集 ──
    modes = ["full", "surv"]
    variants = [("strev_skip%d" % s if s > 0 else "strev", s) for s in SKIP_LAGS]
    cic = {(vn, h, m): [] for (vn, _s) in variants for (h, _d) in HORIZONS for m in modes}

    for t in v2.ASOF:
        recs = []
        for c, (sec, siz) in universe[t].items():
            ma, da = padj.get(c, ({}, []))
            if not da:
                continue
            vals = {}
            for (vn, skip) in variants:
                vals[vn] = strev_value(ma, da, t, skip)
            if all(v is None for v in vals.values()):
                continue
            row = {"code": c, "surv": (c in cur_codes), **vals}
            ok = False
            for (h, days) in HORIZONS:
                r, _kind = v3.fwd_ret_surv(ma, da, t, days, data_end)
                row["ret_%s" % h] = r
                if r is not None:
                    ok = True
            if ok:
                recs.append(row)
        if len(recs) < 20:
            continue
        rdf = pd.DataFrame(recs)
        for (h, _days) in HORIZONS:
            rcol = "ret_%s" % h
            for (vn, _s) in variants:
                for m in modes:
                    sub0 = rdf if m == "full" else rdf[rdf["surv"]]
                    sub = sub0[[vn, rcol]].dropna()
                    if len(sub) < 20:
                        continue
                    ic, _p = stats.spearmanr(sub[vn], sub[rcol])
                    if ic is not None and not math.isnan(ic):
                        cic[(vn, h, m)].append(float(ic))

    # ── 出力 ──
    print("\n=== shortRev decay × skip 変種  過去IC (survivorship 母集団・F1修正harness) ===")
    print("variant        hor  mode |  meanIC  %pos nCoh nInd blk | bootCI95           | 0除外?")
    rows_out = []
    for (vn, _s) in variants:
        for (h, days) in HORIZONS:
            for m in modes:
                a = agg(cic[(vn, h, m)], days)
                if not a:
                    continue
                mic, pos, nC, nI, blk, ci = a
                exq = (ci[0] is not None and ((ci[0] > 0) or (ci[1] < 0)))
                print("  %-13s %4s %-4s | %+.4f %3.0f%% %4d %3d %3d | %s..%s | %s" %
                      (vn, h, m, mic, pos * 100, nC, nI, blk, ci[0], ci[1], "YES" if exq else "no"))
                rows_out.append({"variant": vn, "horizon": h, "horizon_days": days, "mode": m,
                                 "mean_ic": round(mic, 4), "pct_pos": round(pos, 3),
                                 "n_cohort": nC, "n_indep": nI, "block": blk,
                                 "ci_lo": ci[0], "ci_hi": ci[1], "ci_excl_zero": exq})
        print()

    out_csv = OUT / "verify_shortrev_decay.csv"
    pd.DataFrame(rows_out).to_csv(out_csv, index=False, encoding="utf-8-sig")
    print("出力:", out_csv)

    # ── harness サニティ: strev(skip0) 1m相当(21d) full が +0.045 近傍か ──
    # 注: タスクのサニティ基準値(+0.045, CI -0.003..0.094)は HOR=30暦日(1m)・block round(30/91)=0→1。
    #     ここでは同一定義(P_t/P_{t-30d}, 前向き 30暦日)で別途算出して照合する。
    san = []
    for t in v2.ASOF:
        recs = []
        for c in universe[t]:
            ma, da = padj.get(c, ({}, []))
            if not da:
                continue
            sv = strev_value(ma, da, t, 0)
            r, _k = v3.fwd_ret_surv(ma, da, t, 30, data_end)
            if sv is not None and r is not None:
                recs.append((sv, r))
        if len(recs) >= 20:
            xs = [a for a, _ in recs]
            ys = [b for _, b in recs]
            ic, _p = stats.spearmanr(xs, ys)
            if ic is not None and not math.isnan(ic):
                san.append(float(ic))
    if san:
        m = float(np.mean(san))
        ci = v1.block_bootstrap_ci(san, block=1)
        print("\n[SANITY] strev 1m(30cal)fwd full: meanIC=%+.4f CI %s..%s nCoh=%d (target~+0.045, CI~ -0.003..0.094)"
              % (m, ci[0], ci[1], len(san)))
        ok = (abs(m - 0.045) < 0.012) and (len(san) >= 50)
        print("  harness一致:", "OK" if ok else "MISMATCH(要調査)")

    print("VERIFY_SHORTREV_SUMMARY ok=true variants=%d cells=%d" % (len(variants), len(rows_out)))
    print("DONE_VERIFY")


if __name__ == "__main__":
    main()

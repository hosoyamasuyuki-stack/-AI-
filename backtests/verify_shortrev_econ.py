"""
backtests/verify_shortrev_econ.py
  — タスクV3: shortRev(-1m) の経済的大きさ(コスト後に使えるか)の敵対的検証 (2026-06-09)。

目的: 短期リバーサル因子 shortRev=-(P_t/P_{t-1m}-1) の 1m前向きIC≈+0.045 が、
  実際に商品の精度/リターンを改善する「経済的に意味のある大きさ」か、回転コストで消えるかを判定。

★READ-ONLY: master/fins/px の cached のみ。本番SS/予測記録/cron/スコア経路に一切書かない。
  出力=ローカルCSV+標準出力のみ。観測値のみ。git push/dispatch 禁止。

設計(タスク指示どおり):
  1. 四半期リバランスの Q5-Q1 ロングショート(等加重)。各 ASOF t で当時母集団(large/mid)を
     shortRev で5分位。最上位分位=ロング・最下位分位=ショート。保有=次ASOFまで(1四半期)。
     実現四半期リターン=fwd_ret_surv(ma,da,t,91,data_end)。
     四半期スプレッド = 上位分位平均ret − 下位分位平均ret。全t平均×4=gross年率スプレッド。block CI も。
  2. 回転率: 連続2 ASOF で 上位/下位分位の銘柄集合の入替率
     one-way turnover = 1 - |今回∩前回|/|分位サイズ|。平均。年間 turnover ≈ 4×(往復) を別途計算。
  3. コスト後: 片道コスト c ∈ {10,25,40} bps。
     net年率 = gross − (年間往復回転)×c×2(ロング+ショート両足)。各cで net と survives(>0)。
  4. 参考: 上位分位の 対 等加重ユニバース 超過(=ロングオンリー実装) も年率で。

★ harness サニティ: 「shortRev の 1m前向きIC(full,56コホート)」が meanIC≈+0.045
  (CI≈ -0.003..0.094) を再現できることをまず確認。再現できなければ STOP。
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
import backtest_perstock_v1 as v1                # noqa: E402
import backtest_perstock_v2_survivorship as v2   # noqa: E402
import backtest_perstock_v3_corrected as v3       # noqa: E402

OUT = ROOT / "backtests" / "output"
OUT.mkdir(exist_ok=True)

NQ = 5                # 5分位
HOLD_DAYS = 91        # 保有1四半期=次ASOFまで(実現リターン窓)
COST_BPS = [10, 25, 40]   # 片道コスト(bps)候補


def strev_asof(ma, da, t):
    """shortRev = -(P_t / P_{t-1m} - 1)。価格マップ(AdjC)から。"""
    pt = v1.price_asof(ma, da, t)
    p_1m = v1.price_asof(ma, da, t - timedelta(days=30))
    if pt and p_1m and p_1m > 0:
        return -(pt / p_1m - 1)
    return None


def main():
    print("=" * 80)
    print("verify_shortrev_econ : shortRev 経済的大きさ(コスト後) READ-ONLY",
          datetime.now().strftime("%H:%M"))
    print("=" * 80)

    cur_rows = v3.cached_master_current()
    cur_codes = {v2.code_field(r) for r in cur_rows if v2.code_field(r)}
    print("[0] 現在master %d社" % len(cur_rows))

    print("[1] 当時母集団復元(master cached・large/mid)")
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

    print("[2] 価格マップ(AdjC)読込")
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

    # ---- harness サニティ: shortRev 1m前向きIC(full,56コホート) ----
    print("\n[サニティ] shortRev 1m前向きIC (full)")
    sane_ics = []
    for t in v2.ASOF:
        recs = []
        for c in universe[t]:
            ma, da = padj.get(c, ({}, []))
            if not da:
                continue
            sv = strev_asof(ma, da, t)
            r1m, _ = v3.fwd_ret_surv(ma, da, t, 30, data_end)
            if sv is not None and r1m is not None:
                recs.append((sv, r1m))
        if len(recs) < 20:
            continue
        arr = pd.DataFrame(recs, columns=["f", "r"])
        ic, _p = stats.spearmanr(arr["f"], arr["r"])
        if ic is not None and not math.isnan(ic):
            sane_ics.append(float(ic))
    sane_mean = float(np.mean(sane_ics)) if sane_ics else None
    sane_ci = v1.block_bootstrap_ci(sane_ics, block=1)
    print("  meanIC=%+.4f nCoh=%d CI=%s..%s (期待 ≈+0.045 / CI≈-0.003..0.094)" %
          (sane_mean, len(sane_ics), sane_ci[0], sane_ci[1]))
    sane_ok = (sane_mean is not None and 0.030 <= sane_mean <= 0.060 and len(sane_ics) >= 50)
    if not sane_ok:
        print("  !! HARNESS不一致 (meanIC=%s nCoh=%d) — STOP。誤った変種で結論を出さない。" %
              (sane_mean, len(sane_ics)))
        print("HARNESS_MISMATCH=true")
        print("DONE_ECON")
        return
    print("  harness OK ✔ (再現)")

    # ---- 四半期 Q5-Q1 ロングショート(等加重) ----
    print("\n[3] 四半期 Q5-Q1 ロングショート(等加重・保有1四半期)")
    asof_sorted = list(v2.ASOF)
    q_spreads = []           # 各 t の四半期スプレッド(top平均 - bot平均)
    long_xs = []             # ロングオンリー: top平均 - ユニバース等加重平均
    top_sets = []            # 各 t の(t, top銘柄集合)
    bot_sets = []
    qsize_top = []
    qsize_bot = []
    for t in asof_sorted:
        recs = []
        for c in universe[t]:
            ma, da = padj.get(c, ({}, []))
            if not da:
                continue
            sv = strev_asof(ma, da, t)
            if sv is None:
                continue
            r91, _ = v3.fwd_ret_surv(ma, da, t, HOLD_DAYS, data_end)
            if r91 is None:
                continue
            recs.append({"code": c, "f": sv, "r": r91})
        if len(recs) < NQ * 4:   # 各分位 >=4 銘柄を確保
            continue
        df = pd.DataFrame(recs)
        # shortRev 昇順で5分位。最上位分位(高shortRev=直近負け組=ロング)。
        try:
            df["q"] = pd.qcut(df["f"].rank(method="first"), NQ, labels=False)
        except Exception:
            continue
        top = df[df["q"] == NQ - 1]   # 高 shortRev
        bot = df[df["q"] == 0]        # 低 shortRev
        if len(top) < 4 or len(bot) < 4:
            continue
        top_r = float(top["r"].mean())
        bot_r = float(bot["r"].mean())
        uni_r = float(df["r"].mean())
        q_spreads.append(top_r - bot_r)
        long_xs.append(top_r - uni_r)
        top_sets.append((t, set(top["code"])))
        bot_sets.append((t, set(bot["code"])))
        qsize_top.append(len(top))
        qsize_bot.append(len(bot))

    nq = len(q_spreads)
    q_mean = float(np.mean(q_spreads)) if q_spreads else float("nan")
    gross_annual = q_mean * 4.0
    # 四半期スプレッドの block CI(ブロック=1: 四半期は前向き保有窓が概ね非重複) → 年率化
    q_ci = v1.block_bootstrap_ci(q_spreads, block=1)
    gross_ci = (None if q_ci[0] is None else round(q_ci[0] * 4.0, 4),
                None if q_ci[1] is None else round(q_ci[1] * 4.0, 4))
    long_mean = float(np.mean(long_xs)) if long_xs else float("nan")
    longonly_annual = long_mean * 4.0
    long_ci = v1.block_bootstrap_ci(long_xs, block=1)
    longonly_ci = (None if long_ci[0] is None else round(long_ci[0] * 4.0, 4),
                   None if long_ci[1] is None else round(long_ci[1] * 4.0, 4))
    print("  nQuarters=%d  avg分位サイズ top≈%.0f bot≈%.0f" %
          (nq, np.mean(qsize_top) if qsize_top else 0, np.mean(qsize_bot) if qsize_bot else 0))
    print("  四半期スプレッド平均=%+.4f (=%.2f%%/Q)  → gross年率=%+.4f (=%.2f%%) CI95 %s..%s" %
          (q_mean, q_mean * 100, gross_annual, gross_annual * 100, gross_ci[0], gross_ci[1]))
    print("  ロングオンリー(top−ユニバース)四半期=%+.4f → 年率=%+.4f (=%.2f%%) CI95 %s..%s" %
          (long_mean, longonly_annual, longonly_annual * 100, longonly_ci[0], longonly_ci[1]))

    # ---- 回転率(one-way turnover) ----
    print("\n[4] 回転率 (one-way turnover = 1 - |今∩前|/|分位|)")

    def avg_turnover(sets):
        tos = []
        for i in range(1, len(sets)):
            (_, cur), (_, prev) = sets[i], sets[i - 1]
            if not cur:
                continue
            inter = len(cur & prev)
            tos.append(1.0 - inter / float(len(cur)))
        return float(np.mean(tos)) if tos else float("nan")

    to_top = avg_turnover(top_sets)
    to_bot = avg_turnover(bot_sets)
    oneway_q = float(np.nanmean([to_top, to_bot]))   # 1足あたり片道四半期回転(top/bot平均)
    # 年間往復回転(1足分): 四半期×4回リバランス、各回 one-way→「売って買う」往復=2×one-way。
    # ロングショート両足は net式側で ×2 して反映するので、ここは「片足あたり年間往復回転数」を定義。
    annual_roundtrip_per_leg = oneway_q * 4.0 * 2.0
    print("  片道四半期 turnover: top=%.3f bot=%.3f → 平均 one-way/Q=%.3f" % (to_top, to_bot, oneway_q))
    print("  年間往復回転(片足) = one-way/Q × 4リバランス × 2(往復) = %.2f 回転/年" %
          annual_roundtrip_per_leg)

    # ---- コスト後 net 年率 ----
    print("\n[5] コスト後 net 年率スプレッド (ロングショート=両足課金)")
    print("  net = gross − (年間往復回転/足) × c × 2足")
    rows_out = []
    net_by_cost = {}
    for cb in COST_BPS:
        c = cb / 10000.0
        cost_drag = annual_roundtrip_per_leg * c * 2.0   # ×2足(ロング+ショート)
        net = gross_annual - cost_drag
        survives = bool(net > 0)
        net_by_cost[cb] = net
        print("  c=%2dbps  costDrag年=%+.4f (%.2f%%)  net年率=%+.4f (%.2f%%)  survives=%s" %
              (cb, cost_drag, cost_drag * 100, net, net * 100, survives))
        rows_out.append({
            "metric": "longshort_net_annual",
            "cost_bps_oneway": cb,
            "gross_annual_spread": round(gross_annual, 4),
            "annual_cost_drag": round(cost_drag, 4),
            "net_annual_spread": round(net, 4),
            "survives_costs": survives,
            "annual_roundtrip_turnover_per_leg": round(annual_roundtrip_per_leg, 3),
            "n_quarters": nq,
        })

    # ロングオンリー net(片足のみ課金)も参考出力
    print("\n[6] 参考: ロングオンリー net 年率超過 (片足課金)")
    for cb in COST_BPS:
        c = cb / 10000.0
        cost_drag_lo = annual_roundtrip_per_leg * c * 1.0
        net_lo = longonly_annual - cost_drag_lo
        print("  c=%2dbps  net超過年率=%+.4f (%.2f%%) survives=%s" %
              (cb, net_lo, net_lo * 100, bool(net_lo > 0)))
        rows_out.append({
            "metric": "longonly_net_excess_annual",
            "cost_bps_oneway": cb,
            "gross_annual_spread": round(longonly_annual, 4),
            "annual_cost_drag": round(cost_drag_lo, 4),
            "net_annual_spread": round(net_lo, 4),
            "survives_costs": bool(net_lo > 0),
            "annual_roundtrip_turnover_per_leg": round(annual_roundtrip_per_leg, 3),
            "n_quarters": nq,
        })

    out_csv = OUT / "verify_shortrev_econ.csv"
    pd.DataFrame(rows_out).to_csv(out_csv, index=False, encoding="utf-8-sig")
    print("\n出力:", out_csv)

    # ---- 機械可読サマリ ----
    print("\nECON_SUMMARY "
          "gross_annual=%.4f net25=%.4f turnover_per_leg=%.3f survives25=%s longonly_excess=%.4f "
          "gross_ci_lo=%s gross_ci_hi=%s nQ=%d sane_ic=%.4f" % (
              gross_annual, net_by_cost.get(25, float('nan')), annual_roundtrip_per_leg,
              bool(net_by_cost.get(25, -1) > 0), longonly_annual,
              gross_ci[0], gross_ci[1], nq, sane_mean))
    print("DONE_ECON")


if __name__ == "__main__":
    main()

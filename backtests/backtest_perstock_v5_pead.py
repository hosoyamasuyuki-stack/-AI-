"""
backtests/backtest_perstock_v5_pead.py
  — 新因子 一括IC測定 第2弾 (CEO 指示②「複数因子を一括測定」・2026-06-09)。

F1修正で現行3因子(s1/s2/s3)＋v4の momentum/clean E/P は過去ICが0と区別できないと確定。
本スクリプトは F1修正済クリーン harness(v1/v2/v3)を再利用し、証拠の強い新候補を一括で測る:
  (1) strev  : 短期リバーサル = -(P(t)/P(t-1m)-1)  価格のみ・AdjC比=分割相殺=F1免疫
  (2) lowvol : 低ボラ = -(直近~120営業日 日次リターン標準偏差)  価格のみ
  (3) frev   : 業績予想修正 = 同一目標年度(CurFYEn)内の四半期予想EPS(FEPS)の改定率
               = (FEPS_latest - FEPS_prev)/|FEPS_prev|  DiscDate<=t・正=ガイダンス上方
  (4) esurp  : 決算サプライズ = 本決算の実績EPS vs 同年度の直近会社予想FEPS
               = (EPS_FYactual - FEPS_lastSameFY)/|FEPS_lastSameFY|  DiscDate<=t・正=上振れ

frev/esurp は「予想と実績の比」=無次元ゆえ F1(調整価格÷未調整EPS)の基準不一致バグとは無縁。
DiscDate<=t の PIT・freshness 上限で陳腐化した信号を除外。

★短期信号(strev/frev/esurp)は短horizonで効くため HOR に {1m,3m} を追加。
  四半期ASOFでは短horizonほど独立コホートが多い(1m/3m=ほぼ非重複)=検出力が高い。

★READ-ONLY: master/fins/px の cached のみ。本番SS/予測記録/cron/スコア経路に一切書かない。
  出力=ローカルCSV+標準出力のみ。観測値のみ・本番反映は三重ゲート(N充足∧多重比較補正∧CEO手動)。
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
import backtest_perstock_v1 as v1                # noqa: E402  price_asof/block_bootstrap_ci/load_fins/load_prices/num
import backtest_perstock_v2_survivorship as v2   # noqa: E402  is_large_mid/code_field/ASOF
import backtest_perstock_v3_corrected as v3       # noqa: E402  cached_master/cached_master_current/fwd_ret_surv/neutral_ic

OUT = ROOT / "backtests" / "output"
OUT.mkdir(exist_ok=True)
HOR = {"1m": 30, "3m": 91, "6m": 182, "1y": 365, "3y": 365 * 3}
NEWF = ["strev", "lowvol", "frev", "esurp"]
LABEL = {"strev": "shortRev(-1m)", "lowvol": "lowVol(-sigma)", "frev": "fcstRevision", "esurp": "earnSurprise"}
FRESH_FREV = 200   # 予想修正: 直近FEPS開示が t から200日以内(=~2四半期)なら有効
FRESH_ESURP = 260  # 決算サプライズ: 本決算開示が t から260日以内なら有効(年1回ゆえ広め・陳腐化は限界として明記)


def block_for(days):
    """四半期ASOF(~91日間隔)での重複窓ブロックサイズ。"""
    return max(1, int(round(days / 91.0)))


def pead_factors(raw_rows, t):
    """raw fins rows と as-of t から (frev, esurp) を PIT(DiscDate<=t)で返す。"""
    recs = []
    for r in raw_rows:
        dd = r.get("DiscDate")
        if not dd:
            continue
        try:
            d = pd.Timestamp(dd)
        except Exception:
            continue
        if d > t:
            continue
        recs.append((d, r))
    if not recs:
        return (None, None)
    recs.sort(key=lambda x: x[0])
    # 予想系列: FEPS非null + 目標年度(CurFYEn)
    fc = []
    for d, r in recs:
        feps = v1.num(r.get("FEPS"))
        fy = r.get("CurFYEn")
        if feps is not None and fy:
            fc.append((d, str(fy), feps))
    # frev: 同一目標年度内の直近2予想の改定率
    frev = None
    if len(fc) >= 2:
        d_last, fy_last, f_last = fc[-1]
        if (t - d_last).days <= FRESH_FREV:
            prev = [x for x in fc[:-1] if x[1] == fy_last]
            if prev:
                f_prev = prev[-1][2]
                if abs(f_prev) > 1e-9:
                    frev = (f_last - f_prev) / abs(f_prev)
    # esurp: 直近の本決算(FY actual)実績EPS vs 同年度の直近会社予想FEPS
    esurp = None
    fya = [(d, r) for d, r in recs
           if "FYFinancialStatements" in str(r.get("DocType", "")) and v1.num(r.get("EPS")) is not None]
    if fya:
        d_fy, r_fy = fya[-1]
        if (t - d_fy).days <= FRESH_ESURP:
            fy = r_fy.get("CurFYEn") or r_fy.get("CurPerEn")
            act = v1.num(r_fy.get("EPS"))
            cand = [x for x in fc if x[1] == str(fy) and x[0] < d_fy]
            if cand and act is not None:
                f_last = cand[-1][2]
                if abs(f_last) > 1e-9:
                    esurp = (act - f_last) / abs(f_last)
    return (frev, esurp)


def price_factors(ma, da, t):
    """価格マップ(AdjC)と as-of t から (strev, lowvol) を返す。"""
    pt = v1.price_asof(ma, da, t)
    p_1m = v1.price_asof(ma, da, t - timedelta(days=30))
    strev = -(pt / p_1m - 1) if (pt and p_1m and p_1m > 0) else None
    # lowvol: 直近~180暦日(=~120営業日)の日次リターン標準偏差
    lo = t - timedelta(days=180)
    seq = [ma[d] for d in da if lo <= d <= t]
    lowvol = None
    if len(seq) >= 40:
        arr = np.array(seq, dtype=float)
        rets = arr[1:] / arr[:-1] - 1.0
        rets = rets[np.isfinite(rets)]
        if len(rets) >= 30:
            sd = float(np.std(rets))
            lowvol = -sd
    return (strev, lowvol)


def main():
    print("=" * 80)
    print("backtest_perstock_v5_pead : strev+lowvol+frev+esurp  READ-ONLY", datetime.now().strftime("%H:%M"))
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

    print("[2] raw fins + 価格マップ(adj)読込")
    rawf, padj = {}, {}
    for i, c in enumerate(union):
        try:
            rawf[c] = v1.load_fins(c)
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
            rawf[c] = []
            padj[c] = ({}, [])
            print("    WARN %s %r" % (c, e))
        if (i + 1) % 200 == 0:
            print("    loaded %d/%d" % (i + 1, len(union)))
    all_last = [ds[-1] for (pm, ds) in padj.values() if ds]
    data_end = max(all_last) if all_last else pd.Timestamp("2026-06-30")
    print("  data_end=%s" % data_end.date())

    modes = ["full", "surv"]
    cic = {(f, h, m): [] for f in NEWF for h in HOR for m in modes}
    cic_neut = {(f, h, g): [] for f in NEWF for h in HOR for g in ("sec", "siz")}
    cov = {f: 0 for f in NEWF}      # 非null因子値の総数(被覆確認)
    cov_den = 0

    for t in v2.ASOF:
        recs = []
        for c, (sec, siz) in universe[t].items():
            ma, da = padj.get(c, ({}, []))
            if not da:
                continue
            strev, lowvol = price_factors(ma, da, t)
            frev, esurp = pead_factors(rawf.get(c, []), t)
            vals = {"strev": strev, "lowvol": lowvol, "frev": frev, "esurp": esurp}
            if all(v is None for v in vals.values()):
                continue
            cov_den += 1
            for f in NEWF:
                if vals[f] is not None:
                    cov[f] += 1
            row = {"code": c, "surv": (c in cur_codes), "sec": sec, "siz": siz, **vals}
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

    print("\n[被覆] 因子別 非null銘柄×コホート数 / 母数 %d" % cov_den)
    for f in NEWF:
        print("  %-14s %d (%.0f%%)" % (LABEL[f], cov[f], 100.0 * cov[f] / max(1, cov_den)))

    print("\n=== 新因子 過去IC (survivorship 母集団・F1修正harness) ===")
    print("factor          hor mode |  meanIC   %pos nCoh nInd | bootCI95          | 0除外?")
    rows_out = []
    for f in NEWF:
        for h, days in HOR.items():
            for m in modes:
                a = agg(cic[(f, h, m)], days)
                if not a:
                    continue
                mic, pos, nC, nI, ci = a
                exq = (ci[0] is not None and ((ci[0] > 0) or (ci[1] < 0)))
                print("  %-14s %3s %-4s | %+.4f  %3.0f%% %4d %3d | %s..%s | %s" %
                      (LABEL[f], h, m, mic, pos * 100, nC, nI, ci[0], ci[1], "YES" if exq else "no"))
                rows_out.append({"factor": f, "label": LABEL[f], "horizon": h, "mode": m,
                                 "mean_ic": round(mic, 4), "pct_pos": round(pos, 3),
                                 "n_cohort": nC, "n_indep": nI, "ci_lo": ci[0], "ci_hi": ci[1],
                                 "ci_excl_zero": exq})
        print()

    print("=== 新因子 中立化IC [full] ===")
    for f in NEWF:
        for h, days in HOR.items():
            for g, gn in (("sec", "業種内"), ("siz", "サイズ内")):
                a = agg(cic_neut[(f, h, g)], days)
                if not a:
                    continue
                mic, pos, nC, nI, ci = a
                exq = (ci[0] is not None and ((ci[0] > 0) or (ci[1] < 0)))
                print("  %-14s %3s %-8s | %+.4f  %3.0f%% nCoh %d | %s..%s | %s" %
                      (LABEL[f], h, gn, mic, pos * 100, nC, ci[0], ci[1], "YES" if exq else "no"))
                rows_out.append({"factor": "%s_neutral_%s" % (f, g), "label": "%s %s" % (LABEL[f], gn),
                                 "horizon": h, "mode": "full", "mean_ic": round(mic, 4),
                                 "pct_pos": round(pos, 3), "n_cohort": nC, "n_indep": None,
                                 "ci_lo": ci[0], "ci_hi": ci[1], "ci_excl_zero": exq})
        print()

    out_csv = OUT / "perstock_ic_v5_pead.csv"
    pd.DataFrame(rows_out).to_csv(out_csv, index=False, encoding="utf-8-sig")
    print("出力:", out_csv)
    print("限界: ①PEADはASOF=四半期末から前向き計測=開示日からの drift が一部経過済(過小評価側)。")
    print("      ②esurpは本決算が年1回ゆえ陳腐化しやすい(frevの方が新鮮)。③多重比較=因子追加で検定数増。")
    print("      有意性は全因子横断の補正後のみ・観測値のみ・本番反映は三重ゲート。")
    print("PERSTOCK_V5_SUMMARY ok=true union=%d cells=%d" % (len(union), len(rows_out)))
    print("DONE_V5")


if __name__ == "__main__":
    main()

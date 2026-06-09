"""
backtests/verify_pead_eventtime.py
  — タスクV4: PEAD(frev/esurp)を「イベント時間」で再検証。

背景: v5(backtest_perstock_v5_pead)は ASOF=四半期末を as-of に前向き計測するため、
  開示日から四半期末までに PEAD の drift が一部経過済 → PEAD を過小評価する疑い。
  本スクリプトは「開示日 d 起点」で frev/esurp と前向きリターンを測り直し、
  発表起点なら PEAD が出るか(=現行四半期末計測が取りこぼす精度レバーか)を検証する。

設計:
  1. イベント収集: union 各銘柄 raw fins を走査。各開示日 d を as-of として
     v5.pead_factors(raw, d) を呼び、(code, d, frev_at_d, esurp_at_d) を集める。
     - frev_event: 同一目標年度(CurFYEn)内の直近2予想FEPSの改定率(d 当日改定=新鮮)。
     - esurp_event: 本決算開示日 d の実績EPS vs 同年度直近予想FEPS(最も新鮮なサプライズ)。
     - 重複(同 d で値同じ)は排除。
  2. 前向きリターン(イベント時間): d 起点 = price_asof(d+Δ)/price_asof(d)-1。
     Δ=20/60/120 営業日相当 = 暦 28/84/168 日。AdjC使用(分割相殺)。価格欠損/data_end超は除外。
  3. 横断面IC(四半期バケツ): イベントを d の属する四半期(year-Qn)でまとめ、
     各バケツ内で signal と前向きリターンの Spearman IC。バケツ内 n>=20 のみ。
     block_bootstrap_ci: Δ=20/60 は四半期バケツがほぼ非重複→block=1。
     Δ=120 は隣接四半期と重なる(168日>91日)→block=2。
  4. frev_event/esurp_event 各々 Δ=20/60/120。さらに 上位20%vs下位20% のイベント平均前向き
     リターン差(Δ=60)も参考出力。

判定: イベント時間で CI が0を外す正のIC が出れば「PEADは発表起点で実在=四半期末計測が取りこぼし」。
  出なければ「PEADは大型株では本当に弱い」を確証。

★READ-ONLY: master/fins/px の cached のみ。本番SS/予測記録/cron/スコア経路に一切書かない。
  出力=ローカルCSV(backtests/output/verify_pead_eventtime.csv)+標準出力のみ。
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
import backtest_perstock_v5_pead as v5            # noqa: E402

OUT = ROOT / "backtests" / "output"
OUT.mkdir(exist_ok=True)

# Δ(営業日) → 暦日換算。20/60/120 bd ≈ 28/84/168 cal days。
HOR_CAL = {"20d": 28, "60d": 84, "120d": 168}
# ブロック長: 四半期バケツ間隔=91日。168日窓(120d)のみ隣接Qと重なる → block=2。
HOR_BLOCK = {"20d": 1, "60d": 1, "120d": 2}
SIGNALS = ["frev_event", "esurp_event"]


def quarter_bucket(d):
    """開示日 d を四半期バケツ文字列 'YYYY-Qn' に。"""
    q = (d.month - 1) // 3 + 1
    return "%d-Q%d" % (d.year, q)


def collect_events(rawf, union, universe):
    """各銘柄の各開示日 d を as-of として v5.pead_factors(raw,d) を呼び、
    (code, d, frev, esurp) を集める。重複(同 d で同値)は排除。
    union 銘柄のうち、いずれかの ASOF 母集団に居た銘柄のみ対象(=PIT母集団整合)。"""
    # 母集団: union(全 ASOF 和集合)= PIT で Large+Mid だった銘柄。属性(sec/siz)は最後に居た時の値。
    attr = {}
    for t in v2.ASOF:
        for c, (sec, siz) in universe[t].items():
            attr[c] = (sec, siz)   # 後の t で上書き=最新属性
    events = []
    for c in union:
        raw = rawf.get(c, [])
        if not raw:
            continue
        # この銘柄の全開示日(DiscDate)を昇順・重複排除して走査
        ddates = set()
        for r in raw:
            dd = r.get("DiscDate")
            if not dd:
                continue
            try:
                ddates.add(pd.Timestamp(dd))
            except Exception:
                continue
        sec, siz = attr.get(c, ("", ""))
        seen = {}     # (round(frev),round(esurp)) で同 d 連続重複を弾く(値の重複排除)
        for d in sorted(ddates):
            frev, esurp = v5.pead_factors(raw, d)
            if frev is None and esurp is None:
                continue
            key = (round(frev, 6) if frev is not None else None,
                   round(esurp, 6) if esurp is not None else None)
            # 直前イベントと完全同値(同じ改定/サプライズが連続検出)なら排除
            if seen.get("last") == key:
                continue
            seen["last"] = key
            events.append({"code": c, "d": d, "sec": sec, "siz": siz,
                           "frev_event": frev, "esurp_event": esurp,
                           "qbucket": quarter_bucket(d)})
    return pd.DataFrame(events)


def fwd_ret_event(ma, da, d, cal_days, data_end):
    """d 起点の前向きリターン(AdjC)。d または d+Δ に価格無し/data_end超は None。"""
    p0 = v1.price_asof(ma, da, d)
    if p0 is None or p0 <= 0:
        return None
    target = d + timedelta(days=cal_days)
    if target > data_end:
        return None
    pf = v1.price_asof(ma, da, target)
    if pf is None or pf <= 0:
        return None
    return pf / p0 - 1.0


def agg_ic(ics, block):
    if not ics:
        return None
    m = float(np.mean(ics))
    pos = float(np.mean([1 if v > 0 else 0 for v in ics]))
    nC = len(ics)
    nI = max(1, nC // max(1, block))
    ci = v1.block_bootstrap_ci(ics, block=block)
    return (m, pos, nC, nI, ci)


def main():
    print("=" * 84)
    print("verify_pead_eventtime : PEAD を開示日(イベント時間)起点で再検証  READ-ONLY",
          datetime.now().strftime("%H:%M"))
    print("=" * 84)

    cur_rows = v3.cached_master_current()
    cur_codes = {v2.code_field(r) for r in cur_rows if v2.code_field(r)}
    print("[0] 現在master %d社" % len(cur_rows))

    print("[1] 当時母集団復元(master cached・PIT TOPIX Large+Mid)")
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

    print("[2] raw fins + 価格マップ(adj)読込(cached)")
    rawf, padj = {}, {}
    for i, c in enumerate(union):
        try:
            rawf[c] = v1.load_fins(c)
            ma = {}
            for r in v1.load_prices(c):
                dd = r.get("Date")
                if not dd:
                    continue
                a = r.get("AdjC") if r.get("AdjC") is not None else r.get("C")
                if a is not None:
                    ma[pd.Timestamp(dd)] = float(a)
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

    # ── harness サニティ: shortRev 1m前向きIC(full,56コホート)≈+0.045 を再現 ─────
    print("[サニティ] shortRev 1m前向きIC(full・四半期末ASOF・56コホート)")
    san = []
    for t in v2.ASOF:
        recs = []
        for c, (sec, siz) in universe[t].items():
            ma, da = padj.get(c, ({}, []))
            if not da:
                continue
            pt = v1.price_asof(ma, da, t)
            p1 = v1.price_asof(ma, da, t - timedelta(days=30))
            strev = -(pt / p1 - 1) if (pt and p1 and p1 > 0) else None
            r, _k = v3.fwd_ret_surv(ma, da, t, 30, data_end)
            if strev is not None and r is not None:
                recs.append((strev, r))
        if len(recs) < 20:
            continue
        df = pd.DataFrame(recs, columns=["f", "r"])
        ic, _ = stats.spearmanr(df["f"], df["r"])
        if ic is not None and not math.isnan(ic):
            san.append(float(ic))
    san_m = float(np.mean(san)) if san else float("nan")
    san_ci = v1.block_bootstrap_ci(san, block=1)
    print("  shortRev 1m: meanIC=%.4f nCoh=%d CI=%s..%s" % (san_m, len(san), san_ci[0], san_ci[1]))
    if not (len(san) == 56 and 0.035 <= san_m <= 0.055):
        print("  !!! HARNESS MISMATCH: shortRev sanity 不一致 → STOP(誤った変種で結論を出さない)")
        print("PEAD_EVENTTIME_SUMMARY ok=false reason=harness_mismatch")
        return
    print("  → サニティ PASS(meanIC≈+0.045, nCoh=56)。本検証に進む。")

    # ── 1) イベント収集 ─────────────────────────────────────────
    print("[3] イベント収集(各開示日 d を as-of として frev/esurp)")
    ev = collect_events(rawf, union, universe)
    print("  総イベント数=%d  (frev非null=%d, esurp非null=%d)" %
          (len(ev), int(ev["frev_event"].notna().sum()), int(ev["esurp_event"].notna().sum())))
    if len(ev):
        print("  イベント期間: %s 〜 %s  ユニーク銘柄=%d" %
              (ev["d"].min().date(), ev["d"].max().date(), ev["code"].nunique()))
    ev["surv"] = ev["code"].isin(cur_codes)

    # ── 2) 前向きリターン(イベント時間)を Δ ごとに付与 ──────────────
    print("[4] イベント起点 前向きリターン(AdjC・Δ=20/60/120bd)")
    for h, cal in HOR_CAL.items():
        rets = []
        for _, row in ev.iterrows():
            ma, da = padj.get(row["code"], ({}, []))
            rets.append(fwd_ret_event(ma, da, row["d"], cal, data_end) if da else None)
        ev["ret_%s" % h] = rets

    # ── 3) 横断面IC(四半期バケツ内 Spearman) ───────────────────────
    print("[5] 横断面IC(四半期バケツ内 Spearman・バケツ内 n>=20 のみ)")
    rows_out = []
    cell = {}   # (signal,h) -> list of bucket IC
    for sig in SIGNALS:
        for h in HOR_CAL:
            cell[(sig, h)] = []
    bucket_n = {(sig, h): [] for sig in SIGNALS for h in HOR_CAL}

    for sig in SIGNALS:
        for h in HOR_CAL:
            rcol = "ret_%s" % h
            for qb, g in ev.groupby("qbucket"):
                sub = g[[sig, rcol]].dropna()
                if len(sub) < 20:
                    continue
                ic, _p = stats.spearmanr(sub[sig], sub[rcol])
                if ic is not None and not math.isnan(ic):
                    cell[(sig, h)].append(float(ic))
                    bucket_n[(sig, h)].append(len(sub))

    print("\n=== PEAD イベント時間 横断面IC (四半期バケツ平均) ===")
    print("signal       hor  | meanIC   %pos  nBkt nInd | bootCI95          | 0除外? | medN")
    for sig in SIGNALS:
        for h in HOR_CAL:
            ics = cell[(sig, h)]
            blk = HOR_BLOCK[h]
            a = agg_ic(ics, blk)
            if not a:
                print("  %-12s %-4s | (バケツ<必要数 n>=20 が不足)" % (sig, h))
                rows_out.append({"signal": sig, "horizon": h, "mean_ic": None, "pct_pos": None,
                                 "n_bucket": 0, "n_indep": 0, "ci_lo": None, "ci_hi": None,
                                 "ci_excl_zero": None, "med_bucket_n": None, "block": blk})
                continue
            mic, pos, nB, nI, ci = a
            exq = (ci[0] is not None and ((ci[0] > 0) or (ci[1] < 0)))
            medn = int(np.median(bucket_n[(sig, h)])) if bucket_n[(sig, h)] else 0
            print("  %-12s %-4s | %+.4f  %3.0f%%  %4d %3d | %s..%s | %s | %d" %
                  (sig, h, mic, pos * 100, nB, nI, ci[0], ci[1], "YES" if exq else "no", medn))
            rows_out.append({"signal": sig, "horizon": h, "mean_ic": round(mic, 4),
                             "pct_pos": round(pos, 3), "n_bucket": nB, "n_indep": nI,
                             "ci_lo": ci[0], "ci_hi": ci[1], "ci_excl_zero": exq,
                             "med_bucket_n": medn, "block": blk})
        print()

    # ── 4) 上位20% vs 下位20% の イベント平均前向きリターン差(Δ=60d) ─────
    print("=== 参考: 上位20% vs 下位20% イベント平均前向きリターン差(Δ=60d) ===")
    for sig in SIGNALS:
        sub = ev[[sig, "ret_60d"]].dropna()
        if len(sub) < 50:
            print("  %-12s : n=%d 不足" % (sig, len(sub)))
            continue
        rk = sub[sig].rank(pct=True)
        top = sub[rk >= 0.8]["ret_60d"].mean()
        bot = sub[rk <= 0.2]["ret_60d"].mean()
        spread = top - bot
        print("  %-12s : top20%%=%+.4f  bot20%%=%+.4f  spread(top-bot)=%+.4f  (n=%d)" %
              (sig, top, bot, spread, len(sub)))
        rows_out.append({"signal": "%s_q5q1_60d" % sig, "horizon": "60d",
                         "mean_ic": None, "pct_pos": None, "n_bucket": len(sub), "n_indep": None,
                         "ci_lo": round(float(bot), 4), "ci_hi": round(float(top), 4),
                         "ci_excl_zero": None, "med_bucket_n": round(float(spread), 4), "block": None})

    out_csv = OUT / "verify_pead_eventtime.csv"
    pd.DataFrame(rows_out).to_csv(out_csv, index=False, encoding="utf-8-sig")
    print("\n出力:", out_csv)
    print("限界: ①大型株(TOPIX Large+Mid)のみ=小型株のPEADは別。")
    print("      ②会社予想ベース(アナリストコンセンサスでない)=ガイダンス保守性が交絡。")
    print("      ③四半期バケツは多銘柄プール=独立性は時間方向のバケツ数(nInd)が実質N。")
    print("      ④frevは EarnForecastRevision+四半期短信、esurpは本決算(年1回)=esurpはバケツ数が少なめ。")
    print("PEAD_EVENTTIME_SUMMARY ok=true union=%d events=%d cells=%d" %
          (len(union), len(ev), len(rows_out)))
    print("DONE_PEAD_EVENTTIME")


if __name__ == "__main__":
    main()

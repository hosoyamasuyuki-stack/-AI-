"""
backtests/backtest_perstock_v2_survivorship.py — Phase 1 S2 (生存者バイアス補正IC)

手順書_短期中期per-stock過去分析 §4 Phase1 / 引継ぎ STEP3-P1②。
v1(99銘柄=現在の生存大型株のみ)の survivorship バイアスを補正する:
  各 as-of 四半期で「当時実在した TOPIX Large+Mid(=廃止銘柄を含む当時母集団)」を
  /v2/equities/master?date=as-of で復元し、横断面 Spearman IC を測り直す。
  廃止銘柄は廃止時点の終値で「実現リターン(TOB/倒産含む)」を計上し脱落させない。

★並行で「現存銘柄のみ(code が現在master在籍)」の IC も同一手法で算出し、
  full(補正後) − survivor-only(補正前相当) の差 = 生存者バイアスの大きさを直接対比。
  → CEO の問い「割安(s3)の効きが上振れ除いても残るか」に直接答える。

★READ-ONLY: J-Quants GET のみ。本番SS/予測記録/cron/スコア経路に一切書かない。
  出力はローカルCSV(backtests/output/)のみ。因子ロジックは v1 を import 再利用。

実行:
  python backtests/backtest_perstock_v2_survivorship.py                # 本実行(全件・初回は取得で長時間)
  PERSTOCK_UNIVERSE_ONLY=1 python backtests/...                        # 母集団サイズ確認のみ(取得しない)
"""
import os
import sys
import math
import time
from pathlib import Path
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
from scipy import stats

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backtests"))

# v1 の実証済みロジックを再利用(import 時に main() は走らない=__main__ ガード)
import backtest_perstock_v1 as v1  # noqa: E402

OUT = ROOT / "backtests" / "output"
OUT.mkdir(exist_ok=True)

# TOPIX Large+Mid = Core30 + Large70 + Mid400 (=TOPIX500相当・製品ユニバース相当)
LARGE_MID_KEYS = ("Core30", "Large70", "Mid400")
# as-of 四半期(2012〜2025)。3,6,9,12月末。
ASOF = []
for _y in range(2012, 2026):
    for _m, _d in [(3, 31), (6, 30), (9, 30), (12, 31)]:
        ASOF.append(pd.Timestamp(year=_y, month=_m, day=_d))
HORIZONS = {"1y": 365, "3y": 365 * 3}
FACTORS = ["s1", "s2", "s3"]


def is_large_mid(row):
    sc = str(row.get("ScaleCat", ""))
    return any(k in sc for k in LARGE_MID_KEYS)


def code_field(row):
    for k in ("Code", "code", "LocalCode"):
        if k in row and str(row[k]).strip():
            return str(row[k]).strip()
    return None


def master_asof(d):
    """master?date=d を取得(非営業日は最大7日遡及)。(rows, used_date)"""
    base = pd.Timestamp(d)
    for back in range(0, 8):
        dd = (base - pd.Timedelta(days=back)).strftime("%Y-%m-%d")
        j = v1._get("/v2/equities/master", {"date": dd})
        rows = j.get("data", []) if isinstance(j, dict) else []
        if rows:
            return rows, dd
        time.sleep(v1.SLEEP)
    return [], None


def main():
    universe_only = os.environ.get("PERSTOCK_UNIVERSE_ONLY") == "1"
    print("=" * 76)
    print("backtest_perstock_v2_survivorship  (TOPIX Large+Mid 当時母集団・廃止含む)")
    print("READ-ONLY / 本番SS非汚染 / 出力=ローカルCSV  start", datetime.now().strftime("%H:%M"))
    print("=" * 76)

    # 0) 現在母集団(survivor 判定用) + ScaleCat 分布の確認
    cur_j = v1._get("/v2/equities/master", {})
    cur_rows = cur_j.get("data", []) if isinstance(cur_j, dict) else []
    cur_codes = {code_field(r) for r in cur_rows if code_field(r)}
    sc_dist = {}
    for r in cur_rows:
        sc = str(r.get("ScaleCat", ""))
        sc_dist[sc] = sc_dist.get(sc, 0) + 1
    print("\n[0] 現在master 全%d社 / ScaleCat 分布:" % len(cur_rows))
    for k, v in sorted(sc_dist.items(), key=lambda kv: -kv[1]):
        mark = "  <=Large+Mid採用" if any(x in k for x in LARGE_MID_KEYS) else ""
        print("    %-18s %4d%s" % (repr(k), v, mark))
    time.sleep(v1.SLEEP)

    # 1) 各 as-of の母集団(TOPIX Large+Mid・当時) を master?date= で復元
    print("\n[1] 当時母集団の復元(master?date=as-of・TOPIX Large+Mid)")
    universe = {}     # asof(ts) -> {code: (S33Nm, ScaleCat)}
    used_dates = {}
    for t in ASOF:
        rows, used = master_asof(t)
        uni = {}
        for r in rows:
            c = code_field(r)
            if c and is_large_mid(r):
                uni[c] = (r.get("S33Nm", ""), str(r.get("ScaleCat", "")))
        universe[t] = uni
        used_dates[t] = used
        n_delisted = sum(1 for c in uni if c not in cur_codes)
        print("    as-of %s (used %s): Large+Mid=%4d  うち現在廃止=%3d" %
              (t.date(), used, len(uni), n_delisted))
        time.sleep(v1.SLEEP)

    union = sorted({c for uni in universe.values() for c in uni})
    union_delisted = [c for c in union if c not in cur_codes]
    print("\n  union ユニーク銘柄=%d (うち現在廃止=%d)" % (len(union), len(union_delisted)))

    if os.environ.get("PERSTOCK_SMOKE") == "1":
        # 計算経路の煙テスト: 全域に分散した ~50 銘柄(廃止含む)に間引く
        step = max(1, len(union) // 50)
        sampled = union[::step]
        for c in union_delisted[:8]:
            if c not in sampled:
                sampled.append(c)
        union = sorted(set(sampled))
        union_delisted = [c for c in union if c not in cur_codes]
        # 母集団も sampled に絞る(コホート整合)
        for t in ASOF:
            universe[t] = {c: v for c, v in universe[t].items() if c in union}
        print("  [SMOKE] union を %d 銘柄(廃止%d)に間引いて計算経路を検証" %
              (len(union), len(union_delisted)))
    print("  → fins/summary + bars/daily を %d 銘柄分 取得(キャッシュ済は再利用)" % len(union))

    if universe_only:
        print("\n[UNIVERSE_ONLY] 取得せず終了。上記サイズで本実行の規模を確認。")
        print("UNIVERSE_SUMMARY ok=true union=%d delisted=%d at=%s" %
              (len(union), len(union_delisted), datetime.now().strftime("%Y-%m-%d %H:%M")))
        return

    # 2) データ取得(v1 の load_fins/load_prices=同一キャッシュを再利用)
    print("\n[2] データ取得(キャッシュ backtests/.cache_perstock/)")
    fins, px = {}, {}
    t0 = time.time()
    for i, c in enumerate(union):
        try:
            fins[c] = v1.build_fins_df(v1.load_fins(c))
            prows = v1.load_prices(c)
            pmap = {}
            for r in prows:
                dd = r.get("Date")
                vv = r.get("AdjC") or r.get("C")
                if dd and vv is not None:
                    pmap[pd.Timestamp(dd)] = float(vv)
            px[c] = (pmap, sorted(pmap.keys()))
        except Exception as e:
            fins[c] = pd.DataFrame()
            px[c] = ({}, [])
            print("    WARN %s fetch error: %r" % (c, e))
        if (i + 1) % 50 == 0:
            el = time.time() - t0
            print("    loaded %d/%d  (%.0fs, ~%.0fs ETA)" %
                  (i + 1, len(union), el, el / (i + 1) * (len(union) - i - 1)))
    # データ終端(=まだ上場中の判定基準)
    all_last = [ds[-1] for (pm, ds) in px.values() if ds]
    DATA_END = max(all_last) if all_last else pd.Timestamp("2026-06-30")
    print("  data load done. DATA_END=%s" % DATA_END.date())

    def fwd_ret_surv(pmap, ds, t, days):
        """forward リターン。廃止銘柄は廃止時点終値で実現リターンを計上。
        まだ上場中で horizon がデータ終端を超える場合は測定不能=None。"""
        pt = v1.price_asof(pmap, ds, t)
        if pt is None or pt <= 0:
            return None, None
        target = t + timedelta(days=days)
        pf = v1.price_asof(pmap, ds, target)
        if pf is not None:
            return (pf / pt - 1), "full"
        last = ds[-1] if ds else None
        # 真の廃止: 最終価格が as-of 後 かつ データ終端より十分前(=もう取引終了)
        if last is not None and last > t and last < (DATA_END - timedelta(days=30)):
            return (pmap[last] / pt - 1), "delisted"
        return None, None  # まだ上場中だが forward 未到来 → 除外

    # 3) コホート別 横断面 IC を full(補正後) と survivor-only(補正前相当) で算出
    print("\n[3] 横断面 Spearman IC (full=survivorship補正 / surv=現存のみ)")
    keyset = [(f, h, mode) for f in FACTORS for h in HORIZONS for mode in ("full", "surv")]
    c_ic = {k: [] for k in keyset}
    c_q = {k: [] for k in keyset}
    delist_used = {h: 0 for h in HORIZONS}  # 廃止リターンが入った件数

    for t in ASOF:
        recs = []
        for c, (sec, scale) in universe[t].items():
            pmap, ds = px.get(c, ({}, []))
            if not ds:
                continue
            pt = v1.price_asof(pmap, ds, t)
            if pt is None:
                continue
            fac = v1.factors_asof(fins.get(c, pd.DataFrame()), pt, t)
            if fac is None:
                continue
            row = {"code": c, "surv": (c in cur_codes), **fac}
            ok = False
            for h, days in HORIZONS.items():
                r, kind = fwd_ret_surv(pmap, ds, t, days)
                row[f"ret_{h}"] = r
                row[f"kind_{h}"] = kind
                if kind == "delisted":
                    delist_used[h] += 1
                if r is not None:
                    ok = True
            if ok:
                recs.append(row)
        if len(recs) < 20:
            continue
        rdf = pd.DataFrame(recs)
        for f in FACTORS:
            for h in HORIZONS:
                for mode in ("full", "surv"):
                    sub = rdf if mode == "full" else rdf[rdf["surv"]]
                    sub = sub[[f, f"ret_{h}"]].dropna()
                    if len(sub) < 20:
                        continue
                    ic, _p = stats.spearmanr(sub[f], sub[f"ret_{h}"])
                    if ic is None or math.isnan(ic):
                        continue
                    c_ic[(f, h, mode)].append(float(ic))
                    q = sub.copy()
                    q["rk"] = q[f].rank(pct=True)
                    top = q[q["rk"] >= 0.8][f"ret_{h}"].mean()
                    bot = q[q["rk"] <= 0.2][f"ret_{h}"].mean()
                    if top == top and bot == bot:  # not NaN
                        c_q[(f, h, mode)].append(float(top - bot))

    # 4) 集計 + full vs surv の差(=生存者バイアス)
    print("\n=== per-stock 過去IC: full(補正後) vs surv(現存のみ) ===")
    print("factor horizon mode | meanIC  %pos nCoh nInd | bootCI95         | Q5-Q1   | bias(full-surv)")
    rows_out = []
    for f in FACTORS:
        for h in HORIZONS:
            base = {}
            for mode in ("surv", "full"):  # surv を先に計算→full行で bias 表示可
                ics = c_ic[(f, h, mode)]
                if not ics:
                    base[mode] = None
                    continue
                mean_ic = float(np.mean(ics))
                base[mode] = mean_ic
                pos = float(np.mean([1 if v > 0 else 0 for v in ics]))
                nC = len(ics)
                nInd = nC // (4 if h == "1y" else 12)
                ci = v1.block_bootstrap_ci(ics, block=(4 if h == "1y" else 12))
                qsp = float(np.mean(c_q[(f, h, mode)])) if c_q[(f, h, mode)] else None
                bias = ""
                if mode == "full" and base.get("surv") is not None:
                    bias = "%+.3f" % (mean_ic - base["surv"])
                flag = " ⚠過大" if abs(mean_ic) > 0.30 else ""
                print("  %-3s %3s  %-4s | %+.3f  %4.0f%% %4d %4d | %s..%s | %s | %s%s" %
                      (f, h, mode, mean_ic, pos * 100, nC, nInd, ci[0], ci[1],
                       ("%+.3f" % qsp) if qsp is not None else "  n/a", bias, flag))
                rows_out.append({
                    "factor": f, "horizon": h, "mode": mode,
                    "mean_ic": round(mean_ic, 4), "pct_positive": round(pos, 3),
                    "n_cohort": nC, "n_independent": nInd,
                    "ci_lo": ci[0], "ci_hi": ci[1],
                    "mean_q5_q1": round(qsp, 4) if qsp is not None else None,
                    "ci_excludes_zero": (ci[0] is not None and ((ci[0] > 0) or (ci[1] < 0))),
                })

    # bias 行を別途追記
    for f in FACTORS:
        for h in HORIZONS:
            full = next((r for r in rows_out if r["factor"] == f and r["horizon"] == h and r["mode"] == "full"), None)
            surv = next((r for r in rows_out if r["factor"] == f and r["horizon"] == h and r["mode"] == "surv"), None)
            if full and surv:
                rows_out.append({
                    "factor": f, "horizon": h, "mode": "bias_full_minus_surv",
                    "mean_ic": round(full["mean_ic"] - surv["mean_ic"], 4),
                    "pct_positive": None, "n_cohort": None, "n_independent": None,
                    "ci_lo": None, "ci_hi": None, "mean_q5_q1": None, "ci_excludes_zero": None,
                })

    out_df = pd.DataFrame(rows_out)
    stamp = datetime.now().strftime("%Y%m%d_%H%M")
    out_csv = OUT / f"perstock_ic_surv_{stamp}.csv"
    out_df.to_csv(out_csv, index=False, encoding="utf-8-sig")

    print("\n--- 解釈の注意(CSVにも記録) ---")
    print(" * full=当時母集団(廃止含む・補正後) / surv=同コホートで現存銘柄のみ(=v1相当の偏り)。")
    print(" * bias(full-surv)>0 なら『廃止を入れると効きが増した』、<0 なら『生存者選好で効きを過大評価していた』。")
    print(" * 廃止リターン件数: " + ", ".join("%s=%d" % (h, delist_used[h]) for h in HORIZONS) +
          "(廃止時点終値で実現リターンを計上=TOB/倒産含む・近似)。")
    print(" * 因子源乖離: 本BTはJ-Quants再構成、本番出荷はyfinance → 近似proxy。重み確定はライブ満期IC+三重ゲートのみ。")
    print(" * 3y は非重複コホートが薄い(nInd小)→ 判定保留寄り。短期1yを主軸に読む。")
    print(f"\n出力: {out_csv}")
    print(f"PERSTOCK_SURV_SUMMARY ok=true cells={len(rows_out)} union={len(union)} delisted={len(union_delisted)} at={datetime.now().strftime('%Y-%m-%d %H:%M')}")


if __name__ == "__main__":
    main()

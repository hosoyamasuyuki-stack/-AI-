"""
backtests/verify_f1_basis.py — F1(分割調整基準不一致 look-ahead) の独立再測定。

多角検証ワークフロー(2026-06-09)が指摘した F1 を自前で確認する:
  backtest_perstock_v1.factors_asof は PER=price_t/eps・mc=price_t*shout を計算するが、
  price_t は AdjC(将来分割まで遡及反映した調整後終値)を当時開示の EPS/ShOutFY(未来分割なし)で割る
  = 基準不一致 → as-of 後に分割する銘柄の s3 を人為的に上振れ = look-ahead。
  本番(yfinance 現在 trailingPE/marketCap)は自己整合ゆえこのバグを持たない。

本スクリプトは v1 の 99銘柄ユニバース・同一コホート・同一 factors_asof を使い、
s3 因子に渡す株価だけを (a)AdjC=現行バグ (b)当時生終値C=修正 で切り替えて IC を対比する。
forward リターンは両方とも AdjC/AdjC(分割相殺=正しい・v1 と同一)。s1/s2 は price 非依存ゆえ adj==raw(sanity)。

★READ-ONLY: キャッシュ(.cache_perstock/)のみ読む。本番SS/予測記録/cron/スコア経路に一切書かない。
  ネットワーク GET も基本不要(キャッシュ済)。出力は標準出力のみ。
"""
import sys
import math
from pathlib import Path
from datetime import timedelta

import numpy as np
import pandas as pd
from scipy import stats

ROOT = Path(r"C:/AI-investment/-AI-")
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backtests"))
import backtest_perstock_v1 as v1  # noqa: E402

ASOF = []
for y in range(2012, 2026):
    for m, d in [(3, 31), (6, 30), (9, 30), (12, 31)]:
        ASOF.append(pd.Timestamp(year=y, month=m, day=d))
HOR = {"1y": 365, "3y": 365 * 3}
FACTORS = ["s1", "s2", "s3"]


def load_all():
    fins, padj, praw = {}, {}, {}
    for sec, c, scale in v1.STOCKS:
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
    return fins, padj, praw


def run(basis, fins, padj, praw):
    """basis: 'adj'(現行バグ) or 'raw'(修正)。各コホートの横断面 Spearman IC を集める。"""
    cic = {(f, h): [] for f in FACTORS for h in HOR}
    for t in ASOF:
        recs = []
        for sec, c, scale in v1.STOCKS:
            ma, da = padj[c]
            mr, dr = praw[c]
            pt_adj = v1.price_asof(ma, da, t)        # リターン用(AdjC)
            if pt_adj is None:
                continue
            pt_fac = pt_adj if basis == "adj" else v1.price_asof(mr, dr, t)  # 因子用
            if pt_fac is None:
                continue
            fac = v1.factors_asof(fins[c], pt_fac, t)
            if fac is None:
                continue
            row = {"code": c, **fac}
            for h, days in HOR.items():
                pf = v1.price_asof(ma, da, t + timedelta(days=days))
                row[f"ret_{h}"] = (pf / pt_adj - 1) if (pf and pt_adj) else None
            recs.append(row)
        if len(recs) < 20:
            continue
        rdf = pd.DataFrame(recs)
        for f in FACTORS:
            for h in HOR:
                sub = rdf[[f, f"ret_{h}"]].dropna()
                if len(sub) < 20:
                    continue
                ic, _p = stats.spearmanr(sub[f], sub[f"ret_{h}"])
                if ic is not None and not math.isnan(ic):
                    cic[(f, h)].append(float(ic))
    return cic


def main():
    print("=" * 78)
    print("verify_f1_basis : F1(分割調整基準不一致 look-ahead)の独立再測定  READ-ONLY")
    print("99銘柄(v1ユニバース) / as-of 四半期2012-2025 / 横断面Spearman IC")
    print("=" * 78)
    fins, padj, praw = load_all()
    print("cache load done (99 stocks)")
    res = {b: run(b, fins, padj, praw) for b in ["adj", "raw"]}

    print("\nfactor hor basis              meanIC    %pos  nCoh nInd   bootCI95")
    for f in ["s3", "s2", "s1"]:
        for h in ["1y", "3y"]:
            for b in ["adj", "raw"]:
                ics = res[b][(f, h)]
                if not ics:
                    print(f"  {f}  {h}  {b}: (none)")
                    continue
                m = float(np.mean(ics))
                pos = float(np.mean([1 if v > 0 else 0 for v in ics]))
                nC = len(ics)
                nI = nC // (4 if h == "1y" else 12)
                ci = v1.block_bootstrap_ci(ics, block=(4 if h == "1y" else 12))
                tag = "現行=AdjC(バグ)" if b == "adj" else "修正=当時C   "
                print(f"  {f}  {h}  {tag}  {m:+.4f}  {pos*100:4.0f}%  {nC:4d} {nI:3d}   {ci[0]}..{ci[1]}")
        # 差分(s3のみ意味あり)
        a1 = res["adj"][(f, "1y")]
        r1 = res["raw"][(f, "1y")]
        if a1 and r1:
            d1 = np.mean(a1) - np.mean(r1)
            pct = (d1 / np.mean(a1) * 100) if np.mean(a1) else 0
            print(f"    -> {f} 1y  バグ-修正 = {d1:+.4f} ({pct:+.0f}% が基準不一致由来)")
        print()
    print("NOTE: s1/s2 は price 非依存ゆえ adj==raw(sanity)。s3 のみ差が出れば F1 を実証。")
    print("VERIFY_F1_DONE")


if __name__ == "__main__":
    main()

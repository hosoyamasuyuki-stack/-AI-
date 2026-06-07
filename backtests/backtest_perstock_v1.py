"""
backtests/backtest_perstock_v1.py  —  per-stock 過去IC バックテスト (S2-S4)

手順書_短期中期per-stock過去分析_足掛かり設計_2026-06-08 §4 Phase0。
「短期/中期の個別銘柄因子(s1/s2/s3)が将来リターンを過去どれだけ説明したか」を、
真の point-in-time(DiscDate<=as-of)・横断面 Spearman IC で測る。

★READ-ONLY: J-Quants GET のみ。本番スプレッドシート/予測記録/cron/スコア経路に
  一切書かない。出力はローカル検証CSV(backtests/output/)のみ。

★重要な統計設計(協議反映):
 - 評価は勝率でなく IC(情報係数)。横断面 Spearman IC をas-ofコホート単位で算出。
 - 横断面 IC は各as-of日の市場(日経)シフトに不変 → コホート内生リターンで正しく測れる
   (日経データ不要。日経比超過は per-date 定数でランク相関を変えない)。
 - 四半期コホートの1y/3y窓は重複(自己相関)→ ブロックブートストラップ(ブロック長=4Q)で
   信頼区間。独立コホート数(非重複)も併記。素のp値は使わない。
 - 生存者バイアス: 99銘柄は現在の生存リスト=上方バイアス確実。出力に明記。過去IC を
   本番重み変更の単独根拠にしない(根拠はライブ満期ICのみ)。
 - 因子源乖離: 本番 s2/s3 は yfinance、本BTは J-Quants 再構成 → 近似proxy。HYPOTHESES参照。

実行: python backtests/backtest_perstock_v1.py
"""
import os
import sys
import json
import time
import math
from pathlib import Path
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import requests
from scipy import stats

# ── .env ──────────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parent.parent
ENV = ROOT / ".env"
if ENV.exists():
    for line in ENV.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

# 因子閾値は本番定義をそのまま使う(二重実装回避)
sys.path.insert(0, str(ROOT))
from core.config import ROE_THR, FCR_THR, RS_THR, FS_THR, PEG_THR, FCY_THR  # noqa
from core.scoring import thr_high, thr_low, slope_fn  # noqa

BASE = "https://api.jquants.com"
H = {"x-api-key": os.environ.get("JQUANTS_API_KEY", "")}
CACHE = ROOT / "backtests" / ".cache_perstock"
CACHE.mkdir(exist_ok=True)
OUT = ROOT / "backtests" / "output"
OUT.mkdir(exist_ok=True)

# 99銘柄ユニバース(learning_batch_monthly.py STOCKS と同一・業種,コード,規模)
STOCKS = [
    ('食品','2914','大'),('食品','2802','中'),('食品','2809','小'),('繊維','3401','大'),('繊維','3402','中'),
    ('繊維','3103','小'),('パルプ・紙','3861','大'),('パルプ・紙','3863','中'),('パルプ・紙','3880','小'),
    ('化学','4063','大'),('化学','4188','中'),('化学','4901','小'),('医薬品','4519','大'),('医薬品','4502','中'),
    ('医薬品','4527','小'),('ゴム','5108','大'),('ゴム','5101','中'),('ゴム','5189','小'),('ガラス・土石','5201','大'),
    ('ガラス・土石','5202','中'),('ガラス・土石','5233','小'),('鉄鋼','5401','大'),('鉄鋼','5411','中'),('鉄鋼','5471','小'),
    ('非鉄金属','5713','大'),('非鉄金属','5706','中'),('非鉄金属','5741','小'),('金属製品','5801','大'),('金属製品','5803','中'),
    ('金属製品','5947','小'),('機械','6273','大'),('機械','6302','中'),('機械','6413','小'),('電機','6501','大'),
    ('電機','6752','中'),('電機','6504','小'),('輸送機器','7203','大'),('輸送機器','7267','中'),('輸送機器','7270','小'),
    ('精密機器','7741','大'),('精密機器','7751','中'),('精密機器','7762','小'),('その他製品','7974','大'),('その他製品','7912','中'),
    ('その他製品','7911','小'),('鉱業','1605','大'),('鉱業','1662','中'),('鉱業','1663','小'),('建設','1802','大'),
    ('建設','1928','中'),('建設','1847','小'),('電気・ガス','9501','大'),('電気・ガス','9503','中'),('電気・ガス','9531','小'),
    ('陸運','9020','大'),('陸運','9064','中'),('陸運','9069','小'),('海運','9101','大'),('海運','9104','中'),
    ('海運','9107','小'),('空運','9202','大'),('空運','9201','中'),('空運','9206','小'),('倉庫・運輸','9301','大'),
    ('倉庫・運輸','9305','中'),('倉庫・運輸','9302','小'),('情報通信','9432','大'),('情報通信','9433','中'),('情報通信','4307','小'),
    ('卸売','8058','大'),('卸売','2768','中'),('卸売','8015','小'),('小売','9983','大'),('小売','3382','中'),
    ('小売','9843','小'),('銀行','8306','大'),('銀行','8316','中'),('銀行','8331','小'),('証券','8604','大'),
    ('証券','8601','中'),('証券','8473','小'),('保険','8630','大'),('保険','8725','中'),('保険','8729','小'),
    ('その他金融','8591','大'),('その他金融','8593','中'),('その他金融','8771','小'),('不動産','8801','大'),('不動産','8802','中'),
    ('不動産','8935','小'),('サービス','6098','大'),('サービス','4751','中'),('サービス','6200','小'),('半導体','8035','大'),
    ('半導体','6857','中'),('半導体','6146','小'),
]

SLEEP = 0.35  # 120req/分 を守る


def _get(path, params):
    for attempt in range(4):
        try:
            r = requests.get(BASE + path, headers=H, params=params, timeout=25)
            if r.status_code == 200:
                return r.json()
            if r.status_code in (429, 500, 503):
                time.sleep(2 * (attempt + 1))
                continue
            return {}
        except Exception:
            time.sleep(1.5 * (attempt + 1))
    return {}


def code5(c):
    return c + "0" if len(c) == 4 else c


def load_fins(c):
    f = CACHE / f"fins_{c}.json"
    if f.exists():
        return json.loads(f.read_text(encoding="utf-8"))
    rows, params = [], {"code": code5(c)}
    while True:
        j = _get("/v2/fins/summary", params)
        rows += j.get("data", []) if isinstance(j, dict) else []
        pk = j.get("pagination_key") if isinstance(j, dict) else None
        if not pk:
            break
        params["pagination_key"] = pk
        time.sleep(SLEEP)
    time.sleep(SLEEP)
    f.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
    return rows


def load_prices(c):
    f = CACHE / f"px_{c}.json"
    if f.exists():
        return json.loads(f.read_text(encoding="utf-8"))
    rows, params = [], {"code": code5(c), "from": "2009-01-01", "to": "2026-06-30"}
    while True:
        j = _get("/v2/equities/bars/daily", params)
        rows += j.get("data", []) if isinstance(j, dict) else []
        pk = j.get("pagination_key") if isinstance(j, dict) else None
        if not pk:
            break
        params["pagination_key"] = pk
        time.sleep(SLEEP)
    time.sleep(SLEEP)
    f.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
    return rows


def num(x):
    try:
        v = float(x)
        return None if (math.isnan(v) or math.isinf(v)) else v
    except Exception:
        return None


def build_fins_df(rows):
    """年次(FY)行のみ・DiscDate付きで返す。"""
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    if "DocType" not in df.columns or "DiscDate" not in df.columns:
        return pd.DataFrame()
    df = df[df["DocType"].str.contains("FYFinancialStatements", na=False)].copy()
    if df.empty:
        return pd.DataFrame()
    df["DiscDate"] = pd.to_datetime(df["DiscDate"], errors="coerce")
    df["CurPerEn"] = pd.to_datetime(df.get("CurPerEn"), errors="coerce")
    for col in ["NP", "Eq", "CFO", "CFI", "EPS", "ShOutFY"]:
        df[col] = df[col].apply(num) if col in df.columns else None
    df["FCF"] = df.apply(lambda r: (r["CFO"] + r["CFI"]) if (r.get("CFO") is not None and r.get("CFI") is not None) else None, axis=1)
    df["ROE"] = df.apply(lambda r: (r["NP"] / r["Eq"] * 100) if (r.get("NP") is not None and r.get("Eq") not in (None, 0)) else None, axis=1)
    df["FCR"] = df.apply(lambda r: (r["FCF"] / r["NP"] * 100) if (r.get("FCF") is not None and r.get("NP") not in (None, 0)) else None, axis=1)
    df = df.dropna(subset=["DiscDate"]).sort_values("DiscDate").reset_index(drop=True)
    # 同一決算の改訂で DiscDate 重複時は最初(最古開示)を残す=当時既知の値
    df = df.drop_duplicates(subset=["CurPerEn"], keep="first")
    return df


def price_asof(px_map, dates_sorted, t):
    """t 以前で直近の終値(AdjC優先)。"""
    import bisect
    i = bisect.bisect_right(dates_sorted, t) - 1
    if i < 0:
        return None
    # 直近5営業日以内に限る(欠損で大きく遡らない)
    if (t - dates_sorted[i]).days > 12:
        return None
    return px_map[dates_sorted[i]]


def factors_asof(fdf, price_t, t):
    """as-of t(DiscDate<=t)の年次行のみで s1/s2/s3 を当時値で再計算。"""
    av = fdf[fdf["DiscDate"] <= t]
    if len(av) < 4:
        return None
    roe = av["ROE"].dropna()
    fcr = av["FCR"].dropna()
    if len(roe) < 4:
        return None
    roe_mean = roe.tail(4).mean()
    fcr_mean = fcr.tail(4).mean() if len(fcr) else None
    s1 = round(thr_high(roe_mean, ROE_THR) * 0.6 + (thr_high(fcr_mean, FCR_THR) if fcr_mean is not None else 30) * 0.4)
    rsl = slope_fn(roe.tail(4).values)
    fsl = slope_fn(fcr.tail(4).values) if len(fcr) >= 2 else 0.0
    s2 = round(thr_high(rsl, RS_THR) * 0.6 + thr_high(fsl, FS_THR) * 0.4)
    # s3: PER=price/EPS(最新年次<=t), eps_growth=NP CAGR, PEG, FCF利回り
    last = av.iloc[-1]
    eps = last.get("EPS")
    per = (price_t / eps) if (eps and eps > 0) else None
    nps = av["NP"].dropna().values
    eg = None
    if len(nps) >= 3 and nps[0] > 0 and nps[-1] > 0:
        eg = (nps[-1] / nps[0]) ** (1 / (len(nps) - 1)) - 1
    peg = per / (eg * 100) if (per and eg and eg > 0.01) else None
    shout = last.get("ShOutFY")
    mc = price_t * shout if (shout and shout > 0) else None
    fcf = last.get("FCF")
    fy = abs(fcf) / mc * 100 if (fcf and mc and mc > 0) else None
    s3 = round(thr_low(peg, PEG_THR) * 0.5 + thr_high(fy, FCY_THR) * 0.5)
    return {"s1": s1, "s2": s2, "s3": s3}


def block_bootstrap_ci(cohort_ics, block=4, n_boot=2000):
    """重複窓の自己相関を考慮した移動ブロックブートストラップ95%CI。"""
    x = np.array([v for v in cohort_ics if v is not None and not math.isnan(v)])
    n = len(x)
    if n < 4:
        return (None, None)
    rng = np.random.default_rng(20260608)
    means = []
    nblocks = int(math.ceil(n / block))
    for _ in range(n_boot):
        idx = []
        for _b in range(nblocks):
            start = rng.integers(0, max(1, n - block + 1))
            idx += list(range(start, min(start + block, n)))
        means.append(np.mean(x[idx[:n]]))
    lo, hi = np.percentile(means, [2.5, 97.5])
    return (round(float(lo), 4), round(float(hi), 4))


def main():
    print("=" * 72)
    print("backtest_perstock_v1  per-stock 過去IC (真PIT・横断面Spearman)  start", datetime.now().strftime("%H:%M"))
    print("READ-ONLY / 本番SS非汚染 / 出力=ローカルCSVのみ")
    print("=" * 72)

    # 1) データ取得(キャッシュ)
    fins, px = {}, {}
    for i, (sec, c, scale) in enumerate(STOCKS):
        fdf = build_fins_df(load_fins(c))
        prows = load_prices(c)
        pmap = {}
        for r in prows:
            d = r.get("Date")
            v = r.get("AdjC") or r.get("C")
            if d and v is not None:
                pmap[pd.Timestamp(d)] = float(v)
        fins[c] = fdf
        px[c] = (pmap, sorted(pmap.keys()))
        if (i + 1) % 20 == 0:
            print(f"  loaded {i+1}/{len(STOCKS)}")
    print("  data load done")

    # 2) as-of 四半期コホート(3,6,9,12月末)・2012〜
    asof_dates = []
    for y in range(2012, 2026):
        for m, d in [(3, 31), (6, 30), (9, 30), (12, 31)]:
            asof_dates.append(pd.Timestamp(year=y, month=m, day=d))

    HORIZONS = {"1y": 365, "3y": 365 * 3}
    FACTORS = ["s1", "s2", "s3"]
    # cohort_ic[(factor,horizon)] = list of per-cohort Spearman IC
    cohort_ic = {(f, h): [] for f in FACTORS for h in HORIZONS}
    cohort_q = {(f, h): [] for f in FACTORS for h in HORIZONS}  # Q5-Q1 spread
    cohort_n = {(f, h): [] for f in FACTORS for h in HORIZONS}

    for t in asof_dates:
        # この as-of の各銘柄因子 + 各horizon forward return
        recs = []
        for sec, c, scale in STOCKS:
            pmap, ds = px[c]
            pt = price_asof(pmap, ds, t)
            if pt is None:
                continue
            fac = factors_asof(fins[c], pt, t)
            if fac is None:
                continue
            row = {"code": c, **fac}
            for h, days in HORIZONS.items():
                pf = price_asof(pmap, ds, t + timedelta(days=days))
                row[f"ret_{h}"] = (pf / pt - 1) if (pf and pt) else None
            recs.append(row)
        if len(recs) < 20:
            continue
        rdf = pd.DataFrame(recs)
        for f in FACTORS:
            for h in HORIZONS:
                sub = rdf[[f, f"ret_{h}"]].dropna()
                if len(sub) < 20:
                    continue
                ic, _p = stats.spearmanr(sub[f], sub[f"ret_{h}"])
                if ic is not None and not math.isnan(ic):
                    cohort_ic[(f, h)].append(float(ic))
                    cohort_n[(f, h)].append(len(sub))
                    # 分位スプレッド(因子上位20% - 下位20% の平均forward)
                    q = sub.copy()
                    q["rk"] = q[f].rank(pct=True)
                    top = q[q["rk"] >= 0.8][f"ret_{h}"].mean()
                    bot = q[q["rk"] <= 0.2][f"ret_{h}"].mean()
                    if top is not None and bot is not None:
                        cohort_q[(f, h)].append(float(top - bot))

    # 3) 集計
    rows = []
    print("\n=== per-stock 過去IC 結果(横断面 Spearman・コホート平均) ===")
    print("factor horizon | meanIC  %pos  nCohort nIndep | bootCI95         | meanQ5-Q1")
    for f in FACTORS:
        for h in HORIZONS:
            ics = cohort_ic[(f, h)]
            if not ics:
                continue
            mean_ic = float(np.mean(ics))
            pos = float(np.mean([1 if v > 0 else 0 for v in ics]))
            nC = len(ics)
            nIndep = nC // (4 if h == "1y" else 12)  # 非重複コホート数(1y=4Q毎,3y=12Q毎)
            ci = block_bootstrap_ci(ics, block=(4 if h == "1y" else 12))
            qsp = float(np.mean(cohort_q[(f, h)])) if cohort_q[(f, h)] else None
            flag = ""
            if abs(mean_ic) > 0.30:
                flag = " ⚠過大(要過剰適合疑い)"
            print(f"  {f}   {h:>3}    | {mean_ic:+.3f}  {pos*100:4.0f}%  {nC:5d}  {nIndep:4d}  | {ci[0]}..{ci[1]} | {qsp}{flag}")
            rows.append({
                "factor": f, "horizon": h, "mean_ic": round(mean_ic, 4),
                "pct_positive": round(pos, 3), "n_cohort": nC, "n_independent": nIndep,
                "ci_lo": ci[0], "ci_hi": ci[1], "mean_q5_q1": round(qsp, 4) if qsp is not None else None,
                "ci_excludes_zero": (ci[0] is not None and ((ci[0] > 0) or (ci[1] < 0))),
            })

    out_df = pd.DataFrame(rows)
    stamp = datetime.now().strftime("%Y%m%d_%H%M")
    out_csv = OUT / f"perstock_ic_{stamp}.csv"
    out_df.to_csv(out_csv, index=False, encoding="utf-8-sig")

    print("\n--- 解釈の注意(出力CSVにも記録) ---")
    print(" * 生存者バイアス: 99銘柄は現在の生存大型株=IC は上方バイアス確実。重み変更の単独根拠にしない。")
    print(" * 因子源乖離: 本BTはJ-Quants再構成、本番出荷はyfinance → 近似proxy(HYPOTHESES参照)。")
    print(" * 重複窓: 四半期コホートの1y/3yは重複→bootCIはブロック法。nIndep=非重複コホート数(これが実質N)。")
    print(" * 短期の本番因子=s3, 中期の本番因子=s2。短期はs3行、中期はs2行を主に見る。")
    print(" * IC>=0.03-0.05で『方向の足掛かりあり』の目安。|IC|>0.30は過剰適合疑いで赤信号。")
    print(f"\n出力: {out_csv}")
    print(f"PERSTOCK_BT_SUMMARY ok=true cells={len(rows)} at={datetime.now().strftime('%Y-%m-%d %H:%M')}")


if __name__ == "__main__":
    main()

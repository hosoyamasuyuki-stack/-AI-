"""
backtests/probe_universe_history.py — Phase 1 read-only probe (DISPOSABLE)

目的(手順書_短期中期per-stock過去分析 §4 Phase1 / 引継ぎ STEP3-P1①):
  生存者バイアス補正に必要な「過去ユニバースの復元可否」を推測でなく実測する。
  Q1. /v2/equities/master は date パラメータを受けるか(=as-of 母集団取得可否)
  Q2. master に上場廃止/業種/規模/日付フィールドが実在するか
  Q3. 過去日と現在で銘柄集合(コード)が変わるか(=廃止銘柄を含む当時母集団が取れるか)
  Q4. 既知の上場廃止銘柄が遡及取得できるか(master / fins/summary / bars/daily)

★READ-ONLY: GET のみ。本番スプレッドシート・予測記録・cron・スコア経路に一切触れない。
  出力は標準出力 + backtests/output/universe_probe_*.txt(ローカルのみ・gitignore)。
実行: python backtests/probe_universe_history.py   (.env の JQUANTS_API_KEY を使用)
"""
import os
import json
import time
from pathlib import Path
from datetime import datetime

import requests

# ── .env から JQUANTS_API_KEY を読む(python-dotenv 非依存) ──
ROOT = Path(__file__).resolve().parent.parent
ENV = ROOT / ".env"
if ENV.exists():
    for line in ENV.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

API_KEY = os.environ.get("JQUANTS_API_KEY", "")
BASE = "https://api.jquants.com"
H = {"x-api-key": API_KEY}
OUT = ROOT / "backtests" / "output"
OUT.mkdir(exist_ok=True)
SLEEP = 0.4  # 120req/分を守る

# 出力をファイルにも残す
_lines = []


def p(*args):
    s = " ".join(str(a) for a in args)
    print(s)
    _lines.append(s)


def get(path, params):
    r = requests.get(BASE + path, headers=H, params=params, timeout=25)
    ct = r.headers.get("content-type", "")
    j = r.json() if ct.startswith("application/json") else {}
    return r.status_code, j


def get_all(path, params):
    """pagination_key を辿って data を全件取得。(rows, status, pages)"""
    rows, pages, params = [], 0, dict(params)
    while True:
        sc, j = get(path, params)
        pages += 1
        if sc != 200 or not isinstance(j, dict):
            return rows, sc, pages
        rows += j.get("data", []) or []
        pk = j.get("pagination_key")
        if not pk or pages >= 20:
            return rows, sc, pages
        params["pagination_key"] = pk
        time.sleep(SLEEP)


def code_field(row):
    """master 行からコードらしき値を取り出す(列名のゆらぎ対応)。"""
    for k in ("Code", "code", "LocalCode", "Symbol"):
        if k in row and str(row[k]).strip():
            return str(row[k]).strip()
    return None


p("=" * 74)
p("PHASE1 PROBE  過去ユニバース復元可否(survivorship) 実測  key_set=%s" % bool(API_KEY))
p("at=%s" % datetime.now().strftime("%Y-%m-%d %H:%M"))
p("READ-ONLY / GETのみ / 本番SS・cron・予測記録 不可触 / 出力=ローカルのみ")
p("=" * 74)

# ── Q2) master のスキーマ(列・廃止/業種/規模/日付フィールド) ──────────
p("\n[Q2] /v2/equities/master スキーマ確認(全件・date無し=現在)")
cur_rows, sc, pages = get_all("/v2/equities/master", {})
p("  status=%s pages=%s rows(現在全件)=%d" % (sc, pages, len(cur_rows)))
cols = sorted(cur_rows[0].keys()) if cur_rows else []
p("  columns(%d): %s" % (len(cols), ", ".join(cols)))
date_like = [c for c in cols if any(t in c.lower() for t in
             ("date", "delist", "expire", "end", "stop", "abolish", "remove"))]
sector_like = [c for c in cols if any(t in c.lower() for t in
               ("sector", "industry", "scale", "market", "33", "17"))]
p("  日付/廃止らしき列: %s" % date_like)
p("  業種/規模/市場らしき列: %s" % sector_like)
if cur_rows:
    p("  --- master 行サンプル(生) ---")
    p(json.dumps(cur_rows[0], ensure_ascii=False, indent=2)[:1200])
# 廃止日らしき列に値が入っている銘柄が現在master内にあるか
for c in date_like:
    nonblank = sum(1 for r in cur_rows if str(r.get(c, "")).strip())
    if nonblank:
        sample = next((r.get(c) for r in cur_rows if str(r.get(c, "")).strip()), None)
        p("  列 %-22s に値あり: %d/%d 件 (sample=%r)" % (c, nonblank, len(cur_rows), sample))
time.sleep(SLEEP)

cur_codes = {code_field(r) for r in cur_rows if code_field(r)}
p("  現在のユニークコード数: %d" % len(cur_codes))

# ── Q1+Q3) date パラメータ可否 と 過去↔現在の銘柄集合差分 ────────────
p("\n[Q1+Q3] master の date パラメータ可否 と 当時母集団の差分")
PAST_DATES = ["2022-06-30", "2018-06-29", "2014-06-30", "2010-06-30"]
past_code_sets = {}
past_rows_by_date = {}  # date -> {code: row}(廃止銘柄の業種/規模を引くため保持)
for d in PAST_DATES:
    rows, sc, pages = get_all("/v2/equities/master", {"date": d})
    codes = {code_field(r) for r in rows if code_field(r)}
    past_code_sets[d] = codes
    past_rows_by_date[d] = {code_field(r): r for r in rows if code_field(r)}
    same = (codes == cur_codes)
    delisted_since = codes - cur_codes  # 当時あって今ない=廃止/コード消滅
    newly = cur_codes - codes           # 今あって当時ない=新規上場
    p("  date=%s status=%s pages=%s rows=%d uniq=%d %s" %
      (d, sc, pages, len(rows), len(codes),
       "[=現在と同一→date無視の疑い]" if same else "[現在と差分あり→date有効の可能性]"))
    if codes:
        p("      当時あって現在なし(廃止/統合の候補)=%d  /  現在あって当時なし(新規)=%d" %
          (len(delisted_since), len(newly)))
        if delisted_since:
            p("      廃止候補コード sample: %s" % sorted(list(delisted_since))[:12])
    time.sleep(SLEEP)


def is_equity(row):
    """ETF/REIT/出資証券等を除く『普通株式らしさ』判定。
    S33(33業種コード)が普通株に割当たり、Code 末尾が0(銘柄コード4桁+0)のもの。
    ETF/ETN/REIT は S33 が無い/特殊・ScaleCat 空が多い。"""
    s33 = str(row.get("S33", "")).strip()
    code = code_field(row) or ""
    # 普通株は S33 が 4桁業種コードで '0050'〜'9999' の実業種、ETF等は '-'/空/'9999'(その他)
    has_sector = s33 not in ("", "-", "9999", "0", "0000")
    # ProdCat: 011 等が株式。ETF/REIT は別系統。両面で判定。
    return has_sector


# Q3b: 「当時あって今ない」を普通株に絞って真の廃止規模を推定(2014/2022)
p("\n[Q3b] 当時母集団→現在で消えた銘柄の内訳(ETF/REIT除外=真の株式廃止の推定)")
for d in ("2014-06-30", "2022-06-30"):
    gone = past_code_sets[d] - cur_codes
    rowmap = past_rows_by_date[d]
    gone_equity = [c for c in gone if c in rowmap and is_equity(rowmap[c])]
    gone_nonequity = [c for c in gone if c not in gone_equity]
    p("  date=%s 消滅総数=%d → 普通株(推定廃止)=%d / ETF等その他=%d" %
      (d, len(gone), len(gone_equity), len(gone_nonequity)))
    # 廃止株のサンプル(コード+社名)
    samp = sorted(gone_equity)[:8]
    for c in samp:
        r = rowmap[c]
        p("      %s %s  S33Nm=%s ScaleCat=%s" %
          (c, r.get("CoName", ""), r.get("S33Nm", ""), r.get("ScaleCat", "")))
    # 当時母集団の普通株総数(分母)も出す
    base_equity = sum(1 for c, r in rowmap.items() if is_equity(r))
    p("      参考: %s 時点の普通株(推定)母集団=%d → 期間内 廃止率≈%.1f%%(対当時母集団)" %
      (d, base_equity, (len(gone_equity) / base_equity * 100) if base_equity else 0))

# ── Q4) 既知の上場廃止銘柄が遡及取得できるか ──────────────────────────
# best-effort 既知廃止(年月は概況): 65020 東芝(2023-12) / 54860 日立金属(2023-03)
#   67640 三洋電機(2011-04) / 54050 住友金属工業(2012-09 新日鉄統合)
p("\n[Q4] 既知の上場廃止銘柄の遡及取得テスト(master/fins/bars)")
DELISTED = [
    ("65020", "東芝(2023-12廃止)"),
    ("54860", "日立金属(2023-03廃止)"),
    ("67640", "三洋電機(2011-04廃止)"),
    ("54050", "住友金属工業(2012統合)"),
]
for code5, label in DELISTED:
    p("  --- %s %s ---" % (code5, label))
    in_cur = code5 in cur_codes
    in_past = {d: (code5 in s) for d, s in past_code_sets.items()}
    p("      現在master在籍=%s  過去master在籍=%s" % (in_cur, in_past))
    # master 単体(date無し)
    sc_m, jm = get("/v2/equities/master", {"code": code5})
    nm = len(jm.get("data", [])) if isinstance(jm, dict) else 0
    time.sleep(SLEEP)
    # fins/summary(財務履歴)
    sc_f, jf = get("/v2/fins/summary", {"code": code5})
    nf = len(jf.get("data", [])) if isinstance(jf, dict) else 0
    time.sleep(SLEEP)
    # bars/daily(株価・廃止前の日付で)
    sc_b, jb = get("/v2/equities/bars/daily", {"code": code5, "date": "2011-03-01"})
    nb = len(jb.get("data", [])) if isinstance(jb, dict) else 0
    time.sleep(SLEEP)
    p("      master(code) status=%s rows=%d | fins/summary status=%s rows=%d | bars(2011-03-01) status=%s rows=%d"
      % (sc_m, nm, sc_f, nf, sc_b, nb))

# ── 結論サマリ(機械可読) ──────────────────────────────────────────
p("\n" + "=" * 74)
date_param_effective = any(past_code_sets[d] != cur_codes and len(past_code_sets[d]) > 0
                          for d in PAST_DATES)
p("CONCLUSION date_param_effective=%s  (Trueなら as-of 母集団で survivorship 補正可)" % date_param_effective)
p("UNIVERSE_PROBE_SUMMARY ok=true date_param_effective=%s cur_uniq=%d at=%s" %
  (date_param_effective, len(cur_codes), datetime.now().strftime("%Y-%m-%d %H:%M")))

stamp = datetime.now().strftime("%Y%m%d_%H%M")
outfile = OUT / f"universe_probe_{stamp}.txt"
outfile.write_text("\n".join(_lines), encoding="utf-8")
p("\n出力: %s" % outfile)

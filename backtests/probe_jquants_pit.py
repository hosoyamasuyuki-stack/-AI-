"""
backtests/probe_jquants_pit.py  —  S0 read-only probe (DISPOSABLE)

目的(手順書_短期中期per-stock過去分析_足掛かり設計_2026-06-08 §4 S0):
  J-Quants で実際に取得できるデータを「推測でなく実測」する。
  - fins/summary の全フィールド名・履歴年数・年次/四半期・開示日(DiscDate相当)の有無
  - s3 過去再構成に要る ShOutFY/EPS/NP/CFO/CFI の実在
  - equities/master の Date/上場廃止/業種 フィールド(過去ユニバース復元可否)
  - bars/daily の遡及可能年(履歴深さ=実効プラン)

READ-ONLY: GET のみ。本番スプレッドシート・予測記録・cron・スコア経路に一切触れない。
実行: python backtests/probe_jquants_pit.py   (.env の JQUANTS_API_KEY を使用)
"""
import os
import json
from pathlib import Path
from datetime import datetime

import requests

# ── .env から JQUANTS_API_KEY を読む(python-dotenv 非依存) ──
ENV = Path(__file__).resolve().parent.parent / ".env"
if ENV.exists():
    for line in ENV.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

API_KEY = os.environ.get("JQUANTS_API_KEY", "")
BASE = "https://api.jquants.com"
H = {"x-api-key": API_KEY}
CODE = "72030"  # トヨタ(5桁)

print("=" * 70)
print("S0 PROBE  J-Quants 実取得データ実測  code=%s  key_set=%s" % (CODE, bool(API_KEY)))
print("=" * 70)


def get(path, params):
    r = requests.get(BASE + path, headers=H, params=params, timeout=20)
    return r.status_code, (r.json() if r.headers.get("content-type", "").startswith("application/json") else {})


# ── 1) fins/summary ───────────────────────────────────────────
print("\n[1] /v2/fins/summary?code=%s" % CODE)
try:
    sc, j = get("/v2/fins/summary", {"code": CODE})
    print("  status:", sc)
    rows = j.get("data", []) if isinstance(j, dict) else []
    print("  rows:", len(rows))
    if rows:
        cols = sorted(rows[0].keys())
        print("  columns (%d):" % len(cols))
        print("   ", ", ".join(cols))
        # 開示日らしき列の検出
        disc = [c for c in cols if any(t in c.lower() for t in ("disc", "announce", "discloseddate", "date"))]
        print("  日付/開示日らしき列:", disc)
        for c in disc:
            populated = sum(1 for r in rows if str(r.get(c, "")).strip())
            sample = next((r.get(c) for r in rows if str(r.get(c, "")).strip()), None)
            print("    - %s: populated %d/%d  sample=%r" % (c, populated, len(rows), sample))
        # DocType の分布(年次/四半期)
        dts = {}
        for r in rows:
            dt = r.get("DocType", "")
            dts[dt] = dts.get(dt, 0) + 1
        print("  DocType 分布:")
        for k, v in sorted(dts.items()):
            print("    - %s: %d" % (k, v))
        # CurPerEn の範囲(履歴深さ)
        ends = sorted([str(r.get("CurPerEn", "")) for r in rows if r.get("CurPerEn")])
        if ends:
            print("  CurPerEn 範囲:", ends[0], "→", ends[-1], "(=履歴深さ/実効プランの目安)")
        # s3 再構成に要る主要フィールドの実在と最新値サンプル
        need = ["EPS", "NP", "Eq", "CFO", "CFI", "ShOutFY", "Sales", "OP"]
        last = rows[-1]
        print("  s3/s2 再構成キーフィールドの実在(最新行サンプル):")
        for f in need:
            print("    - %-8s present=%-5s  value=%r" % (f, f in last, last.get(f)))
        # 生レコード1件(最新)を全フィールドダンプ
        print("  --- 最新レコード 生ダンプ ---")
        print(json.dumps(last, ensure_ascii=False, indent=2)[:2000])
except Exception as e:
    print("  ERROR:", repr(e))

# ── 2) equities/master ────────────────────────────────────────
print("\n[2] /v2/equities/master?code=%s" % CODE)
try:
    sc, j = get("/v2/equities/master", {"code": CODE})
    print("  status:", sc)
    rows = j.get("data", []) if isinstance(j, dict) else []
    print("  rows:", len(rows))
    if rows:
        cols = sorted(rows[0].keys())
        print("  columns (%d):" % len(cols))
        print("   ", ", ".join(cols))
        delist = [c for c in cols if any(t in c.lower() for t in ("date", "delist", "sector", "market", "scale"))]
        print("  日付/上場廃止/業種らしき列:", delist)
        print("  --- master 生ダンプ ---")
        print(json.dumps(rows[0], ensure_ascii=False, indent=2)[:1500])
except Exception as e:
    print("  ERROR:", repr(e))

# ── 3) bars/daily 遡及可能年(履歴深さ) ────────────────────────
print("\n[3] /v2/equities/bars/daily 遡及テスト(株価履歴の深さ)")
for y in ("2026-06-01", "2020-06-01", "2016-06-01", "2014-06-01", "2012-06-01", "2010-06-01", "2008-06-01"):
    try:
        sc, j = get("/v2/equities/bars/daily", {"code": CODE, "date": y})
        n = len(j.get("data", [])) if isinstance(j, dict) else 0
        c = j.get("data", [{}])[0].get("C") if n else None
        print("  %s  status=%s  rows=%s  C=%s" % (y, sc, n, c))
    except Exception as e:
        print("  %s  ERROR: %r" % (y, e))

print("\nPROBE_SUMMARY ok=true at=%s" % datetime.now().strftime("%Y-%m-%d %H:%M"))

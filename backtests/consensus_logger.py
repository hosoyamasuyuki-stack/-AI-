"""
backtests/consensus_logger.py
  — A=アナリスト・コンセンサス Route1 週次ロガー（2026-06-09）

目的: 会社予想ベースの frev/esurp は全 horizon で null だったため、別データ源＝
  アナリスト・コンセンサス（PEAD で最も頑健・yfinance が日本大型株で無料返却）を
  週次スナップショットして PIT パネルを蓄積し、ライブ満期で T+1 イベント時間 IC 測定する。
  事前確率は「中」（大型株効率＋会社予想 frev が null ゆえ過信しない）。

★READ-ONLY・本番無変更・0円・dispatch ゼロ。
  - 本番 SS（保有/監視/Top50 シート）は get_target_codes で col_values 読取のみ（書込なし）。
  - 予測記録 / v4.3 スコア / core/config.py / cron / 顧客 HTML に一切書かない。
  - 出力 = backtests/consensus_log/consensus_panel.csv（git 非追跡・append only）。

シグナル（手順書 §2-2・実測フィールド構造 2026-06-09 プローブ確認済）:
  - rev_mom_0y / rev_mom_1y  = eps_trend (current − 90daysAgo)/|90daysAgo|（今期/来期）= プロの改定モメンタム
  - rev_breadth_0y / _1y     = eps_revisions (upLast30days − downLast30days)（今期/来期）
  - csurp                    = earnings_history 最新四半期 surprisePercent（実績 vs コンセンサス・分数表記）
  - n_analysts_0q / _0y      = earnings_estimate numberOfAnalysts（カバレッジ品質フィルタ）

罠（手順書 §3）:
  T1 ティッカー = f"{code}.T"（本番ユニバースは 4 文字＝130A/212A 末尾英字含む・truncate しない）
  T2 着手前プローブ = 7203.T price 取得成功を確認してから一括（失敗時 abort）
  T3 rate limit = 1 銘柄ごと sleep ＋ 失敗時リトライ（指数 backoff・最大 3）
  T4 フィールド名サイレント変動 = 各列/行の存在チェック＋欠損 warning（eps_revisions は大小混在）
  T5/T8 冪等 = (code, snapshot_date) ユニーク・既存 skip・append only・過去書換なし
  T9 小カバレッジ = n_analysts は落とさず保持（満期検証で除外可能に）

使い方:
  python backtests/consensus_logger.py                       # 当日 UTC を snapshot_date に全件
  python backtests/consensus_logger.py --limit 3             # スモークテスト（先頭 3 銘柄）
  python backtests/consensus_logger.py --snapshot-date 2026-06-09  # snapshot_date 明示
  python backtests/consensus_logger.py --sleep 1.5
"""
import sys
import time
import argparse
from pathlib import Path
from datetime import datetime, timezone

import numpy as np
import pandas as pd

ROOT = Path(r"C:/AI-investment/-AI-")
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backtests"))

import os                                              # noqa: E402


def _ensure_google_credentials():
    """ローカル実行用シム（本番 core/auth.py は無変更）。

    get_spreadsheet() は env `GOOGLE_CREDENTIALS`（service-account JSON 文字列）を読む。
    ローカル PC には未設定のため、env が空なら `GOOGLE_CREDENTIALS_FILE` が指す
    ローカル JSON ファイルから読み込んで env に流し込む（チャット非露出・Dropbox 平文禁止）。
    本番 GitHub Actions では GOOGLE_CREDENTIALS が直接注入されるため本シムは不発火。
    """
    if os.environ.get("GOOGLE_CREDENTIALS"):
        return
    path = os.environ.get("GOOGLE_CREDENTIALS_FILE")
    if path and Path(path).exists():
        os.environ["GOOGLE_CREDENTIALS"] = Path(path).read_text(encoding="utf-8")


import yfinance as yf                                  # noqa: E402
from core.auth import get_spreadsheet                  # noqa: E402
from tools.fetch_tanshin import get_target_codes       # noqa: E402  L134・保有+監視+Top50

OUT_DIR = ROOT / "backtests" / "consensus_log"
PANEL = OUT_DIR / "consensus_panel.csv"

# 出力列（順序固定・PIT 再現性のため fetched_at_utc を別列で保持）
COLUMNS = [
    "code", "snapshot_date", "fetched_at_utc", "price",
    "rev_mom_0y", "rev_mom_1y", "rev_breadth_0y", "rev_breadth_1y",
    "csurp", "csurp_q_end", "n_analysts_0q", "n_analysts_0y",
    "n_fields_missing",
]


def _num(v):
    """安全な float 変換（NaN/None/変換不能 → np.nan）。"""
    try:
        if v is None:
            return np.nan
        f = float(v)
        return f if np.isfinite(f) else np.nan
    except (TypeError, ValueError):
        return np.nan


def _cell(df, row, col, miss):
    """df.loc[row, col] を存在チェック付きで取得。欠損は miss セットに記録（T4）。"""
    if df is None or not hasattr(df, "index"):
        miss.add(f"{col}@{row}:nodf")
        return np.nan
    if row not in df.index:
        miss.add(f"{col}@{row}:norow")
        return np.nan
    if col not in df.columns:
        miss.add(f"{col}@{row}:nocol")
        return np.nan
    return _num(df.loc[row, col])


def fetch_consensus(code, sleep, max_retry=3):
    """1 銘柄のコンセンサス・スナップショットを返す（dict）。欠損は NaN・行は落とさない。"""
    ticker = f"{code}.T"   # T1: 4 文字コードそのまま・truncate しない
    last_err = None
    for attempt in range(max_retry):
        try:
            t = yf.Ticker(ticker)
            fi = t.fast_info
            try:
                price = _num(fi["lastPrice"])
            except Exception:
                price = _num(getattr(fi, "last_price", None))

            eps_trend = _safe_attr(t, "eps_trend")
            eps_rev = _safe_attr(t, "eps_revisions")
            ehist = _safe_attr(t, "earnings_history")
            eest = _safe_attr(t, "earnings_estimate")

            miss = set()

            # rev_mom = (current − 90daysAgo)/|90daysAgo|
            def rev_mom(rowkey):
                cur = _cell(eps_trend, rowkey, "current", miss)
                ago = _cell(eps_trend, rowkey, "90daysAgo", miss)
                if np.isnan(cur) or np.isnan(ago) or ago == 0:
                    return np.nan
                return (cur - ago) / abs(ago)

            rev_mom_0y = rev_mom("0y")
            rev_mom_1y = rev_mom("+1y")

            # rev_breadth = upLast30days − downLast30days
            def rev_breadth(rowkey):
                up = _cell(eps_rev, rowkey, "upLast30days", miss)
                dn = _cell(eps_rev, rowkey, "downLast30days", miss)
                if np.isnan(up) or np.isnan(dn):
                    return np.nan
                return up - dn

            rev_breadth_0y = rev_breadth("0y")
            rev_breadth_1y = rev_breadth("+1y")

            # csurp = 最新四半期 surprisePercent（index = 四半期末 Timestamp・最新行）
            csurp, csurp_q_end = np.nan, ""
            if ehist is not None and hasattr(ehist, "index") and len(ehist.index) > 0:
                if "surprisePercent" in ehist.columns:
                    try:
                        latest = max(ehist.index)
                        csurp = _num(ehist.loc[latest, "surprisePercent"])
                        csurp_q_end = str(getattr(latest, "date", lambda: latest)())
                    except Exception:
                        miss.add("surprisePercent:latesterr")
                else:
                    miss.add("surprisePercent:nocol")
            else:
                miss.add("earnings_history:empty")

            n_analysts_0q = _cell(eest, "0q", "numberOfAnalysts", miss)
            n_analysts_0y = _cell(eest, "0y", "numberOfAnalysts", miss)

            return {
                "code": code,
                "price": price,
                "rev_mom_0y": rev_mom_0y,
                "rev_mom_1y": rev_mom_1y,
                "rev_breadth_0y": rev_breadth_0y,
                "rev_breadth_1y": rev_breadth_1y,
                "csurp": csurp,
                "csurp_q_end": csurp_q_end,
                "n_analysts_0q": n_analysts_0q,
                "n_analysts_0y": n_analysts_0y,
                "n_fields_missing": len(miss),
                "_miss": miss,
            }
        except Exception as e:                          # T3: 一過性障害はリトライ
            last_err = e
            if attempt < max_retry - 1:
                time.sleep(sleep * (2 ** attempt))
    print(f"  [ERR] {ticker}: {max_retry} 回失敗: {repr(last_err)[:160]}", file=sys.stderr)
    return None


def _safe_attr(t, name):
    """yfinance プロパティを例外安全に取得（T4: 非公式 API ゆえ落ちうる）。"""
    try:
        return getattr(t, name)
    except Exception as e:
        print(f"    [WARN] {name} 取得失敗: {repr(e)[:120]}", file=sys.stderr)
        return None


def jquants_universe(scales=("Core30", "Large70", "Mid400")):
    """J-Quants /v2/equities/master から TOPIX Large+Mid（=v2 コメント「製品ユニバース相当」）を
    取得し、yfinance 用の 4 桁コード集合を返す（ローカル .env の JQUANTS_API_KEY 使用・Google creds 不要）。

    用途: 顧客ユニバース（保有+監視+Top50）は Google Sheet 在＝service-account 認証が要るが、
    ローカル PC に未設定のため、認証不要で同等の大型/中型 JP 母集団を J-Quants から構築する代替経路。
    T1: J-Quants は 5 桁 LocalCode → code[:4]（末尾英字 130A0→130A も正しく 4 文字化・full_scan.py:210 同一）。
    """
    import backtest_perstock_v1 as v1   # noqa: E402  import で .env 自動ロード + _get 提供
    j = v1._get("/v2/equities/master", {})
    rows = j.get("data", []) if isinstance(j, dict) else []
    codes = set()
    for r in rows:
        sc = str(r.get("ScaleCat", ""))
        if not any(k in sc for k in scales):
            continue
        c = None
        for key in ("Code", "code", "LocalCode"):
            if key in r and str(r[key]).strip():
                c = str(r[key]).strip()
                break
        if not c:
            continue
        if len(c) == 5:                  # T1: 5 桁→4 桁（先頭 4 文字）
            c = c[:4]
        codes.add(c)
    return codes


def load_existing_keys():
    """既存 panel の (code, snapshot_date) キー集合（T5 冪等）。"""
    if not PANEL.exists():
        return set()
    try:
        df = pd.read_csv(PANEL, dtype={"code": str, "snapshot_date": str})
        return set(zip(df["code"].astype(str), df["snapshot_date"].astype(str)))
    except Exception as e:
        print(f"[WARN] 既存 panel 読込失敗（新規扱い）: {e}", file=sys.stderr)
        return set()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--snapshot-date", default=None, help="YYYY-MM-DD（既定=当日 UTC）")
    ap.add_argument("--limit", type=int, default=0, help="先頭 N 銘柄のみ（スモークテスト用・0=全件）")
    ap.add_argument("--sleep", type=float, default=1.2, help="銘柄間 sleep 秒（rate limit 対策）")
    ap.add_argument("--universe", choices=["sheet", "jquants"], default="sheet",
                    help="sheet=保有+監視+Top50（要 GOOGLE_CREDENTIALS）/ jquants=TOPIX Large+Mid（.env のみ・creds 不要）")
    args = ap.parse_args()

    now = datetime.now(timezone.utc)
    snapshot_date = args.snapshot_date or now.strftime("%Y-%m-%d")
    fetched_at_utc = now.strftime("%Y-%m-%dT%H:%M:%SZ")

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    # --- T2: 着手前プローブ（7203.T price 取得成功を確認してから一括） ---
    print("[probe] 7203.T fast_info price ...", file=sys.stderr)
    probe = fetch_consensus("7203", args.sleep, max_retry=2)
    if probe is None or np.isnan(probe["price"]):
        print("[ABORT] T2 プローブ失敗（yfinance 障害の可能性）。一括取得を中止。", file=sys.stderr)
        sys.exit(1)
    print(f"[probe OK] 7203.T price={probe['price']}", file=sys.stderr)

    # --- universe（読取のみ） ---
    if args.universe == "jquants":
        codes = sorted(jquants_universe())   # TOPIX Large+Mid（製品ユニバース相当・creds 不要）
        print(f"[universe:jquants] TOPIX Large+Mid {len(codes)} 銘柄 / snapshot_date={snapshot_date}",
              file=sys.stderr)
    else:
        _ensure_google_credentials()
        if not os.environ.get("GOOGLE_CREDENTIALS"):
            print("[ABORT] GOOGLE_CREDENTIALS 未設定。env に直接設定するか、"
                  "GOOGLE_CREDENTIALS_FILE にローカル service-account JSON のパスを設定してください。"
                  "（認証なしで進めるには --universe jquants）", file=sys.stderr)
            sys.exit(2)
        ss = get_spreadsheet()
        codes = sorted(get_target_codes(ss))   # 保有+監視+Top50
        print(f"[universe:sheet] 保有+監視+Top50 {len(codes)} 銘柄 / snapshot_date={snapshot_date}",
              file=sys.stderr)
    if args.limit and args.limit > 0:
        codes = codes[: args.limit]

    existing = load_existing_keys()
    rows, field_health = [], {}
    skipped, failed = 0, 0

    for i, code in enumerate(codes, 1):
        if (str(code), str(snapshot_date)) in existing:
            skipped += 1                                # T5: 同日既存は skip（重複行を作らない）
            continue
        rec = fetch_consensus(code, args.sleep)
        if rec is None:
            failed += 1
            time.sleep(args.sleep)
            continue
        for k in rec.pop("_miss"):
            field_health[k] = field_health.get(k, 0) + 1
        rec.update({"snapshot_date": snapshot_date, "fetched_at_utc": fetched_at_utc})
        rows.append({c: rec.get(c, "") for c in COLUMNS})
        if i % 25 == 0:
            print(f"  ... {i}/{len(codes)} 取得中", file=sys.stderr)
        time.sleep(args.sleep)

    # --- append only（過去書換なし・header はファイル新規時のみ） ---
    if rows:
        new_df = pd.DataFrame(rows, columns=COLUMNS)
        write_header = not PANEL.exists()
        new_df.to_csv(PANEL, mode="a", header=write_header, index=False, encoding="utf-8-sig")
        print(f"[write] +{len(new_df)} 行 → {PANEL}", file=sys.stderr)
    else:
        print("[write] 追加行なし（全件 skip もしくは取得失敗）", file=sys.stderr)

    # --- サマリ（T4 ドリフト検知・社内ログ） ---
    print("\n===== サマリ =====", file=sys.stderr)
    print(f" snapshot_date : {snapshot_date}", file=sys.stderr)
    print(f" 対象          : {len(codes)} / 追加 {len(rows)} / skip(既存) {skipped} / 失敗 {failed}", file=sys.stderr)
    if field_health:
        print(" [T4] 欠損フィールド（件数・将来のフィールド名ドリフト検知）:", file=sys.stderr)
        for k, v in sorted(field_health.items(), key=lambda x: -x[1]):
            print(f"   {k}: {v}", file=sys.stderr)
    else:
        print(" [T4] 欠損フィールドなし", file=sys.stderr)


if __name__ == "__main__":
    main()

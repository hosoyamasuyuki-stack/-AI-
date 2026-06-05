#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""日経 暴落監視（X-2 暴落トリガ・2026-06-05）

場中 1 時間毎に日経225の前日比を **info（regularMarketPrice / regularMarketPreviousClose）**
で取得し、`core.market_guard.is_crash`（-5% 以下・range 健全・-60% 超）で暴落を判定する。
暴落検知時は GitHub Actions の step output `crash=true` を立て、workflow（crash_watch.yml）が
price+dashboard を **臨時再生成**（dispatch でなく同ジョブ内で直接実行＝PAT 不要）する。

設計（CEO 確定 2026-06-05・手順書 §3 準拠）:
- **info を使う**（壊れ得る history 日足は使わない＝68,402 事故の真因回避）。
- 取得失敗 / range 外 / floor 未満（破損級）/ prev 不正 は **誤発火させない**（crash=false）。
- 通知は実装しない（ログ＋dashboard 更新のみ）。job は落とさない（常に exit 0）。
- 判定ロジックは `core.market_guard.is_crash`（純関数・単体テスト済）に集約。
"""
import os
import sys

import yfinance as yf

from core.market_guard import is_crash, index_change_pct, CRASH_THRESHOLD_PCT

TICKER = '^N225'


def evaluate():
    """(crash:bool, chg:float|None, detail:str) を返す。例外は握り潰し crash=false。"""
    try:
        info = yf.Ticker(TICKER).info or {}
        now = info.get('regularMarketPrice')
        prev = info.get('regularMarketPreviousClose') or info.get('previousClose')
        if now is None or prev is None:
            return (False, None, 'info に価格欠落')
        now = float(now)
        prev = float(prev)
        crash = is_crash(TICKER, now, prev)
        chg = index_change_pct(now, prev)
        return (crash, chg, f'now={now} prev={prev}')
    except Exception as e:
        return (False, None, f'取得失敗: {type(e).__name__}: {e}')


def main():
    crash, chg, detail = evaluate()
    chg_s = f'{chg:.2f}' if chg is not None else 'NA'
    # 機械可読 1 行（H-1 / stale 監視と同流儀）。
    print(f'CRASH_WATCH_SUMMARY crash={str(crash).lower()} '
          f'nikkei_chg={chg_s} threshold={CRASH_THRESHOLD_PCT} | {detail}')
    if crash:
        print(f'::warning::暴落監視: 日経 前日比 {chg_s}% '
              f'(閾値 {CRASH_THRESHOLD_PCT}%) → dashboard 臨時再生成')
    else:
        print(f'暴落監視: 平常（日経 前日比 {chg_s}%・閾値 {CRASH_THRESHOLD_PCT}%）')
    # GitHub Actions の後続ステップ条件用 output。
    out = os.environ.get('GITHUB_OUTPUT')
    if out:
        with open(out, 'a', encoding='utf-8') as f:
            f.write(f"crash={'true' if crash else 'false'}\n")
    return 0


if __name__ == '__main__':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass
    sys.exit(main())

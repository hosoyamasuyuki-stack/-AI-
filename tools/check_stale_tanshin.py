#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""決算短信キャッシュ stale 定期検知（X1-a・2026-06-05）

協議資料 `協議資料_データ鮮度と更新スケジュール_X1_X2_2026-06-05.md` の提案 X1-a を採用。
賢者GAS `?action=stale_tanshin` を叩き、決算短信キャッシュに stale（鮮度切れ）が
無いかを **毎日 ログのみ** で監視する。

背景: stale 判定はこれまで完全 on-demand（手動で叩いた時だけ）で、定期検知が無かった。
顧客が古い短信で賢者を実行して初めて発覚するリスク（2026-06-03 クレーム 2 件と同根）。
本スクリプトを fetch_tanshin.yml に相乗りし、日次で stale を可視化する。

設計（CEO 方針 2026-06-05）:
- **job は落とさない**（毎日ログのみ・通知は未実装）。本スクリプトは常に exit 0。
- stale_count > 0 / GAS 到達不可 / ok=false は GitHub Actions の ::warning:: で surface。
- H-1 死活監視と同じ「機械可読 1 行」方式（STALE_MONITOR_SUMMARY）を採用し、
  表示文言が将来変わっても yml 側 parse がドリフトしない。
- URL は core/config.py の GAS_URL_KENJA を SSOT として参照（ハードコード drift 防止）。
  GAS_URL_KENJA は env override 可（テスト時に別 URL を差せる）。
"""
import sys

import requests

from core.config import GAS_URL_KENJA

STALE_ENDPOINT = GAS_URL_KENJA + '?action=stale_tanshin'
TIMEOUT_SEC = 60
MAX_LISTED = 20  # ::warning:: に列挙する stale 銘柄の上限（過剰出力抑制）


def _summary(ok, reachable, cached, stale):
    """yml が parse する機械可読 1 行（H-1 と同流儀・文字列ドリフト耐性）。"""
    return (f'STALE_MONITOR_SUMMARY ok={str(ok).lower()} '
            f'reachable={str(reachable).lower()} cached={cached} stale={stale}')


def main():
    # --- 1. GAS 到達 ---
    try:
        resp = requests.get(STALE_ENDPOINT, timeout=TIMEOUT_SEC)
        resp.raise_for_status()
    except Exception as e:
        print(_summary(ok=False, reachable=False, cached=-1, stale=-1))
        print(f'::warning::stale 監視: 賢者GAS に到達できません '
              f'（{type(e).__name__}: {e}）— 一過性なら翌日復旧。継続するなら deployment 点検')
        return 0

    # --- 2. JSON parse ---
    try:
        data = resp.json()
    except Exception:
        print(_summary(ok=False, reachable=True, cached=-1, stale=-1))
        print(f'::warning::stale 監視: GAS 応答が JSON でない（先頭200字: {resp.text[:200]!r}）')
        return 0

    # --- 3. GAS 内部エラー ---
    if not data.get('ok'):
        print(_summary(ok=False, reachable=True, cached=-1, stale=-1))
        print(f"::warning::stale 監視: GAS が ok=false を返却（error={data.get('error')}）")
        return 0

    # --- 4. 正常: stale 件数を評価 ---
    cached = data.get('cached_count', -1)
    stale_count = data.get('stale_count', 0)
    stale = data.get('stale') or []
    print(_summary(ok=True, reachable=True, cached=cached, stale=stale_count))

    if stale_count > 0:
        # code(doc_type days>threshold日) の形で要約列挙
        items = '; '.join(
            f"{s.get('code')}({s.get('doc_type')} {s.get('days_since')}>{s.get('threshold_days')}日)"
            for s in stale[:MAX_LISTED]
        )
        more = '' if stale_count <= MAX_LISTED else f' ほか{stale_count - MAX_LISTED}件'
        print(f'::warning::stale 監視: 決算短信キャッシュに stale {stale_count} 件 '
              f'/ cached {cached} 件 → {items}{more}')
    else:
        print(f'stale 監視: stale 0 件 / cached {cached} 件（健全）')
    return 0


if __name__ == '__main__':
    # Windows ローカル実行時の Japanese 出力を保証（CI=ubuntu は元々 UTF-8）
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass
    sys.exit(main())

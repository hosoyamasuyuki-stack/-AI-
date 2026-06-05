#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""決算短信 手動バックフィル（人間の最終手段＝X-1 stale 検知の Tier 3・2026-06-05）

自動取得（TDnet 直近31日 ＋ EDINET 90日）が **構造的に取れない** 稀な stale 銘柄を、
人間が「銘柄コード＋提出日＋短信PDF URL」を渡して手動で埋める。

背景（盲点の構造）:
- 決算短信は TDnet 専用。TDnet スクレイプは直近 31 日のみ（TDnet 側の上限）。
- 31〜90 日齢の決算短信で、直近 EDINET 法定書類（有報/四半期/半期）も無い銘柄は、
  日次取得でも EDINET 補完でも取れず stale のまま残る（例: 6594 ニデック通期短信）。
- こうした稀なケースは「人間が最終手段で対応」（CEO 2026-06-05）。本ツールがその手段。

設計:
- 機械作業（PDF 取得・テキスト抽出・Sheet 投入）は自動化し、人間は「正しい短信を選ぶ」
  判断だけを担う（PDF URL と提出日を渡す）。
- 既存 `fetch_tanshin.py` の `extract_pdf_text`（%PDF 検証・MIN_TEXT_CHARS ガード内蔵）と
  `upsert`（50000字 truncate・RAW 投入・最新のみ）を再利用＝挙動を日次取得と完全一致させる。
- 通常は `backfill_tanshin.yml`（手動 dispatch）から env 経由で呼ぶ（ローカル creds 不要）。

使い方:
- ワークフロー: Actions → "Backfill Tanshin (manual)" → code/submit_date/pdf_url/title を入力 → Run
- ローカル: python tools/backfill_tanshin.py <code> <submit_date YYYY-MM-DD> <pdf_url> [title]
"""
import os
import sys

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

from core.auth import get_spreadsheet  # noqa: E402
from tools.fetch_tanshin import extract_pdf_text, upsert, ensure_cache_sheet  # noqa: E402


def _arg(idx, env_key, default=None):
    """argv 優先・無ければ env（ワークフローは env で渡す）。"""
    if len(sys.argv) > idx and sys.argv[idx].strip():
        return sys.argv[idx].strip()
    return (os.environ.get(env_key) or default)


def main():
    code = _arg(1, 'BF_CODE')
    submit_date = _arg(2, 'BF_DATE')
    pdf_url = _arg(3, 'BF_URL')
    title = _arg(4, 'BF_TITLE', '')

    if not code or not submit_date or not pdf_url:
        print('::error::backfill: code / submit_date / pdf_url は必須です '
              '(argv または BF_CODE/BF_DATE/BF_URL)')
        return 1
    code = str(code).strip()
    submit_date = str(submit_date).strip()
    # 提出日フォーマット検証（upsert は文字列比較で最新判定するため YYYY-MM-DD 厳守）。
    import re
    if not re.fullmatch(r'\d{4}-\d{2}-\d{2}', submit_date):
        print(f'::error::backfill: submit_date は YYYY-MM-DD 形式で指定（受領: {submit_date!r}）')
        return 1
    if not title:
        title = f'[手動backfill] {code} 決算短信 {submit_date}'

    print(f'=== 手動バックフィル: {code} / {submit_date} ===')
    print(f'  URL  : {pdf_url}')
    print(f'  title: {title}')

    text, _ = extract_pdf_text(pdf_url, code=code, submit_date=submit_date, sb=None)
    if not text:
        print('::error::backfill: PDF からテキストを抽出できませんでした '
              '（%PDF でない/画像PDF/極端に短い/DL失敗）。URL を確認してください')
        return 1
    print(f'  抽出 {len(text):,} 字')

    ss = get_spreadsheet()
    ws = ensure_cache_sheet(ss)
    upsert(ws, code, submit_date, title, text, '')
    print(f'BACKFILL_RESULT ok=true code={code} submit_date={submit_date} chars={len(text)}')
    print('  → 反映確認: ?action=stale_tanshin で当該銘柄が stale から外れたかを見る')
    return 0


if __name__ == '__main__':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass
    sys.exit(main())

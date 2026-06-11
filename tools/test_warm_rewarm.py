#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""段階3 差分検知（REWARM_SUMMARY）+ 事前ウォーム（warm_kenja パーサ）の単体テスト。

ローカル実フェッチ（Google Sheets / TDnet / EDINET / GAS）に依存しない。
- build_rewarm_summary（純関数）の書式と、H-1 死活監視（MONITOR_SUMMARY grep）への
  無干渉を固定する。
- warm_kenja のパーサは committed ai_dashboard_v13.html（リポジトリ実物）を入力にした
  統合テスト＝「顧客がクリックできる銘柄と同一の scores を抽出できる」を保証する。

実行: cd <repo> && PYTHONPATH=. python tools/test_warm_rewarm.py
"""
import re
import sys

from tools.fetch_tanshin import build_rewarm_summary
from tools import warm_kenja

# fetch_tanshin.yml の死活監視が使う grep パターン（test_monitor_summary.py と同一定義）
YML_SUMMARY_RE = re.compile(r'MONITOR_SUMMARY new=[0-9]+ err=[0-9]+ coverage=[0-9.]+')
REWARM_RE = re.compile(
    r'^REWARM_SUMMARY rewarm_count=([0-9]+) rewarm_codes=([0-9A-Za-z,]+|none) dry_run=([01])$')

failures = []


def check(cond, label):
    print(('  PASS  ' if cond else '  FAIL  ') + label)
    if not cond:
        failures.append(label)


def test_rewarm_summary_format():
    line = build_rewarm_summary({'6920', '130A', '8136'}, False)
    m = REWARM_RE.match(line)
    check(m is not None, f'REWARM 書式: {line}')
    check(m and m.group(1) == '3', 'rewarm_count=3')
    check(m and m.group(2) == '130A,6920,8136', 'codes はソート済（130A 英字コード対応）')
    check(m and m.group(3) == '0', 'dry_run=0')


def test_rewarm_summary_empty_and_dry():
    line = build_rewarm_summary(set(), True)
    m = REWARM_RE.match(line)
    check(m is not None, f'空+dry 書式: {line}')
    check(m and m.group(1) == '0' and m.group(2) == 'none' and m.group(3) == '1',
          '空集合 -> count=0 codes=none dry_run=1')


def test_rewarm_does_not_interfere_with_monitor():
    line = build_rewarm_summary({'6920'}, False)
    check(YML_SUMMARY_RE.search(line) is None,
          'REWARM 行は MONITOR_SUMMARY grep にマッチしない（H-1 無干渉）')
    check(line.startswith('REWARM_SUMMARY '), '独立プレフィックス')


def test_warm_parsers_against_committed_html():
    html = warm_kenja.load_html()
    url = warm_kenja.parse_gas_url(html)
    check(url.startswith('https://script.google.com/macros/s/'), f'GAS URL 抽出: {url[:60]}...')
    targets = warm_kenja.parse_targets(html)
    check(len(targets) >= 100, f'対象 {len(targets)}社 >= 100（保有51+監視69+Top75 規模）')
    codes = {t['code'] for t in targets}
    check(len(codes) == len(targets), '重複なし（保有/監視/Top75 の重複は初出採用）')
    sample = targets[0]
    for k in ('code', 'name', 'v42', 'rank', 'shortScore', 'midScore', 's1', 's2', 's3'):
        check(k in sample, f'payload キー {k} あり')
    # midScore は v4.3 式文字列（顧客 _curMid=note と同一・数値ではない）
    with_v43 = sum(1 for t in targets if str(t['midScore']).startswith('v4.3'))
    check(with_v43 >= len(targets) * 0.9, f'midScore は v4.3 文字列（{with_v43}/{len(targets)}）')
    # payload 形が顧客版（ai_dashboard_v13.html:3113）と同形・uid を含まない
    p = warm_kenja.build_payload(sample)
    check(set(p.keys()) == {'secCode', 'name', 'scores'}, 'payload トップキーは secCode/name/scores のみ')
    check('uid' not in p and 'uid' not in p['scores'], 'uid を絶対に含まない（中立性）')
    check(set(p['scores'].keys()) == {'v42', 'rank', 's1', 's2', 's3', 'shortScore', 'midScore'},
          'scores キーは顧客 payload と完全一致')


def main():
    for fn in (test_rewarm_summary_format, test_rewarm_summary_empty_and_dry,
               test_rewarm_does_not_interfere_with_monitor,
               test_warm_parsers_against_committed_html):
        print(f'## {fn.__name__}')
        fn()
    print(f'\n==== {"FAIL " + str(len(failures)) if failures else "ALL PASS"} ====')
    return 1 if failures else 0


if __name__ == '__main__':
    sys.exit(main())

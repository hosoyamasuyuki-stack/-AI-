#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""賢者キャッシュ 事前ウォーム（段階1/3・2026-06-11）

顧客が「賢者の審判」を押した時に常にキャッシュ即返し（3〜8秒）になるよう、
裏で賢者 GAS (doPost) を叩いて分析結果をキャッシュに着座させる。

設計の核（正本: にこにこ本舗/LISA販売/設計/
仕様書_賢者_事前ウォーム＋決算駆動差分更新_全体実装計画_2026-06-11.md）:

- **uid を絶対に送らない**: doPost の DB 書込（消費 increment / earnings_analyses INSERT /
  プロファイル取得）は全て if(uid) ガード配下＝本ツールは顧客カウント・人気ランキング・
  Supabase に一切触れない（中立性・実コード突合済・計画 §3）。
- **scores は committed ダッシュボード HTML から抽出**: 顧客クリックの payload は
  showD 引数（v42/rank/shortScore/midScore=v4.3 文字列）+ STOCK_SCORES(s1/s2/s3) が一次
  ソース（ai_dashboard_v13.html）。同じ HTML から読む＝warm 生成分析が顧客クリック生成と
  完全同一（J8 scores フル供給・W6 同一性を構造で保証）。市場値の再現も認証情報も不要。
- **KENJA_GAS_URL も同 HTML から抽出**（設定ドリフトなし・単一ソース）。
- **並列度1固定**（T-7: setKenjaCache はロック無し・共有 LIVE キャッシュの競合書込を防ぐ）。
- リトライは銘柄あたり最大2試行（GAS 内 B-4 リトライと積算で上限・T-5）。
- 成功 = ok:true かつ incomplete 無し（incomplete は GAS がキャッシュしない＝未着座）。
- cache_hit=true は「既に温かい」＝ skipped（AI は走っていない＝コスト 0）。

使い方:
  python tools/warm_kenja.py --all                 # HTML 表示の全銘柄（保有+監視+Top75）
  python tools/warm_kenja.py --codes 6920,8136     # 指定銘柄のみ（REWARM_SUMMARY の入力）
  python tools/warm_kenja.py --all --limit 3       # スモーク（先頭3銘柄）
  python tools/warm_kenja.py --all --dry-run       # 対象列挙のみ（GAS を叩かない・コスト0）

機械可読出力: WARM_SUMMARY ok=N skipped=N fail=N total=N fail_codes=...
（MONITOR_SUMMARY / REWARM_SUMMARY とは独立行・既存監視 grep に無干渉）
"""
import argparse
import json
import re
import sys
import time
from pathlib import Path

try:
    import requests
except ImportError:  # ローカルで requests 無し環境でも --dry-run は動かす
    requests = None

REPO_ROOT = Path(__file__).resolve().parent.parent
DASHBOARD_HTML = REPO_ROOT / 'ai_dashboard_v13.html'

# 銘柄間スリープ（秒）。GAS/OpenAI/Sheets のレート配慮（fetch_tanshin の 2 秒に準拠+余裕）
SLEEP_BETWEEN = 3
# 1銘柄あたり最大試行回数（GAS 内 B-4 リトライと積算で上限を絞る・T-5）
MAX_ATTEMPTS = 2
# GAS 応答待ち上限（秒）。実測 40-70 秒 + 余裕。dashboard 側 AbortController は 180 秒
REQUEST_TIMEOUT = 240

# showD('code','name','sect',tot,'rank',shortS,'','','rank','sb','mb','lb','nt','days',midS)
# 生成元: generate_dashboard.py:960-963 / 1041-1058（f-string 固定形式）
SHOWD_RE = re.compile(
    r"showD\('([^']*)','([^']*)','([^']*)',"      # 1=code 2=name 3=sect
    r"([0-9.+-]+),'([^']*)',([0-9.+-]+),"          # 4=tot(v42) 5=rank 6=shortScore
    r"'[^']*','[^']*','[^']*',"                    # sArr,mArr,lRk（未使用）
    r"'[^']*','[^']*','[^']*','([^']*)',"          # sb,mb,lb, 7=nt(midScore=v4.3文字列)
    r"'[^']*',([0-9.+-]+)\)"                       # days, 8=midS(数値・payload未使用)
)
STOCK_SCORES_RE = re.compile(r'STOCK_SCORES\s*=\s*(\{.*?\});', re.DOTALL)
GAS_URL_RE = re.compile(r"KENJA_GAS_URL\s*=\s*'(https://script\.google\.com/[^']+)'")


def load_html(path=None):
    p = Path(path) if path else DASHBOARD_HTML
    return p.read_text(encoding='utf-8')


def parse_gas_url(html):
    m = GAS_URL_RE.search(html)
    if not m:
        raise RuntimeError('KENJA_GAS_URL が HTML から抽出できない（形式ドリフト）')
    return m.group(1)


def parse_stock_scores(html):
    m = STOCK_SCORES_RE.search(html)
    if not m:
        raise RuntimeError('STOCK_SCORES が HTML から抽出できない（形式ドリフト）')
    return json.loads(m.group(1))


def parse_targets(html):
    """HTML の showD 行から（顧客がクリックできる）銘柄と scores を抽出する。

    返り値: list[dict] code/name/v42/rank/shortScore/midScore(s1/s2/s3 は STOCK_SCORES から)。
    顧客 payload（ai_dashboard_v13.html:3113）と同一キー・同一値になるように作る。
    """
    scores_map = parse_stock_scores(html)
    seen = set()
    targets = []
    for m in SHOWD_RE.finditer(html):
        code = m.group(1)
        if not code or code in seen:
            continue  # 保有/監視/Top75 で重複し得る・初出を採用
        seen.add(code)
        sc = scores_map.get(code, [0, 0, 0])
        # e() エスケープ（' → &#39;）を復元（ブラウザは属性パース時に復元して JS に渡すため）
        nt = m.group(7).replace('&#39;', "'")
        targets.append({
            'code': code,
            'name': m.group(2).replace('&#39;', "'"),
            'v42': float(m.group(4)),
            'rank': m.group(5),
            'shortScore': float(m.group(6)),
            'midScore': nt,
            's1': sc[0] if len(sc) > 0 else 0,
            's2': sc[1] if len(sc) > 1 else 0,
            's3': sc[2] if len(sc) > 2 else 0,
        })
    if not targets:
        raise RuntimeError('showD 行が HTML から 1 件も抽出できない（形式ドリフト）')
    return targets


def build_payload(t, force=False):
    """顧客 payload（ai_dashboard_v13.html:3113）と同形。uid は絶対に載せない。

    force=True は forceRefresh を付ける（GAS 側で読込のみスキップ・書込は実施＝強制作り直し）。
    隔週フル再ウォーム（保険・CEO 2026-06-11 採用）専用。顧客は送らないパラメータ。
    """
    p = {
        'secCode': t['code'],
        'name': t['name'],
        'scores': {
            'v42': t['v42'], 'rank': t['rank'],
            's1': t['s1'], 's2': t['s2'], 's3': t['s3'],
            'shortScore': t['shortScore'], 'midScore': t['midScore'],
        },
    }
    if force:
        p['forceRefresh'] = True
    return p


def warm_one(gas_url, t, force=False):
    """1銘柄をウォーム。返り値 (status, detail)。status: ok / skipped / fail。"""
    last_err = ''
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            r = requests.post(gas_url, json=build_payload(t, force),
                              timeout=REQUEST_TIMEOUT, allow_redirects=True)
            data = r.json()
            if data.get('ok') and not data.get('incomplete'):
                if data.get('cache_hit'):
                    return 'skipped', f'cache_hit age={data.get("cache_age_ms", "?")}ms'
                return 'ok', (f'ds={data.get("dataSource", "?")} '
                              f'verdict={(data.get("analysis") or {}).get("verdict", "?")} '
                              f'elapsed={data.get("elapsed_ms", "?")}ms')
            last_err = ('incomplete' if data.get('ok')
                        else str(data.get('error', 'unknown'))[:120])
        except Exception as e:
            last_err = str(e)[:120]
        if attempt < MAX_ATTEMPTS:
            time.sleep(5)
    return 'fail', last_err


def main():
    ap = argparse.ArgumentParser(description='賢者キャッシュ 事前ウォーム（uidなし＝本番DB非接触）')
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument('--all', action='store_true', help='HTML 表示の全銘柄（保有+監視+Top75）')
    g.add_argument('--codes', help='対象コード（カンマ区切り・REWARM_SUMMARY の入力）')
    ap.add_argument('--limit', type=int, help='先頭N件のみ（スモーク用）')
    ap.add_argument('--force', action='store_true',
                    help='保存が新しくても作り直す（隔週フル再ウォーム=保険運転用・forceRefresh送信）')
    ap.add_argument('--dry-run', action='store_true', help='対象列挙のみ（GAS を叩かない）')
    ap.add_argument('--html-file', help='ダッシュボード HTML のパス（既定: リポジトリの committed HTML）')
    args = ap.parse_args()

    html = load_html(args.html_file)
    gas_url = parse_gas_url(html)
    targets = parse_targets(html)
    print(f'HTML 抽出: 対象 {len(targets)}社 / GAS={gas_url[:60]}...')

    if args.codes:
        want = {c.strip().upper() for c in args.codes.split(',') if c.strip()}
        if 'NONE' in want:
            want.discard('NONE')
        targets = [t for t in targets if t['code'].upper() in want]
        missing = sorted(want - {t['code'].upper() for t in targets})
        if missing:
            # HTML 非表示銘柄＝顧客がクリックできない＝ウォーム不要（scores 一次ソースも無い）
            print(f'  [スキップ] HTML 非表示のため対象外: {", ".join(missing)}')
    if args.limit:
        targets = targets[:args.limit]
    print(f'ウォーム対象: {len(targets)}社')

    if args.dry_run:
        for t in targets:
            print(f"  [{t['code']}] {t['name']} v42={t['v42']} rank={t['rank']}")
        print(f'WARM_SUMMARY ok=0 skipped=0 fail=0 total={len(targets)} fail_codes=none dry_run=1')
        return 0

    if requests is None:
        print('::error::requests 未インストール（pip install requests）')
        return 1

    if args.force:
        print('forceRefresh モード: 全対象を作り直す（隔週保険運転）')
    ok = skipped = 0
    fails = []
    for i, t in enumerate(targets, 1):
        status, detail = warm_one(gas_url, t, args.force)
        print(f"  [{i}/{len(targets)}] {t['code']} {t['name']}: {status} ({detail})", flush=True)
        if status == 'ok':
            ok += 1
        elif status == 'skipped':
            skipped += 1
        else:
            fails.append(t['code'])
        time.sleep(SLEEP_BETWEEN)  # T-7: 直列固定+レート配慮

    fail_codes = ','.join(fails) if fails else 'none'
    print(f'WARM_SUMMARY ok={ok} skipped={skipped} fail={len(fails)} '
          f'total={len(targets)} fail_codes={fail_codes} dry_run=0')
    if fails:
        # job は緑のまま可視化（H-1 思想: 監視は機械可読行・::warning:: で浮上）
        print(f'::warning::賢者ウォーム失敗 {len(fails)}社: {fail_codes} — '
              f'incomplete 連続銘柄は要調査（T-5/T-13）')
    return 0


if __name__ == '__main__':
    sys.exit(main())

#!/usr/bin/env python3
"""
health_check.py
毎日 7:45 JST に走り、全ワークフローの直近実行を点検する。
- 失敗があれば exit 1 → workflow が失敗扱い → GitHub からメール通知が飛ぶ
- 期待頻度を超えて古い場合も exit 1
- 結果を system_health.json と system_health.md に書き出してリポジトリにコミット
"""

import os
import sys
import json
import base64
from datetime import datetime, timezone, timedelta
import urllib.request
import urllib.error

REPO = 'hosoyamasuyuki-stack/-AI-'
TOKEN = os.environ.get('GITHUB_TOKEN', '')
NOW = datetime.now(timezone.utc)
JST = timezone(timedelta(hours=9))

# 各ワークフローの「最終成功からの許容経過時間（時間）」
# 余裕を持たせて schedule 遅延 + 連休を吸収
EXPECTATIONS = {
    'daily_price_update.yml':   {'max_hours': 30,   'label': '株価更新'},
    'daily_update.yml':         {'max_hours': 80,   'label': 'FRED指標'},
    'weekly_update.yml':        {'max_hours': 200,  'label': '週次フル再計算'},
    'dashboard_update.yml':     {'max_hours': 200,  'label': 'ダッシュボード生成'},
    'full_scan.yml':            {'max_hours': 200,  'label': '全市場スキャン'},
    'generate_handover.yml':    {'max_hours': 200,  'label': 'handover.txt'},
    'verify.yml':               {'max_hours': 200,  'label': 'verify検証'},
    'sheet_manager.yml':        {'max_hours': 800,  'label': 'シート管理（月次）'},
    'fetch_tanshin.yml':        {'max_hours': 200,  'label': 'TDnet 決算短信取得'},
    # manage_stock.yml は workflow_dispatch ユーザー操作のみ・不正コード入力で失敗が正常 → 除外
}


def api_get(path):
    req = urllib.request.Request(
        f'https://api.github.com{path}',
        headers={
            'Authorization': f'Bearer {TOKEN}',
            'Accept': 'application/vnd.github+json',
        },
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def latest_run(wf_file):
    data = api_get(f'/repos/{REPO}/actions/workflows/{wf_file}/runs?per_page=1')
    runs = data.get('workflow_runs', [])
    return runs[0] if runs else None


def check_one(wf_file, expect):
    run = latest_run(wf_file)
    if not run:
        return {'wf': wf_file, 'label': expect['label'], 'status': 'NO_HISTORY', 'ok': False, 'detail': '実行履歴なし'}

    created = datetime.fromisoformat(run['created_at'].replace('Z', '+00:00'))
    hours_ago = (NOW - created).total_seconds() / 3600
    conclusion = run['conclusion']
    too_old = hours_ago > expect['max_hours']

    if conclusion == 'success' and not too_old:
        verdict = 'OK'
        ok = True
    elif conclusion == 'success' and too_old:
        verdict = 'STALE'
        ok = False
    elif conclusion == 'failure':
        verdict = 'FAILURE'
        ok = False
    elif conclusion is None and run['status'] == 'in_progress':
        verdict = 'RUNNING'
        ok = True
    else:
        verdict = f'OTHER({conclusion})'
        ok = False

    return {
        'wf': wf_file,
        'label': expect['label'],
        'status': verdict,
        'ok': ok,
        'last_run_jst': created.astimezone(JST).strftime('%Y-%m-%d %H:%M JST'),
        'hours_ago': round(hours_ago, 1),
        'max_hours': expect['max_hours'],
        'conclusion': conclusion,
        'url': run['html_url'],
    }


def commit_file(path, content):
    """Contents API でファイルをコミット"""
    url = f'/repos/{REPO}/contents/{path}'
    try:
        existing = api_get(url)
        sha = existing.get('sha')
    except urllib.error.HTTPError as e:
        if e.code == 404:
            sha = None
        else:
            raise
    body = {
        'message': f'health_check: 自動更新 {NOW.astimezone(JST).strftime("%Y-%m-%d %H:%M JST")} [skip ci]',
        'content': base64.b64encode(content.encode('utf-8')).decode('ascii'),
    }
    if sha:
        body['sha'] = sha
    req = urllib.request.Request(
        f'https://api.github.com{url}',
        data=json.dumps(body).encode('utf-8'),
        method='PUT',
        headers={
            'Authorization': f'Bearer {TOKEN}',
            'Accept': 'application/vnd.github+json',
            'Content-Type': 'application/json',
        },
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.status in (200, 201)


def main():
    results = [check_one(wf, exp) for wf, exp in EXPECTATIONS.items()]

    all_ok = all(r['ok'] for r in results)
    failed = [r for r in results if not r['ok']]
    total = len(results)
    ng = len(failed)

    # JSON 出力
    payload = {
        'checked_at_utc': NOW.isoformat(),
        'checked_at_jst': NOW.astimezone(JST).strftime('%Y-%m-%d %H:%M JST'),
        'overall': 'OK' if all_ok else 'NG',
        'ok_count': total - ng,
        'ng_count': ng,
        'total': total,
        'results': results,
    }
    json_str = json.dumps(payload, ensure_ascii=False, indent=2)

    # Markdown 出力
    md = []
    md.append(f'# システム健康診断レポート')
    md.append('')
    md.append(f'**実行時刻**: {payload["checked_at_jst"]}')
    md.append(f'**総合判定**: {"✅ 全 OK" if all_ok else f"❌ {ng}/{total} 件に問題あり"}')
    md.append('')
    md.append('| 項目 | 直近実行 | 経過 | 上限 | 結果 | URL |')
    md.append('|---|---|---|---|---|---|')
    for r in results:
        emoji = '✅' if r['ok'] else '❌'
        last = r.get('last_run_jst', '—')
        ha = r.get('hours_ago', '—')
        mh = r.get('max_hours', '—')
        url = r.get('url', '')
        md.append(f'| {r["label"]} ({r["wf"]}) | {last} | {ha}h | {mh}h | {emoji} {r["status"]} | [run]({url}) |')
    md.append('')
    if ng > 0:
        md.append('## ❌ 要対応項目')
        md.append('')
        for r in failed:
            md.append(f'- **{r["label"]}** ({r["wf"]}): {r["status"]}')
            md.append(f'  - 最終実行: {r.get("last_run_jst", "—")} ({r.get("hours_ago", "—")}h前 / 上限 {r.get("max_hours", "—")}h)')
            md.append(f'  - URL: {r.get("url", "")}')
        md.append('')
    md.append('---')
    md.append('*このレポートは health_check ワークフローが毎朝自動生成しています。*')
    md_str = '\n'.join(md)

    # コンソール出力（Actions ログに残す）
    print(json_str)
    print()
    print(md_str)

    # ファイルコミット
    if TOKEN:
        commit_file('system_health.json', json_str)
        commit_file('system_health.md', md_str)
        print('\n✅ system_health.json / system_health.md をコミットしました')

    # 異常があれば exit 1 → ワークフロー失敗扱い → GitHub からメール通知
    if not all_ok:
        print(f'\n❌ {ng}/{total} 件に問題あり。Actions のメール通知を確認してください。')
        sys.exit(1)
    print(f'\n✅ 全 {total} 件正常稼働。')


if __name__ == '__main__':
    main()

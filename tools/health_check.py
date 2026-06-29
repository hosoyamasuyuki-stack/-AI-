#!/usr/bin/env python3
"""
health_check.py
毎日 7:45 JST に走り、全ワークフローの直近実行を点検する。
- 失敗があれば exit 1 → workflow が失敗扱い → GitHub からメール通知が飛ぶ
- 期待頻度を超えて古い場合も exit 1
- ワークフローの起動成功だけでなく、ダッシュボードHTMLが実際に main へコミットされた
  時刻（鮮度）も点検する（check_dashboard_freshness・2026-06-29 追加）
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
# 監視対象は本番ブランチの run のみ。開発ブランチ上の workflow_dispatch 失敗を
# 本番異常と誤検知した事案（2026-06-09 claude/systemb-edinet-sweep の fetch_tanshin
# dispatch 失敗 → 06-10 朝の健診 NG）の再発防止。schedule run の head_branch は常に
# main のため、main 限定でも NO_HISTORY 側の誤判定は起きない（全 10 workflow 実測済）。
MONITOR_BRANCH = 'main'
TOKEN = os.environ.get('GITHUB_TOKEN', '')
NOW = datetime.now(timezone.utc)
JST = timezone(timedelta(hours=9))

# 各ワークフローの「最終成功からの許容経過時間（時間）」
# 余裕を持たせて schedule 遅延 + 連休を吸収
EXPECTATIONS = {
    'daily_price_update.yml':   {'max_hours': 30,   'label': '株価更新（朝7:30）'},
    # 昼12:30 / 夕16:00 の株価更新（2026-06-29 追加）。両方とも「平日のみ」cron のため、
    # 日本の祝日（月曜祝日で3連休→次の取引日まで約91h／年末年始は最長約150h）を吸収する
    # 必要があり、誤 STALE を避けるため上限を 200h に（既存の平日系 fetch_tanshin 等と同思想）。
    # ・FAILURE（失敗結論）は上限に関係なく即検知 → メール通知が飛ぶ。
    # ・停止の早期検知は下の check_dashboard_freshness（コミット鮮度・約30h）が担う。
    # ・GitHub cron 予備が取引日に（遅れても）発火するため、200h 超過は複数取引日にわたる
    #   完全停止＝真の異常を意味する。
    'midday_price_update.yml':  {'max_hours': 200,  'label': '株価更新（昼12:30）'},
    'close_price_update.yml':   {'max_hours': 200,  'label': '株価更新（夕16:00）'},
    'daily_update.yml':         {'max_hours': 80,   'label': 'FRED指標'},
    'weekly_update.yml':        {'max_hours': 200,  'label': '週次フル再計算'},
    'dashboard_update.yml':     {'max_hours': 200,  'label': 'ダッシュボード生成'},
    'full_scan.yml':            {'max_hours': 200,  'label': '全市場スキャン'},
    'generate_handover.yml':    {'max_hours': 200,  'label': 'handover.txt'},
    'verify.yml':               {'max_hours': 200,  'label': 'verify検証'},
    'sheet_manager.yml':        {'max_hours': 800,  'label': 'シート管理（月次）'},
    'fetch_tanshin.yml':        {'max_hours': 200,  'label': 'TDnet 決算短信取得'},
    'monthly_learning.yml':     {'max_hours': 800,  'label': '月次学習バッチ'},
    # 800h = 33 日（月次実行 cron `0 3 1 * *` の余裕値・連休時 schedule 遅延を吸収）
    # 追加日: 2026-05-07（PROCEDURE_SELF_LEARNING_IMPROVEMENT_2026-05-07.md A-1）
    # manage_stock.yml は workflow_dispatch ユーザー操作のみ・不正コード入力で失敗が正常 → 除外
}

# 顧客に見えるダッシュボード生成物の「鮮度」チェック（2026-06-29 追加・敵対検証A）
# run の conclusion=success だけ見ると「差分なし＝成功・無コミット」や yfinance 障害時の
# 無通知フォールバックで“中身が古いまま success”を取り逃す。実際に main へコミットされた
# ダッシュボードHTMLの最終コミット時刻を見て、本当に更新されているかを確認する。
# 朝の daily_price_update が土日祝も毎日 HTML を再生成＆コミットするため、コミット時刻は
# 連休に非依存で毎日進む → 30h 超は「全価格更新（朝含む）が止まった」＝重大異常。
DASHBOARD_FILE = 'ai_dashboard_v13.html'
DASHBOARD_MAX_HOURS = 30


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
    data = api_get(f'/repos/{REPO}/actions/workflows/{wf_file}/runs?per_page=1&branch={MONITOR_BRANCH}')
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


def check_dashboard_freshness():
    """ダッシュボードHTMLが実際に main へコミットされた時刻で鮮度を判定する（敵対検証A）。
    workflow の起動成功だけでなく、生成物が main に反映され続けているかを見る。"""
    label = 'ダッシュボード鮮度'
    try:
        data = api_get(
            f'/repos/{REPO}/commits?path={DASHBOARD_FILE}&sha={MONITOR_BRANCH}&per_page=1'
        )
    except Exception as e:
        # API 一時障害等。ワークフロー本体の check_one も同 API 障害で失敗するため整合的。
        return {'wf': DASHBOARD_FILE, 'label': label, 'status': 'CHECK_ERROR',
                'ok': False, 'detail': str(e)}
    if not data:
        return {'wf': DASHBOARD_FILE, 'label': label, 'status': 'NO_HISTORY',
                'ok': False, 'detail': 'コミット履歴なし'}

    committed = datetime.fromisoformat(
        data[0]['commit']['committer']['date'].replace('Z', '+00:00')
    )
    hours_ago = (NOW - committed).total_seconds() / 3600
    too_old = hours_ago > DASHBOARD_MAX_HOURS
    return {
        'wf': DASHBOARD_FILE,
        'label': label,
        'status': 'STALE' if too_old else 'OK',
        'ok': not too_old,
        'last_run_jst': committed.astimezone(JST).strftime('%Y-%m-%d %H:%M JST'),
        'hours_ago': round(hours_ago, 1),
        'max_hours': DASHBOARD_MAX_HOURS,
        'conclusion': 'committed',
        'url': data[0].get('html_url', ''),
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
    # 生成物の鮮度チェックを末尾に追加（起動成功だけでは取り逃すサイレント停止対策・敵対検証A）
    results.append(check_dashboard_freshness())

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

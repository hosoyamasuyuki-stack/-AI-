"""
check_api_keys.py - APIキー健全性チェッカー

全APIキーの設定状態と接続テストを一括実行。
セッション開始時・デプロイ前に実行して問題を早期発見する。

使い方:
  ローカル:  python check_api_keys.py
  Actions:   各workflowのステップ冒頭に追加可能
"""

import os
import sys
import json
import requests

# ============================================================
# APIキー台帳（唯一の真実の源）
# ============================================================
API_KEYS = {
    'GOOGLE_CREDENTIALS': {
        'env_var': 'GOOGLE_CREDENTIALS',
        'required_by': ['weekly_update', 'daily_price_update', 'daily_update',
                        'generate_dashboard', 'full_scan', 'manage_stock',
                        'sheet_manager', 'verify', 'record_changelog'],
        'source': 'Google Cloud Console > Service Accounts > Keys',
        'type': 'json',
    },
    'SPREADSHEET_ID': {
        'env_var': 'SPREADSHEET_ID',
        'required_by': ['全スクリプト'],
        'source': 'Google Sheets URL',
        'type': 'string',
    },
    'JQUANTS_API_KEY': {
        'env_var': 'JQUANTS_API_KEY',
        'required_by': ['weekly_update', 'daily_price_update', 'full_scan',
                        'manage_stock', 'verify'],
        'source': 'https://jpx-jquants.com/ > マイページ > APIキー',
        'type': 'string',
        'test_url': 'https://api.jquants.com/v2/equities/bars/daily',
    },
    'FRED_API_KEY': {
        'env_var': 'FRED_API_KEY',
        'required_by': ['daily_update', 'generate_dashboard'],
        'source': 'https://fred.stlouisfed.org/docs/api/api_key.html',
        'type': 'string',
        'test_url': 'https://api.stlouisfed.org/fred/series?series_id=VIXCLS&api_key={key}&file_type=json',
    },
    'GITHUB_TOKEN': {
        'env_var': 'GITHUB_TOKEN',
        'required_by': ['full_update (push)', 'GASプロキシ'],
        'source': 'https://github.com/settings/tokens (Classic, repo+workflow)',
        'type': 'string',
    },
    'EDINET_API_KEY': {
        'env_var': 'EDINET_API_KEY',
        'required_by': ['賢者の審判 (GAS経由)'],
        'source': 'https://disclosure.edinet-fsa.go.jp/',
        'type': 'string',
        'note': 'GASスクリプトプロパティに設定。GitHub Secretsには不要。',
    },
    'OPENAI_API_KEY': {
        'env_var': 'OPENAI_API_KEY',
        'required_by': ['賢者の審判 (GAS経由)'],
        'source': 'https://platform.openai.com/api-keys',
        'type': 'string',
        'note': 'GASスクリプトプロパティ「kenja-rich-api」に設定。',
    },
}

# ============================================================
# チェック実行
# ============================================================
def check_all():
    print("=" * 60)
    print("APIキー健全性チェック")
    print("=" * 60)

    errors = []
    warnings = []

    for name, info in API_KEYS.items():
        val = os.environ.get(info['env_var'], '')
        status = '---'

        if not val:
            status = '❌ 未設定'
            if info.get('note'):
                warnings.append(f"{name}: 未設定（{info['note']}）")
            else:
                errors.append(f"{name}: 未設定！ 取得先: {info['source']}")
        elif info['type'] == 'json':
            try:
                json.loads(val)
                status = '✅ JSON有効'
            except json.JSONDecodeError:
                status = '❌ JSON無効'
                errors.append(f"{name}: JSONパースエラー")
        elif len(val) < 5:
            status = '⚠️ 短すぎる'
            warnings.append(f"{name}: 値が短すぎます（{len(val)}文字）")
        else:
            status = f'✅ 設定済 ({len(val)}文字)'

        used_by = ', '.join(info['required_by'][:3])
        if len(info['required_by']) > 3:
            used_by += f' 他{len(info["required_by"])-3}件'
        print(f"  {name:25s} {status:20s} 使用: {used_by}")

    # 接続テスト
    print()
    print("接続テスト:")

    # J-Quants
    jq_key = os.environ.get('JQUANTS_API_KEY', '')
    if jq_key:
        try:
            r = requests.get(
                'https://api.jquants.com/v2/equities/bars/daily',
                headers={'x-api-key': jq_key},
                params={'code': '72030', 'date': '2026-03-28'},
                timeout=10
            )
            if r.status_code == 200:
                print(f"  J-Quants API:  ✅ 正常 (HTTP {r.status_code})")
            else:
                print(f"  J-Quants API:  ❌ HTTP {r.status_code} {r.text[:80]}")
                errors.append(f"J-Quants API: HTTP {r.status_code}")
        except Exception as e:
            print(f"  J-Quants API:  ❌ {e}")
            errors.append(f"J-Quants API: {e}")
    else:
        print("  J-Quants API:  ⏭️ スキップ（キー未設定）")

    # FRED
    fred_key = os.environ.get('FRED_API_KEY', '')
    if fred_key:
        try:
            r = requests.get(
                f'https://api.stlouisfed.org/fred/series?series_id=VIXCLS&api_key={fred_key}&file_type=json',
                timeout=10
            )
            if r.status_code == 200:
                print(f"  FRED API:      ✅ 正常 (HTTP {r.status_code})")
            else:
                print(f"  FRED API:      ❌ HTTP {r.status_code}")
                errors.append(f"FRED API: HTTP {r.status_code}")
        except Exception as e:
            print(f"  FRED API:      ❌ {e}")

    # サマリー
    print()
    print("=" * 60)
    if errors:
        print(f"❌ エラー {len(errors)}件:")
        for e in errors:
            print(f"   - {e}")
    if warnings:
        print(f"⚠️ 警告 {len(warnings)}件:")
        for w in warnings:
            print(f"   - {w}")
    if not errors and not warnings:
        print("✅ 全APIキー正常")

    print("=" * 60)
    return len(errors)


if __name__ == '__main__':
    exit_code = check_all()
    sys.exit(1 if exit_code > 0 else 0)

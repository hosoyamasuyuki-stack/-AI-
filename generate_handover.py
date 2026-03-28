#!/usr/bin/env python3
"""
generate_handover.py
Handover_v3.0シートを読み込み、handover.txtを生成してGitHubにコミットする
GitHub Actionsで毎週月曜日に自動実行
"""

import os
import json
import base64
import requests
import gspread
from google.oauth2.service_account import Credentials

# === 設定 ===
from core.config import SPREADSHEET_ID
SHEET_NAME = 'Handover_v3.0'
GITHUB_REPO = 'hosoyamasuyuki-stack/-AI-'
GITHUB_FILE = 'handover.txt'
GITHUB_TOKEN = os.environ.get('GITHUB_TOKEN', '')

def get_sheet_data():
    """Handover_v3.0シートの全データを取得"""
    # GitHub Actions環境ではサービスアカウントJSONを環境変数から取得
    creds_json = os.environ.get('GOOGLE_CREDENTIALS_JSON', '')
    
    if creds_json:
        creds_dict = json.loads(creds_json)
        creds = Credentials.from_service_account_info(
            creds_dict,
            scopes=['https://www.googleapis.com/auth/spreadsheets.readonly']
        )
    else:
        # ローカル実行時
        from google.colab import auth
        from google.auth import default
        auth.authenticate_user()
        creds, _ = default()
    
    gc = gspread.authorize(creds)
    ss = gc.open_by_key(SPREADSHEET_ID)
    sh = ss.worksheet(SHEET_NAME)
    
    # A列の全データを取得
    all_values = sh.col_values(1)
    return all_values

def generate_handover_text(rows):
    """handover.txtの内容を生成"""
    lines = []
    lines.append('=' * 60)
    lines.append('AI Investment System - Handover Document')
    lines.append('Auto-generated from Handover_v3.0 sheet')
    lines.append('=' * 60)
    lines.append('')
    
    for row in rows:
        if row:
            lines.append(row)
    
    lines.append('')
    lines.append('=' * 60)
    lines.append('次回セッション開始フレーズ：')
    lines.append('「このURLの引き継ぎ書を読んで続きをお願いします」')
    lines.append('URL: https://hosoyamasuyuki-stack.github.io/-AI-/handover.txt')
    lines.append('=' * 60)
    
    return '\n'.join(lines)

def commit_to_github(content):
    """GitHub APIでhandover.txtをコミット"""
    url = f'https://api.github.com/repos/{GITHUB_REPO}/contents/{GITHUB_FILE}'
    headers = {
        'Authorization': f'token {GITHUB_TOKEN}',
        'Content-Type': 'application/json'
    }
    
    # 既存ファイルのSHAを取得
    response = requests.get(url, headers=headers)
    sha = None
    if response.status_code == 200:
        sha = response.json().get('sha')
    
    # ファイルをコミット
    encoded = base64.b64encode(content.encode('utf-8')).decode('utf-8')
    data = {
        'message': 'Auto-update handover.txt [skip ci]',
        'content': encoded,
    }
    if sha:
        data['sha'] = sha
    
    response = requests.put(url, headers=headers, json=data)
    
    if response.status_code in [200, 201]:
        print('✅ handover.txt をGitHubにコミットしました')
        return True
    else:
        print(f'❌ コミット失敗: {response.status_code} {response.text}')
        return False

def main():
    print('📖 Handover_v3.0シートを読み込み中...')
    rows = get_sheet_data()
    print(f'✅ {len(rows)}行を取得')
    
    print('📝 handover.txtを生成中...')
    content = generate_handover_text(rows)
    
    # ローカルにも保存
    with open('handover.txt', 'w', encoding='utf-8') as f:
        f.write(content)
    print('✅ handover.txt をローカルに保存')
    
    if GITHUB_TOKEN:
        print('🚀 GitHubにコミット中...')
        commit_to_github(content)
    else:
        print('⚠️ GITHUB_TOKEN未設定 - ローカル保存のみ')
    
    print('✅ 完了')

if __name__ == '__main__':
    main()

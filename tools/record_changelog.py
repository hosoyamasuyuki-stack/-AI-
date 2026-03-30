# record_changelog.py
# GitHub Actionsから呼ばれる。コミット情報をHandover_ChangeLogに自動追記。
# 環境変数: GOOGLE_CREDENTIALS / SPREADSHEET_ID / COMMIT_MSG / COMMIT_SHA / CHANGED_FILES

import os, json, gspread
from google.oauth2.service_account import Credentials
from datetime import datetime

from core.auth import get_spreadsheet
ss = get_spreadsheet()

commit_msg    = os.environ.get('COMMIT_MSG', '(no message)')
commit_sha    = os.environ.get('COMMIT_SHA', '')[:7]
changed_files = os.environ.get('CHANGED_FILES', '').replace('\n', ' / ')
now = datetime.now().strftime('%Y/%m/%d %H:%M')

SHEET = 'Handover_ChangeLog'
try:
    ws = ss.worksheet(SHEET)
except Exception:
    ws = ss.add_worksheet(title=SHEET, rows=500, cols=5)
    ws.update('A1', [['\u65e5\u6642', 'SHA', '\u30b3\u30df\u30c3\u30c8\u30e1\u30c3\u30bb\u30fc\u30b8', '\u5909\u66f4\u30d5\u30a1\u30a4\u30eb', '\u5099\u8003']])
    print(f'Created: {SHEET}')

row = [now, commit_sha, commit_msg, changed_files, '']
all_vals = ws.get_all_values()
next_row = len(all_vals) + 1
ws.update(f'A{next_row}', [row])
print(f'OK: ChangeLog\u8ffd\u8a18 ({now} / {commit_sha} / {commit_msg})')

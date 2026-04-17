# diagnose_code.py
# Usage: python verify/diagnose_code.py <code>
# 指定銘柄コードが どのシートに どういう値で書き込まれているか一覧表示。
# スコア揺れの原因究明用。
import sys
from core.auth import get_spreadsheet

code = sys.argv[1] if len(sys.argv) > 1 else '4792'
ss = get_spreadsheet()
print(f"=== Diagnose {code} ===\n")

TARGET_SHEETS = [
    '保有銘柄_v4.3スコア',
    '監視銘柄_v4.3スコア',
    'コアスキャン_v4.3',
    'コアスキャン_日次',
    '予測記録',
]

for name in TARGET_SHEETS:
    try:
        ws = ss.worksheet(name)
        vals = ws.get_all_values()
        if not vals:
            print(f"[{name}] empty")
            continue
        hdr = vals[0]
        # シートのフルヘッダーを表示
        print(f"[{name}] ヘッダー({len(hdr)}列):")
        for j, h in enumerate(hdr):
            print(f"    col{j:2d} = '{h}'")
        print()

        # 予測記録は行1がサブヘッダー・行2からデータ
        data_start = 2 if name == '予測記録' else 1
        found = False
        for i, row in enumerate(vals[data_start:], start=data_start + 1):
            code_cell = None
            for j, h in enumerate(hdr):
                if 'コード' in str(h) or 'code' in str(h).lower():
                    code_cell = j
                    break
            if code_cell is None:
                continue
            if len(row) > code_cell and str(row[code_cell]).strip() == code:
                found = True
                print(f"[{name}] 行{i} - 全列ダンプ")
                for j in range(max(len(row), len(hdr))):
                    v = row[j] if j < len(row) else ''
                    h = hdr[j] if j < len(hdr) else f'col{j}'
                    print(f"    {j:3d} | {h:22s} = '{v}'")
                print()
        if not found:
            print(f"[{name}] {code} なし\n")
    except Exception as e:
        print(f"[{name}] エラー: {e}\n")

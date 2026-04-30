# ============================================================
# verify_holdings.py
# 47 銘柄反映後の検証スクリプト
# 4 シート整合性 + 銘柄リスト + 行数
# ============================================================
import os, csv, sys
from core.auth import get_spreadsheet

EXPECTED_47 = {
    '1605','1847','1879','1928','1942','2003','212A','2768','2914','3496',
    '4063','4221','4413','4792','5838','6098','6200','6501','6637','6920',
    '7187','7733','7741','8001','8053','8058','8136','8303','8306','8316',
    '8331','8343','8386','8473','8541','8591','8593','8600','8630','8729',
    '8766','8771','8935','9267','9432','9433','9434'
}

ss = get_spreadsheet()
print(f"=== 47 銘柄反映 検証レポート ===")
print(f"Spreadsheet: {ss.title}")
print()

results = {}
for sheet_name in ['保有銘柄_v4.3スコア', 'コアスキャン_v4.3', 'コアスキャン_日次', '予測記録']:
    try:
        ws = ss.worksheet(sheet_name)
        all_vals = ws.get_all_values()
        rows = len(all_vals)
        # コード列を特定
        if not all_vals:
            results[sheet_name] = {'rows': 0, 'codes': set()}
            continue
        header = all_vals[0]
        code_col = 0
        for i, h in enumerate(header):
            if h in ('コード', '銘柄コード'):
                code_col = i
                break
        # データ行
        data_start = 2 if '予測記録' in sheet_name else 1
        codes = set()
        for row in all_vals[data_start:]:
            if len(row) > code_col:
                c = str(row[code_col]).strip()
                if c:
                    codes.add(c)
        results[sheet_name] = {'rows': rows, 'codes': codes, 'data_count': len(codes)}
        print(f"[{sheet_name}]")
        print(f"  シート行数（grid）: {rows}")
        print(f"  ユニーク銘柄: {len(codes)}")
        # 期待集合との差分
        missing = EXPECTED_47 - codes
        extra   = codes - EXPECTED_47
        if sheet_name == '保有銘柄_v4.3スコア':
            print(f"  期待 47 銘柄との差分:")
            print(f"    不足（足りない）: {sorted(missing) if missing else 'なし ✅'}")
            print(f"    余分（含まれない予定）: {sorted(extra) if extra else 'なし ✅'}")
        print()
    except Exception as e:
        results[sheet_name] = {'error': str(e)}
        print(f"[{sheet_name}] ERROR: {e}")

# 4 シート間整合性
print("=== 4 シート整合性 ===")
holding_codes = results.get('保有銘柄_v4.3スコア', {}).get('codes', set())
corescan_v43  = results.get('コアスキャン_v4.3', {}).get('codes', set())
corescan_day  = results.get('コアスキャン_日次', {}).get('codes', set())
predict       = results.get('予測記録', {}).get('codes', set())

print(f"保有銘柄_v4.3スコア : {len(holding_codes)} 銘柄")
print(f"コアスキャン_v4.3   : {len(corescan_v43)} 銘柄  (保有との差: {len(holding_codes - corescan_v43)} 不足)")
print(f"コアスキャン_日次   : {len(corescan_day)} 銘柄  (保有との差: {len(holding_codes - corescan_day)} 不足)")
print(f"予測記録           : {len(predict)} 銘柄       (保有との差: {len(holding_codes - predict)} 不足)")

if holding_codes == EXPECTED_47:
    print("\n✅✅✅ 保有銘柄_v4.3スコア は期待 47 銘柄と完全一致 ✅✅✅")
else:
    print("\n⚠️  保有銘柄_v4.3スコア が期待と不一致")
    sys.exit(1)

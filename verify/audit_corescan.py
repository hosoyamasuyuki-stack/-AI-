# audit_corescan.py
# コアスキャン_v4.3 の旧バグ版データを一括監査
# ・4792 と同じ列ミスマッチパターン（変数1列に ROEトレンド値が入る等）を検出
# ・必要なら --fix で自動修復（保有/監視シートの最新値で上書き）
# Usage:
#   python verify/audit_corescan.py          # 監査のみ
#   python verify/audit_corescan.py --fix    # 修復実行
import argparse
from core.auth import get_spreadsheet

ap = argparse.ArgumentParser()
ap.add_argument('--fix', action='store_true', help='異常行を修復')
args = ap.parse_args()

ss = get_spreadsheet()
print("=== コアスキャン_v4.3 監査 ===")

try:
    cs_ws = ss.worksheet('コアスキャン_v4.3')
    cs_vals = cs_ws.get_all_values()
except Exception as e:
    print(f"ERROR: コアスキャン_v4.3 読込失敗: {e}")
    exit(1)

if len(cs_vals) < 2:
    print("ERROR: データなし")
    exit(1)

hdr = cs_vals[0]
print(f"ヘッダー({len(hdr)}列): {hdr}")

# 列インデックス
def find_col(h, name):
    return h.index(name) if name in h else None

col = {k: find_col(hdr, k) for k in
       ['コード', '総合スコア', 'ランク', 'ROE平均', 'FCR平均',
        'ROEトレンド', 'PEG', 'FCF利回り', '変数1', '変数2', '変数3']}

missing = [k for k, v in col.items() if v is None]
if missing:
    print(f"WARN: ヘッダー欠落 {missing}")

# 保有+監視シートから「正しい値」を読む
truth = {}
for sn in ['保有銘柄_v4.3スコア', '監視銘柄_v4.3スコア']:
    try:
        ws = ss.worksheet(sn)
        vals = ws.get_all_values()
        if len(vals) < 2:
            continue
        h = vals[0]
        ci = h.index('コード') if 'コード' in h else 0
        for r in vals[1:]:
            if len(r) <= ci:
                continue
            code = str(r[ci]).strip()
            if not code:
                continue
            truth[code] = {k: r[h.index(k)] if k in h and h.index(k) < len(r) else ''
                           for k in ['総合スコア', 'ランク', 'ROE平均', 'FCR平均',
                                     'ROEトレンド', 'PEG', 'FCF利回り',
                                     '変数1', '変数2', '変数3', '株価']}
    except Exception as e:
        print(f"  WARN: {sn}読込失敗 {e}")
print(f"真実シート: {len(truth)}銘柄の正しい値を取得")

# 監査ループ
abnormal = []
for i, row in enumerate(cs_vals[1:], start=2):
    if len(row) <= col['コード']:
        continue
    code = str(row[col['コード']]).strip()
    if not code:
        continue
    def v(k):
        ci = col.get(k)
        if ci is None or len(row) <= ci:
            return ''
        return str(row[ci]).strip()

    issues = []
    try:
        v1 = float(v('変数1') or 0)
        v2 = float(v('変数2') or 0)
        v3 = float(v('変数3') or 0)
        tot = float(v('総合スコア') or 0)
    except (ValueError, TypeError):
        issues.append('数値変換失敗')
        v1 = v2 = v3 = tot = 0

    # 判定1: 変数1/2/3 の絶対値が全て 1未満 → 生データ混入
    if abs(v1) < 1 and abs(v2) < 1 and abs(v3) < 1 and (v1 or v2 or v3):
        issues.append(f'変数1/2/3<1（生データ混入）={v1}/{v2}/{v3}')

    # 判定2: 総合スコアと 変数計算値が大きく乖離
    if v1 or v2 or v3:
        expected = v1 * 0.4 + v2 * 0.35 + v3 * 0.25
        if abs(tot - expected) > 5.0:
            issues.append(f'総合乖離 {tot}≠{expected:.1f}')

    # 判定3: 真実シートとの乖離
    t = truth.get(code)
    if t:
        try:
            tv1 = float(t.get('変数1', 0) or 0)
            tv2 = float(t.get('変数2', 0) or 0)
            tv3 = float(t.get('変数3', 0) or 0)
            if abs(v1 - tv1) > 3 or abs(v2 - tv2) > 3 or abs(v3 - tv3) > 3:
                issues.append(f'真実シートと乖離: 真{tv1}/{tv2}/{tv3} vs コアスキャン{v1}/{v2}/{v3}')
        except:
            pass

    if issues:
        abnormal.append({'row': i, 'code': code, 'issues': issues, 'truth': t})

# レポート
print(f"\n=== 監査結果: {len(abnormal)}件の異常 ===")
for a in abnormal[:20]:  # 最初の20件のみ表示
    print(f"  行{a['row']} {a['code']}: {'; '.join(a['issues'])}")
if len(abnormal) > 20:
    print(f"  ... 他 {len(abnormal) - 20} 件")

if not abnormal:
    print("✅ すべて正常")
    exit(0)

# 修復
if args.fix:
    print(f"\n=== 修復モード: {len(abnormal)}行を真実シートの値で上書き ===")
    fixed = 0
    for a in abnormal:
        t = a['truth']
        if not t:
            print(f"  {a['code']}: 真実シートに存在しない → スキップ")
            continue
        # コアスキャン_v4.3 のヘッダー順で新行を作る
        new_row = []
        value_map = {
            'コード': a['code'],
            '銘柄名': '',  # 後述: 旧行から取得
            '業種':  '',
            '総合スコア':  t.get('総合スコア', ''),
            'ランク':     t.get('ランク', ''),
            'ROE平均':    t.get('ROE平均', ''),
            'FCR平均':    t.get('FCR平均', ''),
            'ROEトレンド': t.get('ROEトレンド', ''),
            'PEG':        t.get('PEG', ''),
            'FCF利回り':  t.get('FCF利回り', ''),
            '変数1':      t.get('変数1', ''),
            '変数2':      t.get('変数2', ''),
            '変数3':      t.get('変数3', ''),
            '株価':       t.get('株価', ''),
        }
        # 旧行から銘柄名・業種を引き継ぐ
        old_row = cs_vals[a['row'] - 1]
        for k in ('銘柄名', '業種'):
            if k in hdr:
                idx = hdr.index(k)
                if len(old_row) > idx and old_row[idx]:
                    value_map[k] = old_row[idx]
        new_row = [value_map.get(h, '') for h in hdr]
        try:
            cs_ws.update(f'A{a["row"]}', [new_row])
            fixed += 1
            print(f"  修復: 行{a['row']} {a['code']}")
        except Exception as e:
            print(f"  修復失敗: {a['code']} {e}")
    print(f"\n✅ 修復完了: {fixed}/{len(abnormal)}行")
else:
    print(f"\n※ 修復するには --fix オプションを付けて再実行")
    exit(2)  # CI failure として検出可能

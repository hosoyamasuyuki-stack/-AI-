#!/usr/bin/env python3
"""
被覆モニタ（2026-06-10）: MONITOR_SUMMARY 整形ロジックの単体テスト。

ローカル実フェッチ（Google Sheets / TDnet / EDINET）に依存せず、build_monitor_summary
（純関数）と早期 return 行の書式が、fetch_tanshin.yml の死活監視 grep と後方互換である
ことを固定する。

H-1 死活監視（fetch_tanshin.yml）は MONITOR_SUMMARY 行を grep で parse する。
過去事案 run 26925050076「異常でも job が緑」＝表示文言ドリフトで grep 空振り の再発防止。
被覆モニタの uncovered_count/uncovered_codes 追記が、既存 new=/err=/coverage= の個別抽出を
一切壊さないことを保証する。

実行: cd <repo> && PYTHONPATH=. python tools/test_monitor_summary.py
"""
import os
import re
import sys

from tools.fetch_tanshin import build_monitor_summary

# fetch_tanshin.yml の死活監視が使う grep パターンと同等（ここを変えたら yml も変える）。
YML_SUMMARY_RE = re.compile(r'MONITOR_SUMMARY new=[0-9]+ err=[0-9]+ coverage=[0-9.]+')
YML_NEW_RE = re.compile(r'new=([0-9]+)')
YML_ERR_RE = re.compile(r'err=([0-9]+)')
YML_COV_RE = re.compile(r'coverage=([0-9.]+)')
YML_UNCOV_RE = re.compile(r'uncovered_count=([0-9]+)')
YML_UNCOV_CODES_RE = re.compile(r'uncovered_codes=([0-9A-Za-z,]+)')

# 早期 return（対象0社・異常系）の行。fetch_tanshin.py main() のハードコードと一致させる。
EARLY_RETURN_LINE = ('MONITOR_SUMMARY new=0 err=0 coverage=0.0 '
                     'uncovered_count=0 uncovered_codes=none')

failures = []


def check(cond, msg):
    if not cond:
        failures.append(msg)
        print(f'  [FAIL] {msg}')
    else:
        print(f'  [ok] {msg}')


def yml_extract(line):
    """yml の grep ロジックを Python で再現（先頭3トークンは固定パターン経由）。"""
    m = YML_SUMMARY_RE.search(line)
    assert m, f'yml の MONITOR_SUMMARY 固定パターンがマッチしない: {line!r}'
    prefix = m.group(0)
    new = int(YML_NEW_RE.search(prefix).group(1))
    err = int(YML_ERR_RE.search(prefix).group(1))
    cov = float(YML_COV_RE.search(prefix).group(1))
    um = YML_UNCOV_RE.search(line)
    uncov = int(um.group(1)) if um else 0          # 欠落時は 0 扱い（yml の :- デフォルトと同等）
    cm = YML_UNCOV_CODES_RE.search(line)
    codes = cm.group(1) if cm else 'none'
    return new, err, cov, uncov, codes


print('=== build_monitor_summary 後方互換テスト ===')

# 1) 正常系: 未取得2社（保有/監視）
line = build_monitor_summary(3, 1, 93.0, 2, '有価証券報告書:2', ['6146', '7203'])
new, err, cov, uncov, codes = yml_extract(line)
check(new == 3, f'正常: new=3 抽出 (得={new})')
check(err == 1, f'正常: err=1 抽出 (得={err})')
check(abs(cov - 93.0) < 1e-9, f'正常: coverage=93.0 抽出 (得={cov})')
check(uncov == 2, f'正常: uncovered_count=2 抽出 (得={uncov})')
check(codes == '6146,7203', f'正常: uncovered_codes=6146,7203 抽出 (得={codes})')
check(line.startswith(
    'MONITOR_SUMMARY new=3 err=1 coverage=93.0 edinet_new=2 edinet_doctype='),
    '正常: 先頭5トークンの順序・書式が System B 時点と不変')

# 2) 未取得0社 → none
line0 = build_monitor_summary(0, 0, 100.0, 0, 'none', [])
new, err, cov, uncov, codes = yml_extract(line0)
check(uncov == 0, f'未取得0: uncovered_count=0 (得={uncov})')
check(codes == 'none', f'未取得0: uncovered_codes=none (得={codes})')

# 3) 末尾英字コード（212A 等・新形式コード）を含む
lineA = build_monitor_summary(1, 0, 80.0, 0, 'none', ['130A', '212A'])
_, _, _, uncovA, codesA = yml_extract(lineA)
check(uncovA == 2, f'英字コード: uncovered_count=2 (得={uncovA})')
check(codesA == '130A,212A', f'英字コード: uncovered_codes=130A,212A (得={codesA})')

# 4) 早期 return 行（異常系・対象0社）も yml grep と整合
print('=== 早期 return 行 後方互換テスト ===')
new, err, cov, uncov, codes = yml_extract(EARLY_RETURN_LINE)
check(new == 0 and err == 0, '早期return: new=0 err=0 抽出')
check(abs(cov - 0.0) < 1e-9, '早期return: coverage=0.0 抽出')
check(uncov == 0, '早期return: uncovered_count=0 抽出')
check(codes == 'none', '早期return: uncovered_codes=none 抽出')

# 5) coverage<40 ゲート（yml awk）が新書式でも float 比較で成立
line_low = build_monitor_summary(0, 5, 12.3, 0, 'none', ['9999'])
_, _, cov_low, _, _ = yml_extract(line_low)
check(cov_low < 40.0, f'被覆率ゲート: coverage 12.3 < 40 を float 比較で検知 (得={cov_low})')

# 6) ソースのドリフト検知: 早期 return 行が fetch_tanshin.py に実在すること
print('=== ソース整合テスト ===')
src_path = os.path.join(os.path.dirname(__file__), 'fetch_tanshin.py')
with open(src_path, encoding='utf-8') as f:
    src = f.read()
check('uncovered_count=0 uncovered_codes=none' in src,
      '早期return行（uncovered_count=0 uncovered_codes=none）がソースに実在')
check('def build_monitor_summary(' in src, 'build_monitor_summary 定義がソースに実在')
check('def get_priority_codes(' in src, 'get_priority_codes 定義がソースに実在')

if failures:
    print(f'\n[FAILED] {len(failures)} 件 FAIL')
    sys.exit(1)
print('\n[ALL PASS] 全テスト PASS（MONITOR_SUMMARY 後方互換・被覆モニタ追記・早期return整合）')
sys.exit(0)

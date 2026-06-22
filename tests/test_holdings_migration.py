"""
保有→監視 移行 + 保有優先dedup（2026-06-22・CEO新方針）の純関数ガード。
本番 Sheets 認証(get_spreadsheet)はモジュール import 時に走るためスタブして無効化し、
ネットワーク非依存で次を固定する:
  - find_row_by_code が大文字小文字を無視（130A/130a・前後空白）で一致する（コード表記ゆれの取りこぼし防止）。
  - parse_csv が『複数口座で1行でも LISA表示=TRUE なら保有』をOR集約し、コードを大文字正規化する。
  - compute_diff の keep/remove/add の集合演算。
"""
import os
import sys
from unittest.mock import MagicMock

# ── 認証スタブ（import 時の get_spreadsheet を無効化）──
import core.auth as _auth
_auth.get_spreadsheet = lambda *a, **k: MagicMock()

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from manage_stock import find_row_by_code          # noqa: E402
from bulk_diff_apply import parse_csv, compute_diff  # noqa: E402


class FakeWs:
    """find_row_by_code が使う get_all_values() と title だけを持つ最小スタブ。"""
    def __init__(self, title, values):
        self.title = title
        self._values = values

    def get_all_values(self):
        return self._values


def _holdings_ws():
    return FakeWs('保有銘柄_v4.3スコア', [
        ['コード', '銘柄名'],
        ['7203', 'トヨタ自動車'],
        ['130A', 'Veritas'],     # 新形式 英数字コード（大文字）
        ['6758', 'ソニーグループ'],
    ])


class TestFindRowCaseInsensitive:
    def test_numeric_code(self):
        row, _ = find_row_by_code(_holdings_ws(), '7203')
        assert row == 2

    def test_alnum_code_lowercase_matches_uppercase_sheet(self):
        # シートは 130A（大文字）、検索は 130a（小文字）でも一致する
        row, _ = find_row_by_code(_holdings_ws(), '130a')
        assert row == 3

    def test_whitespace_trimmed(self):
        row, _ = find_row_by_code(_holdings_ws(), ' 6758 ')
        assert row == 4

    def test_absent_code_returns_none(self):
        row, _ = find_row_by_code(_holdings_ws(), '9999')
        assert row is None


class TestParseCsv:
    def _write(self, tmp_path, rows, header):
        p = tmp_path / 'pf.csv'
        import csv as _csv
        with open(p, 'w', encoding='utf-8-sig', newline='') as f:
            w = _csv.DictWriter(f, fieldnames=header)
            w.writeheader()
            for r in rows:
                w.writerow(r)
        return str(p)

    def test_or_aggregation_multi_account(self, tmp_path):
        # 同一コードが個人=TRUE / 法人=FALSE の2行 → 1行でも TRUE なら保有とみなす
        header = ['個人/法人', '証券コード', '銘柄名', 'LISA表示']
        rows = [
            {'個人/法人': '法人', '証券コード': '7203', '銘柄名': 'トヨタ', 'LISA表示': 'FALSE'},
            {'個人/法人': '個人', '証券コード': '7203', '銘柄名': 'トヨタ', 'LISA表示': 'TRUE'},
            {'個人/法人': '個人', '証券コード': '6758', '銘柄名': 'ソニー', 'LISA表示': 'FALSE'},
        ]
        codes = parse_csv(self._write(tmp_path, rows, header))
        assert '7203' in codes          # どこか1行が TRUE
        assert '6758' not in codes       # 全行 FALSE は対象外

    def test_code_uppercased(self, tmp_path):
        header = ['証券コード', '銘柄名', 'LISA表示']
        rows = [{'証券コード': '130a', '銘柄名': 'Veritas', 'LISA表示': 'true'}]  # 小文字コード・小文字true
        codes = parse_csv(self._write(tmp_path, rows, header))
        assert '130A' in codes           # 大文字に正規化・'true' も TRUE 扱い


class TestComputeDiff:
    def test_sets(self):
        latest = {'7203': 'a', '6758': 'b'}        # CSV（現保有）
        existing = {'6758': 'b', '9984': 'c'}      # シート既存
        diff = compute_diff(latest, existing)
        assert diff['keep'] == ['6758']
        assert diff['remove'] == ['9984']          # CSVから消えた=売却→監視へ移行対象
        assert diff['add'] == ['7203']             # 新規 or 買戻し対象

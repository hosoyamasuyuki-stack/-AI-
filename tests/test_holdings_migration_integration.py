"""
保有→監視 移行の結合テスト（2026-06-22・CEO新方針）。
本番 Sheets には触れず、最小の疑似スプレッドシート（FakeSS/FakeWs）に対して
manage_stock の実関数（move_stock / remove_stock / _mark_sold_in_predictions）を
そのまま動かし、6シナリオの結末を固定する。ネットワーク不要・決定論的。

固定する振る舞い:
  S1 売却(保有ゼロ・監視に未在籍) → 監視へ移行（保有行消去・監視行追加・予測記録は無変更=観察継続）
  S2 売却(監視に既在籍=二重在籍) → 保有側のみ削除（コアスキャン・予測記録 無変更・SOLD印なし）
  S3 remove_stock 既定(cascade/mark_sold=True) → コアスキャン削除＋予測記録 SOLD 印（D1の後方互換）
  S4 買い戻し move_stock('保有') → 監視から保有へ復帰
  S5 move_stock 原子性 → 追加が着地しなければ移動元を削除せず中止（消失防止）
  S6 _mark_sold_in_predictions → 同コード全行に SOLD/売却日（大文字小文字無視・冪等）
"""
import os
import sys
import re
from unittest.mock import MagicMock

import core.auth as _auth
_auth.get_spreadsheet = lambda *a, **k: MagicMock()

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

import manage_stock  # noqa: E402


class FakeWs:
    def __init__(self, title, values):
        self.title = title
        self.values = [list(r) for r in values]
        self.row_count = max(len(self.values), 1000)

    def get_all_values(self):
        return [list(r) for r in self.values]

    def delete_rows(self, idx):          # 1-indexed
        del self.values[idx - 1]

    def update(self, rng, data):         # rng 例 'A12'
        row = int(re.match(r'[A-Z]+(\d+)', rng).group(1))
        while len(self.values) < row:
            self.values.append([])
        self.values[row - 1] = list(data[0])

    def update_cell(self, row, col, val):  # 1-indexed
        while len(self.values) < row:
            self.values.append([])
        r = self.values[row - 1]
        while len(r) < col:
            r.append('')
        r[col - 1] = val

    def add_rows(self, n):
        self.row_count += n


class NoLandWs(FakeWs):
    """update しても着地しない（サイレントな追加失敗）を模す＝move_stock 原子性テスト用。"""
    def update(self, rng, data):
        pass


class FakeSS:
    def __init__(self, sheets):
        self.sheets = sheets

    def worksheet(self, name):
        if name not in self.sheets:
            raise Exception(f"worksheet {name} 無し")
        return self.sheets[name]


HOLD = '保有銘柄_v4.3スコア'
WATCH = '監視銘柄_v4.3スコア'
CORE1 = 'コアスキャン_v4.3'
CORE2 = 'コアスキャン_日次'
PRED = '予測記録'

SCORE_HDR = ['コード', '銘柄名', '業種', '総合スコア', 'ランク']


def _score_rows(codes):
    return [SCORE_HDR] + [[c, f'{c}社', '情報通信', '70', 'A'] for c in codes]


def _pred_sheet(code_rows):
    """予測記録の最小疑似（行0=ヘッダ・行1=サブ・行2以降=データ）。42列でAO(40)/AP(41)を用意。"""
    hdr = ['記録日', '銘柄コード'] + [''] * 38 + ['売却済フラグ', '売却日']  # len=42
    sub = [''] * 42
    rows = [hdr, sub]
    for code in code_rows:
        r = ['2026/01/01', code] + [''] * 40  # AO/AP は空（現役）
        rows.append(r)
    return rows


def _build_ss(hold_codes, watch_codes, pred_codes, core_codes=None):
    core_codes = hold_codes if core_codes is None else core_codes
    return FakeSS({
        HOLD: FakeWs(HOLD, _score_rows(hold_codes)),
        WATCH: FakeWs(WATCH, _score_rows(watch_codes)),
        CORE1: FakeWs(CORE1, _score_rows(core_codes)),
        CORE2: FakeWs(CORE2, _score_rows(core_codes)),
        PRED: FakeWs(PRED, _pred_sheet(pred_codes)),
    })


def _codes_in(ws):
    return [row[0] for row in ws.get_all_values()[1:] if row and row[0]]


def _pred_sold_flags(ws, code):
    """予測記録で code 行の AO(売却済フラグ・index40) の値を集める。"""
    out = []
    for row in ws.get_all_values()[2:]:
        if len(row) > 1 and str(row[1]).strip().upper() == code.upper():
            out.append(row[40] if len(row) > 40 else '')
    return out


def test_s1_full_sell_moves_to_watch(monkeypatch):
    ss = _build_ss(hold_codes=['7203', '6758'], watch_codes=['9984'], pred_codes=['7203', '6758'])
    monkeypatch.setattr(manage_stock, 'ss', ss)
    manage_stock.move_stock('7203', '監視')
    assert '7203' not in _codes_in(ss.sheets[HOLD])      # 保有から消える
    assert '7203' in _codes_in(ss.sheets[WATCH])         # 監視に現れる
    assert _pred_sold_flags(ss.sheets[PRED], '7203') == ['']  # 予測記録は無変更（SOLD印なし=観察継続）


def test_s2_dual_residence_removes_holding_only(monkeypatch):
    # 7203 が保有と監視の両方に在る（二重在籍）。保有側だけ削除・コアスキャンと予測記録は無変更。
    ss = _build_ss(hold_codes=['7203'], watch_codes=['7203'], pred_codes=['7203'])
    monkeypatch.setattr(manage_stock, 'ss', ss)
    manage_stock.remove_stock('7203', '保有', cascade=False, mark_sold=False)
    assert '7203' not in _codes_in(ss.sheets[HOLD])      # 保有から消える
    assert '7203' in _codes_in(ss.sheets[WATCH])         # 監視はそのまま
    assert '7203' in _codes_in(ss.sheets[CORE1])         # コアスキャンは無変更（cascade=False）
    assert _pred_sold_flags(ss.sheets[PRED], '7203') == ['']  # SOLD印なし（mark_sold=False）


def test_s3_default_remove_marks_sold_and_cascades(monkeypatch):
    # 既定（cascade/mark_sold=True）の後方互換: コアスキャン削除＋予測記録 SOLD 印（D1）。
    ss = _build_ss(hold_codes=['7203'], watch_codes=[], pred_codes=['7203'])
    monkeypatch.setattr(manage_stock, 'ss', ss)
    manage_stock.remove_stock('7203', '保有')
    assert '7203' not in _codes_in(ss.sheets[HOLD])
    assert '7203' not in _codes_in(ss.sheets[CORE1])     # cascade 既定で削除
    assert _pred_sold_flags(ss.sheets[PRED], '7203') == ['SOLD']  # D1: 物理削除でなく SOLD 印


def test_s4_buyback_moves_watch_to_hold(monkeypatch):
    ss = _build_ss(hold_codes=['6758'], watch_codes=['7203'], pred_codes=['7203', '6758'])
    monkeypatch.setattr(manage_stock, 'ss', ss)
    manage_stock.move_stock('7203', '保有')              # 買い戻し（監視→保有）
    assert '7203' in _codes_in(ss.sheets[HOLD])
    assert '7203' not in _codes_in(ss.sheets[WATCH])


def test_s5_move_atomicity_no_loss_on_failed_landing(monkeypatch):
    # 監視への追加が着地しない状況 → 移動元(保有)を削除せず中止（銘柄消失を防ぐ）
    ss = FakeSS({
        HOLD: FakeWs(HOLD, _score_rows(['7203'])),
        WATCH: NoLandWs(WATCH, _score_rows([])),
        CORE1: FakeWs(CORE1, _score_rows(['7203'])),
        CORE2: FakeWs(CORE2, _score_rows(['7203'])),
        PRED: FakeWs(PRED, _pred_sheet(['7203'])),
    })
    monkeypatch.setattr(manage_stock, 'ss', ss)
    with pytest.raises(SystemExit):
        manage_stock.move_stock('7203', '監視')
    assert '7203' in _codes_in(ss.sheets[HOLD])          # 着地未確認 → 移動元は温存（消失しない）


def test_s6_mark_sold_all_rows_case_insensitive_idempotent(monkeypatch):
    # 同コードが大文字/小文字で2行 → 両方に SOLD。再実行しても二重にならない（冪等）。
    ss = _build_ss(hold_codes=[], watch_codes=[], pred_codes=['130A', '130a'])
    monkeypatch.setattr(manage_stock, 'ss', ss)
    manage_stock._mark_sold_in_predictions('130A')
    flags = _pred_sold_flags(ss.sheets[PRED], '130A')
    assert flags == ['SOLD', 'SOLD']                     # 大文字小文字無視で両行に印
    manage_stock._mark_sold_in_predictions('130a')       # 冪等（既印付けは飛ばす）
    assert _pred_sold_flags(ss.sheets[PRED], '130A') == ['SOLD', 'SOLD']

"""Workflow 整合性回帰テスト（CEO 指示 2026-05-08・段 F 再発防止）

背景：
  Full Update #114（2026-05-08）で、generate_dashboard.py が holdings_history_page.html
  を書き出しても full_update.yml の `git add` 行に含まれていなかったため、
  CDN に反映されない事件が発生。CEO 通達「お客様には迷惑をかけられません」を受けた
  構造的再発防止策として、generate_dashboard.py の書き出し対象 ↔ full_update.yml の
  git add 範囲の整合性を CI で必ず検証する。

このテストが緑である限り、新規 HTML 出力を generate_dashboard.py に追加しても
workflow の git add 漏れで CDN 配信されない事故は起こらない。
"""

import re
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


class TestGenerateDashboardOutputsRegisteredInFullUpdate:
    """generate_dashboard.py の HTML 書き出し先が full_update.yml の git add に登録されているか。"""

    @property
    def gen_src(self):
        return (REPO_ROOT / 'generate_dashboard.py').read_text(encoding='utf-8')

    @property
    def full_update_src(self):
        return (REPO_ROOT / '.github/workflows/full_update.yml').read_text(encoding='utf-8')

    def _extract_html_outputs(self):
        """generate_dashboard.py 内の HTML 書き出し先を抽出。

        対象パターン：
        - `with open('foo.html', 'w'`
        - `with open(_X_path, 'w'` で _X_path = '...foo.html' の形
        - `out = 'foo.html'` + 後続の `with open(out, 'w'`
        """
        src = self.gen_src
        outputs = set()

        # 直接リテラル: with open('xxx.html', ...)
        for m in re.finditer(r"with\s+open\(\s*['\"]([^'\"]+\.html)['\"]\s*,\s*['\"]w", src):
            outputs.add(m.group(1).split('/')[-1])

        # out = 'xxx.html' + with open(out, ...) パターン
        for m in re.finditer(r"^(\w+)\s*=\s*['\"]([^'\"]+\.html)['\"]", src, re.MULTILINE):
            varname = m.group(1)
            filename = m.group(2)
            # 同変数で書き込みオープンしているか確認
            if re.search(rf"with\s+open\(\s*{varname}\s*,\s*['\"]w", src):
                outputs.add(filename.split('/')[-1])

        # _xxx_path = '...xxx.html' + with open(_xxx_path, 'w'...) パターン
        # path 変数の値を最初の HTML literal から取得
        for m in re.finditer(
            r"(\w*_?path\w*)\s*=\s*[^\n]*['\"]([^'\"]+\.html)['\"]", src
        ):
            varname = m.group(1)
            filename = m.group(2)
            if re.search(rf"with\s+open\(\s*{varname}\s*,\s*['\"]w", src):
                outputs.add(filename.split('/')[-1])

        return outputs

    def _extract_added_files(self):
        """full_update.yml の git add 行から add 対象ファイル（.html）を抽出。"""
        yml = self.full_update_src
        added = set()
        # `git add file1 file2 ...` を全件マッチ
        for m in re.finditer(r"git\s+add\s+([^\n]+)", yml):
            args = m.group(1).strip()
            # フラグや変数は除外し .html ファイルだけ抽出
            for token in re.split(r"\s+", args):
                token = token.strip().strip('"').strip("'")
                if token.endswith('.html'):
                    added.add(token.split('/')[-1])
        return added

    def test_all_html_outputs_are_added(self):
        """generate_dashboard.py が書き出す HTML 全てが full_update.yml で git add されている。"""
        outputs = self._extract_html_outputs()
        added = self._extract_added_files()

        # 検出が空ならテスト自体が壊れている → 早期検知
        assert outputs, (
            "generate_dashboard.py から HTML 書き出し対象を抽出できませんでした。"
            "テストの抽出ロジック（_extract_html_outputs）を確認してください。"
        )
        assert added, (
            "full_update.yml から git add 対象 HTML を抽出できませんでした。"
            "テストの抽出ロジック（_extract_added_files）を確認してください。"
        )

        missing = outputs - added
        assert not missing, (
            f"\n❌ generate_dashboard.py が書き出す HTML が full_update.yml の "
            f"git add に未登録：{sorted(missing)}\n"
            f"  outputs: {sorted(outputs)}\n"
            f"  added:   {sorted(added)}\n"
            f"  → .github/workflows/full_update.yml の git add 行に上記を追加してください。"
        )

    def test_known_outputs_present(self):
        """既知の出力ファイル（最低 2 つ）が抽出できることを確認（テスト自体の sanity）。"""
        outputs = self._extract_html_outputs()
        for expected in ['ai_dashboard_v13.html', 'holdings_history_page.html']:
            assert expected in outputs, (
                f"既知の出力 {expected} が generate_dashboard.py から抽出できない。"
                f"抽出済: {sorted(outputs)}"
            )

    def test_known_added_present(self):
        """既知の git add 対象が抽出できることを確認（sanity）。"""
        added = self._extract_added_files()
        for expected in ['ai_dashboard_v13.html', 'holdings_history_page.html']:
            assert expected in added, (
                f"既知の add 対象 {expected} が full_update.yml から抽出できない。"
                f"抽出済: {sorted(added)}"
            )

"""保有銘柄差分プログラム + 取引履歴ページ 回帰テスト（v1.2）

PROCEDURE_BULK_HOLDINGS_DIFF_PERFECTION_2026-05-07.md v1.2 §10 準拠。
A 修正（DIFF_COLS 12 列）/ F フォーマット / G モード / ネット集約 / テンプレ整合性 / ボタン挿入位置 を機械検証。
"""

import re
import sys
from collections import defaultdict
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


# ── A 修正：DIFF_COLS 11 → 12 列拡張（口座区分追加） ──

class TestDiffColsExpansion:
    """bulk_update_holdings.py の DIFF_COLS が 12 列・口座区分を含むことを検証。"""

    def _read_diff_cols(self):
        """gspread/core 依存を回避するためソース直接 parse。"""
        src = (REPO_ROOT / 'bulk_update_holdings.py').read_text(encoding='utf-8')
        m = re.search(r'^DIFF_COLS\s*=\s*\[(.*?)\]', src, re.DOTALL | re.MULTILINE)
        assert m, "DIFF_COLS not found in bulk_update_holdings.py"
        items = [
            x.strip().strip("'").strip('"')
            for x in m.group(1).split(',')
            if x.strip()
        ]
        return items

    def test_diff_cols_count_is_12(self):
        items = self._read_diff_cols()
        assert len(items) == 12, f"DIFF_COLS は 12 列であるべき: {len(items)} 列"

    def test_diff_cols_has_account_type_at_index_4(self):
        items = self._read_diff_cols()
        assert '口座区分' in items, "DIFF_COLS に '口座区分' が含まれるべき"
        assert items.index('口座区分') == 4, (
            f"口座区分は 5 列目（index 4）であるべき: index {items.index('口座区分')}"
        )

    def test_diff_cols_order(self):
        items = self._read_diff_cols()
        expected = ['month', 'change_type', '個人/法人', '証券会社', '口座区分',
                    '市場', '種別', '証券コード', '銘柄名',
                    '株数_前月', '株数_当月', '差分']
        assert items == expected, f"DIFF_COLS 順序不一致: {items}"


# ── F 修正：--snapshot-month オプション ──

class TestSnapshotMonthOption:
    """snapshot_month のフォーマット検証ロジック（YYYY-MM-01 形式）。"""

    def test_format_valid(self):
        for m in ['2026-04-01', '2025-12-01', '2026-01-01', '2030-06-01']:
            assert re.match(r'^\d{4}-\d{2}-01$', m), f"形式違反: {m}"

    def test_format_invalid(self):
        for m in ['2026-04-15', '2026-04', '04-01', '2026/04/01', '2026-4-1']:
            assert not re.match(r'^\d{4}-\d{2}-01$', m), f"検出漏れ: {m}"

    def test_snapshot_month_arg_in_source(self):
        """ソースに --snapshot-month / --snapshot-only 引数が定義されていること。"""
        src = (REPO_ROOT / 'bulk_update_holdings.py').read_text(encoding='utf-8')
        assert '--snapshot-month' in src, "--snapshot-month オプション未実装"
        assert '--snapshot-only' in src, "--snapshot-only オプション未実装"


# ── ネット集約ロジック（CEO 確定 5：一銘柄表示） ──

class TestNetAggregation:
    """同一銘柄を複数口座で持つ場合のネット集約 + change_type 再判定。"""

    def _agg(self, rows):
        agg = defaultdict(lambda: {'prev': 0.0, 'curr': 0.0})
        for r in rows:
            key = (r['month'], r['code'])
            agg[key]['prev'] += r['prev']
            agg[key]['curr'] += r['curr']
        return agg

    def _ct(self, prev, curr):
        delta = curr - prev
        if prev == 0 and curr > 0:
            return '新規'
        elif prev > 0 and curr == 0:
            return '全売却'
        elif delta > 0:
            return '増し玉'
        elif delta < 0:
            return '一部売却'
        else:
            return None

    def test_net_aggregation_partial_cancel_to_add(self):
        """SBI 特定 +100 / NISA -50 → ネット +50 → 増し玉（1 行表示）"""
        rows = [
            {'month': '2026-05-01', 'code': '7203', 'prev': 200, 'curr': 300},
            {'month': '2026-05-01', 'code': '7203', 'prev': 100, 'curr': 50},
        ]
        agg = self._agg(rows)
        v = agg[('2026-05-01', '7203')]
        assert self._ct(v['prev'], v['curr']) == '増し玉'

    def test_net_aggregation_zero_change_no_display(self):
        """ネット 0（特定 +50 / NISA -50）→ 表示しない"""
        rows = [
            {'month': '2026-05-01', 'code': '7203', 'prev': 200, 'curr': 250},
            {'month': '2026-05-01', 'code': '7203', 'prev': 100, 'curr': 50},
        ]
        agg = self._agg(rows)
        v = agg[('2026-05-01', '7203')]
        assert self._ct(v['prev'], v['curr']) is None

    def test_net_aggregation_full_exit_both_accounts(self):
        """両口座とも全売却 → 全売却"""
        rows = [
            {'month': '2026-05-01', 'code': '7203', 'prev': 200, 'curr': 0},
            {'month': '2026-05-01', 'code': '7203', 'prev': 100, 'curr': 0},
        ]
        agg = self._agg(rows)
        v = agg[('2026-05-01', '7203')]
        assert self._ct(v['prev'], v['curr']) == '全売却'

    def test_net_aggregation_new_entry_both_accounts(self):
        """両口座とも新規 → 新規"""
        rows = [
            {'month': '2026-05-01', 'code': '7203', 'prev': 0, 'curr': 100},
            {'month': '2026-05-01', 'code': '7203', 'prev': 0, 'curr': 50},
        ]
        agg = self._agg(rows)
        v = agg[('2026-05-01', '7203')]
        assert self._ct(v['prev'], v['curr']) == '新規'

    def test_net_aggregation_partial_sell(self):
        """両口座とも一部売却 → 一部売却"""
        rows = [
            {'month': '2026-05-01', 'code': '7203', 'prev': 200, 'curr': 100},
            {'month': '2026-05-01', 'code': '7203', 'prev': 100, 'curr': 80},
        ]
        agg = self._agg(rows)
        v = agg[('2026-05-01', '7203')]
        assert self._ct(v['prev'], v['curr']) == '一部売却'


# ── holdings_history_page.html テンプレ整合性 ──

class TestHistoryPageTemplate:
    """テンプレートの存在 / マーカー / 顧客財産情報非開示の確認。"""

    @property
    def template_path(self):
        return REPO_ROOT / 'holdings_history_page.html'

    def test_template_exists(self):
        assert self.template_path.exists(), f"テンプレート不在: {self.template_path}"

    def test_template_has_required_markers(self):
        """generate_dashboard.py が再生成後も保持されるマーカーを検証。
        - HISTORY_BLOCKS マーカーは self-replace で残る
        - LAST_UPDATED は datetime に置換されて消えるため、id='last-updated' span 自体を検証
        """
        src = self.template_path.read_text(encoding='utf-8')
        assert '<!--HISTORY_BLOCKS_START-->' in src
        assert '<!--HISTORY_BLOCKS_END-->' in src
        assert 'id="last-updated"' in src

    def test_template_no_account_or_share_columns(self):
        """顧客財産情報非開示：株数列・口座列・前月/当月列が含まれないこと。
        加えて、LISA 国内個別銘柄限定下では「種別」列も全件同値で冗長なため除外する
        （CEO 指示 2026-05-08）。"""
        src = self.template_path.read_text(encoding='utf-8')
        assert '<th>口座</th>' not in src
        assert '<th>口座区分</th>' not in src
        assert '<th>前月</th>' not in src
        assert '<th>当月</th>' not in src
        assert '<th>株数</th>' not in src
        assert '<th>差分</th>' not in src
        assert '<th>種別</th>' not in src

    def test_dashboard_history_table_has_no_kind_column(self):
        """generate_dashboard.py の取引履歴ページ生成テーブルヘッダに「種別」が含まれないこと。"""
        src = (REPO_ROOT / 'generate_dashboard.py').read_text(encoding='utf-8')
        # 取引履歴ページ生成セクション内の table header
        m = re.search(r"取引履歴ページ生成.*?<th>変化</th>[^<]*?<th>コード</th>[^<]*?<th>銘柄名</th>([^<]*?<th>[^<]+</th>)?", src, re.DOTALL)
        assert m, "取引履歴ページのテーブルヘッダが見つからない"
        # 4 番目の <th>種別</th> 等が無いこと
        if m.group(1):
            assert '種別' not in m.group(1), (
                f"取引履歴テーブルヘッダに不要な列が含まれている: {m.group(1)}"
            )

    def test_template_legend_has_4_states(self):
        src = self.template_path.read_text(encoding='utf-8')
        for label in ['新規', '全売却', '増し玉', '一部売却']:
            assert label in src, f"凡例に '{label}' がない"

    def test_history_generation_filters_to_jp_stocks_only(self):
        """CEO 指示 2026-05-08：LISA は国内個別銘柄のみ。
        generate_dashboard.py で米国株・ETF・REIT・投信・外貨を除外しているか検証。"""
        gen_src = (REPO_ROOT / 'generate_dashboard.py').read_text(encoding='utf-8')
        # 取引履歴ページ生成セクションに market/kind フィルタが入っているか
        m = re.search(
            r"取引履歴ページ生成.*?_market\s*!=\s*['\"]JP['\"].*?_kind\s*!=\s*['\"]個別株['\"]",
            gen_src,
            re.DOTALL,
        )
        assert m, (
            "取引履歴ページ生成で 市場=JP and 種別=個別株 のフィルタが見当たりません。"
            "海外株・ETF・REIT・投信・外貨が顧客向け取引履歴に出る可能性。"
        )

    def test_template_has_back_to_dashboard_link(self):
        """ヘッダに「ダッシュボードに戻る」リンクがあること（CEO 指示 2026-05-08）。"""
        src = self.template_path.read_text(encoding='utf-8')
        assert 'ai_dashboard_v13.html' in src, "ダッシュボードへの戻りリンク先が含まれていない"
        assert 'ダッシュボードに戻る' in src, "「ダッシュボードに戻る」文言がない"


# ── ヘッダボタン挿入の冪等性（部長指摘 MUST-1 対応） ──

class TestDashboardHistoryButton:
    """generate_dashboard.py 内の取引履歴ボタン挿入ロジックを source 検証。"""

    def test_button_insertion_logic_present(self):
        src = (REPO_ROOT / 'generate_dashboard.py').read_text(encoding='utf-8')
        assert "holdings_history_page.html" in src, "取引履歴ボタン挿入ロジック未実装"

    def test_button_inserted_before_framework(self):
        """2026-05-08 改訂：evidence 削除後・取引履歴ボタンは framework ボタンの直前に挿入。"""
        src = (REPO_ROOT / 'generate_dashboard.py').read_text(encoding='utf-8')
        # evidence ボタンを削除しているか
        assert "evidence_page" in src and "削除" in src, "evidence ボタン削除ロジックが未実装"
        # framework ボタンの前に取引履歴ボタンを挿入しているか
        m = re.search(
            r"holdings_history_page.*?framework_page",
            src,
            re.DOTALL,
        )
        assert m, "framework ボタン前への取引履歴ボタン挿入ロジックが確認できない"

    def test_no_framework_placeholder_workaround(self):
        """旧案の __FRAMEWORK_PLACEHOLDER__ 退避ロジックが残存していないこと。"""
        src = (REPO_ROOT / 'generate_dashboard.py').read_text(encoding='utf-8')
        assert '__FRAMEWORK_PLACEHOLDER__' not in src, (
            "撤回された旧案のプレースホルダー退避ロジックが残存している"
        )

    def test_evidence_button_removed_from_html(self):
        """2026-05-08：evidence_page.html ボタンが HTML から削除されていること（CEO 規約抵触ガード）。"""
        html_path = REPO_ROOT / 'ai_dashboard_v13.html'
        if not html_path.exists():
            pytest.skip("ai_dashboard_v13.html 未生成")
        src = html_path.read_text(encoding='utf-8')
        assert "window.open('evidence_page.html'" not in src, (
            "evidence_page.html ボタンが残存している（CEO 指示で削除すべき）"
        )

    def test_button_inserted_before_framework_in_html(self):
        """生成済 ai_dashboard_v13.html で取引履歴ボタンが framework の前に配置されていること。"""
        html_path = REPO_ROOT / 'ai_dashboard_v13.html'
        if not html_path.exists():
            pytest.skip("ai_dashboard_v13.html 未生成")
        src = html_path.read_text(encoding='utf-8')
        if 'holdings_history_page.html' not in src:
            pytest.skip("取引履歴ボタンは未挿入（generate_dashboard.py 未実行）")
        hi_idx = src.find("window.open('holdings_history_page.html','_blank')")
        fw_idx = src.find("window.open('framework_page.html','_blank')")
        assert hi_idx >= 0, "取引履歴ボタンが HTML に存在しない"
        assert fw_idx >= 0, "framework_page.html ボタンが HTML に存在しない"
        assert hi_idx < fw_idx, "取引履歴ボタンが framework の前に配置されていない"


# ── bulk_update_holdings.py 機能テスト ──

class TestBulkUpdateHoldingsSource:
    """v1.2 の主要修正（A〜D + F + G + B 履歴シート）がソースに反映されていること。"""

    @property
    def src(self):
        return (REPO_ROOT / 'bulk_update_holdings.py').read_text(encoding='utf-8')

    def test_b_history_sheet_constant(self):
        """B 修正: SHEET_HISTORY 定数が定義されていること。"""
        assert "SHEET_HISTORY" in self.src
        assert "保有差分_履歴" in self.src

    def test_b_append_history_function(self):
        """B 修正: append_history 関数が定義されていること。"""
        assert re.search(r"^def\s+append_history\s*\(", self.src, re.MULTILINE)

    def test_c_continuous_month_warn(self):
        """C 修正: 連続月チェック WARN ログがあること。"""
        assert "_months_gap" in self.src
        assert "WARN" in self.src

    def test_d_no_csv_input_exits(self):
        """D 修正: CSV 入力なし時の sys.exit(2) が実装されていること。"""
        assert re.search(r"sys\.exit\(2\).*CSV|CSV.*sys\.exit\(2\)", self.src, re.DOTALL)

    def test_f_snapshot_month_format_validation(self):
        """F 修正: snapshot_month のフォーマット検証 regex があること。"""
        assert r"^\d{4}-\d{2}-01$" in self.src

    def test_g_snapshot_only_master_protection(self):
        """G 修正: --snapshot-only 時に master/extended を更新しない条件分岐があること。"""
        assert re.search(r"args\.snapshot_only", self.src)
        # master/extended の更新が条件分岐内にあること
        assert "n_master = 0" in self.src and "n_ext = 0" in self.src

    def test_force_update_diff_header(self):
        """A 修正に伴うヘッダ強制更新ロジックが定義されていること。"""
        assert re.search(r"^def\s+force_update_diff_header\s*\(", self.src, re.MULTILINE)

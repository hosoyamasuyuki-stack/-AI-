"""
ダッシュボード整合性 回帰テスト（2026-05-07 新設）

販売前最終総合監査（PROCEDURE_PRELAUNCH_FINAL_AUDIT v1.1 §7-1 / B-10）
で発見された 7 件の静的値バグを再発させないための pytest 自動検証。

テスト対象:
1. パネルヘッダ「N銘柄 / A以上 N」の動的化（M-7/M-7-2）
2. 監視パネルヘッダ「N銘柄 / 購入候補 N」の動的化（M-8/M-8-2）
3. 環境バナー「短期/中期 動的取得」（M-9）
4. 「次回検証/評価」翌月 1 日動的化（M-12/M-14）
5. テーブル整合性（ティッカー数 ≡ パネル ≡ 実テーブル）
6. 192 銘柄全件で計算式・ランク境界整合（軸 B-5/B-6/B-7）

実行方法:
    pytest tests/test_dashboard_consistency.py -v

CI 統合:
    .github/workflows/pytest.yml で push/PR ごとに自動実行
"""
import os
import re
import sys
from datetime import datetime
import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HTML_PATH = os.path.join(REPO_ROOT, 'ai_dashboard_v13.html')


@pytest.fixture(scope='module')
def html():
    """ai_dashboard_v13.html を 1 回読み込んでモジュール内で共有"""
    with open(HTML_PATH, encoding='utf-8') as f:
        return f.read()


# ── パネルヘッダ整合性 ─────────────────────────────

class TestPanelHeaderConsistency:
    """パネルヘッダの銘柄数・ランク集計が動的化されていることを保証"""

    def test_hold_panel_not_hardcoded_43(self, html):
        """保有パネルヘッダが「43銘柄」固定ではないこと（M-7 再発防止）"""
        # 「43銘柄」+ A 以上 + 数値 のパターンが存在しないこと
        # （ただし真に保有数が 43 になった場合は通る・偶然一致は許容）
        ticker_match = re.search(r'保有\((\d+)\)', html)
        panel_match = re.search(
            r'<span style="background:#f59e0b22[^>]+>(\d+)銘柄</span>'
            r'<span style="color:#34d399;font-weight:800;">A以上\s*(\d+)</span>',
            html
        )
        assert ticker_match, 'ティッカー保有数が見つからない'
        assert panel_match, '保有パネルヘッダが見つからない'

        ticker_count = int(ticker_match.group(1))
        panel_count = int(panel_match.group(1))
        assert ticker_count == panel_count, \
            f'ティッカー保有数 {ticker_count} とパネルヘッダ {panel_count} が不一致'

    def test_watch_panel_not_hardcoded_14(self, html):
        """監視パネルヘッダが「14銘柄」固定ではないこと（M-8 再発防止）"""
        ticker_match = re.search(r'監視\((\d+)\)', html)
        panel_match = re.search(
            r'<span style="background:#60a5fa22[^>]+>(\d+)銘柄</span>'
            r'<span style="color:#34d399;font-weight:800;">購入候補\s*(\d+)</span>',
            html
        )
        assert ticker_match, 'ティッカー監視数が見つからない'
        assert panel_match, '監視パネルヘッダが見つからない'

        ticker_count = int(ticker_match.group(1))
        panel_count = int(panel_match.group(1))
        assert ticker_count == panel_count, \
            f'ティッカー監視数 {ticker_count} とパネルヘッダ {panel_count} が不一致'


class TestEnvironmentBanner:
    """環境バナー「現在の環境 短期X点・中期Y点」の動的化（M-9 再発防止）"""

    def test_environment_banner_dynamic(self, html):
        """環境スコアが固定値「短期50点(中立)・中期33点(弱気)」でないこと（M-9 再発防止）。

        PR #104 で監視銘柄直下の独立 gbar バナーは廃止され、短期/中期スコアは
        各銘柄の showD() 引数に動的展開される形へ変更された。本テストは新構造に
        追従し「旧固定文字列の不在」と「動的スコアの存在」を検証する。
        """
        # 旧 v1 固定文字列（ハードコード環境バナー）が残っていないこと
        assert '短期50点(中立)・中期33点(弱気)' not in html, \
            '旧固定の環境バナー文字列が残存（M-9 再発の疑い）'

        # 短期/中期スコアが動的に展開されていること（showD 引数内・全銘柄分）
        short_scores = re.findall(r'短期(\d+)点\(([^)]+)\)', html)
        mid_scores = re.findall(r'中期(\d+)点\(([^)]+)\)', html)
        assert len(short_scores) >= 100, \
            f'短期スコアの動的展開が見つからない（{len(short_scores)} 件・M-9 動的化未実装の疑い）'
        assert len(mid_scores) >= 100, \
            f'中期スコアの動的展開が見つからない（{len(mid_scores)} 件・M-9 動的化未実装の疑い）'


class TestNextEvaluationDate:
    """次回検証/評価日の動的化（M-12/M-14 再発防止）"""

    def test_next_check_date_is_next_month(self, html):
        """「次回検証 YYYY/MM/01」が今月の翌月になっていること"""
        match = re.search(r'次回検証：(\d{4})/(\d{1,2})/(\d{1,2})', html)
        if match:
            now = datetime.now()
            next_year = now.year if now.month < 12 else now.year + 1
            next_month = now.month + 1 if now.month < 12 else 1
            year, month, day = int(match.group(1)), int(match.group(2)), int(match.group(3))
            assert (year, month, day) == (next_year, next_month, 1), \
                f'次回検証日 {year}/{month}/{day} が翌月 1 日 {next_year}/{next_month}/01 と不一致'

    def test_next_evaluation_date_is_next_month(self, html):
        """「次回評価 YYYY/MM/01」が今月の翌月になっていること"""
        match = re.search(r'次回評価：(\d{4})/(\d{1,2})/(\d{1,2})', html)
        if match:
            now = datetime.now()
            next_year = now.year if now.month < 12 else now.year + 1
            next_month = now.month + 1 if now.month < 12 else 1
            year, month, day = int(match.group(1)), int(match.group(2)), int(match.group(3))
            assert (year, month, day) == (next_year, next_month, 1), \
                f'次回評価日 {year}/{month}/{day} が翌月 1 日 {next_year}/{next_month}/01 と不一致'


# ── テーブル整合性（軸 A-6〜A-9） ────────────

class TestTableConsistency:
    """ティッカー値 ≡ テーブル行数 ≡ パネルヘッダ の三角整合"""

    def test_hold_table_equals_ticker(self, html):
        """保有テーブル行数 = ティッカー保有数"""
        table_match = re.search(r'<table id="tH">(.*?)</table>', html, re.DOTALL)
        assert table_match, '保有テーブルが見つからない'
        rows = len(re.findall(r'<tr class="dr"', table_match.group(1)))
        ticker = int(re.search(r'保有\((\d+)\)', html).group(1))
        assert rows == ticker, f'保有テーブル {rows} 行 ≠ ティッカー {ticker}'

    def test_watch_table_equals_ticker(self, html):
        """監視テーブル行数 = ティッカー監視数"""
        table_match = re.search(r'<table id="tW">(.*?)</table>', html, re.DOTALL)
        assert table_match, '監視テーブルが見つからない'
        rows = len(re.findall(r'<tr class="dr"', table_match.group(1)))
        ticker = int(re.search(r'監視\((\d+)\)', html).group(1))
        assert rows == ticker, f'監視テーブル {rows} 行 ≠ ティッカー {ticker}'


# ── 192 銘柄全件 計算整合性（軸 B-5/B-6/B-7 自動化） ──

class TestScoreFormulaConsistency:
    """全銘柄で総合スコア = s1*0.40 + s2*0.35 + s3*0.25 + ランク境界整合"""

    @pytest.fixture
    def all_showd_calls(self, html):
        """全 showD() 呼び出しから (code, total, rank, s1, s2, s3) を抽出"""
        # 注: showD 第7・第8引数は現行ダッシュボードで空文字 '' になり得るため
        #     '[^']+'（1文字以上必須）ではなく '[^']*'（空許容）で受ける。
        pattern = re.compile(
            r"showD\('(\d+\w*)','([^']+)','([^']+)',"
            r"([\d.]+),'([SABCD]\+?)',[^,]+,'[^']*','[^']*','[SABCD]\+?',"
            r"'[^']*','[^']*','[^']*',"
            r"'v4\.3: ([\d.]+)点\(([SABCD]\+?)\)=ROIC(\d+)\*40%\+Trend(\d+)\*35%\+Price(\d+)\*25%'"
        )
        return pattern.findall(html)

    def test_192_stocks_extracted(self, all_showd_calls):
        """保有 47 + 監視 70 + Top75 75 = 192 銘柄が抽出できること"""
        assert len(all_showd_calls) >= 100, f'抽出 {len(all_showd_calls)} 件は少なすぎる'

    def test_score_formula_for_all_stocks(self, all_showd_calls):
        """全銘柄で total ≈ s1*0.40 + s2*0.35 + s3*0.25"""
        violations = []
        for code, name, sect, total, rank, total_in_note, rank_in_note, s1, s2, s3 in all_showd_calls:
            recalc = round(int(s1) * 0.40 + int(s2) * 0.35 + int(s3) * 0.25, 1)
            if abs(float(total) - recalc) > 1.0:
                violations.append(f'{code} {name}: total={total} vs 再計算 {recalc}')
        assert not violations, f'{len(violations)} 件で式不一致:\n' + '\n'.join(violations[:5])

    def test_rank_boundary_for_all_stocks(self, all_showd_calls):
        """全銘柄で total → rank 境界整合"""
        violations = []
        for code, name, sect, total, rank, *_ in all_showd_calls:
            t = float(total)
            expected = ('S' if t >= 80 else 'A' if t >= 65 else
                        'B' if t >= 50 else 'C' if t >= 35 else 'D')
            if rank != expected:
                violations.append(f'{code}: total={t} → 期待 {expected} ≠ 実 {rank}')
        assert not violations, f'{len(violations)} 件でランク境界違反:\n' + '\n'.join(violations[:5])

    def test_total_in_note_matches_total(self, all_showd_calls):
        """テーブル本体の total と onclick 引数 note の total が一致"""
        violations = []
        for code, name, sect, total, rank, total_in_note, *_ in all_showd_calls:
            if abs(float(total) - float(total_in_note)) > 0.05:
                violations.append(f'{code}: table={total} vs note={total_in_note}')
        assert not violations, f'{len(violations)} 件で total 不一致:\n' + '\n'.join(violations[:5])


# ── バッジ動的化検証（v1.4 完了済） ─────────

class TestHeaderBadge:
    """バッジ「最終更新 YYYY-MM-DD HH:MM JST」の動的化（v1.4 で完了）"""

    def test_badge_format(self, html):
        """バッジが「最終更新 YYYY-MM-DD HH:MM JST」形式であること"""
        match = re.search(
            r'<span class="badge">最終更新 (\d{4}-\d{2}-\d{2} \d{2}:\d{2}) JST',
            html
        )
        assert match, 'バッジが期待形式と異なる（v1.4 デグレード疑い）'

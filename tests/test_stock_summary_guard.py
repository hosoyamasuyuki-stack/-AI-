"""
3年もつ仕組み: 銘柄「ひとことまとめ」(buildSummary) 回帰ガード
2026-05-19 制定。STRUCTURE_RULES §0 原則4(継続検証) / PR#99 静的ガード思想に準拠。

目的: 将来の誰の編集でも、以下の致命/規約事故を二度と再発させない。
 - 市場全体の虚偽断定・売買助言表現の混入
 - generate_dashboard.py の showD への 'down','down' リテラル復活(全銘柄同一の元凶)
 - buildSummary の例外エンベロープ(try/catch)欠落(showD/賢者 全停止の致命事案クラス)
node 不要・既存 pytest CI でそのまま実行可能な静的アサート。
"""
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HTML = os.path.join(ROOT, "ai_dashboard_v13.html")
GD = os.path.join(ROOT, "generate_dashboard.py")

# 顧客向け まとめ で禁止: 市場全体の断定 + 売買助言 + 規約抵触語
FORBIDDEN = [
    "今の株式市場は急落中", "急落中です", "逆風になる見込み", "焦って売らない",
    "今すぐ買う", "売却を検討", "お勧めしません", "買い時",
    "投資判断", "投資助言", "投資顧問", "利益保証", "運用判断",
]


def _build_summary_src() -> str:
    with open(HTML, encoding="utf-8") as f:
        lines = f.read().split("\n")
    start = next(i for i, l in enumerate(lines) if l.startswith("function buildSummary("))
    end = next(j for j in range(start + 1, len(lines)) if lines[j].rstrip("\r") == "}")
    return "\n".join(lines[start:end + 1])


def test_no_down_literal_in_generate_dashboard():
    """showD に 'down','down' リテラルが復活していない(全銘柄同一の元凶)。"""
    with open(GD, encoding="utf-8") as f:
        src = f.read()
    assert "'down','down'" not in src, "generate_dashboard.py に 'down','down' が復活している"


def test_build_summary_has_exception_envelope():
    """buildSummary が try/catch で showD/賢者 を保護している。"""
    src = _build_summary_src()
    assert "try{" in src or "try {" in src, "buildSummary に try が無い"
    assert "catch(" in src or "catch (" in src, "buildSummary に catch が無い"
    assert "return safe" in src, "buildSummary の安全フォールバック return が無い"


def test_build_summary_has_no_forbidden_phrases():
    """まとめに市場断定・売買助言・規約抵触語が無い(コメント行は除外)。"""
    src = _build_summary_src()
    code = "\n".join(
        l for l in src.split("\n") if not l.lstrip().startswith("//")
    )
    hit = [w for w in FORBIDDEN if w in code]
    assert not hit, f"buildSummary に禁止表現: {hit}"


def test_build_summary_uses_real_per_stock_metrics():
    """まとめが STOCK_SCORES の実数値(roe/fcr/roeT/peg/fy)を使い銘柄別生成している。"""
    src = _build_summary_src()
    assert "STOCK_SCORES[code]" in src, "STOCK_SCORES[code] を参照していない(銘柄別でない疑い)"
    for token in ("roe", "fcr", "fy"):
        assert token in src, f"指標 {token} を使っていない"

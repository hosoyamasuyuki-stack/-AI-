"""
verify/threshold_advisor.py
予測精度から閾値補正候補を抽出する読込専用バッチ

【設計原則・厳守】
- 既存の閾値（core/config.py）には**書込しない**（読込のみ）
- 「閾値補正提案」シートに記録するのみ（CEO 手動レビュー）
- 既存スクリプトは本ファイルを import しない（独立運用）
- 既存シート（保有/監視/コアスキャン_v4.3/コアスキャン_日次/予測記録）に書込しない
- 失敗しても他のスクリプトに影響しない設計

【実行】
- 毎月1日 12:00 JST（monthly_learning.yml の Step 4）
- 手動: python verify/threshold_advisor.py [--dry-run] [--months 6] [--min-samples 30] [--low-rate 60]

【入力】
- core/config.py の閾値（参考表示のみ）
- 「予測記録」シート（個別銘柄 4 軸予測の記録日付）
- STEP0_目先 / STEP0_短期 / STEP0_中期 / STEP0_長期 シート（verify_axis.py 出力・勝敗）

【出力】
- 「閾値補正提案」シート（新設・既存衝突なし）
  ヘッダー: 検証日 / 軸 / スコア帯 / 業種 / 直近勝率 / 標本数 /
           現在閾値 / 提案閾値補正 / CEO 判定 / 補正実施日

【参考】
- weekly_update.py Part6 の check_weight_adjustment（インデックス的中率 70%/60% 判定）の個別銘柄版
- CLAUDE.md line 896「REVIEW 2 連続したら学習用 100 銘柄でモデル再検証」

【作成日】2026-05-07（B-1-1）
【参考仕様書】Dropbox/にこにこ本舗/PROCEDURE_SELF_LEARNING_IMPROVEMENT_2026-05-07.md v2.0
"""

import os
import sys
import argparse
import warnings
from datetime import datetime, timedelta
from collections import defaultdict

import gspread

# 既存閾値を読込のみで参照（書込API は呼ばない・呼べない設計）
from core.config import (ROE_THR, FCR_THR, RS_THR, FS_THR, PEG_THR, FCY_THR)
from core.auth import get_spreadsheet

warnings.filterwarnings('ignore')

# ── 引数パース ─────────────────────────────────────────────
parser = argparse.ArgumentParser(
    description='閾値補正提案を生成（読込のみ・既存閾値変更なし・CEO レビュー用）'
)
parser.add_argument('--months',      type=int,   default=6,
                    help='集計対象期間（月数・既定 6）')
parser.add_argument('--min-samples', type=int,   default=30,
                    help='最小標本数（既定 30）')
parser.add_argument('--low-rate',    type=float, default=60.0,
                    help='検討候補の勝率閾値（％・既定 60.0）')
parser.add_argument('--dry-run',     action='store_true',
                    help='シート書込を行わず標準出力のみ')
args = parser.parse_args()

NOW     = datetime.now()
NOW_STR = NOW.strftime('%Y/%m/%d %H:%M')
TODAY   = NOW.date()
CUTOFF  = TODAY - timedelta(days=30 * args.months)

print(f"=== threshold_advisor v1.0 ({NOW_STR}) ===")
print(f"集計対象: 直近 {args.months} ヶ月（{CUTOFF} 以降）")
print(f"最小標本数: {args.min_samples}")
print(f"検討候補勝率閾値: < {args.low_rate}%")
print(f"モード: {'DRY-RUN' if args.dry_run else 'LIVE'}")

# ── Sheets 接続 ────────────────────────────────────────────
ss = get_spreadsheet()
print(f"接続完了: {ss.title}")


# ── STEP0_<axis> シートから勝敗データ収集 ──────────────────
def load_step0_results():
    """4 軸の STEP0_* シートから勝敗データを読込"""
    axes_en = {'目先': 'near', '短期': 'short', '中期': 'mid', '長期': 'long'}
    results = []
    for axis_jp, axis_en in axes_en.items():
        sheet_name = f"STEP0_{axis_en}"
        try:
            ws = ss.worksheet(sheet_name)
            rows = ws.get_all_values()
            # verify_axis.py の出力構造:
            # 行 0-8: メタ行（タイトル・verify_date・NK225・凡例・空行）
            # 行 9: データヘッダー（code/name/sector/score/rank/direction/.../result/note）
            # 行 10 以降: データ
            if len(rows) < 11:
                continue
            header = rows[9]
            for row in rows[10:]:
                if len(row) < 13:
                    continue
                code = row[0].strip()
                if not code:
                    continue
                rec = dict(zip(header, row + [''] * (len(header) - len(row))))
                results.append({
                    'axis_jp': axis_jp,
                    'code':    code,
                    'name':    rec.get('name', ''),
                    'sector':  rec.get('sector', ''),
                    'score':   rec.get('score', ''),
                    'rank':    rec.get('rank', ''),
                    'result':  rec.get('result', ''),       # 'win' / 'lose' / 'no data'
                    'days':    rec.get('days_elapsed', ''),
                })
        except Exception as e:
            print(f"  WARN: {sheet_name} 読込失敗: {e}")
    return results


# ── 予測記録から記録日付を取得（CUTOFF フィルタ用）──────────
def load_predict_dates():
    """予測記録シートから記録日付 + コードを読込"""
    try:
        ws   = ss.worksheet('予測記録')
        rows = ws.get_all_values()
        if len(rows) < 3:
            return {}
        # 行 0 = ヘッダー, 行 1 = サブヘッダー, 行 2 以降 = データ
        date_map = {}
        for row in rows[2:]:
            if len(row) < 2:
                continue
            try:
                d    = datetime.strptime(row[0].replace('-', '/'), '%Y/%m/%d').date()
                code = row[1].strip()
                if code:
                    date_map.setdefault(code, []).append(d)
            except Exception:
                continue
        return date_map
    except Exception as e:
        print(f"  WARN: 予測記録 読込失敗: {e}")
        return {}


# ── 集計 ──────────────────────────────────────────────────
def analyze(results, date_map):
    """
    軸別 × ランク別 × 業種別の勝率を集計し、低勝率セグメントを抽出
    （weekly_update.py Part6 の check_weight_adjustment 個別銘柄版）
    """
    # CUTOFF より新しい予測のみフィルタ
    filtered = []
    for r in results:
        if r['result'] not in ('win', 'lose'):
            continue
        dates = date_map.get(r['code'], [])
        if not any(d >= CUTOFF for d in dates):
            continue
        filtered.append(r)

    print(f"\n集計対象（{args.months} ヶ月フィルタ後）: {len(filtered)} レコード")

    # 軸 × ランク × 業種 でグループ化
    groups = defaultdict(lambda: {'win': 0, 'lose': 0})
    for r in filtered:
        key = (r['axis_jp'], r['rank'], r['sector'])
        if r['result'] == 'win':
            groups[key]['win'] += 1
        elif r['result'] == 'lose':
            groups[key]['lose'] += 1

    # 検討候補抽出（最小標本数以上 + 勝率 low_rate 未満）
    candidates = []
    for (axis, rank, sector), counts in groups.items():
        total = counts['win'] + counts['lose']
        if total < args.min_samples:
            continue
        rate = counts['win'] / total * 100
        if rate >= args.low_rate:
            continue
        candidates.append({
            'axis':   axis,
            'rank':   rank,
            'sector': sector,
            'total':  total,
            'win':    counts['win'],
            'rate':   round(rate, 1),
        })

    candidates.sort(key=lambda c: c['rate'])
    return candidates, len(filtered)


# ── 提案生成 ──────────────────────────────────────────────
def generate_proposal(c):
    """
    検討候補から閾値補正提案を生成（保守的・自動補正は行わない）

    ロジック:
      - 勝率 50% 未満 = ROE_THR/FCR_THR を +2pt 上方修正候補（ランク厳格化）
      - 勝率 50-60% = +1pt 上方修正候補（経過観察）
      - それ以上 = 経過観察

    ⚠️ これは「提案」であり、core/config.py を自動更新しない（CEO 手動判定）
    """
    if c['rate'] < 50:
        return (f"ROE_THR/FCR_THR を +2pt 上方修正候補"
                f"（{c['rank']}ランクの該当業種をより厳格化・要 CEO 判定）")
    elif c['rate'] < 60:
        return (f"ROE_THR/FCR_THR を +1pt 上方修正候補（経過観察）")
    return "経過観察"


# ── シート書込 ────────────────────────────────────────────
def write_to_sheet(candidates, total_samples):
    """「閾値補正提案」シートに書込（既存衝突なし・新設）"""
    SHEET_NAME = '閾値補正提案'

    # 既存シート確認 → クリア or 新設
    try:
        ws = ss.worksheet(SHEET_NAME)
        ws.clear()
    except gspread.exceptions.WorksheetNotFound:
        ws = ss.add_worksheet(title=SHEET_NAME, rows=200, cols=10)
        print(f"  新規作成: {SHEET_NAME}")

    # 次回実行日（毎月1日）
    next_run = (NOW.replace(day=1) + timedelta(days=32)).replace(day=1)

    # メタ 3 行 + 空行 + ヘッダー + データ
    rows = [
        ['最終実行日',   NOW_STR,                                                                          '', '', '', '', '', '', '', ''],
        ['実行結果',     f"success（提案 {len(candidates)} 件 / 標本数合計 {total_samples} 件）",          '', '', '', '', '', '', '', ''],
        ['次回実行予定', next_run.strftime('%Y/%m/%d'),                                                    '', '', '', '', '', '', '', ''],
        ['',             '',                                                                                '', '', '', '', '', '', '', ''],
        ['検証日', '軸', 'スコア帯', '業種', '直近勝率', '標本数', '現在閾値', '提案閾値補正', 'CEO 判定', '補正実施日'],
    ]

    if not candidates:
        rows.append([
            NOW.strftime('%Y/%m/%d'),
            '–', '–', '–', '–', '–', '–',
            f'提案 0 件（標本不足 or 全勝率 {args.low_rate}% 以上 = 既存閾値の妥当性が維持されている）',
            '', '',
        ])
    else:
        for c in candidates:
            current_threshold = (f"ROE_THR=[(25,100),(20,85),...] "
                                 f"FCR_THR=[(120,100),(100,90),...]")
            rows.append([
                NOW.strftime('%Y/%m/%d'),
                c['axis'],
                c['rank'],
                c['sector'],
                f"{c['rate']}%",
                c['total'],
                current_threshold,
                generate_proposal(c),
                '',  # CEO 判定（手動入力）
                '',  # 補正実施日（手動入力）
            ])

    ws.update('A1', rows)
    print(f"  ✅ {SHEET_NAME} 書込完了: 提案 {len(candidates)} 件 + メタ 4 行")


# ── 作業ログ記録 ──────────────────────────────────────────
def log_to_work_log(candidates, total_samples):
    """作業ログシートに記録"""
    try:
        wl   = ss.worksheet('作業ログ')
        last = len(wl.get_all_values()) + 1
        wl.update(f'A{last}', [[
            NOW_STR,
            'threshold_advisor.py',
            f'閾値補正提案生成: {len(candidates)} 件 / 標本数 {total_samples}',
            '読込のみ・既存閾値変更なし',
            '✅完了',
        ]])
    except Exception:
        pass


# ── メイン ─────────────────────────────────────────────────
def main():
    print("\n=== Step 1: STEP0_<axis> シート読込 ===")
    results = load_step0_results()
    print(f"  4 軸合計: {len(results)} レコード")

    print("\n=== Step 2: 予測記録から日付取得 ===")
    date_map = load_predict_dates()
    print(f"  予測記録銘柄数: {len(date_map)}")

    print("\n=== Step 3: 勝率集計 + 検討候補抽出 ===")
    candidates, total_samples = analyze(results, date_map)
    print(f"  検討候補: {len(candidates)} 件")
    if candidates:
        print(f"  上位 10 件:")
        for c in candidates[:10]:
            print(f"    [{c['axis']}] {c['rank']} / {c['sector']}: "
                  f"{c['rate']}% ({c['win']}/{c['total']})")

    print("\n=== Step 4: シート書込 ===")
    if args.dry_run:
        print("  [DRY-RUN] シート書込スキップ")
    else:
        write_to_sheet(candidates, total_samples)
        log_to_work_log(candidates, total_samples)

    print(f"\n✅ 完了: {NOW_STR}")
    print(f"次回実行: 毎月1日 12:00 JST（monthly_learning.yml の Step 4）")
    print(f"レビュー手順: PRE_LAUNCH_HEALTH_CHECK_SPEC.md v1.2 §H 参照")


if __name__ == '__main__':
    main()

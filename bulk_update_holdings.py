# ============================================================
# bulk_update_holdings.py v3.2
# AI投資判断システム 保有ポートフォリオ一括更新
#
# v3.2 (2026-05-08) PROCEDURE_BULK_HOLDINGS_DIFF_PERFECTION v1.2 反映:
#   - A: DIFF_COLS 11→12 列拡張（口座区分追加・compute_diff key を 5 要素化）
#   - B: 保有差分_履歴 シート新設・追記式（過去全月分を時系列保持）
#   - C: 連続月チェック警告（直前月でない場合 WARN）
#   - D: 引数なし実行のハング防止（即時 exit 2）
#   - F: --snapshot-month オプション（過去月後付け投入）
#   - G: --snapshot-only オプション（master/extended 保護モード）
#
# v3 (2026-04-30) からの引継ぎ:
#   - 入力 CSV は portfolio-extractor v3 仕様（14 列・日本語列名）
#   - LISA 表示シート（保有ポートフォリオ_master）= LISA表示=TRUE のみ抽出
#   - 全体閲覧シート（保有ポートフォリオ_extended）= 全件
#
# 既存システムへの干渉: ゼロ
#   - 既存の「保有銘柄_v4.3スコア」「監視銘柄_v4.3スコア」「予測記録」などには触れない
#   - 新シート 5 本（master / extended / snapshot / diff / history）を独立管理
#
# 実行例:
#   通常運用（当月）:
#     python bulk_update_holdings.py --csv-file portfolio.csv
#   過去月後付け投入（STEP 0 の 4 月末スナップショット投入）:
#     python bulk_update_holdings.py --csv-file 2026-04-30_保有銘柄統合.csv \
#         --snapshot-month=2026-04-01 --snapshot-only
#   ドライラン:
#     python bulk_update_holdings.py --csv-file portfolio.csv --dry-run
# ============================================================
import os
import sys
import io
import csv
import re
import argparse
import warnings
from datetime import datetime

import gspread

from core.config import SPREADSHEET_ID, GSHEETS_SCOPE
from core.auth import get_spreadsheet

warnings.filterwarnings('ignore')

# ── 定数 ─────────────────────────────────────────────────────
SHEET_MASTER     = '保有ポートフォリオ_master'      # LISA表示=TRUE のみ
SHEET_EXTENDED   = '保有ポートフォリオ_extended'    # 全件（CEO 全体閲覧用）
SHEET_SNAPSHOT   = '保有スナップショット'           # 月次累積
SHEET_DIFF       = '保有差分'                       # 当月差分（即時表示用）
SHEET_HISTORY    = '保有差分_履歴'                  # 過去全月分（取引履歴ページ用）★v1.2 新設

# v3 入力 CSV カラム（日本語）
INPUT_COLS = ['取得日', '個人/法人', '証券会社', '口座区分', '市場', '種別',
              '証券コード', '銘柄名', '株数', '通貨', '取得単価', '現在値',
              '評価額(円)', 'LISA表示']

MASTER_COLS = INPUT_COLS  # master / extended は入力と同じ 14 列を保持
SNAPSHOT_COLS = ['snapshot_month'] + INPUT_COLS  # 月次キー追加（15 列）
# A 修正: DIFF_COLS を 11 → 12 列に拡張（口座区分を 5 列目に追加）
DIFF_COLS = ['month', 'change_type', '個人/法人', '証券会社', '口座区分', '市場', '種別',
             '証券コード', '銘柄名', '株数_前月', '株数_当月', '差分']

NOW   = datetime.now()
NOW_S = NOW.strftime('%Y/%m/%d %H:%M:%S')
DEFAULT_SNAPSHOT_MONTH = NOW.strftime('%Y-%m-01')


# ── シート確保（無ければ作成） ──────────────────────────────
def ensure_sheet(ss, sheet_name, header_cols):
    try:
        ws = ss.worksheet(sheet_name)
        all_vals = ws.get_all_values()
        if not all_vals:
            ws.update('A1', [header_cols])
        return ws
    except gspread.exceptions.WorksheetNotFound:
        ws = ss.add_worksheet(title=sheet_name, rows=2000, cols=len(header_cols))
        ws.update('A1', [header_cols])
        print(f"  [新規作成] {sheet_name}")
        return ws


# ── DIFF_COLS 11→12 列拡張に伴う既存シートヘッダ強制更新（A 修正・部長指摘 MUST-2） ──
def force_update_diff_header(ss):
    """既存 保有差分 / 保有差分_履歴 シートのヘッダを 12 列形式に強制更新。
    旧 11 列形式のデータ行は「口座区分」空欄のまま温存（後方互換）。
    """
    for sheet_name in (SHEET_DIFF, SHEET_HISTORY):
        try:
            ws = ss.worksheet(sheet_name)
            existing = ws.get_all_values()
            if existing and len(existing[0]) != len(DIFF_COLS):
                print(f"  [HEADER UPDATE] {sheet_name}: {len(existing[0])} → {len(DIFF_COLS)} 列")
                ws.update('A1', [DIFF_COLS])
        except gspread.exceptions.WorksheetNotFound:
            pass  # ensure_sheet が後で新規作成


# ── CSV パース（v3 仕様・日本語列対応） ────────────────────
def parse_csv_text(text):
    """v3 統合 CSV をパース。BOM/CRLF/UTF-8-sig 対応。"""
    text = (text or '').strip()
    if not text:
        return []
    if text.startswith('﻿'):
        text = text[1:]

    reader = csv.DictReader(io.StringIO(text))
    rows = []
    for raw in reader:
        if not raw:
            continue
        row = {(k or '').strip(): (v or '').strip() for k, v in raw.items() if k}
        if not row.get('証券コード'):
            continue
        rows.append(row)
    return rows


# ── master / extended 全置換 ────────────────────────────────
def replace_sheet(ws, rows, cols):
    """シート全体を rows で置き換え（ヘッダ行は維持）。"""
    new_data = [[r.get(c, '') for c in cols] for r in rows]
    last_row = max(2, len(ws.get_all_values()))
    ws.batch_clear([f"A2:{chr(ord('A') + len(cols) - 1)}{last_row}"])
    if new_data:
        ws.update('A2', new_data, value_input_option='USER_ENTERED')
    return len(new_data)


# ── snapshot upsert ──────────────────────────────────────────
def upsert_snapshot(ws, rows, snapshot_month):
    """指定月のスナップショットを upsert（既存の同月行を消してから書込）。"""
    all_vals = ws.get_all_values()
    body = all_vals[1:] if len(all_vals) > 1 else []

    # 指定月以外を保持
    keep = [row for row in body if (len(row) > 0 and row[0] != snapshot_month)]

    new_body = keep + [
        [snapshot_month] + [r.get(c, '') for c in INPUT_COLS]
        for r in rows
    ]

    last_row = max(2, len(all_vals) + len(rows))
    last_col = chr(ord('A') + len(SNAPSHOT_COLS) - 1)
    ws.batch_clear([f"A2:{last_col}{last_row}"])
    if new_body:
        ws.update('A2', new_body, value_input_option='USER_ENTERED')


# ── diff 計算（A 修正: key 5 要素化 / C 修正: 連続月警告） ──
def compute_diff(snapshot_ws, current_month):
    """直近過去月と current_month を比較して差分行を生成。
    A 修正: キー = (個人/法人, 証券会社, 口座区分, 市場, 証券コード) 5 要素
    C 修正: 直前月でない場合に WARN ログ
    """
    all_vals = snapshot_ws.get_all_values()
    if len(all_vals) < 2:
        return []

    body = all_vals[1:]
    months = sorted({row[0] for row in body if row and row[0]})
    if current_month not in months:
        return []

    past_months = [m for m in months if m < current_month]
    if not past_months:
        prev_map = {}
        print(f"  [INFO] 過去月のスナップショットなし → 全銘柄が「新規」扱い")
    else:
        prev_month = past_months[-1]

        # ── 連続月チェック（C 修正） ──
        try:
            _curr_dt = datetime.strptime(current_month, '%Y-%m-01')
            _prev_dt = datetime.strptime(prev_month, '%Y-%m-01')
            _months_gap = (_curr_dt.year - _prev_dt.year) * 12 + (_curr_dt.month - _prev_dt.month)
            if _months_gap > 1:
                print(f"  [WARN] 直前のスナップショットは {prev_month}（{_months_gap} ヶ月前）")
                print(f"         先月のデータがないため「先月との差分」ではなく「{_months_gap} ヶ月前との差分」を計算します")
        except ValueError as _e:
            print(f"  [WARN] 連続月チェック失敗: {_e}")

        prev_map = {}
        for r in body:
            if r and r[0] == prev_month and len(r) >= 14:
                # SNAPSHOT_COLS = [snapshot_month, 取得日, 個人/法人, 証券会社, 口座区分,
                #                  市場, 種別, 証券コード, 銘柄名, 株数, ...]
                key = (r[2], r[3], r[4], r[5], r[7])  # A 修正: 口座区分(r[4]) を追加
                prev_map[key] = (float(r[9] or 0), r[8], r[6])  # shares, 銘柄名, 種別（全売却の引継ぎ用）

    curr_map = {}
    for r in body:
        if r and r[0] == current_month and len(r) >= 14:
            key = (r[2], r[3], r[4], r[5], r[7])  # A 修正: 5 要素
            curr_map[key] = (float(r[9] or 0), r[8], r[6])  # shares, 銘柄名, 種別

    # ── 銘柄合計（net）で集計（複数口座にまたがる銘柄の誤判定防止・CEO 2026-06）──
    # 例: 6637 を法人で全売却・個人(楽天)で継続保有 → 口座別だと法人分の 100→0 だけ見て
    #     「全売却」と誤判定。銘柄合計なら 300→200=一部売却 と正しく判定される。
    # 個人/法人・証券会社・口座区分は銘柄合算では非該当のため空欄（顧客非表示・CEO指示）。
    code_agg = {}
    for src_map, fld in ((prev_map, 'prev'), (curr_map, 'curr')):
        for key, val in src_map.items():
            market, code = key[3], key[4]
            a = code_agg.setdefault(code, {'prev': 0.0, 'curr': 0.0, 'name': '', 'kind': '', 'market': market})
            a[fld] += val[0]
            a['market'] = market
            if val[1]:
                a['name'] = val[1]
            if val[2]:
                a['kind'] = val[2]

    diffs = []
    for code in sorted(code_agg.keys()):
        a = code_agg[code]
        prev_shares = a['prev']
        curr_shares = a['curr']
        delta = curr_shares - prev_shares

        if prev_shares == 0 and curr_shares > 0:
            # past_months が空のときは「初期保有」（CEO 指示 2026-05-08）/ ありなら「新規」
            ct = '初期保有' if not past_months else '新規'
        elif prev_shares > 0 and curr_shares == 0:
            ct = '全売却'
        elif delta > 0:
            ct = '増し玉'
        elif delta < 0:
            ct = '一部売却'
        else:
            continue  # 変化なしはスキップ

        # 区分（個人法人/証券会社/口座区分）は銘柄合算では空欄（顧客非表示）
        diffs.append([current_month, ct, '', '', '', a['market'], a['kind'],
                      code, a['name'], prev_shares, curr_shares, delta])
    return diffs


# ── diff 全置換（即時表示用） ────────────────────────────────
def write_diff(ws, diffs):
    last_row = max(2, len(ws.get_all_values()))
    last_col = chr(ord('A') + len(DIFF_COLS) - 1)
    ws.batch_clear([f"A2:{last_col}{last_row}"])
    if diffs:
        ws.update('A2', diffs, value_input_option='USER_ENTERED')


# ── 履歴シート追記（B 新設・取引履歴ページのデータソース） ──
def append_history(ws, diffs, current_month):
    """保有差分_履歴 に当月分を追記（再実行時の重複は排除）。"""
    all_vals = ws.get_all_values()
    if not all_vals:
        ws.update('A1', [DIFF_COLS])
        all_vals = [DIFF_COLS]
    body = all_vals[1:] if len(all_vals) > 1 else []

    # 当月分以外を保持
    keep = [row for row in body if (len(row) > 0 and row[0] != current_month)]

    new_body = keep + diffs

    last_row = max(2, len(all_vals) + len(diffs))
    last_col = chr(ord('A') + len(DIFF_COLS) - 1)
    ws.batch_clear([f"A2:{last_col}{last_row}"])
    if new_body:
        ws.update('A2', new_body, value_input_option='USER_ENTERED')


# ── メイン ──────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description='保有ポートフォリオ一括更新 v3.2')
    parser.add_argument('--csv-file', help='v3 統合 CSV ファイルパス')
    parser.add_argument('--csv-text', help='v3 統合 CSV 本文')
    parser.add_argument('--dry-run',  action='store_true',
                        help='Sheets 書き込みせず検証のみ')
    parser.add_argument('--snapshot-month',
                        help='snapshot_month を上書き（例: 2026-04-01・過去月後付け投入用）')
    parser.add_argument('--snapshot-only', action='store_true',
                        help='snapshot/diff/history のみ更新し、master/extended は触らない（過去月投入時の上書き保護）')
    args = parser.parse_args()

    # F 修正: snapshot_month の決定とフォーマット検証
    snapshot_month = args.snapshot_month or DEFAULT_SNAPSHOT_MONTH
    if not re.match(r'^\d{4}-\d{2}-01$', snapshot_month):
        print(f"ERROR: --snapshot-month は YYYY-MM-01 形式で指定してください: {snapshot_month}")
        sys.exit(2)

    # CSV 取得（D 修正: 引数なしハング防止）
    text = None
    if args.csv_text:
        text = args.csv_text
    elif args.csv_file:
        with open(args.csv_file, encoding='utf-8-sig') as f:
            text = f.read()
    elif os.environ.get('HOLDINGS_CSV'):
        text = os.environ['HOLDINGS_CSV']

    if not text or not text.strip():
        print("ERROR: CSV 入力がありません。--csv-file / --csv-text / 環境変数 HOLDINGS_CSV のいずれかを指定してください。")
        sys.exit(2)

    print(f"{'='*60}")
    print(f"保有ポートフォリオ一括更新 v3.2")
    print(f"実行日時: {NOW_S}")
    print(f"対象月  : {snapshot_month}{'  (CLI 指定)' if args.snapshot_month else ''}")
    if args.snapshot_only:
        print(f"モード  : SNAPSHOT-ONLY (master/extended は保護)")
    if args.dry_run:
        print(f"モード  : DRY-RUN (Sheets 書き込みなし)")
    print(f"{'='*60}")

    rows = parse_csv_text(text)
    print(f"  CSV パース: {len(rows)} 行")

    # LISA 表示対象（master）と全件（extended）を分離
    lisa_rows = [r for r in rows if (r.get('LISA表示') or '').upper() == 'TRUE']
    print(f"  LISA 表示対象（master 行き）: {len(lisa_rows)} 行")
    print(f"  全件（extended 行き）        : {len(rows)} 行")

    if args.dry_run:
        print("\n[DRY-RUN] Sheets 書き込みをスキップ")
        for r in lisa_rows[:5]:
            print(f"  {r}")
        return

    # Sheets 書き込み
    ss = get_spreadsheet()

    # A 修正: 既存シートのヘッダを 12 列に強制更新（必要時のみ）
    force_update_diff_header(ss)

    ws_master   = ensure_sheet(ss, SHEET_MASTER,   MASTER_COLS)
    ws_extended = ensure_sheet(ss, SHEET_EXTENDED, MASTER_COLS)
    ws_snapshot = ensure_sheet(ss, SHEET_SNAPSHOT, SNAPSHOT_COLS)
    ws_diff     = ensure_sheet(ss, SHEET_DIFF,     DIFF_COLS)
    ws_history  = ensure_sheet(ss, SHEET_HISTORY,  DIFF_COLS)  # B 新設

    # G 修正: snapshot-only モード時は master/extended を保護
    if args.snapshot_only:
        print(f"  [SNAPSHOT-ONLY] master/extended は保護（更新スキップ）")
        n_master = 0
        n_ext = 0
    else:
        n_master = replace_sheet(ws_master,   lisa_rows, MASTER_COLS)
        n_ext    = replace_sheet(ws_extended, rows,      MASTER_COLS)
        print(f"  master 更新   : {n_master} 行（LISA 表示対象）")
        print(f"  extended 更新 : {n_ext} 行（全件・CEO 全体閲覧）")

    # スナップショット（全件で履歴管理）
    upsert_snapshot(ws_snapshot, rows, snapshot_month)
    print(f"  snapshot upsert: {snapshot_month}")

    # 差分（全件ベース・先月との変化）
    diffs = compute_diff(ws_snapshot, snapshot_month)
    write_diff(ws_diff, diffs)
    print(f"  diff 生成     : {len(diffs)} 件")

    # B 新設: 履歴シートへの追記（取引履歴ページのデータソース）
    append_history(ws_history, diffs, snapshot_month)
    print(f"  history 追記  : {len(diffs)} 件（{snapshot_month}）")

    print(f"\n{'='*60}")
    print(f"完了: master={n_master} / extended={n_ext} / diffs={len(diffs)}")
    print(f"{'='*60}")


if __name__ == '__main__':
    main()

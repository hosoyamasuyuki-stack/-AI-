# ============================================================
# bulk_diff_apply.py
# 統合 CSV と既存 Sheets `保有銘柄_v4.3スコア` の差分を計算し、
# 既存 manage_stock.py の add_stock / remove_stock を for ループで呼出
# 4 シート cascade（コアスキャン_v4.3 / コアスキャン_日次 / 予測記録）も自動連動
#
# 設計思想:
#   - 新規ロジック追加なし（manage_stock.py を 100% 流用）
#   - 失敗銘柄はスキップして他は続行
#   - dry-run モード必須（差分プレビュー → CEO 承認 → 本番実行の 2 段階）
#
# CEO 承認手順書: 金融投資/保有銘柄/PROCEDURE_2026-04-30.md
#
# 実行:
#   python bulk_diff_apply.py --csv path/to/portfolio.csv --dry-run
#   python bulk_diff_apply.py --csv path/to/portfolio.csv          # 本番
# ============================================================
import os
import sys
import csv
import argparse
import time
import warnings
from datetime import datetime

import gspread
from core.config import SPREADSHEET_ID, GSHEETS_SCOPE
from core.auth import get_spreadsheet

# 既存 manage_stock.py の関数をそのまま import
from manage_stock import add_stock, remove_stock, move_stock, find_row_by_code, SHEET_MAP

warnings.filterwarnings('ignore')

NOW = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
TIMESTAMP = datetime.now().strftime('%Y%m%d-%H%M%S')

# バックアップ対象シート（manage_stock の cascade 対象 + 監視）。
# 監視は『売却→監視へ移行』で破壊的更新を受けるためロールバック資産として必須（2026-06-22 追加）。
BACKUP_SHEETS = [
    '保有銘柄_v4.3スコア',
    '監視銘柄_v4.3スコア',
    'コアスキャン_v4.3',
    'コアスキャン_日次',
    '予測記録',
]


def backup_sheets(ss, out_dir):
    """4 シートを CSV エクスポートして out_dir に保存。"""
    os.makedirs(out_dir, exist_ok=True)
    saved = []
    for sheet_name in BACKUP_SHEETS:
        try:
            ws = ss.worksheet(sheet_name)
            all_vals = ws.get_all_values()
            safe_name = sheet_name.replace('/', '_').replace(' ', '_')
            out = os.path.join(out_dir, f'{safe_name}.csv')
            with open(out, 'w', encoding='utf-8-sig', newline='') as f:
                writer = csv.writer(f)
                for row in all_vals:
                    writer.writerow(row)
            saved.append((sheet_name, out, len(all_vals)))
            print(f"  [BACKUP] {sheet_name}: {len(all_vals)} 行 → {out}")
        except Exception as e:
            print(f"  [BACKUP-WARN] {sheet_name}: {e}")
    return saved


def parse_csv(path):
    """統合 CSV から『どれか1行でも LISA表示=TRUE』の銘柄コード集合を返す。
    複数口座（個人/法人・SBI/楽天）で同一コードが複数行になっても、1行でも TRUE なら保有とみなす（OR集約）。
    コードは大文字に正規化（130A/130a・全角差の取りこぼし防止＝全経路で統一）。"""
    codes = {}
    with open(path, encoding='utf-8-sig') as f:
        for r in csv.DictReader(f):
            if (r.get('LISA表示') or '').strip().upper() != 'TRUE':
                continue
            code = (r.get('証券コード') or '').strip().upper()
            if code and code not in codes:
                codes[code] = r.get('銘柄名', '')
    return codes


def get_existing_codes(ss):
    """既存 Sheets `保有銘柄_v4.3スコア` の A 列（2 行目以降）から銘柄コード集合を取得。"""
    ws = ss.worksheet(SHEET_MAP['保有'])
    all_vals = ws.get_all_values()
    if len(all_vals) < 2:
        return {}
    header = all_vals[0]
    code_col = 0
    for i, h in enumerate(header):
        if h in ('コード', '銘柄コード'):
            code_col = i
            break
    name_col = 1 if len(header) > 1 else 0
    existing = {}
    for row in all_vals[1:]:
        if len(row) > code_col:
            code = str(row[code_col]).strip().upper()  # CSV側と同じ大文字正規化で集合比較の取りこぼしを防ぐ
            if code:
                existing[code] = row[name_col] if len(row) > name_col else ''
    return existing


def compute_diff(latest, existing):
    """差分計算。"""
    latest_set = set(latest.keys())
    existing_set = set(existing.keys())
    return {
        'keep':   sorted(latest_set & existing_set),
        'remove': sorted(existing_set - latest_set),
        'add':    sorted(latest_set - existing_set),
    }


def print_diff_report(diff, latest, existing):
    print(f"\n{'='*60}")
    print(f"差分計算結果")
    print(f"{'='*60}")
    print(f"継続保有: {len(diff['keep'])} 銘柄（操作なし）")
    print(f"\n監視へ移行（売却=保有ゼロ・記録は保全）対象: {len(diff['remove'])} 銘柄")
    print(f"  ※ これらは保有から消すのではなく『監視』へ移ります（取引履歴にも残ります）。")
    for c in diff['remove']:
        print(f"  → {c} {existing.get(c, '?')}")
    print(f"\n追加対象（新規 or 監視からの買い戻し）: {len(diff['add'])} 銘柄")
    for c in diff['add']:
        print(f"  + {c} {latest.get(c, '?')}")
    print(f"{'='*60}\n")


def main():
    parser = argparse.ArgumentParser(description='保有銘柄 差分一括反映')
    parser.add_argument('--csv', required=True, help='v3 統合 CSV パス')
    parser.add_argument('--dry-run', action='store_true',
                        help='Sheets 書込なし・差分計算のみ表示')
    parser.add_argument('--sleep-sec', type=float, default=2.0,
                        help='各 manage_stock 呼出間の待機秒数（J-Quants レート対策）')
    args = parser.parse_args()

    print(f"{'='*60}")
    print(f"bulk_diff_apply v1.0  ({NOW})")
    print(f"CSV : {args.csv}")
    print(f"Mode: {'DRY-RUN' if args.dry_run else 'LIVE'}")
    print(f"{'='*60}")

    # CSV から最新銘柄取得
    latest = parse_csv(args.csv)
    print(f"\nCSV から取得: {len(latest)} 銘柄（LISA表示=TRUE）")

    # 既存 Sheets から取得
    ss = get_spreadsheet()
    existing = get_existing_codes(ss)
    print(f"Sheets 既存 : {len(existing)} 銘柄")

    # 差分計算
    diff = compute_diff(latest, existing)
    print_diff_report(diff, latest, existing)

    if args.dry_run:
        print("[DRY-RUN] Sheets 書き込みはスキップしました")
        print(f"本番実行するには --dry-run を外して再実行")
        return

    # ── Step 4: 事前バックアップ（必須・自動）──────────────
    backup_dir = os.environ.get('BACKUP_DIR', f'/tmp/holdings_backup/{TIMESTAMP}')
    need = len(BACKUP_SHEETS)
    print(f"\n{'='*60}")
    print(f"事前バックアップ作成中（{need} シート → {backup_dir}）")
    print(f"{'='*60}")
    saved = backup_sheets(ss, backup_dir)
    if len(saved) < need:
        print(f"\n⚠️ バックアップが不完全です（{len(saved)}/{need} シート）。中止します。")
        sys.exit(1)
    print(f"\n✅ バックアップ完了: {len(saved)} シート保存")

    # 本番実行
    print(f"\n{'='*60}")
    print(f"本番実行開始（manage_stock.py を {len(diff['remove']) + len(diff['add'])} 回呼出）")
    print(f"{'='*60}")

    success_remove, fail_remove = [], []
    success_add, fail_add = [], []
    watch_sheet = SHEET_MAP['監視']

    # 売却（CSVから外れた＝保有ゼロ）銘柄は「消す」のではなく「監視へ移行」する（CEO 2026-06-22）。
    #   ・監視に未在籍 → move_stock(code,'監視')（保有→監視へ移動・予測記録はそのまま＝観察継続・売却印なし）
    #   ・既に監視にも在籍（二重在籍）→ 移動できないので保有側だけ削除（cascade/売却印なし＝監視で観察継続）
    for i, code in enumerate(diff['remove'], 1):
        n = len(diff['remove'])
        try:
            print(f"\n[監視へ移行 {i}/{n}] {code} {existing.get(code, '?')} 保有→監視 ...")
            watch_row, _ = find_row_by_code(ss.worksheet(watch_sheet), code)
            if watch_row:
                # 二重在籍: 監視の既存行は壊さず、保有側だけ削除（売却印を付けない＝監視で観察継続）
                remove_stock(code, '保有', cascade=False, mark_sold=False)
                print(f"  ✓ 保有側のみ削除（監視に既存・観察継続）")
            else:
                move_stock(code, '監視')
                print(f"  ✓ 監視へ移行完了")
            success_remove.append(code)
        except SystemExit:
            # manage_stock 側は失敗時 sys.exit(1) するので例外で捕捉
            fail_remove.append(code)
            print(f"  ✗ 監視へ移行 失敗（manage_stock 内部エラー）")
        except Exception as e:
            fail_remove.append(code)
            print(f"  ✗ 監視へ移行 失敗: {e}")
        if i < n + len(diff['add']):
            time.sleep(args.sleep_sec)

    # add: CSVに新たに載った銘柄。監視に在れば「買い戻し」として監視→保有へ戻す。無ければ新規追加。
    for i, code in enumerate(diff['add'], 1):
        n = len(diff['add'])
        try:
            print(f"\n[ADD {i}/{n}] {code} {latest.get(code, '?')} ...")
            watch_row, _ = find_row_by_code(ss.worksheet(watch_sheet), code)
            if watch_row:
                # 買い戻し: 監視に在る銘柄を保有へ戻す（add_stock は二重在籍で sys.exit するため move を使う）
                move_stock(code, '保有')
                print(f"  ✓ 監視→保有へ復帰（買い戻し）")
            else:
                add_stock(code, '保有')
                print(f"  ✓ 追加完了")
            success_add.append(code)
        except SystemExit:
            fail_add.append(code)
            print(f"  ✗ 追加失敗（manage_stock 内部エラー・財務データ不足等）")
        except Exception as e:
            fail_add.append(code)
            print(f"  ✗ 追加失敗: {e}")
        if i < n:
            time.sleep(args.sleep_sec)

    # サマリレポート
    print(f"\n{'='*60}")
    print(f"完了レポート")
    print(f"{'='*60}")
    print(f"監視へ移行  成功: {len(success_remove)} / 失敗: {len(fail_remove)}")
    print(f"追加/買戻し  成功: {len(success_add)} / 失敗: {len(fail_add)}")
    if fail_remove:
        print(f"\n監視へ移行 失敗銘柄:")
        for c in fail_remove:
            print(f"  - {c}")
    if fail_add:
        print(f"\n追加失敗銘柄:")
        for c in fail_add:
            print(f"  - {c}")

    print(f"\n{'='*60}")
    print(f"次のステップ:")
    print(f"  1. 4 シート整合性確認（保有銘柄_v4.3スコア / コアスキャン_v4.3 / 予測記録）")
    print(f"  2. python generate_dashboard.py で HTML 再生成")
    print(f"  3. git commit + push で GitHub Pages デプロイ")
    print(f"{'='*60}")

    # 1 件でも失敗があれば exit 1
    if fail_remove or fail_add:
        sys.exit(1)


if __name__ == '__main__':
    main()

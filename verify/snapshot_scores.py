"""
verify/snapshot_scores.py
本番 v4.3 スコアの point-in-time スナップショット（読込専用・追記のみ）。

2026-06-06: 自己学習の母。スコアシート（コアスキャン/保有/監視）は毎回 上書き再生成され
過去スコアが消える（D5）。毎月、その時点の全表示銘柄スコアを別シート「スコア履歴_snapshot」へ
append-only で凍結保存し、後で「予測時点スコア vs 満期リターン」の IC/勝率を計算できるようにする。

【設計原則・厳守】（verify/threshold_advisor.py と同じ）
- 既存シート（コアスキャン_v4.3 / 保有銘柄_v4.3スコア / 監視銘柄_v4.3スコア）には書込しない（読込のみ）
- 「スコア履歴_snapshot」へ追記のみ（上書き禁止＝履歴を消さない）
- 失敗しても他スクリプト・顧客 v4.3 スコアに影響しない（独立運用・例外は隔離）
- 末尾に機械可読 1 行 SNAPSHOT_MONITOR_SUMMARY を出力（死活監視が parse）

【実行】monthly_learning.yml Step6（毎月1日16:00JST・場外）。手動: python verify/snapshot_scores.py
"""
import warnings
from datetime import datetime

import gspread
from core.auth import get_spreadsheet

warnings.filterwarnings('ignore')

SNAPSHOT_SHEET = 'スコア履歴_snapshot'
# (区分ラベル, 読込元シート)
SOURCE_SHEETS = [
    ('保有',           '保有銘柄_v4.3スコア'),
    ('監視',           '監視銘柄_v4.3スコア'),
    ('スクリーニング', 'コアスキャン_v4.3'),
]
HEADER = ['記録日', '記録日時', '区分', 'コード', '銘柄名', '総合スコア', 'ランク',
          '変数1', '変数2', '変数3', 'PEG', 'FCF利回り', '株価']


def main():
    now = datetime.now()
    today = now.strftime('%Y/%m/%d')
    now_str = now.strftime('%Y/%m/%d %H:%M')
    ss = get_spreadsheet()
    print(f"接続完了: {ss.title}  実行: {now_str}")

    # スナップショット先シート（無ければ新設・ヘッダー付与）
    try:
        ws = ss.worksheet(SNAPSHOT_SHEET)
    except gspread.exceptions.WorksheetNotFound:
        ws = ss.add_worksheet(title=SNAPSHOT_SHEET, rows=4000, cols=len(HEADER))
        ws.update('A1', [HEADER])
        print(f"新規作成: {SNAPSHOT_SHEET}")

    # 既存行から冪等キー（記録日_区分_コード）を集める（同日2回実行でも重複追記しない）
    existing = ws.get_all_values()
    have = set()
    for r in existing[1:]:
        if len(r) >= 4 and r[0] and r[3]:
            have.add(f"{r[0]}_{r[2]}_{r[3]}")

    rows = []
    read_total = 0
    for label, sheet in SOURCE_SHEETS:
        try:
            data = ss.worksheet(sheet).get_all_values()
        except Exception as e:
            print(f"  WARN: {sheet} 読込失敗: {e}")
            continue
        if len(data) < 2:
            continue
        hdr = data[0]

        def col(*names):
            for n in names:
                if n in hdr:
                    return hdr.index(n)
            return -1

        ci = col('コード', 'code')
        cn = col('銘柄名', 'name')
        ct = col('総合スコア', '総合')
        cr = col('ランク', 'rank')
        c1 = col('変数1', 'Real ROIC(s1)', '変数1(s1)')
        c2 = col('変数2', 'トレンド(s2)', '変数2(s2)')
        c3 = col('変数3', '価格(s3)', '変数3(s3)')
        cpeg = col('PEG')
        cfy = col('FCF利回り')
        cp = col('株価')

        def gv(row, idx):
            return row[idx] if 0 <= idx < len(row) else ''

        for row in data[1:]:
            code = str(gv(row, ci)).strip()
            if not code:
                continue
            read_total += 1
            key = f"{today}_{label}_{code}"
            if key in have:
                continue
            rows.append([
                today, now_str, label, code, str(gv(row, cn)),
                gv(row, ct), gv(row, cr),
                gv(row, c1), gv(row, c2), gv(row, c3),
                gv(row, cpeg), gv(row, cfy), gv(row, cp),
            ])
            have.add(key)

    if rows:
        # 追記（既存行を上書きしない＝履歴を消さない）。learning_batch と同じ next_row 方式。
        next_row = len(existing) + 1
        needed = next_row + len(rows)
        if needed > ws.row_count:
            ss.batch_update({"requests": [{"updateSheetProperties": {
                "properties": {"sheetId": ws.id, "gridProperties": {"rowCount": needed + 200}},
                "fields": "gridProperties(rowCount)"}}]})
        ws.update(f'A{next_row}', rows)
        print(f"✅ {SNAPSHOT_SHEET} に {len(rows)} 行 追記（読込 {read_total} 件）")
    else:
        print(f"ℹ️ 本日分は追記済み（読込 {read_total} 件・重複スキップ）")

    print(f"SNAPSHOT_MONITOR_SUMMARY ok=true rows={len(rows)} read={read_total} sheet={SNAPSHOT_SHEET}")


if __name__ == '__main__':
    try:
        main()
    except Exception as e:
        # 失敗時も機械可読サマリを出す（guard が ok=false / 行欠落 を検知）。再 raise で従来挙動維持。
        print(f"SNAPSHOT_MONITOR_SUMMARY ok=false rows=0 read=0 reason={type(e).__name__}")
        raise

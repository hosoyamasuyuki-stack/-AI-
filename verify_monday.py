# ============================================================
# verify_monday.py
# AI投資判断システム 週次自動検証スクリプト
#
# 【実行タイミング】毎週月曜 11:00 JST（dashboard_update完了30分後）
# 【目的】
#   以下3点を自動チェックしてスプレッドシートに結果を記録する
#   Check1: インデックス予測記録シートが存在し今週分が記録されているか
#   Check2: 日経・SP500の短期/中期/長期予測が正しく記録されているか
#   Check3: バリュエーション_日次シートのPBR・CAPEが実測値になっているか
#
# 【通知方法】
#   作業ログシートに ✅正常 or ⚠️要確認 を書き込む
#   異常があった場合は「週次検証アラート」シートに詳細を記録
#
# 【認証】GOOGLE_CREDENTIALS（環境変数）
# ============================================================

import os, json, warnings
import pandas as pd
from datetime import datetime, timedelta
import gspread
from google.oauth2.service_account import Credentials
from core.auth import get_spreadsheet
warnings.filterwarnings('ignore')

# ── 認証 ────────────────────────────────────────────────────
ss = get_spreadsheet()

NOW   = datetime.now().strftime('%Y/%m/%d %H:%M')
TODAY = datetime.now()
print(f"✅ 接続完了: {ss.title}")
print(f"実行日時: {NOW}")
print(f"\n{'='*60}")
print(f"週次自動検証スクリプト")
print(f"{'='*60}")

alerts  = []   # 異常リスト
results = []   # 検証結果サマリー

# ============================================================
# Check1: インデックス予測記録シートの確認
# ============================================================
print(f"\n--- Check1: インデックス予測記録シート ---")

INDEX_SHEET = 'インデックス予測記録'
c1_status   = '✅正常'
c1_detail   = ''

try:
    ws_idx = ss.worksheet(INDEX_SHEET)
    rows   = ws_idx.get_all_values()

    if len(rows) < 2:
        c1_status = '⚠️要確認'
        c1_detail = 'シートは存在するがデータが0件。weekly_update v4.2が正常実行されていない可能性。'
        alerts.append(f"[Check1] {c1_detail}")
        print(f"  ⚠️ データなし: {c1_detail}")
    else:
        # 最新行の記録日時を確認（今週月曜に記録されているか）
        latest_row  = rows[-1]
        latest_date = latest_row[0][:10] if latest_row[0] else ''

        # 今週月曜日の日付を計算
        monday = TODAY - timedelta(days=TODAY.weekday())
        monday_str = monday.strftime('%Y/%m/%d')

        if latest_date == monday_str:
            c1_detail = f"今週分の記録あり（{latest_date}）。合計{len(rows)-1}件蓄積済み。"
            print(f"  ✅ 今週分記録確認: {latest_date}（累計{len(rows)-1}件）")

            # 予測方向が空でないか確認
            if len(latest_row) > 1 and latest_row[1]:
                print(f"  ✅ 日経短期予測: {latest_row[1]}")
            else:
                c1_status = '⚠️要確認'
                c1_detail += ' / 予測方向が空欄。'
                alerts.append("[Check1] 予測方向が空欄。LONG_TERM_ENABLEDまたはスコア取得を確認。")

        else:
            c1_status = '⚠️要確認'
            c1_detail = (f"今週分（{monday_str}）の記録がない。"
                         f"最新は{latest_date}。"
                         f"weekly_update v4.2の実行ログを確認してください。")
            alerts.append(f"[Check1] {c1_detail}")
            print(f"  ⚠️ 今週分なし: 最新={latest_date} / 期待={monday_str}")

except gspread.exceptions.WorksheetNotFound:
    c1_status = '⚠️要確認'
    c1_detail = f"「{INDEX_SHEET}」シートが存在しない。weekly_update v4.2が実行されていない可能性。"
    alerts.append(f"[Check1] {c1_detail}")
    print(f"  ⚠️ シートなし: {c1_detail}")

results.append({'項目': 'Check1: インデックス予測記録', '状態': c1_status, '詳細': c1_detail})

# ============================================================
# Check2: 予測内容の妥当性確認
# ============================================================
print(f"\n--- Check2: 予測内容の妥当性確認 ---")

c2_status = '✅正常'
c2_detail = ''

try:
    ws_idx = ss.worksheet(INDEX_SHEET)
    rows   = ws_idx.get_all_values()

    if len(rows) >= 2:
        latest = rows[-1]
        checks = []

        # 短期予測方向（B列=index1）
        dir_nikkei_short = latest[1]  if len(latest) > 1  else ''
        dir_sp500_short  = latest[5]  if len(latest) > 5  else ''
        # 中期予測方向（C列=index2）
        dir_nikkei_mid   = latest[2]  if len(latest) > 2  else ''
        # 長期予測方向（D列=index3）
        dir_nikkei_long  = latest[3]  if len(latest) > 3  else ''
        # 短期スコア（J列=index9）
        short_score      = latest[9]  if len(latest) > 9  else ''
        # 中期スコア（K列=index10）
        mid_score        = latest[10] if len(latest) > 10 else ''
        # 日経記録時水準（N列=index13）
        nikkei_level     = latest[13] if len(latest) > 13 else ''
        # SP500記録時水準（O列=index14）
        sp500_level      = latest[14] if len(latest) > 14 else ''

        # 予測方向の妥当性チェック
        valid_dirs = {'強気↑↑', 'やや強気↑', '中立→', 'やや弱気↓', '弱気↓↓', 'データ未整備'}
        for label, val in [('日経短期', dir_nikkei_short), ('SP500短期', dir_sp500_short),
                           ('日経中期', dir_nikkei_mid)]:
            if val in valid_dirs:
                checks.append(f"  ✅ {label}: {val}")
            elif val == '':
                checks.append(f"  ⚠️ {label}: 空欄")
                alerts.append(f"[Check2] {label}の予測方向が空欄")
                c2_status = '⚠️要確認'
            else:
                checks.append(f"  ✅ {label}: {val}")

        # 長期予測の確認
        if dir_nikkei_long == 'データ未整備':
            checks.append(f"  ℹ️ 長期予測: データ未整備（LONG_TERM_ENABLED確認）")
        elif dir_nikkei_long:
            checks.append(f"  ✅ 長期予測: {dir_nikkei_long}")
        else:
            checks.append(f"  ⚠️ 長期予測: 空欄")

        # スコアの妥当性チェック（0-100の範囲内か）
        try:
            ss_val = float(short_score)
            ms_val = float(mid_score)
            if 0 <= ss_val <= 100 and 0 <= ms_val <= 100:
                checks.append(f"  ✅ スコア: 短期{ss_val:.0f}点 / 中期{ms_val:.0f}点（正常範囲）")
            else:
                checks.append(f"  ⚠️ スコア異常: 短期{ss_val} / 中期{ms_val}（範囲外）")
                c2_status = '⚠️要確認'
                alerts.append(f"[Check2] スコアが異常値: 短期{ss_val} / 中期{ms_val}")
        except:
            checks.append(f"  ⚠️ スコア取得失敗: '{short_score}' / '{mid_score}'")

        # 指数水準の確認（空でないか）
        if nikkei_level and sp500_level:
            checks.append(f"  ✅ 記録時水準: 日経{nikkei_level} / SP500{sp500_level}")
        else:
            checks.append(f"  ⚠️ 記録時水準が空欄（4週後の自動検証ができない）")
            c2_status = '⚠️要確認'
            alerts.append("[Check2] 指数水準が空欄。get_current_price()の取得失敗を確認。")

        for c in checks:
            print(c)

        c2_detail = ' / '.join([f"日経短期:{dir_nikkei_short}", f"短期{short_score}点",
                                 f"中期{mid_score}点", f"日経{nikkei_level}"])
    else:
        c2_status = '⚠️要確認'
        c2_detail = 'データなし（Check1と同様）'
        print(f"  ℹ️ データなし → Check1を確認")

except Exception as e:
    c2_status = '⚠️要確認'
    c2_detail = f"確認失敗: {e}"
    alerts.append(f"[Check2] 確認失敗: {e}")
    print(f"  ⚠️ 確認失敗: {e}")

results.append({'項目': 'Check2: 予測内容の妥当性', '状態': c2_status, '詳細': c2_detail})

# ============================================================
# Check3: バリュエーション_日次シートのPBR・CAPE確認
# ============================================================
print(f"\n--- Check3: バリュエーション指標の実測値確認 ---")

c3_status = '✅正常'
c3_detail = ''

# 実測値の許容範囲（v21修正後の期待値）
VALID_RANGES = {
    'PBR_日本':      (1.3, 2.5,  '期待値1.7倍前後'),
    'PBR_米国':      (3.0, 6.5,  '期待値4.5-5.0倍'),
    'シラーPER_日本': (15, 35,   '期待値20-26倍'),
    'シラーPER_米国': (25, 50,   '期待値36-40倍'),
}

# 旧ソースの誤値（この値に近い場合は警告）
OLD_VALUES = {
    'PBR_日本':      1.2,   # EWJ由来の誤値
    'PBR_米国':      1.5,   # SPY由来の誤値
    'シラーPER_米国': 33.0,  # per×1.3の誤値
}

try:
    ws_val = ss.worksheet('バリュエーション_日次')
    rows   = ws_val.get_all_values()

    if len(rows) < 2:
        c3_status = '⚠️要確認'
        c3_detail = 'バリュエーション_日次シートにデータなし'
        alerts.append(f"[Check3] {c3_detail}")
        print(f"  ⚠️ {c3_detail}")
    else:
        header   = rows[0]
        latest   = rows[1]  # 最新行（2行目）
        rec      = dict(zip(header, latest))
        updated  = rec.get('更新日時', '不明')
        c3_checks = []

        print(f"  最終更新: {updated}")

        for col, (mn, mx, note) in VALID_RANGES.items():
            val_str = rec.get(col, '')
            if val_str in ('', 'None', '-'):
                c3_checks.append(f"  ⚠️ {col}: 空欄（取得失敗）")
                c3_status = '⚠️要確認'
                alerts.append(f"[Check3] {col}が空欄")
                continue
            try:
                val = float(val_str)
                # 旧値チェック
                old = OLD_VALUES.get(col)
                if old and abs(val - old) < 0.1:
                    c3_checks.append(f"  ⚠️ {col}: {val}（旧ソースの誤値{old}に近い。v21修正が反映されていない可能性）")
                    c3_status = '⚠️要確認'
                    alerts.append(f"[Check3] {col}={val}は旧ソース誤値({old})の可能性あり")
                elif mn <= val <= mx:
                    c3_checks.append(f"  ✅ {col}: {val}（{note}・正常範囲）")
                else:
                    c3_checks.append(f"  ⚠️ {col}: {val}（正常範囲{mn}-{mx}の範囲外）")
                    c3_status = '⚠️要確認'
                    alerts.append(f"[Check3] {col}={val}が範囲外({mn}-{mx})")
            except ValueError:
                c3_checks.append(f"  ⚠️ {col}: '{val_str}'（数値変換失敗）")
                c3_status = '⚠️要確認'

        for c in c3_checks:
            print(c)

        # PBR日本の詳細情報
        pbr_jp = rec.get('PBR_日本', '')
        pbr_us = rec.get('PBR_米国', '')
        cape_us = rec.get('シラーPER_米国', '')
        c3_detail = f"PBR日本:{pbr_jp} / PBR米国:{pbr_us} / CAPE米国:{cape_us} / 更新:{updated[:10] if updated else '不明'}"

except Exception as e:
    c3_status = '⚠️要確認'
    c3_detail = f"確認失敗: {e}"
    alerts.append(f"[Check3] 確認失敗: {e}")
    print(f"  ⚠️ 確認失敗: {e}")

results.append({'項目': 'Check3: バリュエーション実測値', '状態': c3_status, '詳細': c3_detail})

# ============================================================
# 結果をスプレッドシートに記録
# ============================================================
print(f"\n{'='*60}")
print(f"検証結果サマリー")
print(f"{'='*60}")

overall = '✅全項目正常' if all(r['状態'] == '✅正常' for r in results) else f'⚠️要確認({len(alerts)}件)'
print(f"  総合判定: {overall}")
for r in results:
    print(f"  {r['状態']} {r['項目']}")
if alerts:
    print(f"\n  アラート詳細:")
    for a in alerts:
        print(f"    {a}")

# 作業ログに記録
try:
    wl   = ss.worksheet('作業ログ')
    last = len(wl.get_all_values()) + 1
    alert_summary = ' / '.join(alerts) if alerts else 'なし'
    wl.update(f'A{last}', [[
        NOW, 'verify_monday.py',
        f'週次検証: {overall} | C1:{results[0]["状態"]} C2:{results[1]["状態"]} C3:{results[2]["状態"]}',
        alert_summary, overall
    ]])
    print(f"\n✅ 作業ログ記録完了")
except Exception as e:
    print(f"⚠️ 作業ログ記録失敗: {e}")

# 異常があった場合は「週次検証アラート」シートに詳細を記録
if alerts:
    try:
        ALERT_SHEET = '週次検証アラート'
        try:
            ws_alert = ss.worksheet(ALERT_SHEET)
        except:
            ws_alert = ss.add_worksheet(title=ALERT_SHEET, rows=500, cols=5)
            ws_alert.update('A1', [['実行日時', '総合判定', 'アラート内容', 'Check1', 'Check2', 'Check3']])

        last_alert = len(ws_alert.get_all_values()) + 1
        ws_alert.update(f'A{last_alert}', [[
            NOW, overall,
            ' / '.join(alerts),
            results[0]['状態'], results[1]['状態'], results[2]['状態']
        ]])
        print(f"✅ アラート詳細を「{ALERT_SHEET}」シートに記録")
    except Exception as e:
        print(f"⚠️ アラートシート記録失敗: {e}")

print(f"\n✅ verify_monday.py 完了: {NOW}")

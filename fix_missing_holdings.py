# ============================================================
# fix_missing_holdings.py
# 保有銘柄_v4.3スコア に存在するが、コアスキャン_v4.3 / 予測記録 に
# 存在しない銘柄を検出し、補完する。
#
# manage_stock.py の add_stock の cascade ロジックを参考に、
# 既存銘柄の補完専用ロジックで実装（重複チェックで弾かれない設計）。
# ============================================================
import os, sys
from datetime import datetime, timedelta
from core.auth import get_spreadsheet
from manage_stock import find_row_by_code, SHEET_MAP

ss = get_spreadsheet()
NOW = datetime.now()

def get_codes(ws, code_col_name='コード'):
    """シートから銘柄コードリストを取得"""
    all_vals = ws.get_all_values()
    if not all_vals:
        return set(), all_vals
    header = all_vals[0]
    code_col = 0
    for i, h in enumerate(header):
        if h in (code_col_name, '銘柄コード', 'コード'):
            code_col = i
            break
    data_start = 2 if '予測記録' in (ws.title or '') else 1
    codes = set()
    for row in all_vals[data_start:]:
        if len(row) > code_col:
            c = str(row[code_col]).strip()
            if c:
                codes.add(c)
    return codes, all_vals


def get_holding_row_by_code(holding_ws, all_vals, code):
    """保有銘柄_v4.3スコア シートから指定コードの行データを取得"""
    if not all_vals:
        return None
    header = all_vals[0]
    code_col = 0
    for i, h in enumerate(header):
        if h in ('コード', '銘柄コード'):
            code_col = i
            break
    for row in all_vals[1:]:
        if len(row) > code_col and str(row[code_col]).strip() == str(code).strip():
            return dict(zip(header, row))
    return None


def append_to_corescan(code, row_data):
    """コアスキャン_v4.3 に既存保有データから複製で追加"""
    cs_ws = ss.worksheet('コアスキャン_v4.3')
    cs_codes, cs_all = get_codes(cs_ws)
    if code in cs_codes:
        print(f"  [SKIP] コアスキャン_v4.3 に既存")
        return
    cs_header = cs_all[0]
    new_row = [row_data.get(h, '') for h in cs_header]
    next_row = len(cs_all) + 1
    cs_ws.update(f'A{next_row}', [new_row], value_input_option='USER_ENTERED')
    print(f"  [ADD] コアスキャン_v4.3 行 {next_row} に追加")


def append_to_predict(code, row_data):
    """予測記録に初期予測を追加（manage_stock.py の add_stock と同じロジック）"""
    pred_ws = ss.worksheet('予測記録')
    pred_codes, pred_all = get_codes(pred_ws, code_col_name='銘柄コード')
    if code in pred_codes:
        print(f"  [SKIP] 予測記録 に既存")
        return

    name = row_data.get('銘柄名', code)
    sector = row_data.get('業種', '')
    rank = row_data.get('ランク', 'B')
    total = row_data.get('総合スコア', 0)
    price = row_data.get('株価', 0)

    dir_map = {'S': '強気↑↑', 'A': '強気↑', 'B': '中立→', 'C': '弱気↓', 'D': '弱気↓↓'}
    init_dir = dir_map.get(rank, '中立→')

    target_pct = {'S': 15, 'A': 10, 'B': 5, 'C': -5, 'D': -10}.get(rank, 0)
    try:
        price_num = float(str(price).replace(',', '')) if price else 0
        target_price = round(price_num * (1 + target_pct / 100)) if price_num else ''
    except:
        target_price = ''

    today = NOW
    ver_4w = (today + timedelta(days=28)).strftime('%Y/%m/%d')
    ver_1y = (today + timedelta(days=365)).strftime('%Y/%m/%d')
    ver_3y = (today + timedelta(days=365*3)).strftime('%Y/%m/%d')
    ver_5y = (today + timedelta(days=365*5)).strftime('%Y/%m/%d')

    basis = f"v4.3スコア{total}点(ランク{rank})に基づく初期予測"
    action = '買い検討' if rank in ('S','A') else ('様子見' if rank == 'B' else '時期尚早')

    pred_row = [
        today.strftime('%Y/%m/%d'),
        str(code), name, sector, price, total, rank, action,
        init_dir, target_price, basis, ver_4w, '', '', '', '',
        init_dir, target_price, basis, ver_1y, '', '', '', '',
        init_dir, target_price, basis, ver_3y, '', '', '', '',
        init_dir, target_price, basis, ver_5y, '', '', '', '',
    ]
    next_row = len(pred_all) + 1
    pred_ws.update(f'A{next_row}', [pred_row], value_input_option='USER_ENTERED')
    print(f"  [ADD] 予測記録 行 {next_row} に追加")


def main():
    print("=== 不足銘柄補完 ===")
    print(f"実行日時: {NOW.strftime('%Y-%m-%d %H:%M:%S')}")
    print()

    # 保有銘柄_v4.3スコア の銘柄リスト
    h_ws = ss.worksheet('保有銘柄_v4.3スコア')
    h_codes, h_all = get_codes(h_ws)
    print(f"保有銘柄_v4.3スコア: {len(h_codes)} 銘柄")

    # コアスキャン_v4.3 / 予測記録 と比較
    cs_ws = ss.worksheet('コアスキャン_v4.3')
    cs_codes, _ = get_codes(cs_ws)

    pred_ws = ss.worksheet('予測記録')
    pred_codes, _ = get_codes(pred_ws, code_col_name='銘柄コード')

    missing_cs = h_codes - cs_codes
    missing_pred = h_codes - pred_codes

    print(f"コアスキャン_v4.3 不足: {sorted(missing_cs) if missing_cs else 'なし'}")
    print(f"予測記録         不足: {sorted(missing_pred) if missing_pred else 'なし'}")
    print()

    all_missing = sorted(missing_cs | missing_pred)
    if not all_missing:
        print("✅ 不足なし・補完不要")
        return

    print(f"=== 補完対象: {len(all_missing)} 銘柄 ===")
    for code in all_missing:
        print(f"\n[{code}]")
        row_data = get_holding_row_by_code(h_ws, h_all, code)
        if not row_data:
            print(f"  [ERROR] 保有銘柄_v4.3スコア に {code} が見つからない")
            continue
        print(f"  銘柄名: {row_data.get('銘柄名', '?')}")
        print(f"  業種  : {row_data.get('業種', '?')}")
        print(f"  ランク: {row_data.get('ランク', '?')}")
        if code in missing_cs:
            try:
                append_to_corescan(code, row_data)
            except Exception as e:
                print(f"  [WARN] コアスキャン_v4.3 補完失敗: {e}")
        if code in missing_pred:
            try:
                append_to_predict(code, row_data)
            except Exception as e:
                print(f"  [WARN] 予測記録 補完失敗: {e}")

    print("\n=== 補完完了 ===")


if __name__ == '__main__':
    main()

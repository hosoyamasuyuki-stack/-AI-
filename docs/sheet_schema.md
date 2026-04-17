# Google Sheets スキーマ定義

**Source of Truth**: [core/config.py](../core/config.py) の `SHEET_SCHEMA` 辞書
このドキュメントはその**参照ビュー**。実装との乖離があれば config.py を優先。

## 保有銘柄_v4.3スコア / 監視銘柄_v4.3スコア（18列）

| col | 名称 | 型 | 書き手 |
|-----|------|-----|-------|
| 0 | コード | str | manage_stock.py, weekly_update.py |
| 1 | 銘柄名 | str | ↑ |
| 2 | 業種 | str | ↑ |
| 3 | 種別 | str | ↑ |
| 4 | 総合スコア | float | ↑, daily_price_update.py (SYNC) |
| 5 | ランク | S/A/B/C/D | ↑ |
| 6 | ROE平均 | float | ↑ |
| 7 | FCR平均 | float | ↑ |
| 8 | ROEトレンド | float | ↑ |
| 9 | PEG | float | ↑, daily_price_update.py (SYNC) |
| 10 | FCF利回り | float | ↑, daily_price_update.py (SYNC) |
| 11 | 変数1 | int 0-100 | weekly_update.py, manage_stock.py |
| 12 | 変数2 | int 0-100 | ↑ |
| 13 | 変数3 | int 0-100 | ↑, daily_price_update.py (SYNC) |
| 14 | 取得期数 | int | weekly_update.py |
| 15 | 株価 | int | ↑, daily_price_update.py (SYNC) |
| 16 | 算出日時 | str | ↑ |
| 17 | 前回ランク | S/A/B/C/D | weekly_update.py |

**Source of Truth**: この2シートが保有/監視の最新状態の真実源（教訓16）

## コアスキャン_v4.3（17列）

毎週月曜に weekly_update.py が del→add で再作成。
列順は 保有/監視と異なる（ROE平均系が先、変数が後ろ）。
**他スクリプトからは読み込まない**（教訓16）。manage_stock.py の re-add 時に value_map で同期される。

## コアスキャン_日次（13列）

daily_price_update.py が上書き。変数1/2は週次から継承、変数3のみ日次計算。
**他スクリプトからは読み込まない**。

## スクリーニング_Top50（15列・実際は150行まで保存）

full_scan.py が毎週日曜22:00 JST に全市場スキャン結果を書く。
Top50 のうち S/A ランクは 予測記録 にも自動登録される（2026/04/17〜）。

## 予測記録（40列・行0=グループヘッダー・行1=サブヘッダー・行2+=データ）

```
col  0:      記録日
col  1:      銘柄コード
col  2:      銘柄名
col  3:      業種
col  4:      記録時株価
col  5:      総合スコア
col  6:      ランク
col  7:      推奨アクション
col  8-15:   ◆目先（4週）  [予測方向/目標株価/根拠/検証予定日/実績株価/騰落率/日経比超過/勝敗]
col 16-23:   ◆短期（1年）  同上
col 24-31:   ◆中期（3年）  同上
col 32-39:   ◆長期（5年）  同上
```

**Source of Truth**: 4軸予測システムの真実源（教訓16）
- 書き手: manage_stock.py（新規追加時）/ full_scan.py（S/A銘柄）/ verify_axis.py（勝敗/騰落率/日経比更新）
- 読み手: generate_dashboard.py（方向と勝敗をTDセルに反映）

## MacroPhase（市場環境）

daily_update.py が毎日7:00 JST に 4層スコアを更新。
- Layer A: リスク指標（VIX, HYG, TED, 信用スプレッド）40pt
- Layer B: 金融政策（FF金利, 日銀, 長短金利差, M2）30pt
- Layer C: 経済活動（ISM, 失業率, 鉱工業生産, 設備稼働率）20pt
- Layer D: バリュエーション（CAPE, PBR, 益回り, バフェット指標）10pt

読み手: generate_dashboard.py（ヘッダーのマクロ総合バッジ）

## バリュエーション_日次

daily_update.py + generate_dashboard.py が書く。
日本/米国の PBR・CAPE・益回り・配当利回り・バフェット指数 を日次で。

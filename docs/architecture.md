# システムアーキテクチャ

## データフロー

```
┌─────────────────────────────────────────────────────────┐
│ 外部API（毎日/毎週取得）                                  │
│  ・J-Quants V2         ・yfinance                        │
│  ・FRED                ・nikkei225jp.com  ・multpl.com   │
│  ・EDINET              ・BOJ（日銀API）                   │
└──────────────┬──────────────────────────────────────────┘
               │
    ┌──────────▼──────────┐
    │ データ取得スクリプト │
    │ ・weekly_update.py  │ 月曜10:00 JST / v4.3全変数
    │ ・daily_update.py   │ 毎日7:00 JST  / FRED+MacroPhase
    │ ・daily_price_update│ 毎日7:30 JST  / 株価+変数3
    │ ・full_scan.py      │ 日曜22:00 JST / 全市場Top50
    │ ・manage_stock.py   │ 手動/UI      / 銘柄追加削除
    └──────────┬──────────┘
               │
    ┌──────────▼──────────────────────────┐
    │ Google Sheets（Source of Truth）     │
    │ ・保有銘柄_v4.3スコア（保有の真実）   │
    │ ・監視銘柄_v4.3スコア（監視の真実）   │
    │ ・予測記録（4軸予測の真実）           │
    │ ・MacroPhase（マクロ市場環境）        │
    │ ・バリュエーション_日次               │
    └──────────┬──────────────────────────┘
               │ （派生シート: コアスキャン_v4.3 / _日次 は読まない）
    ┌──────────▼──────────┐
    │ generate_dashboard  │ HTML再生成（毎日7:30後）
    │  ・整合性ガード       │ >80%同値で ERROR 停止（教訓17）
    │  ・精度バッジ         │ 目先勝率を表示
    └──────────┬──────────┘
               │
    ┌──────────▼──────────┐
    │ ai_dashboard_v13.html│ GitHub Pages 公開
    └──────────┬──────────┘
               │
    ┌──────────▼──────────┐
    │ 検証ループ            │
    │ ・verify_axis.py     │ 予測 vs 実績で勝敗判定
    │ ・verify_monday.py   │ 週次整合性
    │ ・audit_corescan.py  │ コアスキャン監査（教訓16）
    └─────────────────────┘
```

## 役割別ファイル構成

### 本番稼働（ルート）
- `weekly_update.py`: v4.3スコア全変数再計算（週次）
- `daily_update.py`: FRED・MacroPhase更新（日次）
- `daily_price_update.py`: 株価・変数3更新（日次）
- `full_scan.py`: 全市場スクリーニング（週次）
- `manage_stock.py`: 銘柄追加/削除/移動（手動）
- `generate_dashboard.py`: HTML再生成
- `sheet_manager.py`: SheetManagementLedger生成（月次）
- `learning_batch_monthly.py`: 学習用100銘柄バッチ（月次）

### 共通モジュール（core/）
- `config.py`: 定数・閾値・スキーマ定義（教訓16）
- `auth.py`: Google Sheets認証
- `scoring.py`: v4.3スコア計算ヘルパー
- `api.py`: J-Quants API

### 検証・診断（verify/）
- `verify_axis.py`: 4軸予測検証（目先/短期/中期/長期）
- `verify_monday.py`: 週次システム健全性
- `audit_corescan.py`: コアスキャン_v4.3 データ整合性
- `diagnose_code.py`: 銘柄別全シート診断

### テスト（tests/）
- `test_scoring.py`: v4.3 スコア計算の単体テスト

### 運用ツール（tools/）
- `check_api_keys.py`: 全APIキー設定状態チェック
- `generate_handover.py`: 引き継ぎ書自動生成
- `record_changelog.py`: 変更履歴記録

### GAS 連携（gas/, gas_deploy/）
- `gas_kenja_proxy.js`: 賢者の審判 GASプロキシ
- `gas_manage_stock_addition.js`: 銘柄管理 GASプロキシ

## GitHub Actions（自動化）

| Workflow | Cron | 用途 |
|----------|------|------|
| daily_update.yml | 7:00 JST | FRED + MacroPhase |
| daily_price_update.yml | 7:30 JST | 株価 + 変数3 + HTML再生成 |
| dashboard_update.yml | on-demand | HTML再生成 |
| weekly_update.yml | 月10:00 JST | v4.3全変数 + 整合性チェック |
| full_scan.yml | 日22:00 JST | 全市場Top50 + 予測記録自動登録 |
| full_update.yml | on-demand | 全4ステップ一括 |
| manage_stock.yml | on-demand | 銘柄追加/削除/移動 |
| verify.yml | 月/月次/年次 | 予測検証 |
| audit_corescan.yml | on-demand | コアスキャン監査 |
| diagnose.yml | on-demand | 銘柄別診断 |
| pytest.yml | PR時 | 単体テスト |
| sheet_manager.yml | 月1日9:00 | SheetManagementLedger |
| monthly_learning.yml | 月次 | 学習用100銘柄 |
| backtest_h005.yml | on-demand | H005バックテスト |
| generate_handover.yml | on-demand | 引き継ぎ書生成 |
| auto_changelog.yml | push時 | 変更履歴 |

## 教訓の物理配置

- **教訓16（Source of Truth）**: `core/config.py` の `SOURCE_OF_TRUTH` 辞書に明文化
- **教訓17（検証定義統一・整合性ガード）**:
  - `verify/verify_axis.py` に勝敗判定を一元化
  - `generate_dashboard.py` に `_guard_cell_diversity()` で >80% 同値ERROR
  - `weekly_update.py` 末尾に整合性チェック
- **確認チェックリスト**: CLAUDE.md `## 確認チェックリスト` セクション

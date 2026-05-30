# システム健康診断レポート

**実行時刻**: 2026-05-31 08:42 JST
**総合判定**: ❌ 1/10 件に問題あり

| 項目 | 直近実行 | 経過 | 上限 | 結果 | URL |
|---|---|---|---|---|---|
| 株価更新 (daily_price_update.yml) | 2026-05-31 08:33 JST | 0.1h | 30h | ❌ FAILURE | [run](https://github.com/hosoyamasuyuki-stack/-AI-/actions/runs/26697882024) |
| FRED指標 (daily_update.yml) | 2026-05-30 08:18 JST | 24.4h | 80h | ✅ OK | [run](https://github.com/hosoyamasuyuki-stack/-AI-/actions/runs/26667111751) |
| 週次フル再計算 (weekly_update.yml) | 2026-05-25 14:13 JST | 138.5h | 200h | ✅ OK | [run](https://github.com/hosoyamasuyuki-stack/-AI-/actions/runs/26384470058) |
| ダッシュボード生成 (dashboard_update.yml) | 2026-05-25 14:56 JST | 137.8h | 200h | ✅ OK | [run](https://github.com/hosoyamasuyuki-stack/-AI-/actions/runs/26385776684) |
| 全市場スキャン (full_scan.yml) | 2026-05-24 23:26 JST | 153.3h | 200h | ✅ OK | [run](https://github.com/hosoyamasuyuki-stack/-AI-/actions/runs/26363863947) |
| handover.txt (generate_handover.yml) | 2026-05-25 08:55 JST | 143.8h | 200h | ✅ OK | [run](https://github.com/hosoyamasuyuki-stack/-AI-/actions/runs/26376335272) |
| verify検証 (verify.yml) | 2026-05-25 15:23 JST | 137.3h | 200h | ✅ OK | [run](https://github.com/hosoyamasuyuki-stack/-AI-/actions/runs/26386594922) |
| シート管理（月次） (sheet_manager.yml) | 2026-05-01 16:53 JST | 711.8h | 800h | ✅ OK | [run](https://github.com/hosoyamasuyuki-stack/-AI-/actions/runs/25207168683) |
| TDnet 決算短信取得 (fetch_tanshin.yml) | 2026-05-30 14:58 JST | 17.7h | 200h | ✅ OK | [run](https://github.com/hosoyamasuyuki-stack/-AI-/actions/runs/26676291352) |
| 月次学習バッチ (monthly_learning.yml) | 2026-05-01 18:19 JST | 710.4h | 800h | ✅ OK | [run](https://github.com/hosoyamasuyuki-stack/-AI-/actions/runs/25209398760) |

## ❌ 要対応項目

- **株価更新** (daily_price_update.yml): FAILURE
  - 最終実行: 2026-05-31 08:33 JST (0.1h前 / 上限 30h)
  - URL: https://github.com/hosoyamasuyuki-stack/-AI-/actions/runs/26697882024

---
*このレポートは health_check ワークフローが毎朝自動生成しています。*
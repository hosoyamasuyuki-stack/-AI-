# システム健康診断レポート

**実行時刻**: 2026-06-08 08:45 JST
**総合判定**: ❌ 1/10 件に問題あり

| 項目 | 直近実行 | 経過 | 上限 | 結果 | URL |
|---|---|---|---|---|---|
| 株価更新 (daily_price_update.yml) | 2026-06-08 08:36 JST | 0.1h | 30h | ✅ RUNNING | [run](https://github.com/hosoyamasuyuki-stack/-AI-/actions/runs/27108246566) |
| FRED指標 (daily_update.yml) | 2026-06-08 08:10 JST | 0.6h | 80h | ✅ OK | [run](https://github.com/hosoyamasuyuki-stack/-AI-/actions/runs/27107677723) |
| 週次フル再計算 (weekly_update.yml) | 2026-06-08 08:04 JST | 0.7h | 200h | ✅ OK | [run](https://github.com/hosoyamasuyuki-stack/-AI-/actions/runs/27107531760) |
| ダッシュボード生成 (dashboard_update.yml) | 2026-06-08 08:35 JST | 0.2h | 200h | ✅ OK | [run](https://github.com/hosoyamasuyuki-stack/-AI-/actions/runs/27108217903) |
| 全市場スキャン (full_scan.yml) | 2026-06-07 23:54 JST | 8.8h | 200h | ✅ OK | [run](https://github.com/hosoyamasuyuki-stack/-AI-/actions/runs/27095954843) |
| handover.txt (generate_handover.yml) | 2026-06-01 09:02 JST | 167.7h | 200h | ✅ OK | [run](https://github.com/hosoyamasuyuki-stack/-AI-/actions/runs/26728306689) |
| verify検証 (verify.yml) | 2026-06-01 15:50 JST | 160.9h | 200h | ✅ OK | [run](https://github.com/hosoyamasuyuki-stack/-AI-/actions/runs/26739748646) |
| シート管理（月次） (sheet_manager.yml) | 2026-06-01 13:12 JST | 163.5h | 800h | ✅ OK | [run](https://github.com/hosoyamasuyuki-stack/-AI-/actions/runs/26734740667) |
| TDnet 決算短信取得 (fetch_tanshin.yml) | 2026-06-07 15:45 JST | 17.0h | 200h | ❌ FAILURE | [run](https://github.com/hosoyamasuyuki-stack/-AI-/actions/runs/27085271422) |
| 月次学習バッチ (monthly_learning.yml) | 2026-06-07 04:32 JST | 28.2h | 800h | ✅ OK | [run](https://github.com/hosoyamasuyuki-stack/-AI-/actions/runs/27071793866) |

## ❌ 要対応項目

- **TDnet 決算短信取得** (fetch_tanshin.yml): FAILURE
  - 最終実行: 2026-06-07 15:45 JST (17.0h前 / 上限 200h)
  - URL: https://github.com/hosoyamasuyuki-stack/-AI-/actions/runs/27085271422

---
*このレポートは health_check ワークフローが毎朝自動生成しています。*
# システム健康診断レポート

**実行時刻**: 2026-06-07 08:44 JST
**総合判定**: ❌ 1/10 件に問題あり

| 項目 | 直近実行 | 経過 | 上限 | 結果 | URL |
|---|---|---|---|---|---|
| 株価更新 (daily_price_update.yml) | 2026-06-07 08:35 JST | 0.1h | 30h | ✅ RUNNING | [run](https://github.com/hosoyamasuyuki-stack/-AI-/actions/runs/27076992509) |
| FRED指標 (daily_update.yml) | 2026-06-06 08:14 JST | 24.5h | 80h | ✅ OK | [run](https://github.com/hosoyamasuyuki-stack/-AI-/actions/runs/27045026841) |
| 週次フル再計算 (weekly_update.yml) | 2026-06-01 14:52 JST | 137.9h | 200h | ✅ OK | [run](https://github.com/hosoyamasuyuki-stack/-AI-/actions/runs/26737729497) |
| ダッシュボード生成 (dashboard_update.yml) | 2026-06-06 16:53 JST | 15.9h | 200h | ✅ OK | [run](https://github.com/hosoyamasuyuki-stack/-AI-/actions/runs/27056733798) |
| 全市場スキャン (full_scan.yml) | 2026-05-31 23:49 JST | 152.9h | 200h | ✅ OK | [run](https://github.com/hosoyamasuyuki-stack/-AI-/actions/runs/26715772590) |
| handover.txt (generate_handover.yml) | 2026-06-01 09:02 JST | 143.7h | 200h | ✅ OK | [run](https://github.com/hosoyamasuyuki-stack/-AI-/actions/runs/26728306689) |
| verify検証 (verify.yml) | 2026-06-01 15:50 JST | 136.9h | 200h | ✅ OK | [run](https://github.com/hosoyamasuyuki-stack/-AI-/actions/runs/26739748646) |
| シート管理（月次） (sheet_manager.yml) | 2026-06-01 13:12 JST | 139.5h | 800h | ✅ OK | [run](https://github.com/hosoyamasuyuki-stack/-AI-/actions/runs/26734740667) |
| TDnet 決算短信取得 (fetch_tanshin.yml) | 2026-06-06 15:05 JST | 17.6h | 200h | ❌ FAILURE | [run](https://github.com/hosoyamasuyuki-stack/-AI-/actions/runs/27054538868) |
| 月次学習バッチ (monthly_learning.yml) | 2026-06-07 04:32 JST | 4.2h | 800h | ✅ OK | [run](https://github.com/hosoyamasuyuki-stack/-AI-/actions/runs/27071793866) |

## ❌ 要対応項目

- **TDnet 決算短信取得** (fetch_tanshin.yml): FAILURE
  - 最終実行: 2026-06-06 15:05 JST (17.6h前 / 上限 200h)
  - URL: https://github.com/hosoyamasuyuki-stack/-AI-/actions/runs/27054538868

---
*このレポートは health_check ワークフローが毎朝自動生成しています。*
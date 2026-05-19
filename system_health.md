# システム健康診断レポート

**実行時刻**: 2026-05-20 08:45 JST
**総合判定**: ❌ 1/10 件に問題あり

| 項目 | 直近実行 | 経過 | 上限 | 結果 | URL |
|---|---|---|---|---|---|
| 株価更新 (daily_price_update.yml) | 2026-05-20 08:41 JST | 0.1h | 30h | ✅ RUNNING | [run](https://github.com/hosoyamasuyuki-stack/-AI-/actions/runs/26132038526) |
| FRED指標 (daily_update.yml) | 2026-05-20 08:09 JST | 0.6h | 80h | ✅ OK | [run](https://github.com/hosoyamasuyuki-stack/-AI-/actions/runs/26130840381) |
| 週次フル再計算 (weekly_update.yml) | 2026-05-18 14:00 JST | 42.7h | 200h | ✅ OK | [run](https://github.com/hosoyamasuyuki-stack/-AI-/actions/runs/26014462105) |
| ダッシュボード生成 (dashboard_update.yml) | 2026-05-18 14:42 JST | 42.1h | 200h | ❌ FAILURE | [run](https://github.com/hosoyamasuyuki-stack/-AI-/actions/runs/26015758087) |
| 全市場スキャン (full_scan.yml) | 2026-05-17 23:26 JST | 57.3h | 200h | ✅ OK | [run](https://github.com/hosoyamasuyuki-stack/-AI-/actions/runs/25993519352) |
| handover.txt (generate_handover.yml) | 2026-05-18 08:53 JST | 47.9h | 200h | ✅ OK | [run](https://github.com/hosoyamasuyuki-stack/-AI-/actions/runs/26006385311) |
| verify検証 (verify.yml) | 2026-05-18 15:09 JST | 41.6h | 200h | ✅ OK | [run](https://github.com/hosoyamasuyuki-stack/-AI-/actions/runs/26016633963) |
| シート管理（月次） (sheet_manager.yml) | 2026-05-01 16:53 JST | 447.9h | 800h | ✅ OK | [run](https://github.com/hosoyamasuyuki-stack/-AI-/actions/runs/25207168683) |
| TDnet 決算短信取得 (fetch_tanshin.yml) | 2026-05-18 15:36 JST | 41.1h | 200h | ✅ OK | [run](https://github.com/hosoyamasuyuki-stack/-AI-/actions/runs/26017604305) |
| 月次学習バッチ (monthly_learning.yml) | 2026-05-01 18:19 JST | 446.4h | 800h | ✅ OK | [run](https://github.com/hosoyamasuyuki-stack/-AI-/actions/runs/25209398760) |

## ❌ 要対応項目

- **ダッシュボード生成** (dashboard_update.yml): FAILURE
  - 最終実行: 2026-05-18 14:42 JST (42.1h前 / 上限 200h)
  - URL: https://github.com/hosoyamasuyuki-stack/-AI-/actions/runs/26015758087

---
*このレポートは health_check ワークフローが毎朝自動生成しています。*
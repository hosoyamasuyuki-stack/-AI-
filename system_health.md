# システム健康診断レポート

**実行時刻**: 2026-05-18 08:42 JST
**総合判定**: ❌ 1/10 件に問題あり

| 項目 | 直近実行 | 経過 | 上限 | 結果 | URL |
|---|---|---|---|---|---|
| 株価更新 (daily_price_update.yml) | 2026-05-18 08:30 JST | 0.2h | 30h | ❌ FAILURE | [run](https://github.com/hosoyamasuyuki-stack/-AI-/actions/runs/26005888269) |
| FRED指標 (daily_update.yml) | 2026-05-18 07:57 JST | 0.8h | 80h | ✅ OK | [run](https://github.com/hosoyamasuyuki-stack/-AI-/actions/runs/26005177387) |
| 週次フル再計算 (weekly_update.yml) | 2026-05-11 13:53 JST | 162.8h | 200h | ✅ OK | [run](https://github.com/hosoyamasuyuki-stack/-AI-/actions/runs/25651043118) |
| ダッシュボード生成 (dashboard_update.yml) | 2026-05-11 14:30 JST | 162.2h | 200h | ✅ OK | [run](https://github.com/hosoyamasuyuki-stack/-AI-/actions/runs/25652157242) |
| 全市場スキャン (full_scan.yml) | 2026-05-17 23:26 JST | 9.3h | 200h | ✅ OK | [run](https://github.com/hosoyamasuyuki-stack/-AI-/actions/runs/25993519352) |
| handover.txt (generate_handover.yml) | 2026-05-11 08:45 JST | 168.0h | 200h | ✅ OK | [run](https://github.com/hosoyamasuyuki-stack/-AI-/actions/runs/25643080378) |
| verify検証 (verify.yml) | 2026-05-11 14:54 JST | 161.8h | 200h | ✅ OK | [run](https://github.com/hosoyamasuyuki-stack/-AI-/actions/runs/25652928922) |
| シート管理（月次） (sheet_manager.yml) | 2026-05-01 16:53 JST | 399.8h | 800h | ✅ OK | [run](https://github.com/hosoyamasuyuki-stack/-AI-/actions/runs/25207168683) |
| TDnet 決算短信取得 (fetch_tanshin.yml) | 2026-05-11 15:12 JST | 161.5h | 200h | ✅ OK | [run](https://github.com/hosoyamasuyuki-stack/-AI-/actions/runs/25653505824) |
| 月次学習バッチ (monthly_learning.yml) | 2026-05-01 18:19 JST | 398.4h | 800h | ✅ OK | [run](https://github.com/hosoyamasuyuki-stack/-AI-/actions/runs/25209398760) |

## ❌ 要対応項目

- **株価更新** (daily_price_update.yml): FAILURE
  - 最終実行: 2026-05-18 08:30 JST (0.2h前 / 上限 30h)
  - URL: https://github.com/hosoyamasuyuki-stack/-AI-/actions/runs/26005888269

---
*このレポートは health_check ワークフローが毎朝自動生成しています。*
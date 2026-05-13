# システム健康診断レポート

**実行時刻**: 2026-05-14 08:42 JST
**総合判定**: ❌ 1/10 件に問題あり

| 項目 | 直近実行 | 経過 | 上限 | 結果 | URL |
|---|---|---|---|---|---|
| 株価更新 (daily_price_update.yml) | 2026-05-14 08:37 JST | 0.1h | 30h | ✅ OK | [run](https://github.com/hosoyamasuyuki-stack/-AI-/actions/runs/25832656103) |
| FRED指標 (daily_update.yml) | 2026-05-14 08:10 JST | 0.5h | 80h | ✅ OK | [run](https://github.com/hosoyamasuyuki-stack/-AI-/actions/runs/25831717229) |
| 週次フル再計算 (weekly_update.yml) | 2026-05-11 13:53 JST | 66.8h | 200h | ✅ OK | [run](https://github.com/hosoyamasuyuki-stack/-AI-/actions/runs/25651043118) |
| ダッシュボード生成 (dashboard_update.yml) | 2026-05-11 14:30 JST | 66.2h | 200h | ✅ OK | [run](https://github.com/hosoyamasuyuki-stack/-AI-/actions/runs/25652157242) |
| 全市場スキャン (full_scan.yml) | 2026-05-10 23:20 JST | 81.4h | 200h | ❌ FAILURE | [run](https://github.com/hosoyamasuyuki-stack/-AI-/actions/runs/25631089049) |
| handover.txt (generate_handover.yml) | 2026-05-11 08:45 JST | 72.0h | 200h | ✅ OK | [run](https://github.com/hosoyamasuyuki-stack/-AI-/actions/runs/25643080378) |
| verify検証 (verify.yml) | 2026-05-11 14:54 JST | 65.8h | 200h | ✅ OK | [run](https://github.com/hosoyamasuyuki-stack/-AI-/actions/runs/25652928922) |
| シート管理（月次） (sheet_manager.yml) | 2026-05-01 16:53 JST | 303.8h | 800h | ✅ OK | [run](https://github.com/hosoyamasuyuki-stack/-AI-/actions/runs/25207168683) |
| TDnet 決算短信取得 (fetch_tanshin.yml) | 2026-05-11 15:12 JST | 65.5h | 200h | ✅ OK | [run](https://github.com/hosoyamasuyuki-stack/-AI-/actions/runs/25653505824) |
| 月次学習バッチ (monthly_learning.yml) | 2026-05-01 18:19 JST | 302.4h | 800h | ✅ OK | [run](https://github.com/hosoyamasuyuki-stack/-AI-/actions/runs/25209398760) |

## ❌ 要対応項目

- **全市場スキャン** (full_scan.yml): FAILURE
  - 最終実行: 2026-05-10 23:20 JST (81.4h前 / 上限 200h)
  - URL: https://github.com/hosoyamasuyuki-stack/-AI-/actions/runs/25631089049

---
*このレポートは health_check ワークフローが毎朝自動生成しています。*
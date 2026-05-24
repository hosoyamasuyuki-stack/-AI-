# システム健康診断レポート

**実行時刻**: 2026-05-25 08:43 JST
**総合判定**: ❌ 1/10 件に問題あり

| 項目 | 直近実行 | 経過 | 上限 | 結果 | URL |
|---|---|---|---|---|---|
| 株価更新 (daily_price_update.yml) | 2026-05-25 08:32 JST | 0.2h | 30h | ✅ RUNNING | [run](https://github.com/hosoyamasuyuki-stack/-AI-/actions/runs/26375855094) |
| FRED指標 (daily_update.yml) | 2026-05-25 08:02 JST | 0.7h | 80h | ✅ OK | [run](https://github.com/hosoyamasuyuki-stack/-AI-/actions/runs/26375206316) |
| 週次フル再計算 (weekly_update.yml) | 2026-05-18 14:00 JST | 162.7h | 200h | ✅ OK | [run](https://github.com/hosoyamasuyuki-stack/-AI-/actions/runs/26014462105) |
| ダッシュボード生成 (dashboard_update.yml) | 2026-05-18 14:42 JST | 162.0h | 200h | ❌ FAILURE | [run](https://github.com/hosoyamasuyuki-stack/-AI-/actions/runs/26015758087) |
| 全市場スキャン (full_scan.yml) | 2026-05-24 23:26 JST | 9.3h | 200h | ✅ OK | [run](https://github.com/hosoyamasuyuki-stack/-AI-/actions/runs/26363863947) |
| handover.txt (generate_handover.yml) | 2026-05-18 08:53 JST | 167.8h | 200h | ✅ OK | [run](https://github.com/hosoyamasuyuki-stack/-AI-/actions/runs/26006385311) |
| verify検証 (verify.yml) | 2026-05-18 15:09 JST | 161.6h | 200h | ✅ OK | [run](https://github.com/hosoyamasuyuki-stack/-AI-/actions/runs/26016633963) |
| シート管理（月次） (sheet_manager.yml) | 2026-05-01 16:53 JST | 567.8h | 800h | ✅ OK | [run](https://github.com/hosoyamasuyuki-stack/-AI-/actions/runs/25207168683) |
| TDnet 決算短信取得 (fetch_tanshin.yml) | 2026-05-24 15:13 JST | 17.5h | 200h | ✅ OK | [run](https://github.com/hosoyamasuyuki-stack/-AI-/actions/runs/26353738286) |
| 月次学習バッチ (monthly_learning.yml) | 2026-05-01 18:19 JST | 566.4h | 800h | ✅ OK | [run](https://github.com/hosoyamasuyuki-stack/-AI-/actions/runs/25209398760) |

## ❌ 要対応項目

- **ダッシュボード生成** (dashboard_update.yml): FAILURE
  - 最終実行: 2026-05-18 14:42 JST (162.0h前 / 上限 200h)
  - URL: https://github.com/hosoyamasuyuki-stack/-AI-/actions/runs/26015758087

---
*このレポートは health_check ワークフローが毎朝自動生成しています。*
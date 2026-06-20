# システム健康診断レポート

**実行時刻**: 2026-06-21 08:49 JST
**総合判定**: ❌ 1/10 件に問題あり

| 項目 | 直近実行 | 経過 | 上限 | 結果 | URL |
|---|---|---|---|---|---|
| 株価更新 (daily_price_update.yml) | 2026-06-21 08:45 JST | 0.1h | 30h | ✅ RUNNING | [run](https://github.com/hosoyamasuyuki-stack/-AI-/actions/runs/27887507227) |
| FRED指標 (daily_update.yml) | 2026-06-20 08:03 JST | 24.8h | 80h | ✅ OK | [run](https://github.com/hosoyamasuyuki-stack/-AI-/actions/runs/27852310631) |
| 週次フル再計算 (weekly_update.yml) | 2026-06-15 08:09 JST | 144.7h | 200h | ✅ OK | [run](https://github.com/hosoyamasuyuki-stack/-AI-/actions/runs/27515028770) |
| ダッシュボード生成 (dashboard_update.yml) | 2026-06-18 11:12 JST | 69.6h | 200h | ✅ OK | [run](https://github.com/hosoyamasuyuki-stack/-AI-/actions/runs/27732199611) |
| 全市場スキャン (full_scan.yml) | 2026-06-15 00:08 JST | 152.7h | 200h | ❌ OTHER(cancelled) | [run](https://github.com/hosoyamasuyuki-stack/-AI-/actions/runs/27502917271) |
| handover.txt (generate_handover.yml) | 2026-06-15 09:03 JST | 143.8h | 200h | ✅ OK | [run](https://github.com/hosoyamasuyuki-stack/-AI-/actions/runs/27516336004) |
| verify検証 (verify.yml) | 2026-06-15 22:28 JST | 130.4h | 200h | ✅ OK | [run](https://github.com/hosoyamasuyuki-stack/-AI-/actions/runs/27549642579) |
| シート管理（月次） (sheet_manager.yml) | 2026-06-01 13:12 JST | 475.6h | 800h | ✅ OK | [run](https://github.com/hosoyamasuyuki-stack/-AI-/actions/runs/26734740667) |
| TDnet 決算短信取得 (fetch_tanshin.yml) | 2026-06-20 15:44 JST | 17.1h | 200h | ✅ OK | [run](https://github.com/hosoyamasuyuki-stack/-AI-/actions/runs/27863246334) |
| 月次学習バッチ (monthly_learning.yml) | 2026-06-07 04:32 JST | 340.3h | 800h | ✅ OK | [run](https://github.com/hosoyamasuyuki-stack/-AI-/actions/runs/27071793866) |

## ❌ 要対応項目

- **全市場スキャン** (full_scan.yml): OTHER(cancelled)
  - 最終実行: 2026-06-15 00:08 JST (152.7h前 / 上限 200h)
  - URL: https://github.com/hosoyamasuyuki-stack/-AI-/actions/runs/27502917271

---
*このレポートは health_check ワークフローが毎朝自動生成しています。*
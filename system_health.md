# システム健康診断レポート

**実行時刻**: 2026-07-02 08:56 JST
**総合判定**: ❌ 1/13 件に問題あり

| 項目 | 直近実行 | 経過 | 上限 | 結果 | URL |
|---|---|---|---|---|---|
| 株価更新（朝7:30） (daily_price_update.yml) | 2026-07-02 08:51 JST | 0.1h | 30h | ✅ RUNNING | [run](https://github.com/hosoyamasuyuki-stack/-AI-/actions/runs/28555497069) |
| 株価更新（昼12:30） (midday_price_update.yml) | 2026-07-01 16:53 JST | 16.0h | 200h | ✅ OK | [run](https://github.com/hosoyamasuyuki-stack/-AI-/actions/runs/28502353096) |
| 株価更新（夕16:00） (close_price_update.yml) | 2026-07-01 19:37 JST | 13.3h | 200h | ✅ OK | [run](https://github.com/hosoyamasuyuki-stack/-AI-/actions/runs/28511502660) |
| FRED指標 (daily_update.yml) | 2026-07-02 08:20 JST | 0.6h | 80h | ✅ OK | [run](https://github.com/hosoyamasuyuki-stack/-AI-/actions/runs/28554241751) |
| 週次フル再計算 (weekly_update.yml) | 2026-06-29 08:01 JST | 72.9h | 200h | ✅ OK | [run](https://github.com/hosoyamasuyuki-stack/-AI-/actions/runs/28338969375) |
| ダッシュボード生成 (dashboard_update.yml) | 2026-06-29 08:37 JST | 72.3h | 200h | ✅ OK | [run](https://github.com/hosoyamasuyuki-stack/-AI-/actions/runs/28339870070) |
| 全市場スキャン (full_scan.yml) | 2026-06-28 23:49 JST | 81.1h | 200h | ✅ OK | [run](https://github.com/hosoyamasuyuki-stack/-AI-/actions/runs/28325956573) |
| handover.txt (generate_handover.yml) | 2026-06-29 09:03 JST | 71.9h | 200h | ✅ OK | [run](https://github.com/hosoyamasuyuki-stack/-AI-/actions/runs/28340517791) |
| verify検証 (verify.yml) | 2026-07-01 14:45 JST | 18.2h | 200h | ✅ OK | [run](https://github.com/hosoyamasuyuki-stack/-AI-/actions/runs/28496402683) |
| シート管理（月次） (sheet_manager.yml) | 2026-07-01 13:00 JST | 19.9h | 800h | ✅ OK | [run](https://github.com/hosoyamasuyuki-stack/-AI-/actions/runs/28492541655) |
| TDnet 決算短信取得 (fetch_tanshin.yml) | 2026-07-01 15:48 JST | 17.1h | 200h | ✅ OK | [run](https://github.com/hosoyamasuyuki-stack/-AI-/actions/runs/28499129848) |
| 月次学習バッチ (monthly_learning.yml) | 2026-07-01 19:42 JST | 13.2h | 800h | ❌ FAILURE | [run](https://github.com/hosoyamasuyuki-stack/-AI-/actions/runs/28511726877) |
| ダッシュボード鮮度 (ai_dashboard_v13.html) | 2026-07-01 19:44 JST | 13.2h | 36h | ✅ OK | [run](https://github.com/hosoyamasuyuki-stack/-AI-/commit/a35fa0de0cc87e94381058b9c8c684ac35272b63) |

## ❌ 要対応項目

- **月次学習バッチ** (monthly_learning.yml): FAILURE
  - 最終実行: 2026-07-01 19:42 JST (13.2h前 / 上限 800h)
  - URL: https://github.com/hosoyamasuyuki-stack/-AI-/actions/runs/28511726877

---
*このレポートは health_check ワークフローが毎朝自動生成しています。*
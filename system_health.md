# システム健康診断レポート

**実行時刻**: 2026-05-11 08:35 JST
**総合判定**: ❌ 1/10 件に問題あり

| 項目 | 直近実行 | 経過 | 上限 | 結果 | URL |
|---|---|---|---|---|---|
| 株価更新 (daily_price_update.yml) | 2026-05-11 08:27 JST | 0.1h | 30h | ✅ OK | [run](https://github.com/hosoyamasuyuki-stack/-AI-/actions/runs/25642711897) |
| FRED指標 (daily_update.yml) | 2026-05-11 07:54 JST | 0.7h | 80h | ✅ OK | [run](https://github.com/hosoyamasuyuki-stack/-AI-/actions/runs/25642052905) |
| 週次フル再計算 (weekly_update.yml) | 2026-05-04 13:35 JST | 163.0h | 200h | ✅ OK | [run](https://github.com/hosoyamasuyuki-stack/-AI-/actions/runs/25301228828) |
| ダッシュボード生成 (dashboard_update.yml) | 2026-05-04 13:58 JST | 162.6h | 200h | ✅ OK | [run](https://github.com/hosoyamasuyuki-stack/-AI-/actions/runs/25301850320) |
| 全市場スキャン (full_scan.yml) | 2026-05-10 23:20 JST | 9.2h | 200h | ❌ FAILURE | [run](https://github.com/hosoyamasuyuki-stack/-AI-/actions/runs/25631089049) |
| handover.txt (generate_handover.yml) | 2026-05-04 08:39 JST | 167.9h | 200h | ✅ OK | [run](https://github.com/hosoyamasuyuki-stack/-AI-/actions/runs/25294145847) |
| verify検証 (verify.yml) | 2026-05-04 14:31 JST | 162.1h | 200h | ✅ OK | [run](https://github.com/hosoyamasuyuki-stack/-AI-/actions/runs/25302737195) |
| シート管理（月次） (sheet_manager.yml) | 2026-05-01 16:53 JST | 231.7h | 800h | ✅ OK | [run](https://github.com/hosoyamasuyuki-stack/-AI-/actions/runs/25207168683) |
| TDnet 決算短信取得 (fetch_tanshin.yml) | 2026-05-04 14:48 JST | 161.8h | 200h | ✅ OK | [run](https://github.com/hosoyamasuyuki-stack/-AI-/actions/runs/25303231200) |
| 月次学習バッチ (monthly_learning.yml) | 2026-05-01 18:19 JST | 230.3h | 800h | ✅ OK | [run](https://github.com/hosoyamasuyuki-stack/-AI-/actions/runs/25209398760) |

## ❌ 要対応項目

- **全市場スキャン** (full_scan.yml): FAILURE
  - 最終実行: 2026-05-10 23:20 JST (9.2h前 / 上限 200h)
  - URL: https://github.com/hosoyamasuyuki-stack/-AI-/actions/runs/25631089049

---
*このレポートは health_check ワークフローが毎朝自動生成しています。*
# 保有ポートフォリオ一括更新 — CEO レビュー資料

**作成日**: 2026-04-30
**目的**: CEO が変更内容を確認してから本番反映するための資料

---

## 1. 何を作ったか（サマリ）

CEO の課題「最新データを一括更新できる仕組みがない」を解決する 6 部品を実装。

| # | 種類 | ファイル | 場所 | 状態 |
|---|---|---|---|---|
| 1 | Python | `bulk_update_holdings.py` | RICH-KAIZEN repo ルート | 新規 |
| 2 | Workflow | `.github/workflows/bulk_update_holdings.yml` | RICH-KAIZEN repo | 新規 |
| 3 | GAS スニペット | `gas/gas_bulk_holdings_addition.js` | RICH-KAIZEN repo | 新規（既存 GAS に追加するコード） |
| 4 | Dashboard UI | `docs/dashboard_bulk_update_snippet.html` | RICH-KAIZEN repo | 新規（ai_dashboard_v13.html に統合する素材） |
| 5 | Skill | `~/.claude/skills/portfolio-extractor/SKILL.md` | ローカル `.claude/skills/` | 新規 |
| 6 | 仕様書 | `LISA_RK_INTEGRATION_SPEC.md` v1.2 | Dropbox | 既存更新 |

**既存システム変更ゼロ**：保有銘柄_v4.3スコア / 18 workflow / manage_stock.py / generate_dashboard.py / LISA Next.js すべて不変。

---

## 2. 動作フロー（CEO 視点）

```
① CEO がスクショ撮影（楽天 / SBI 等）
       ↓
② Claude Code で「保有株を CSV にして」+ スクショ添付
       ↓ portfolio-extractor スキルが起動
③ プレビュー確認 → CSV ファイル生成
       ↓
④ LISA admin or RICH-KAIZEN ダッシュボードを開く
       ↓
⑤ 「📋 一括更新」ボタン → モーダル
       ↓
⑥ CSV 貼付（or ファイルアップロード）→ 「投入」
       ↓
⑦ 確認ダイアログ「N 行で全置換します」→ OK
       ↓
⑧ GAS が GitHub Actions の bulk_update_holdings.yml を起動
       ↓
⑨ Python が Sheets を更新（2-3 分）
   ・ 保有ポートフォリオ_master を全置換
   ・ 保有スナップショット に当月分追加
   ・ 保有差分 を再生成
       ↓
⑩ 翌週月曜の dashboard_update.yml で ai_dashboard_v13.html に反映
```

---

## 3. CEO に作業していただきたいこと（順序）

### Phase A：本番反映前の事前作業（CEO 操作）

1. **GAS への追加**（5 分）
   - `https://script.google.com/u/0/home/projects/...`（既存 manage_stock GAS のプロジェクト）
   - `gas/gas_bulk_holdings_addition.js` の内容を既存 GAS の doPost に統合
   - 新バージョンとしてデプロイ

2. **GitHub Secrets 確認**（既設定なら不要・確認のみ）
   - `GOOGLE_CREDENTIALS` ✅ 既設定
   - `JQUANTS_API_KEY` ✅ 既設定
   - `SPREADSHEET_ID` ✅ 既設定

### Phase B：6 ファイルの GitHub push（CEO 操作 or 私が API push）

push 対象（RICH-KAIZEN repo `hosoyamasuyuki-stack/-AI-`）：
- `bulk_update_holdings.py`
- `.github/workflows/bulk_update_holdings.yml`
- `gas/gas_bulk_holdings_addition.js`
- `docs/dashboard_bulk_update_snippet.html`
- `BULK_UPDATE_REVIEW.md`（本資料・任意）

push 後、GitHub Actions の workflow_dispatch から手動実行で動作確認可能。

### Phase C：ダッシュボードへの UI 統合（後日でも可）

- `ai_dashboard_v13.html` に `docs/dashboard_bulk_update_snippet.html` の内容を統合
- これがないと CEO は GitHub Actions web UI から手動実行する必要あり
- ただし、まず GitHub Actions web UI で手動投入 → 動作確認 → 後でダッシュボード統合、という段階的進行可

### Phase D：通し試験

1. GitHub Actions web UI で `Bulk Update Holdings` workflow を `dry_run=true` で起動
2. CSV 例：
   ```
   market,code,shares
   JP,7203,100
   ```
3. ログで「dry-run 成功」を確認
4. dry_run=false で再実行
5. Google Sheets で 3 シート（保有ポートフォリオ_master / 保有スナップショット / 保有差分）が新規作成されていることを確認
6. CEO 本番運用開始

---

## 4. 設計判断の根拠（要 CEO 確認）

| 判断 | 内容 | 根拠 |
|---|---|---|
| 既存シート不変 | `保有銘柄_v4.3スコア` には触らない | 既存 18 workflow が依存・販売 5/12 までのリスク回避 |
| 新シート 3 本独立 | master / snapshot / diff を新設 | スコア管理（既存）と持ち株管理（新）の責務分離 |
| 取得単価扱わず | CSV 列に含めない | CEO 確定 2026-04-30（分割購入時に表示されない） |
| broker / account_type 列を最初から持つ | DEFAULT='manual' / 'unspecified' で空運用 | 3 年後の楽天+SBI 併用 / NISA 区分で破壊的変更を回避 |
| market 列を最初から持つ | DEFAULT='JP' | 米国株対応時に列追加マイグレ不要 |
| snapshot_month は DATE 型 | '2026-05-01' 形式 | 年跨ぎインデックス効く |
| 差分は当月分のみ | unchanged は出力しない | ノイズ低減・履歴は snapshot に残る |
| 1 行 = 1 (market, broker, account_type, code) | 同一銘柄複数行は株数合算 | スクショで分かれて表示される場合に対応 |

---

## 5. リスクと緩和策

| リスク | 緩和策 |
|---|---|
| CSV を間違えて投入 → 過去 master が消える | snapshot に当月分が残るので前月以前は無事・dry_run で事前確認可 |
| GAS 経由で workflow_dispatch が失敗 | GitHub Actions web UI から手動実行可・手動 fallback 可 |
| Sheets API のレート制限 | 既存 sheet_manager.py と同じ `gspread` を使用・実績あり |
| J-Quants 銘柄名取得失敗 | name 空欄で続行・致命ではない（manage_stock.py と同挙動） |
| 米国株（US）コード取扱 | market='US' で保存のみ・第一弾は表示・分析対象外（明示） |

---

## 6. 受け入れ基準（CEO 確認）

- [ ] dry_run で CSV 検証ができる
- [ ] 本番実行で 3 シートが自動作成される
- [ ] master が CSV の内容で全置換される
- [ ] snapshot に当月分が記録される
- [ ] diff に先月との変化（new / removed / increased / decreased）が出る
- [ ] 既存の保有銘柄_v4.3スコア / 監視銘柄_v4.3スコア / 予測記録 / コアスキャン_v4.3 に変更が一切ない
- [ ] LISA / Vercel / Stripe / Supabase に変更が一切ない

---

## 7. 次回セッション引き継ぎポイント

- 仕様書（Dropbox）`LISA_RK_INTEGRATION_SPEC.md` を**最初に必ず読む**
- 本資料は反映確認後、`docs/` に移動 or 削除して OK
- スキル `portfolio-extractor` は CEO の指示で随時改善
- ダッシュボード UI 統合（Phase C）は次セッション開始時の優先タスク

---

## 8. 私から CEO への確認 4 点

1. **Phase A の GAS 追加は CEO 操作で OK か**（私が GitHub web 経由で送れるが GAS は CEO のアカウント）
2. **Phase B の push 方法**：私が API トークンで push するか / CEO が GitHub web で commit するか
3. **Phase C のダッシュボード UI 統合タイミング**：今すぐ / 動作確認後 / 販売後
4. **販売 5/12 までの通し試験スケジュール**：いつ Phase D を実施するか

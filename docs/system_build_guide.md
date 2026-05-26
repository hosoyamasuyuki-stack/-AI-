# AI投資判断システム 構築ガイド（外部チーム向け）
# Version 2.0 | 2026-03-27

> **目的**: 日本株のファンダメンタル分析を自動化するシステムをゼロから構築するための技術情報
> **対象読者**: Python中級以上のエンジニア
> **内容**: API仕様・認証方法・コスト・開発中に踏んだ地雷と対策

---

## 1. システム概要

日本株を対象に、財務データ・株価・マクロ経済指標を自動収集し、
ダッシュボードで可視化する投資判断支援システム。

### アーキテクチャ
```
[GitHub Actions (cron/手動)]
    |
    v
[Python Scripts] ---> [Google Sheets (データストア)]
    |                         |
    |                         v
    +---> [HTML生成スクリプト] ---> [GitHub Pages (ダッシュボード)]
                                            |
                                            v
                                       [ブラウザ]
                                            |
                                            v
                                  [GAS Proxy] ---> [Claude API / EDINET API]
```

**技術スタック**: Python 3.11 / Google Sheets(gspread) / GitHub Actions / GitHub Pages / GAS

---

## 2. 外部API完全仕様

---

### 2-A. J-Quants API（日本株 財務・株価データ）

| 項目 | 内容 |
|------|------|
| 提供元 | JPX（日本取引所グループ） |
| ベースURL | `https://api.jquants.com` |
| 認証 | HTTPヘッダー `x-api-key: <API_KEY>` |
| 料金 | 無料: 月12,000リクエスト / Light: 月1,100円 |
| 申込 | https://application.jpx-jquants.com/ |

**エンドポイント**:

```
GET /v2/equities/bars/daily?code={5桁コード}&date={YYYY-MM-DD}
  レスポンス: AdjC（調整済み終値）, C（終値）, Vo（出来高）

GET /v2/fins/summary?code={5桁コード}
  レスポンス:
    NP（純利益）, EPS, FEPS（予想EPS）, ROE,
    TA（総資産）, Sales, OP（営業利益）,
    ShOutFY（発行済株式数）, Eq（自己資本）,
    CFO（営業CF）, CFI（投資CF）
  ※ FCF = CFO + CFI

GET /v2/equities/master?code={5桁コード}
  レスポンス: TotalMarketValue（時価総額）
```

#### 地雷と注意点
| # | 地雷 | 詳細 | 対策 |
|---|------|------|------|
| 1 | **銘柄コード5桁** | 4桁(7203)ではなく5桁(72030)を送る必要がある | 末尾に`'0'`を追加: `code = str(code) + '0'` |
| 2 | **v1とv2で認証が全く違う** | v1はメール+パスワード→トークン取得方式。v2はx-api-keyヘッダーのみ | v2を使う。v1は非推奨 |
| 3 | **v1の認証が突然400エラー** | v1のメール認証エンドポイントが不安定（2026/03時点） | v2に移行。v1財務データが必要ならサポートに問い合わせ |
| 4 | **TotalMarketValueの罠** | `/v2/equities/master`が返すTotalMarketValueを時価総額として使うと、`/v2/fins/summary`のShOutFYとの二重計算になる | 時価総額 = ShOutFY x 株価 で自前計算する |
| 5 | **無料プランのAPI制限** | 月12,000回。100銘柄x3エンドポイントx30日=9,000回でギリギリ | バッチ処理で最適化。キャッシュ活用 |
| 6 | **財務データの期数** | OLS回帰で傾きを計算するには最低6期分の財務データが必要 | 新規上場銘柄はデータ不足でスコア計算不可 |

---

### 2-B. FRED API（米国・世界の経済指標）

| 項目 | 内容 |
|------|------|
| 提供元 | Federal Reserve Bank of St. Louis |
| ベースURL | `https://api.stlouisfed.org/fred/series/observations` |
| 認証 | クエリパラメータ `api_key=<API_KEY>` |
| 料金 | **完全無料** |
| レート制限 | 120回/分 |
| 申込 | https://fred.stlouisfed.org/docs/api/api_key.html |

**リクエスト例**:
```
GET https://api.stlouisfed.org/fred/series/observations
    ?series_id=VIXCLS
    &sort_order=desc
    &limit=5
    &api_key=YOUR_KEY
    &file_type=json
```

**推奨シリーズID（用途別）**:

```
=== リスク指標（相場の温度計）===
VIXCLS           : VIX恐怖指数（最重要。RED/GREEN判定の核）
BAMLH0A0HYM2     : ハイイールド信用スプレッド（信用不安の先行指標）
TEDRATE          : TEDスプレッド（銀行間の信用リスク）
BAMLC0A0CM       : 投資適格社債スプレッド
T10Y2Y           : 10年-2年利回り差（マイナス=逆イールド→景気後退警告）

=== 金融政策（中央銀行の動き）===
DGS10            : 米国10年国債利回り
DGS2             : 米国2年国債利回り
IRLTLT01JPM156N  : 日本長期金利
M2SL             : 米国M2マネーサプライ
MYAGM2JPM189S    : 日本M2マネーサプライ
WALCL            : FRBバランスシート
BOGMBASE         : マネタリーベース

=== 経済活動 ===
INDPRO           : 鉱工業生産指数
TCU              : 設備稼働率（中期スコアに使用）
UNRATE           : 失業率
RSXFS            : 小売売上高
HOUST            : 住宅着工件数
DGORDER          : 耐久財受注
UMCSENT          : ミシガン大消費者信頼感指数
MANEMP           : 製造業雇用者数
CPIAUCSL         : CPI（インフレ）
PCEPI            : PCEデフレーター

=== 為替・コモディティ ===
DEXJPUS          : ドル円為替レート
DTWEXBGS         : ドルインデックス
DCOILWTICO       : WTI原油価格
GOLDPMGBD228NLBM : 金価格

=== バリュエーション ===
DDDM01USA156NWDB : バフェット指標（米国・株式時価総額/GDP）
DDDM01JPA156NWDB : バフェット指標（日本）
```

#### 地雷と注意点
| # | 地雷 | 詳細 | 対策 |
|---|------|------|------|
| 1 | **月次データの更新タイミング** | M2SL等の月次指標は1-2ヶ月遅れで公開 | 最新値が空の場合のフォールバック処理必須 |
| 2 | **レート制限120回/分** | 25指標を一気に取得すると引っかかる可能性 | 各リクエスト間に0.5秒sleepを挟む |
| 3 | **欠損値 "."** | 休日や未公開期間のデータは`"."`が返る | `float(val)`でValueError→スキップ処理 |
| 4 | **file_type=json指定忘れ** | デフォルトはXML | 必ず`&file_type=json`を付ける |

---

### 2-C. yfinance（Yahoo Finance・株価データ）

| 項目 | 内容 |
|------|------|
| 提供元 | Yahoo Finance（非公式Pythonライブラリ） |
| 認証 | **不要** |
| 料金 | **完全無料** |
| インストール | `pip install yfinance` |

**主要ティッカー**:
```python
# 日本株個別
"{4桁コード}.T"    # 例: "7203.T"（トヨタ）

# 指数・ETF
"^N225"            # 日経225
"^GSPC"            # S&P 500
"^VIX"             # VIX
"^SOX"             # 半導体指数
"^RUT"             # ラッセル2000
"HYG"              # ハイイールドETF
"SPY"              # S&P 500 ETF（PER・配当利回り取得）
"1306.T"           # TOPIX ETF（日本の配当利回り取得）
"USDJPY=X"         # ドル円

# 使い方
import yfinance as yf
t = yf.Ticker("7203.T")
hist = t.history(period="5d")   # 直近5日
info = t.info                   # PER, 配当利回り等
df = yf.download(["^N225","^GSPC"], period="1mo")  # 一括取得
```

#### 地雷と注意点（最も問題が多いAPI）
| # | 地雷 | 深刻度 | 詳細 | 対策 |
|---|------|--------|------|------|
| 1 | **突然の仕様変更** | 高 | Yahoo側の変更でライブラリが突然動かなくなる（年に数回発生） | 必ずJ-Quantsとのフォールバック構成にする |
| 2 | **15分遅延** | 中 | リアルタイムではない | 終値確定後（15:30 JST以降）に取得推奨 |
| 3 | **レート制限** | 中 | 短時間に大量リクエストでIPブロックされる | 50銘柄バッチで`yf.download()`を使う |
| 4 | **`.info`が空dictを返す** | 高 | 一部銘柄やタイミングで`info`が空になる | try/exceptで囲み、デフォルト値を設定 |
| 5 | **日本株の財務データ精度** | 中 | CFO, CFI等の詳細財務はJ-Quantsの方が正確 | 財務分析はJ-Quants、株価はyfinanceが理想 |
| 6 | **GitHub Actionsでの実行** | 中 | サーバー環境でブロックされやすい | `PRICE_SOURCE`環境変数で切り替え可能にしておく |

---

### 2-D. EDINET API（有価証券報告書）

| 項目 | 内容 |
|------|------|
| 提供元 | 金融庁 |
| ベースURL | `https://api.edinet-fsa.go.jp/api/v2/documents.json` |
| 認証 | クエリパラメータ `Subscription-Key=<API_KEY>` |
| 料金 | **完全無料** |
| 申込 | https://disclosure2dl.edinet-fsa.go.jp/guide/static/register |

**リクエスト例**:
```
GET https://api.edinet-fsa.go.jp/api/v2/documents.json
    ?date=2026-03-27&type=2&Subscription-Key=YOUR_KEY
```

**レスポンスの重要フィールド**:
```
docID, edinetCode, filerName, docDescription,
submitDateTime, periodStart, periodEnd, secCode
```

#### 地雷と注意点
| # | 地雷 | 詳細 | 対策 |
|---|------|------|------|
| 1 | **証券コード5桁** | `secCode`は5桁で返る | J-Quantsと同じく5桁で比較 |
| 2 | **日付指定が1日単位** | 特定日の提出文書しか返らない | 7日間隔で90日前まで遡るループ検索が必要 |
| 3 | **大量の文書** | 決算期は1日に数百件 | `secCode`でフィルタして最新1件を取得 |

---

### 2-E. Claude API（AI分析）

| 項目 | 内容 |
|------|------|
| 提供元 | Anthropic |
| ベースURL | `https://api.anthropic.com/v1/messages` |
| 認証 | ヘッダー `x-api-key: <API_KEY>` + `anthropic-version: 2023-06-01` |
| 料金 | Sonnet: 入力$3/出力$15 per 1Mトークン |
| 申込 | https://console.anthropic.com/ |

**リクエスト例**:
```json
POST https://api.anthropic.com/v1/messages
Headers:
  x-api-key: YOUR_KEY
  anthropic-version: 2023-06-01
  Content-Type: application/json

Body:
{
  "model": "claude-sonnet-4-20250514",
  "max_tokens": 4000,
  "messages": [
    {"role": "user", "content": "銘柄分析プロンプト"}
  ]
}
```

**コスト目安**: 1銘柄分析あたり約2-5円

#### 地雷と注意点
| # | 地雷 | 詳細 | 対策 |
|---|------|------|------|
| 1 | **ブラウザから直接呼ぶとAPIキー露出** | fetchでクライアント側から呼ぶとキーがdevtoolsで丸見え | GASプロキシ経由で呼ぶ（サーバーサイド） |
| 2 | **GASのPOSTリダイレクト** | GASのdoPostはリダイレクト時にbodyが消失する | URLパラメータ方式（`?action=xxx`）で回避 |
| 3 | **max_tokens不足** | 長い分析結果が途中で切れる | 4000トークン以上を設定 |

---

### 2-F. Google Sheets API（gspread経由）

| 項目 | 内容 |
|------|------|
| 認証 | サービスアカウントJSON |
| 料金 | **無料**（300リクエスト/分） |
| ライブラリ | `gspread` + `google-auth` |

**認証コード**:
```python
import json, os, gspread
from google.oauth2.service_account import Credentials

scope = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive"
]
creds_dict = json.loads(os.environ["GOOGLE_CREDENTIALS"])
creds = Credentials.from_service_account_info(creds_dict, scopes=scope)
gc = gspread.authorize(creds)
book = gc.open_by_key(os.environ["SPREADSHEET_ID"])
ws = book.worksheet("シート名")

# 読み取り
rows = ws.get_all_values()

# 書き込み（セル指定）
ws.update_cell(1, 1, "値")

# バッチ書き込み（推奨）
ws.update("A1:C3", [["a","b","c"],["d","e","f"],["g","h","i"]])
```

**セットアップ手順**:
1. Google Cloud Console → プロジェクト作成
2. 「Sheets API」と「Drive API」を有効化
3. サービスアカウント作成 → JSONキーダウンロード
4. スプレッドシートをサービスアカウントのメールアドレスに共有（編集者権限）
5. JSONを1行化して環境変数`GOOGLE_CREDENTIALS`に設定

#### 地雷と注意点（最も実害が大きかったAPI）
| # | 地雷 | 深刻度 | 詳細 | 対策 |
|---|------|--------|------|------|
| 1 | **300回/分のレート制限** | 致命的 | 100銘柄分を個別にupdate_cellすると簡単に超過 | バッチ書き込み（`ws.update()`）を使う。大量更新前に**60秒待機** |
| 2 | **APIレート制限エラーのリトライ** | 高 | 429エラーが返ったらそのまま落ちる | `time.sleep(60)` + 最大3回リトライを実装 |
| 3 | **シート名の存在確認** | 高 | 存在しないシート名を自信を持って指定してしまう | コード内で参照する前に`book.worksheets()`で確認 |
| 4 | **GOOGLE_CREDENTIALSの形式** | 中 | 改行入りJSONだとGitHub Secretsで壊れる | 1行化: `cat key.json | jq -c .` |
| 5 | **二重書き込み** | 中 | 同じデータを複数箇所に書く設計でAPI呼び出しが倍増 | 書き込み先を整理し、1回の更新でまとめる |

---

### 2-G. Webスクレイピング（APIキー不要）

| データ | URL | 抽出方法 |
|--------|-----|---------|
| 日本PBR | `https://indexes.nikkei.co.jp/nkave/index/profile?idx=0009` | regex: `PBR.*?([\d.]+)\s*倍` |
| 米国PBR | `https://www.multpl.com/s-p-500-price-to-book` | テーブルからfloat抽出 |
| シラーCAPE | `https://www.multpl.com/shiller-pe` | テーブルからfloat抽出 |

**必須**: `User-Agent`ヘッダーを設定しないと403で弾かれる
```python
headers = {"User-Agent": "Mozilla/5.0 (compatible)"}
resp = requests.get(url, headers=headers)
```

---

## 3. コスト構造

| 項目 | 無料版 | 推奨版 |
|------|--------|--------|
| J-Quants | 無料（月12,000回） | Light: 1,100円/月 |
| FRED API | 無料 | 無料 |
| yfinance | 無料 | 無料 |
| EDINET | 無料 | 無料 |
| Claude API | なし | 従量（月500-1,000円） |
| Google Sheets | 無料 | 無料 |
| GitHub Actions | 無料（2,000分/月） | 無料 |
| GitHub Pages | 無料 | 無料 |
| **合計** | **0円** | **約1,600-2,100円/月** |

**最小構成（月額0円）**: yfinance + FRED + Google Sheets + GitHub Actions + GitHub Pages

---

## 4. GitHub Actions 設計ガイド

### cron設定（JST変換が必須）

```yaml
# GitHub ActionsのcronはUTC。日本時間-9時間で設定
# 例: JST 07:00 → UTC 22:00（前日）
schedule:
  - cron: '0 22 * * *'     # 毎日 07:00 JST
  - cron: '0 22 * * 1-5'   # 平日のみ 07:00 JST
  - cron: '0 1 * * 1'      # 毎週月曜 10:00 JST
  - cron: '0 0 1 * *'      # 毎月1日 09:00 JST
```

### YAMLテンプレート
```yaml
name: My Update Job
on:
  schedule:
    - cron: '30 22 * * *'
  workflow_dispatch:           # 手動実行も可能にしておく

env:
  TZ: Asia/Tokyo               # ★必須（Python内のdatetime判定が狂う）

concurrency:                   # ★ボタン連打防止
  group: my-update
  cancel-in-progress: true

jobs:
  update:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'
      - run: pip install gspread google-auth requests yfinance pandas numpy
      - run: python my_script.py
        env:
          JQUANTS_API_KEY: ${{ secrets.JQUANTS_API_KEY }}
          FRED_API_KEY: ${{ secrets.FRED_API_KEY }}
          SPREADSHEET_ID: ${{ secrets.SPREADSHEET_ID }}
          GOOGLE_CREDENTIALS: ${{ secrets.GOOGLE_CREDENTIALS }}
```

### GitHub Actions git push テンプレート
```yaml
      - name: Commit and Push
        run: |
          git config user.name "github-actions[bot]"
          git config user.email "github-actions[bot]@users.noreply.github.com"
          git add my_output.html
          git diff --cached --quiet || git commit -m "auto: update dashboard"
          git pull --rebase        # ★これがないとpush失敗する
          git push
        env:
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
```

#### GitHub Actions の地雷
| # | 地雷 | 深刻度 | 詳細 | 対策 |
|---|------|--------|------|------|
| 1 | **TZ未設定** | 致命的 | PythonのdatetimeがUTCになり、「今日の株価」が昨日になる | `env: TZ: Asia/Tokyo`を全YAMLに設定 |
| 2 | **git push競合** | 高 | 他のworkflowが先にpushするとrejected | `git pull --rebase`を必ずpush前に実行 |
| 3 | **git add -A** | 高 | .envや一時ファイルまでコミットされる | 特定ファイルを明示指定: `git add output.html` |
| 4 | **concurrency未設定** | 中 | ボタン連打やcron重複で多重実行 | `concurrency: group: xxx, cancel-in-progress: true` |
| 5 | **continue-on-error未設定** | 中 | 1ステップ失敗で後続が全停止 | 独立ステップには`continue-on-error: true` |
| 6 | **pip installがworkflowごとに異なる** | 中 | あるworkflowだけyfinance未インストールでImportError | 全workflowのpip installを統一管理 |
| 7 | **GitHubトークンの種類** | 高 | Fine-grainedトークンはCORSでブラウザJSからのPUTがブロック | **Classicトークン**を使う（repo+workflowスコープ） |

---

## 5. GASプロキシ設計

ブラウザのHTMLダッシュボードからGitHub ActionsやClaude APIを呼ぶには、
CORS制限を回避するためGAS（Google Apps Script）を中間プロキシとして使う。

### 構成
```
[ダッシュボードHTML]
  → fetch(GAS_URL + "?action=full_update")
  → [GAS doGet(e)]
      → e.parameter.action で分岐
      → UrlFetchApp.fetch("https://api.github.com/repos/.../dispatches", {
            method: "POST",
            headers: { Authorization: "token " + GITHUB_TOKEN },
            payload: JSON.stringify({ ref: "main" })
        })
      → return ContentService.createTextOutput(JSON.stringify({ok:true}))
```

### GAS の地雷
| # | 地雷 | 詳細 | 対策 |
|---|------|------|------|
| 1 | **doPostのリダイレクトでbody消失** | GAS WebAppはリダイレクト時にPOST bodyを失う | URLパラメータ（`?action=xxx`）で情報を渡す |
| 2 | **デプロイバージョン** | コード変更後に「新しいデプロイ」しないと反映されない | 毎回「新しいデプロイ」を選択 |
| 3 | **スクリプトプロパティ** | APIキーをコード内にハードコードしてしまう | `PropertiesService.getScriptProperties().getProperty("KEY")` |
| 4 | **実行時間制限** | GASは6分（通常）/30分（Workspace）でタイムアウト | Claude API呼び出しはmax_tokensを控えめに |

---

## 6. ダッシュボード（HTML）設計の地雷

### Python → HTML 生成時の罠
| # | 地雷 | 深刻度 | 詳細 | 対策 |
|---|------|--------|------|------|
| 1 | **r-string内の\u** | 致命的 | `r'''...\u{1F4B0}...'''`でもPythonが`\u`を解釈しようとする | `b'''...'''`（バイト列）を使うか、JSを別ファイルにする |
| 2 | **日本語・絵文字** | 高 | Python文字列としてエスケープされて壊れる | HTMLエンティティ（`&#x1F4B0;`）か英語に置換 |
| 3 | **外部JSファイルの読み込み順序** | 高 | `<script src="app.js">`の関数がインラインJSから呼べない | インラインJS統合が最も確実。またはdefer+DOMContentLoaded |

### HTML/CSSの罠
| # | 地雷 | 詳細 | 対策 |
|---|------|------|------|
| 4 | **tableにdisplay:block** | `width:100%`が無効になりレイアウト崩壊 | テーブルは`display:table`のまま、外側のdivでスクロール |
| 5 | **max-height/max-widthハードコード** | 画面サイズで崩れる | flexboxの`flex:1`で高さを伝播させる |
| 6 | **GitHub Pagesキャッシュ** | 更新したのに古いHTMLが表示される | URLに`?v=N`を付けてキャッシュ回避 |
| 7 | **raw.githubusercontent.comの遅延** | CDNキャッシュで10分以上遅れる | コミット確認は`api.github.com`を使う |

---

## 7. データ設計で踏んだ地雷

| # | 地雷 | 深刻度 | 実際に起きたこと | 対策 |
|---|------|--------|----------------|------|
| 1 | **abs(FCF)** | 致命的 | `abs()`をつけたためマイナスFCF（赤字企業）が正の値になり、本来Dランクの銘柄がAランクと判定された | FCFの符号を保持する。`abs()`は絶対に使わない |
| 2 | **銘柄リストのハードコード** | 致命的 | 56銘柄をPython配列にハードコード→銘柄追加のたびにコード変更が必要。119銘柄に増えた時に更新漏れ | シートから動的取得する |
| 3 | **PEG < 0.5 のスコアが10点** | 高 | 閾値テーブルの設計ミスで、最も割安な銘柄（PEG=0.3）が最低スコアになった | 閾値テーブルは「低い方が良い」指標で`thr_low()`を別関数にする |
| 4 | **シート名の思い込み** | 中 | 存在しないシート名をコードに書いてエラー | 必ず`book.worksheets()`で実在確認してからアクセス |
| 5 | **3行構造のシート** | 中 | ヘッダー/サブヘッダー/データの3行構造で`rows[1:]`とすると、サブヘッダーがデータに混入 | `rows[2:]`が正しい。シート構造を必ず目視確認 |
| 6 | **APIキーのハードコード** | 高 | デバッグ中にAPIキーをソースコードに直書き→GitHubに公開 | 環境変数(`os.environ[]`)のみ使用。.envは.gitignoreに追加 |
| 7 | **キー名の不一致** | 中 | dict["vix"]で参照しているのにdict["VIX"]で格納→KeyError | 定数でキー名を管理。大文字小文字を統一 |

---

## 8. 環境変数テンプレート

```env
# .env（ローカル開発用）
JQUANTS_API_KEY=your_key
FRED_API_KEY=your_key
SPREADSHEET_ID=your_spreadsheet_id
GOOGLE_CREDENTIALS={"type":"service_account","project_id":"..."}
GITHUB_TOKEN=ghp_your_token
EDINET_API_KEY=your_key
PRICE_SOURCE=jquants   # jquants または yfinance

# GASスクリプトプロパティ（GAS管理画面で設定）
GITHUB_TOKEN=ghp_your_token
EDINET_API_KEY=your_key
CLAUDE_API_KEY=sk-ant-your_key
```

### GitHub Secrets に設定するもの
```
JQUANTS_API_KEY
FRED_API_KEY
SPREADSHEET_ID
GOOGLE_CREDENTIALS   ← JSONを1行化して設定
GITHUB_TOKEN         ← Classic PAT（repo + workflow スコープ）
```

---

## 9. Python依存パッケージ

```
# requirements.txt
gspread>=5.0
google-auth>=2.0
requests>=2.28
yfinance>=0.2.18
pandas>=1.5
numpy>=1.24

# オプション
scipy>=1.10        # 統計検定（バックテスト用）
```

---

## 10. APIキー取得手順

| API | 取得URL | 所要時間 | 備考 |
|-----|---------|---------|------|
| J-Quants | https://application.jpx-jquants.com/ | 即日 | メール認証→APIキー発行 |
| FRED | https://fred.stlouisfed.org/docs/api/api_key.html | 即日 | 無料アカウント作成のみ |
| EDINET | https://disclosure2dl.edinet-fsa.go.jp/guide/static/register | 即日 | 利用者登録 |
| Google Cloud | https://console.cloud.google.com/ | 即日 | サービスアカウント+JSONキー |
| Claude | https://console.anthropic.com/ | 即日 | クレジットカード登録必要 |
| GitHub | https://github.com/settings/tokens | 即日 | **Classicトークン推奨** |

---

## 11. ライセンス・利用規約

- **J-Quants**: 商用利用は要確認（JPX利用規約参照）
- **yfinance**: 非公式ライブラリ。Yahoo Finance利用規約に準拠。商用利用グレーゾーン
- **FRED**: 出典表示必須 `"Source: FRED, Federal Reserve Bank of St. Louis"`
- **EDINET**: 金融庁利用規約に準拠
- **Claude API**: Anthropic利用規約に準拠

---

## 12. 総括：開発で学んだ最重要教訓

1. **APIデータは必ず実データで確認** — 「たぶんこう返る」で実装すると必ずバグる
2. **シートから動的取得** — ハードコードは技術的負債の元凶
3. **フォールバックを必ず用意** — yfinanceが落ちてもJ-Quantsで、逆も然り
4. **Google Sheets APIのレート制限は60秒待機で回避** — リトライなしだと本番で落ちる
5. **GitHub ActionsのTZは初日に設定** — 後から直すと日付関連のバグが連鎖する
6. **git push前にpull --rebase** — 複数workflowが同じリポジトリにpushする場合は必須
7. **APIキーは1文字もソースに書かない** — 環境変数とGitHub Secrets/GASプロパティのみ
8. **abs()は金融データに使わない** — マイナスの意味がある数値を正にすると判断が逆転する
9. **Classicトークンを使う** — Fine-grainedはCORSでブラウザJSからブロックされる
10. **1年の株価予測は勝率50%** — 短期予測よりも長期ファンダメンタルに注力する方が有効

---

*Generated: 2026-03-27 | AI Investment System Build Guide v2.0*
*細矢AI投資判断システム開発チーム*

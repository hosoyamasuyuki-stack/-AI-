# AI Investment Decision System

Self-learning AI investment decision system targeting +3.9% annual excess return over Nikkei 225 (top 3-4% of Japanese investors). Manages 46 holdings + 27 watchlist stocks with automated scoring, macro analysis, and weekly full-market screening of ~3,800 Japanese stocks.

**Dashboard:** https://hosoyamasuyuki-stack.github.io/-AI-/ai_dashboard_v13.html

---

## Architecture

```
[J-Quants API] --> weekly_update.py ---------> [Google Spreadsheet]
[FRED API]     --> daily_update.py  ---------> [Google Spreadsheet]
[yfinance]     --> daily_price_update.py ----> [Google Spreadsheet]
[J-Quants API] --> full_scan.py (3,800 stocks) -> [Google Spreadsheet]
                                                       |
                                                       v
                                            generate_dashboard.py
                                                       |
                                                       v
                                            ai_dashboard_v13.html
                                                       |
                                                       v
                                              [GitHub Pages]

[Dashboard Button] --> GAS Proxy --> GitHub Actions --> manage_stock.py
                                                   --> full_update (4-step pipeline)
```

## Scoring Model (v4.3)

```
Total Score = Real ROIC (40%) x Trend (35%) x Price (25%)

Variable 1 - Real ROIC: ROE score (60%) + FCF conversion rate (40%)
Variable 2 - Trend:     ROE 3-4yr slope (60%) + FCR slope (40%)
Variable 3 - Price:     PEG score (50%) + FCF yield (50%)

Rank: S >= 80 / A >= 65 / B >= 50 / C < 50 / D = low
```

## File Structure

```
core/                        # Shared modules (config, auth, scoring, API)
  __init__.py
  config.py                  # Constants, thresholds, API endpoints
  auth.py                    # Google Sheets authentication
  scoring.py                 # safe(), thr_high(), thr_low(), slope_fn()
  api.py                     # get_price_jq(), get_fin_jq() (J-Quants V2)

.github/workflows/           # GitHub Actions automation (12 YAML files)

ai_dashboard_v13.html        # Main dashboard (GitHub Pages)
evidence_page.html           # Backtest results visualization
framework_page.html          # Investment framework explanation

generate_dashboard.py        # HTML generation from spreadsheet data
weekly_update.py             # Weekly full v4.3 score computation
daily_update.py              # Daily FRED 25 indicators + MacroPhase
daily_price_update.py        # Daily stock price + Variable 3 update
full_scan.py                 # Weekly scan of all ~3,800 listed stocks
manage_stock.py              # Add/remove/move stocks via dashboard

verify_0415.py               # 2026/04/15 STEP0 auto-verification
verify_monday.py             # Weekly Monday verification checks
backtest_H002_v1.py          # H002 Variable1 backtest (adopted)
backtest_H004_v1.py          # H004 Variable3 backtest (framework)
backtest_H004_v2.py          # H004 Variable3 backtest (production, adopted)
backtest_H005_v1.py          # H005-A MacroPhase GREEN strategy (rejected)
backtest_H005_v2.py          # H005-A 11 strategies exhaustive (VIX strategy adopted)
backtest_H005B_v1.py         # H005-B crash buying 5yr hold (adopted p=0.0035)

learning_batch_monthly.py    # Monthly batch for 99 learning stocks
sheet_manager.py             # Monthly SheetManagementLedger
record_changelog.py          # Change history recording
generate_handover.py         # Handover document generation

kenja.js                     # Deep Insight Analysis JS
gas_kenja_proxy.js           # GAS proxy for Claude API integration
gas_manage_stock_addition.js # GAS proxy for stock management

CLAUDE.md                    # AI development partner instructions
handover.txt                 # Lightweight handover (GitHub Pages)
handover_FINAL.txt           # Complete handover document
H004_complete_record.txt     # H004 backtest detailed record
```

## Automated Schedules (JST)

| Schedule | Script | Purpose |
|----------|--------|---------|
| Daily 7:00 | daily_update.py | FRED 25 indicators + MacroPhase 4-layer score |
| Daily 7:30 | daily_price_update.py | Stock prices + Variable 3 recalc |
| Mon 10:00 | weekly_update.py | Full v4.3 score (all 3 variables) |
| Mon 11:00 | verify_monday.py | Weekly verification checks |
| Sun 22:00 | full_scan.py | Full market scan (~3,800 stocks) -> Top 50 |
| 1st of month 9:00 | monthly_learning.py | 99 learning stocks monthly batch |
| 1st of month 9:30 | sheet_manager.py | SheetManagementLedger (staggered 30min after monthly_learning) |
| 2026/04/15 | verify_0415.py | STEP0 prediction verification |

## Setup

### 1. Clone and install
```bash
git clone https://github.com/hosoyamasuyuki-stack/-AI-.git
cd -AI-
pip install -r requirements.txt
```

### 2. Configure environment
```bash
cp .env.example .env
# Edit .env with your actual API keys (see .env.example for details)
```

### 3. GitHub Secrets (for Actions)
Set these in Settings > Secrets and variables > Actions:

| Secret | Purpose |
|--------|---------|
| GOOGLE_CREDENTIALS | Service account JSON for Google Sheets |
| SPREADSHEET_ID | Google Spreadsheet ID |
| JQUANTS_API_KEY | J-Quants V2 API key |
| FRED_API_KEY | FRED API key |
| EDINET_API_KEY | EDINET API key |
| GITHUB_TOKEN | Auto-provided by GitHub Actions |

### 4. Google Apps Script
The GAS proxy handles dashboard button actions (full update, stock management).
- Project: See CLAUDE.md for GAS project URL
- Script properties: GITHUB_TOKEN, EDINET_API_KEY

---

## ⚠️ API Key Management — Critical Checklist

**When J-Quants API key is reissued (expires or regenerated):**

```bash
# 1. Verify the new key works
curl -s -H "x-api-key: YOUR_NEW_KEY" "https://api.jquants.com/v2/fins/summary?code=72030"
# Should return JSON with financial data (not 403)

# 2. Update .env file
JQUANTS_API_KEY=YOUR_NEW_KEY

# 3. Update GitHub Secrets
# Settings > Secrets and variables > Actions > JQUANTS_API_KEY > Update
```

**MUST update ALL 3 locations simultaneously:**

| Location | Used by | How to update |
|----------|---------|---------------|
| `.env` (local) | Local scripts | Edit directly |
| GitHub Secrets: `JQUANTS_API_KEY` | All GitHub Actions | Settings > Secrets |
| J-Quants dashboard | Source of new key | jpx-jquants.com > マイページ |

**⚠️ Incident Record (2026/03/29):** Key was reissued via dashboard → GitHub Secrets not updated → full_scan failed for all 3,506 stocks (HTTP 403). This took 2 days to diagnose. **Always update Secrets immediately after reissuing.**

**Health check tool:**
```bash
python check_api_keys.py  # Checks all 7 keys + live connectivity test
```

**Other keys with multi-location management:**

| Key | .env | GitHub Secrets | GAS Script Properties |
|-----|------|----------------|----------------------|
| JQUANTS_API_KEY | ✓ | ✓ | — |
| FRED_API_KEY | ✓ | ✓ | — |
| GOOGLE_CREDENTIALS | ✓ | ✓ | — |
| GITHUB_TOKEN | ✓ | auto | ✓ |
| EDINET_API_KEY | ✓ | — | ✓ |
| OPENAI_API_KEY (kenja-rich-api) | — | — | ✓ |

---

## Technology Stack

- **Python 3.11** (GitHub Actions runtime)
- **Google Sheets API** via gspread (data storage)
- **J-Quants V2 API** (Japanese stock financial/price data)
- **FRED API** (25 US macro indicators)
- **yfinance** (real-time stock prices)
- **GitHub Pages** (dashboard hosting)
- **GitHub Actions** (automation/scheduling)
- **Google Apps Script** (serverless proxy)

## Hypothesis Registry

| ID | Hypothesis | Status |
|----|-----------|--------|
| H001 | 3-variable scoring model | Adopted (+4.46%/yr) |
| H002 | Variable 1 (Real ROIC) | Verified |
| H003 | Variable 2 (Trend) | Rejected (reverses in V-recovery) |
| H004 | Variable 3 (Price) | Conditionally adopted (+9.13%/yr, p=0.0321) |
| H005-A | MacroPhase timing (11 strategies) | Mostly rejected. Only H adopted: VIX>=30 cash-out (+4.76%/yr, p=0.0022) |
| H005-B | Crash buying (VIX>=30, 5yr hold) | Adopted: PANIC +21.81%/yr vs CALM +13.01%/yr, diff +8.80%, p=0.0035 |
| H006 | STEP0 prediction record | Pending (2026/04/15) |

## Backtest Methodology

- Survivorship bias removed
- Walk-forward 5-window validation (2017-2024)
- Bonferroni correction (alpha = 0.025)
- Transaction costs: round-trip 0.4% + tax 20.315%
- Minimum sample: n >= 84, at least 3 periods
- Rejection criteria: p > 0.05 OR excess < +3.9%/yr OR 3+ losses in 5 windows

## License

Private repository. All rights reserved.

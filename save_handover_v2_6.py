# save_handover_v2_6.py
# 【最後のフル版引き継ぎ書】次回からはChangeLog差分方式に移行
#
# Colabで実行手順:
#   from google.colab import auth
#   auth.authenticate_user()
# 上記を実行後、このスクリプト全体を貼り付けて実行

import gspread
from google.auth import default

creds, _ = default()
gc = gspread.authorize(creds)
SPREADSHEET_ID = '1GtlVhGcPjMU0pJWsijwnmTe1rFJXAGvkaJFjav9gGcE'
ss = gc.open_by_key(SPREADSHEET_ID)
print("OK: " + ss.title)

lines = [
    "=" * 64,
    "AI Investment System Handover v2.6",
    "Date: 2026/03/24",
    "Updates: MacroPhase 4-layer GREEN/YELLOW/RED implementation",
    "Note: LAST full-format handover. v2.7+ = ChangeLog diff only.",
    "=" * 64,
    "",
    "[ALERT 1] 3-year holding is statistically optimal (H001-C +4.46%/yr)",
    "[ALERT 2] J-Quants Standard / /v2/equities/bars/daily / YYYYMMDD / data[AdjC]",
    "[ALERT 3] Stop immediately when Hosoyama points out the original purpose",
    "[ALERT 4] Before backtest: 3Y window? PHASE1-2-3? Rejection criteria defined?",
    "[ALERT 5] Confirm sheet names from CODE before stating them (Bug35 lesson)",
    "[ALERT 6] MacroPhase sheet = Group B permanent. Never delete.",
    "",
    "[SECTION 1] Basic Info",
    "SpreadsheetID : 1GtlVhGcPjMU0pJWsijwnmTe1rFJXAGvkaJFjav9gGcE",
    "GitHub        : https://github.com/hosoyamasuyuki-stack/-AI-",
    "Dashboard     : https://hosoyamasuyuki-stack.github.io/-AI-/ai_dashboard_v12_edinet.html",
    "",
    "[GOAL - confirmed 2026/03/24, all 5 members agreed]",
    "Nikkei225 annual excess +3.9% or more = top 3-4% of Japanese investors",
    "= +7.8M yen/year excess on 200M yen assets",
    "Mission: Protect and grow top-3% assets with top-3% management",
    "",
    "[SECTION 2] API Keys",
    "J-Quants : 7bEWg3-b2MPc0DWG1vjSugW48LahAiVi622Nxy8S7PA (Standard 3300yen/month)",
    "FRED     : 467c035b9ae8a723c2b9ee2184a22522",
    "EDINET   : c04000e8425241a38eb3e695d5eca188",
    "GAS URL  : https://script.google.com/macros/s/AKfycby8lU6RV2WafwWJKcof0FFRRWGGGRIgRequ54rlp00HYTWwYL3Iefoy_eTXFlhwWDyS/exec",
    "",
    "[SECTION 3] H001-C Backtest (confirmed 2026/03/22-23)",
    "3Y holding: ADOPTED  +4.46%/year (threshold +3.9%) ACHIEVED",
    "5Y holding: rejected +2.41%/year",
    "7Y holding: rejected +1.77%/year",
    "",
    "[SECTION 4] Sheet Groups (2026/03/24)",
    "Group B - Permanent (11 sheets, DO NOT DELETE)",
    "  DesignLogic_permanent / StatsProcedure_permanent / HypothesisLog",
    "  H001C_3Y5Y7Yholding / Handover_v2.6 / ThinkingProcess_DesignDecisions",
    "  v4.3DesignRecord / StockMaster / EDINETscore / Settings",
    "  MacroPhase (NEW: daily 4-layer score log)",
    "",
    "Group A - Active (36 sheets, DO NOT DELETE)",
    "  Macro: VIX/HYspread/TEDspread/USDJPY/DXY/LongShortSpread",
    "         US10Y/IGspread/WTI/Gold/USM2/JapanM2/EuroM3/FRBbalance",
    "         USCPI/USPCE/USUnemployment/USRetail/USIndustrialProd",
    "         USCapacityUtilization/USHousing/USDurable/USConsumerConf",
    "         ISMPMI/USMonetaryBase/Nikkei225/TOPIX/SP500/SOX/Russell2000",
    "         ShillerPER/AnomalyScore",
    "  Weekly: CoreScan_v4.3/IntegratedScore_weekly/WeeklySignal",
    "          FactorDecayCheck/IndexForecastLog/WorkLog",
    "  Real:   HoldingStocks_v4.3/WatchStocks_v4.3/ForecastRecord",
    "Group C - Delete recommended (~55 sheets, confirm with Hosoyama first)",
    "",
    "[SECTION 5] Automation Schedule",
    "Daily  07:00: daily_update.py (32 macro + MacroPhase 4-layer)",
    "Daily  07:30: daily_price_update.py",
    "Weekly Mon 10:00: weekly_update.py v4.2",
    "Weekly Mon 10:30: generate_dashboard.py v21 (MacroPhase gauge enabled)",
    "Weekly Mon 11:00: verify_monday.py",
    "Monthly 1st 09:00: sheet_manager.py / learning_batch_monthly.py",
    "2026/04/15 09:00: verify_0415.py v2 (one-time / fully automated)",
    "",
    "[SECTION 6] MacroPhase Implementation (NEW 2026/03/24)",
    "Purpose: WHEN to invest (timing) separate from WHAT to buy (score)",
    "Design : 4-layer 100pt -> GREEN(>=60) / YELLOW(30-59) / RED(<30)",
    "Layer A (40pt): VIX / HYspread / TEDspread / LongShortSpread",
    "Layer B (30pt): JapanM2 / FRBbalance",
    "Layer C (20pt): ISMPMI / USUnemployment",
    "Layer D (10pt): ShillerPER",
    "Sheet  : MacroPhase (auto-created by daily_update.py from tomorrow)",
    "Display: Dashboard top signal + reason + 4-layer bar (foldable)",
    "Current: RED (2026/03/24) VIX=26.78 / HYG down / Buffett=179%",
    "",
    "3 commits 2026/03/24:",
    "  f8cdf4e daily_update.py       +calc_macro_phase/+save_macro_phase",
    "  377d9b1 generate_dashboard.py +build_phase_gauge_html/+replace",
    "  a5895e0 ai_dashboard_v12.html +MACRO_PHASE_GAUGE anchor",
    "",
    "[SECTION 7] v4.3 Scoring",
    "Variable1 Real ROIC (40%) = ROEscore*60% + FCRscore*40%",
    "Variable2 Trend     (35%) = ROEtrend*60% + FCRtrend*40%",
    "Variable3 Price     (25%) = PEGscore*50% + FCFyield*50%",
    "Total = V1*0.40 + V2*0.35 + V3*0.25",
    "",
    "[SECTION 8] Next Session Priorities",
    "Priority1: 2026/03/30 verify_monday first result check",
    "Priority2: 2026/03/30 PBR check (1.76 / 4.8)",
    "Priority3: Setup ChangeLog format (Handover_Base + Handover_ChangeLog)",
    "Priority4: Delete Group C sheets (after Hosoyama confirmation)",
    "Priority5: H002 backtest (Variable1 only / 3Y / PHASE1-2-3)",
    "",
    "[SECTION 9] Handover Format Change (from v2.7)",
    "Old: 400-line Python, manual Colab each session",
    "New: Handover_Base (once) + Handover_ChangeLog (3 lines/session)",
    "     Handover_Auto = monthly auto by sheet_manager.py",
    "",
    "[SECTION 10] Hypothesis Status",
    "H001/H001-B: rejected / H001-C: 3Y ADOPTED(+4.46%)",
    "H002: pending (Variable1/3Y) / H003: pending (Variable2/3Y)",
    "H004: accumulating (Spring 2027) / H005,H006: rejected",
    "H007: planned (Moat: ROIC/GrossMargin/FCFconversion)",
    "",
    "[SECTION 11] Checklist",
    "Session start: Read 6 alerts / MacroPhase=RED / 3Y philosophy",
    "Session end  : Append Handover_ChangeLog 3 lines (from v2.7)",
    "Deadlines    : 2026/03/30 verify+PBR / 2026/04/15 STEP0 auto",
    "",
    "[SECTION 12] Final Check (2026/03/24)",
    "Statistician : MacroPhase 4-layer design CONFIRMED",
    "Investor     : RED=wait / score+phase 2-axis CONFIRMED",
    "Programmer   : 3 files committed / syntax OK CONFIRMED",
    "Beginner     : RED/YELLOW/GREEN signal clear CONFIRMED",
    "Maintenance  : MacroPhase=GroupB / daily auto CONFIRMED",
    "",
    "=" * 64,
    "v2.6 complete. Next -> ChangeLog 3-line format only.",
    "Top priority: 2026/03/30 verify_monday + PBR",
    "=" * 64,
]

SHEET_NAME = 'Handover_v2.6'
try:
    ss.del_worksheet(ss.worksheet(SHEET_NAME))
except Exception:
    pass

rows = [[i + 1, line] for i, line in enumerate(lines)]
ws = ss.add_worksheet(title=SHEET_NAME, rows=len(rows) + 10, cols=2)
ws.update('A1', [['No', 'Content']])
ws.update('A2', rows)

print("Saved: " + SHEET_NAME)
print("Lines: " + str(len(rows)))
print("Next session: ChangeLog 3-line format only!")

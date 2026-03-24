# create_handover_base.py
# Handover_Baseシートを作成する。一度だけ実行する。
# 内容が変わったときのみ再実行する。
#
# Colab実行手順:
#   from google.colab import auth
#   auth.authenticate_user()

import gspread
from google.auth import default

creds, _ = default()
gc = gspread.authorize(creds)
SPREADSHEET_ID = '1GtlVhGcPjMU0pJWsijwnmTe1rFJXAGvkaJFjav9gGcE'
ss = gc.open_by_key(SPREADSHEET_ID)
print("OK: " + ss.title)

lines = [
    "=" * 60,
    "AI Investment System -- Handover_Base",
    "STATIC INFO: Only update when fundamentals change.",
    "For recent changes -> read Handover_ChangeLog",
    "For monthly snapshot -> read Handover_Auto",
    "=" * 60,
    "",
    "[IDENTITY]",
    "System   : AI Investment Decision System",
    "Owner    : Hosoyama (long-term investor, 5Y horizon)",
    "Goal     : Nikkei225 excess +3.9%/yr = top 3-4% of JP investors",
    "Assets   : 200M yen -> +7.8M yen/yr excess target",
    "",
    "[CORE PHILOSOPHY]",
    "1Y win rate = 50% (coin flip) -> 3Y holding is optimal (H001-C)",
    "5Y holding: 88% of buy-signal stocks beat Nikkei",
    "H001-C confirmed: 3Y +4.46%/yr excess (threshold +3.9%) ADOPTED",
    "MacroPhase RED = wait / GREEN = invest (score + timing = 2-axis)",
    "",
    "[INFRASTRUCTURE]",
    "SpreadsheetID : 1GtlVhGcPjMU0pJWsijwnmTe1rFJXAGvkaJFjav9gGcE",
    "GitHub        : https://github.com/hosoyamasuyuki-stack/-AI-",
    "Dashboard     : https://hosoyamasuyuki-stack.github.io/-AI-/ai_dashboard_v12_edinet.html",
    "Colab         : https://colab.research.google.com (auth first)",
    "",
    "[API KEYS]",
    "J-Quants : 7bEWg3-b2MPc0DWG1vjSugW48LahAiVi622Nxy8S7PA (Standard)",
    "FRED     : 467c035b9ae8a723c2b9ee2184a22522",
    "EDINET   : c04000e8425241a38eb3e695d5eca188",
    "GAS URL  : https://script.google.com/macros/s/AKfycby8lU6RV2WafwWJKcof0FFRRWGGGRIgRequ54rlp00HYTWwYL3Iefoy_eTXFlhwWDyS/exec",
    "",
    "[SCORING v4.3]",
    "Variable1 Real ROIC (40%) = ROEscore*60% + FCRscore*40%",
    "Variable2 Trend     (35%) = ROEtrend*60% + FCRtrend*40%",
    "Variable3 Price     (25%) = PEGscore*50% + FCFyield*50%",
    "Total = V1*0.40 + V2*0.35 + V3*0.25",
    "Rank  : S(>=80) A(>=65) B(>=50) C(>=35) D(<35)",
    "",
    "[MACRO PHASE]",
    "4-layer 100pt: GREEN(>=60) / YELLOW(30-59) / RED(<30)",
    "Layer A (40pt): VIX / HYspread / TEDspread / LongShortSpread",
    "Layer B (30pt): JapanM2 / FRBbalance",
    "Layer C (20pt): ISMPMI / USUnemployment",
    "Layer D (10pt): ShillerPER",
    "Sheet: MacroPhase (daily auto-update by daily_update.py)",
    "",
    "[AUTOMATION]",
    "Daily  07:00: daily_update.py (32 macro + MacroPhase)",
    "Daily  07:30: daily_price_update.py (Variable3)",
    "Weekly Mon 10:00: weekly_update.py v4.2",
    "Weekly Mon 10:30: generate_dashboard.py v21",
    "Weekly Mon 11:00: verify_monday.py",
    "Monthly 1st 09:00: sheet_manager.py + learning_batch_monthly.py",
    "2026/04/15 09:00: verify_0415.py v2 (one-time)",
    "",
    "[STOCKS]",
    "Holdings : 46 stocks (HoldingStocks_v4.3)",
    "Watchlist: 73 stocks (WatchStocks_v4.3)",
    "Learning : 99 stocks (monthly batch, model accuracy only)",
    "Total    : 218 stocks tracked",
    "",
    "[PERMANENT SHEETS - NEVER DELETE]",
    "DesignLogic_permanent / StatsProcedure_permanent / HypothesisLog",
    "H001C_3Y5Y7Yholding / Handover_v2.6 / ThinkingProcess_DesignDecisions",
    "v4.3DesignRecord / StockMaster / EDINETscore / Settings / MacroPhase",
    "Handover_Base / Handover_ChangeLog / Handover_Auto",
    "",
    "[HANDOVER SYSTEM (from v2.7)]",
    "Handover_Base      : this sheet (static, update rarely)",
    "Handover_ChangeLog : auto-appended on every GitHub push",
    "Handover_Auto      : monthly snapshot by sheet_manager.py",
    "-> Session start: read ChangeLog for recent history",
    "-> Full context : read Base + ChangeLog + Auto",
    "",
    "[HYPOTHESIS STATUS]",
    "H001/H001-B: rejected",
    "H001-C     : 3Y ADOPTED +4.46%/yr",
    "H002       : pending (Variable1 only / 3Y)",
    "H003       : pending (Variable2 / 3Y)",
    "H004       : accumulating (rank momentum / Spring 2027)",
    "H005,H006  : rejected",
    "H007       : planned (Moat: ROIC/GrossMargin/FCFconversion)",
    "",
    "[KEY ALERTS - READ EVERY SESSION]",
    "ALERT1: 3Y holding optimal (H001-C)",
    "ALERT2: J-Quants /v2/equities/bars/daily / YYYYMMDD / data[AdjC]",
    "ALERT3: Stop when Hosoyama points out original purpose",
    "ALERT4: Before backtest: 3Y? PHASE1-2-3? Rejection criteria?",
    "ALERT5: Confirm sheet names from CODE before stating",
    "ALERT6: MacroPhase = Group B permanent. Never delete.",
    "",
    "=" * 60,
    "End of Handover_Base. Check ChangeLog for recent updates.",
    "=" * 60,
]

SHEET = 'Handover_Base'
try:
    ss.del_worksheet(ss.worksheet(SHEET))
except Exception:
    pass
ws = ss.add_worksheet(title=SHEET, rows=len(lines)+10, cols=2)
ws.update('A1', [['No', 'Content']])
ws.update('A2', [[i+1, l] for i, l in enumerate(lines)])
print(f"Saved: {SHEET} ({len(lines)} lines)")
print("This is the STATIC base. Update only when fundamentals change.")

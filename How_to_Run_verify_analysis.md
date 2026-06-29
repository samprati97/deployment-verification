# AdServer Release Verification — User Guide
 
---
 
## How to Start
 
Type either of these phrases in chat to begin:
 
> **`start verification`** &nbsp;or&nbsp; **`start new verification`**
 
Claude will take it from there.
 
---
 
## What Happens When You Trigger It
 
### Step 1 — Attach the CSV
Claude will ask you to attach the data file. Export your query results from Athena/Presto and attach the CSV directly in the chat.
 
**How to export from Athena/Presto:**
- Run the SQL query from `general_verification_automation-instructions.txt`
- Export the result as a **UTF-16, tab-separated CSV**
- Run the export after the release has been live for at least **1–2 hours**
### Step 2 — Claude reads your dates
Once the file is attached, Claude reads the available dates from the CSV and asks you to configure the run interactively — the same 7 prompts the script uses:
 
| Prompt | What to enter |
|--------|--------------|
| Deployment date | Select the release day from the numbered list |
| Comparison date | Select the baseline day (usually previous day) |
| Deployment hour | 24-hour ET, e.g. `6` for 6:00 AM |
| Exclude last hour | Press Enter for Yes (recommended) |
| AWS Region | Press Enter for both EAST + WEST (recommended) |
| Environment | Press Enter for Production (recommended) |
| Significance threshold | Press Enter for 10% (recommended) |
 
### Step 3 — Review & confirm
The script shows a summary of the exact PRE and POST windows before doing any work. Type `Y` to proceed, `R` to re-enter settings, or `N` to exit.
 
### Step 4 — Get your PDF
The report is saved automatically as:
```
Release_Verification_Report_YYYY-MM-DD_v3.pdf
```
A typical run takes **30–60 seconds**.
 
---
 
## Reading the Report
 
| Section | What it shows |
|---------|--------------|
| **Page 1 — Summary** | Badge counts (release-caused drops / pre-existing / increases) + overall metrics table |
| **Page 2 — Drop Tables** | ⚠️ Release-caused drops and ℹ️ pre-existing trend drops |
| **Chart Pages** | Hourly blue/red charts for each release-caused drop. Vertical line = deployment hour |
| **Increases Page** | 🟢 Metrics/rates that improved ≥10% post-release |
 
**On the charts:** Grey line = previous day. Blue = today OK. Red = today dropped >10% vs previous day.
Rate KPI deltas are shown in **pp (percentage points)**.
 
---
 
## Decision Guide
 
| Result | Action |
|--------|--------|
| Release-caused drops = 0 | ✅ Release is clean |
| Pre-existing drops only | ℹ️ Not release-caused — monitor trend |
| Release-caused drops > 0, drop starts **after** deployment line, >10% | 🚨 Escalate per rollback process |
| Drop starts **before** deployment line | ℹ️ Organic trend — not release-caused |
 
---
 
## Metrics & Rates Reference
 
**Metrics:** `publisher_requests`, `throttled_requests`, `delivery_requests`, `responses`, `wins`, `impressions`, `clicks`, `cost`, `revenue`, `video_impressions`, `video_completes`, `profits`
 
**Derived Rates:**
- `throttling_rate` = throttled_requests / publisher_requests
- `response_rate` = responses / delivery_requests
- `win_rate` = wins / responses
- `impression_rate` = impressions / wins
- `ctr` = clicks / impressions
- `margin` = profits / revenue
- `video_completion_rate` = video_completes / video_impressions
**Dimensions analyzed:** `delivery_type` × `demand_type_name` × `line_item_bonus_paid`
 
---
 
## Quick Checklist — Every Release
 
- [ ] Export CSV from Athena/Presto (wait ≥1–2 hrs after release goes live)
- [ ] Type **`start verification`** in chat
- [ ] Attach the CSV when prompted
- [ ] Answer the 7 configuration prompts (defaults are safe for most releases)
- [ ] Verify PRE/POST windows in the confirmation summary → confirm **Y**
- [ ] Open the PDF → check badge counts on page 1
- [ ] If release-caused drops > 0 → review charts → escalate if red starts after deployment line
- [ ] Share PDF for release sign-off
---
 
## Claude Workflow — What Claude Does on Trigger
 
When you type `start verification` or `start new verification`, Claude will:
 
1. Ask you to attach the data CSV in the chat
2. Read the available dates from the CSV
3. **Present each of the 7 configuration prompts as interactive multiple-choice questions** (using the `AskUserQuestion` tool), one group at a time — never as a plain text table
4. Show a confirmation summary of the PRE/POST windows and ask Y / R / N before running
5. Copy the uploaded file to the working directory
6. Install required Python packages if not already present
7. Run `verify_analysis.py` in **CLI mode**, passing all confirmed settings as arguments (no manual stdin interaction)
8. Save the PDF report to the `Adserver Verification` folder
9. Present the PDF for download
> **IMPORTANT — Interactive prompt rule:** Claude must **always** use `AskUserQuestion` interactive prompts for each configuration step. Never show a static table and ask the user to type all answers at once. Each prompt (or logical group of 2) should be its own `AskUserQuestion` call with clearly labelled options and recommended defaults marked.
 
> **Note:** Claude handles all file paths automatically — you never need to edit the script or move files manually.
 
---
 
## Prerequisites (one-time setup)
 
Python 3.8+ and the following packages:
 
```bash
pip install pandas numpy matplotlib reportlab --break-system-packages
```
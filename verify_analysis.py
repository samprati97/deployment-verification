#!/usr/bin/env python3
"""
AdServer Release Verification — v3
Adds hourly blue/red charts for each post-release drop.
Interactive configuration with confirmation step.
"""
 
import sys
import argparse
import pandas as pd
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
from matplotlib.lines import Line2D
import io, os, tempfile
 
from reportlab.lib.pagesizes import landscape, A4
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    PageBreak, HRFlowable, Image as RLImage, KeepTogether
)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
from reportlab.lib.units import inch
from reportlab.lib.enums import TA_CENTER
import warnings
warnings.filterwarnings("ignore")
 
# ──────────────────────────────────────────────────────────────────────────────
# CONFIGURATION  (interactive prompts OR CLI arguments)
# ──────────────────────────────────────────────────────────────────────────────
# Default CSV location — edit this if your file is elsewhere
_DEFAULT_CSV = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "General Verification Data.csv")
 
def _parse_args():
    p = argparse.ArgumentParser(description="AdServer Release Verification")
    p.add_argument("--csv",             default=None,  help="Path to data CSV (skips interactive prompt)")
    p.add_argument("--out",             default=None,  help="Output PDF path (optional)")
    p.add_argument("--release-date",    default=None,  dest="release_date")
    p.add_argument("--compare-date",    default=None,  dest="compare_date")
    p.add_argument("--hour",            default=None,  type=int)
    p.add_argument("--no-exclude-last", dest="exclude_last", action="store_false", default=True)
    p.add_argument("--region",          default="BOTH", choices=["BOTH","EAST","WEST"])
    p.add_argument("--env",             default="Production", choices=["Production","Canary","Both"])
    p.add_argument("--threshold",       default=0.10,  type=float)
    return p.parse_args()
 
_args = _parse_args()
 
# ── Determine CSV path ────────────────────────────────────────────────────────
CSV_PATH = _args.csv or _DEFAULT_CSV
 
# ── CLI mode (all required args supplied) vs Interactive mode ─────────────────
_CLI_MODE = all([_args.release_date, _args.compare_date, _args.hour is not None])
 
if _CLI_MODE:
    RELEASE_DATE    = _args.release_date
    COMPARE_DATE    = _args.compare_date
    RELEASE_HOUR    = _args.hour
    EXCLUDE_LAST_HR = _args.exclude_last
    REGION_FILTER   = None if _args.region == "BOTH" else _args.region
    REGION_LABEL    = "EAST + WEST" if _args.region == "BOTH" else _args.region
    ENV_FILTER      = None if _args.env == "Both" else _args.env
    DROP_THRESHOLD  = _args.threshold
    RISE_THRESHOLD  = _args.threshold
    OUT_PATH        = _args.out or os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        f"Release_Verification_Report_{RELEASE_DATE}_v3.pdf")
else:
    # ── Interactive configuration ─────────────────────────────────────────────
    def get_user_config():
        while True:
            print("\n" + "="*62)
            print("   AdServer Release Verification — Configuration")
            print("="*62)
 
            # ── Step 0: CSV file path ──────────────────────────────────────
            print("\nStep 1 of 7 — Data File")
            print(f"  Default location: {_DEFAULT_CSV}")
            raw = input(
                "\n  Press Enter to use the default file, or paste the full path to a new CSV: "
            ).strip()
            csv_path = raw if raw else _DEFAULT_CSV
            if not os.path.exists(csv_path):
                print(f"\n  ⚠  File not found: {csv_path}")
                print("     Check the path and try again.")
                continue
 
            print(f"\nReading available dates from:\n  {csv_path}")
            try:
                sample = pd.read_csv(csv_path, encoding='utf-16', sep='\t', usecols=["Date Hour"])
                sample = sample.rename(columns={"Date Hour": "date_hour"})
                sample["date_hour"] = pd.to_datetime(sample["date_hour"].astype(str).str.strip(), errors='coerce')
                dates = sorted(sample["date_hour"].dropna().dt.strftime("%Y-%m-%d").unique())
            except Exception as e:
                print(f"\n  ERROR reading CSV: {e}")
                sys.exit(1)
            if not dates:
                print("\n  ERROR: No valid date_hour data found in CSV.")
                sys.exit(1)
            print(f"\nAvailable dates in the file ({len(dates)} found):")
            for i, d in enumerate(dates, 1):
                print(f"  [{i}]  {d}")
 
            print("\nStep 2 of 7 — Deployment Date")
            while True:
                raw = input("\nSelect DEPLOYMENT date number: ").strip()
                if raw.isdigit() and 1 <= int(raw) <= len(dates):
                    release_date = dates[int(raw) - 1]; break
                print(f"  ⚠  Please enter a number between 1 and {len(dates)}.")
 
            print("\nStep 3 of 7 — Comparison (Baseline) Date")
            while True:
                raw = input("Select COMPARISON (baseline) date number: ").strip()
                if raw.isdigit() and 1 <= int(raw) <= len(dates):
                    compare_date = dates[int(raw) - 1]
                    if compare_date == release_date:
                        print("  ⚠  Comparison date must be different from deployment date.")
                        continue
                    break
                print(f"  ⚠  Please enter a number between 1 and {len(dates)}.")
 
            print("\nStep 4 of 7 — Deployment Hour")
            while True:
                raw = input("Enter DEPLOYMENT HOUR (0–23, e.g. 6 for 6:00 AM ET): ").strip()
                if raw.isdigit() and 0 <= int(raw) <= 23:
                    release_hour = int(raw); break
                print("  ⚠  Please enter an integer between 0 and 23.")
 
            print("\nStep 5 of 7 — Exclude Last Hour")
            while True:
                raw = input("Exclude last (potentially incomplete) hour of data? [Y/n]: ").strip().upper()
                if raw in ("", "Y"): exclude_last = True;  break
                if raw == "N":       exclude_last = False; break
                print("  ⚠  Enter Y or N.")
 
            print("\nStep 6 of 7 — AWS Region")
            print("  [1]  Both EAST and WEST  ← Recommended")
            print("  [2]  EAST only")
            print("  [3]  WEST only")
            while True:
                raw = input("\nSelect region (press Enter for [1]): ").strip()
                if raw in ("", "1"): region = None;   region_label = "EAST + WEST"; break
                if raw == "2":       region = "EAST"; region_label = "EAST";        break
                if raw == "3":       region = "WEST"; region_label = "WEST";        break
                print("  ⚠  Please enter 1, 2, or 3.")
 
            print("\nStep 7 of 7 — Environment")
            print("  [1]  Production only  ← Recommended")
            print("  [2]  Canary only")
            print("  [3]  Both")
            while True:
                raw = input("\nSelect environment (press Enter for [1]): ").strip()
                if raw in ("", "1"): env = "Production"; break
                if raw == "2":       env = "Canary";     break
                if raw == "3":       env = None;         break
                print("  ⚠  Please enter 1, 2, or 3.")
 
            print("\nSignificance threshold:")
            print("  [1]  5%   ← Sensitive")
            print("  [2]  10%  ← Recommended")
            print("  [3]  15%  ← Conservative")
            while True:
                raw = input("\nSelect threshold (press Enter for [2]): ").strip()
                if raw in ("", "2"): threshold = 0.10; threshold_label = "10%"; break
                if raw == "1":       threshold = 0.05; threshold_label = "5%";  break
                if raw == "3":       threshold = 0.15; threshold_label = "15%"; break
                print("  ⚠  Please enter 1, 2, or 3.")
 
            try:
                hrs_df = pd.read_csv(csv_path, encoding='utf-16', sep='\t', usecols=["Date Hour"])
                hrs_df = hrs_df.rename(columns={"Date Hour": "date_hour"})
                hrs_df["date_hour"] = pd.to_datetime(hrs_df["date_hour"].astype(str).str.strip(), errors='coerce')
                hrs_df = hrs_df.dropna(subset=["date_hour"]) # Drop the trailing NaN
                hrs_df["date_str"]  = hrs_df["date_hour"].dt.strftime("%Y-%m-%d")
                hrs_df["hour"]      = hrs_df["date_hour"].dt.hour
                rel_hours = hrs_df[hrs_df["date_str"] == release_date]["hour"]
                raw_max   = int(rel_hours.max()) if not rel_hours.empty else 23
            except Exception:
                raw_max = 23
 
            post_end = (raw_max - 1) if exclude_last else raw_max
            pre_end  = release_hour - 1
 
            print("\n" + "="*62)
            print("   VERIFICATION CONFIGURATION — Please Confirm")
            print("="*62)
            print(f"  Deployment Date    :  {release_date}")
            print(f"  Comparison Date    :  {compare_date}")
            print(f"  Deployment Hour    :  {release_hour:02d}:00 ET")
            print(f"  Environment        :  {env or 'All (Canary + Production)'}")
            print(f"  AWS Region         :  {region_label}")
            print(f"  Exclude Last Hour  :  {'Yes' if exclude_last else 'No'}")
            print(f"  Significance Threshold :  {threshold_label}")
            print()
            if release_hour > 0:
                print(f"  PRE-RELEASE  window :  {release_date}  00:00 – {pre_end:02d}:59 ET")
                print(f"               vs       {compare_date}  00:00 – {pre_end:02d}:59 ET")
            else:
                print("  PRE-RELEASE  window :  (none — deployment at midnight)")
            print(f"  POST-RELEASE window :  {release_date}  {release_hour:02d}:00 – {post_end:02d}:59 ET")
            print(f"               vs       {compare_date}  {release_hour:02d}:00 – {post_end:02d}:59 ET")
            print("="*62)
 
            answer = input("\nProceed?  [Y = yes  /  N = exit  /  R = re-enter]:  ").strip().upper()
            if answer in ("Y", ""):
                return dict(
                    CSV_PATH=csv_path,
                    RELEASE_DATE=release_date, COMPARE_DATE=compare_date,
                    RELEASE_HOUR=release_hour, EXCLUDE_LAST_HR=exclude_last,
                    REGION_FILTER=region, REGION_LABEL=region_label,
                    ENV_FILTER=env, THRESHOLD=threshold,
                )
            elif answer == "N":
                print("\nExiting — no report generated.")
                sys.exit(0)
            else:
                print("\n↩  Re-entering configuration …\n")
 
    cfg = get_user_config()
    CSV_PATH        = cfg["CSV_PATH"]
    RELEASE_DATE    = cfg["RELEASE_DATE"]
    COMPARE_DATE    = cfg["COMPARE_DATE"]
    RELEASE_HOUR    = cfg["RELEASE_HOUR"]
    EXCLUDE_LAST_HR = cfg["EXCLUDE_LAST_HR"]
    REGION_FILTER   = cfg["REGION_FILTER"]
    REGION_LABEL    = cfg["REGION_LABEL"]
    ENV_FILTER      = cfg["ENV_FILTER"]
    DROP_THRESHOLD  = cfg["THRESHOLD"]
    RISE_THRESHOLD  = cfg["THRESHOLD"]
    OUT_PATH        = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        f"Release_Verification_Report_{RELEASE_DATE}_v3.pdf")
 
DIMENSIONS  = ["delivery_type", "demand_type_name", "line_item_bonus_paid"]
METRICS     = ["publisher_requests","throttled_requests","delivery_requests",
               "responses","impressions","wins","clicks",
               "cost","revenue","video_impressions","video_completes"]
ALL_KPIS    = METRICS + ["profits","throttling_rate","response_rate","win_rate",
                          "impression_rate","ctr","margin","video_completion_rate"]
HEADLINE_KPIS = ["impressions","wins","responses","clicks","revenue","cost","profits",
                 "margin","response_rate","win_rate","impression_rate","ctr","video_completion_rate"]
 
RATE_KPIS = {"throttling_rate","response_rate","win_rate","impression_rate",
             "ctr","margin","video_completion_rate"}
 
TMP_DIR = tempfile.mkdtemp()
 
# Human-readable labels (used in PDF)
env_label    = ENV_FILTER or "All"
region_label = REGION_LABEL
 
# Short date labels for column headers (MM/DD)
rel_lbl  = pd.Timestamp(RELEASE_DATE).strftime("%-m/%-d")
comp_lbl = pd.Timestamp(COMPARE_DATE).strftime("%-m/%-d")
 
# ──────────────────────────────────────────────────────────────────────────────
# 1. LOAD & FILTER
# ──────────────────────────────────────────────────────────────────────────────
print("\nLoading …")
df = pd.read_csv(CSV_PATH, encoding='utf-16', sep='\t')
df.columns = (df.columns.str.strip().str.lower()
              .str.replace('"', '', regex=False)
              .str.replace(' ', '_', regex=False)
              .str.replace('?', '', regex=False))
df = df.rename(columns={
    'demand_type':    'demand_type_name',
    'bonus_or_paid':  'line_item_bonus_paid',
})

# --- DATA CLEANING FIX ---
# Coerce invalid/empty dates to NaT, then drop those completely corrupt rows.
df["date_hour"] = pd.to_datetime(df["date_hour"].astype(str).str.strip(), errors='coerce')
df = df.dropna(subset=["date_hour"])

df["date_str"]  = df["date_hour"].dt.strftime("%Y-%m-%d")
# Force the hour column to be an integer so it never gets interpreted as a float!
df["hour"]      = df["date_hour"].dt.hour.astype(int)

for c in df.select_dtypes("object").columns:
    df[c] = df[c].str.strip().str.replace('"','', regex=False)
for col in METRICS:
    df[col] = df[col].astype(str).str.replace(',', '', regex=False)
    df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)
 
if ENV_FILTER:
    df = df[df["is_canary"] == ENV_FILTER]
if REGION_FILTER:
    df = df[df["aws_region"] == REGION_FILTER]
if EXCLUDE_LAST_HR:
    max_hr = int(df[df["date_str"]==RELEASE_DATE]["hour"].max())
    df = df[~((df["date_str"]==RELEASE_DATE)&(df["hour"]==max_hr))]
    print(f" Excluded hour {max_hr:02d}:00 on release day")
 
# ──────────────────────────────────────────────────────────────────────────────
# 2. WINDOWS
# ──────────────────────────────────────────────────────────────────────────────
rel  = df[df["date_str"]==RELEASE_DATE].copy()
comp = df[df["date_str"]==COMPARE_DATE].copy()

# Because we forced df["hour"] to int earlier, max_rel_hour is guaranteed to be an int
max_rel_hour = int(rel["hour"].max()) if not rel.empty else 23
 
rel_post   = rel[rel["hour"] >= RELEASE_HOUR]
comp_post  = comp[(comp["hour"] >= RELEASE_HOUR) & (comp["hour"] <= max_rel_hour)]
rel_pre    = rel[rel["hour"] < RELEASE_HOUR]
comp_pre   = comp[comp["hour"] < RELEASE_HOUR]
 
# ──────────────────────────────────────────────────────────────────────────────
# 3. AGG + RATES
# ──────────────────────────────────────────────────────────────────────────────
def agg(frame):
    return frame.groupby(DIMENSIONS)[METRICS].sum().reset_index()
 
def add_rates(g):
    g = g.copy(); eps=1e-9
    g["profits"]               = g["revenue"] - g["cost"]
    g["throttling_rate"]       = np.where(g["publisher_requests"]>0, g["throttled_requests"]/(g["publisher_requests"]+eps), np.nan)
    g["response_rate"]         = np.where(g["delivery_requests"]>0,  g["responses"]/(g["delivery_requests"]+eps), np.nan)
    g["win_rate"]              = np.where(g["responses"]>0,          g["wins"]/(g["responses"]+eps), np.nan)
    g["impression_rate"]       = np.where(g["wins"]>0,               g["impressions"]/(g["wins"]+eps), np.nan)
    g["ctr"]                   = np.where(g["impressions"]>0,        g["clicks"]/(g["impressions"]+eps), np.nan)
    g["margin"]                = np.where(g["revenue"]>0,            g["profits"]/(g["revenue"]+eps), np.nan)
    g["video_completion_rate"] = np.where(g["video_impressions"]>0, g["video_completes"]/(g["video_impressions"]+eps), np.nan)
    return g
 
rp_agg   = add_rates(agg(rel_post))
cp_agg   = add_rates(agg(comp_post))
rpre_agg = add_rates(agg(rel_pre))
cpre_agg = add_rates(agg(comp_pre))
 
def merge_diff(td, yd):
    m = td.merge(yd, on=DIMENSIONS, suffixes=("_t","_y"), how="outer")
    for kpi in ALL_KPIS:
        tc,yc = f"{kpi}_t",f"{kpi}_y"
        if tc not in m.columns: m[tc]=np.nan
        if yc not in m.columns: m[yc]=np.nan
        m[f"{kpi}_delta"] = m[tc]-m[yc]
        m[f"{kpi}_pct"]   = np.where(m[yc].abs()>1e-6,(m[tc]-m[yc])/m[yc].abs()*100,np.nan)
    return m
 
post_diff = merge_diff(rp_agg, cp_agg)
pre_diff  = merge_diff(rpre_agg, cpre_agg)
pre_diff_indexed = pre_diff.set_index(DIMENSIONS)
 
# ──────────────────────────────────────────────────────────────────────────────
# 4. FLAG DROPS / INCREASES
# ──────────────────────────────────────────────────────────────────────────────
drops_release=[]; drops_trend=[]; increases=[]; pre_drops_all=[]
 
for _, row in post_diff.iterrows():
    dim_key  = tuple(row[d] for d in DIMENSIONS)
    dim_dict = {d: row[d] for d in DIMENSIONS}
    for kpi in HEADLINE_KPIS:
        pct   = row.get(f"{kpi}_pct", np.nan)
        t_val = row.get(f"{kpi}_t", np.nan)
        y_val = row.get(f"{kpi}_y", np.nan)
        delta = row.get(f"{kpi}_delta", np.nan)
        if pd.isna(pct): continue
        rec = {**dim_dict,"kpi":kpi,"today":t_val,"yesterday":y_val,"delta":delta,"pct":pct}
        if pct <= -DROP_THRESHOLD*100:
            pre_pct=np.nan
            try:
                pr = pre_diff_indexed.loc[dim_key]
                pre_pct = pr[f"{kpi}_pct"]
            except: pass
            if not pd.isna(pre_pct) and pre_pct <= -DROP_THRESHOLD*100:
                drops_trend.append({**rec,"pre_pct":pre_pct})
            else:
                drops_release.append({**rec,"pre_pct":pre_pct})
        elif pct >= RISE_THRESHOLD*100:
            increases.append(rec)
 
for _, row in pre_diff.iterrows():
    dim_dict={d:row[d] for d in DIMENSIONS}
    for kpi in HEADLINE_KPIS:
        pct=row.get(f"{kpi}_pct",np.nan); t=row.get(f"{kpi}_t",np.nan)
        y=row.get(f"{kpi}_y",np.nan); d2=row.get(f"{kpi}_delta",np.nan)
        if pd.isna(pct): continue
        if pct<=-DROP_THRESHOLD*100:
            pre_drops_all.append({**dim_dict,"kpi":kpi,"today":t,"yesterday":y,"delta":d2,"pct":pct})
 
df_drops_rel   = pd.DataFrame(drops_release).sort_values("pct")  if drops_release else pd.DataFrame()
df_drops_trend = pd.DataFrame(drops_trend).sort_values("pct")    if drops_trend  else pd.DataFrame()
df_inc         = pd.DataFrame(increases).sort_values("pct",ascending=False) if increases else pd.DataFrame()
df_pre_drops   = pd.DataFrame(pre_drops_all).sort_values("pct")  if pre_drops_all else pd.DataFrame()
 
print(f"  Release-caused drops: {len(df_drops_rel)}")
print(f"  Pre-existing drops:   {len(df_drops_trend)}")
print(f"  Increases:            {len(df_inc)}")
 
# ──────────────────────────────────────────────────────────────────────────────
# 5. HOURLY DATA (for charts)
# ──────────────────────────────────────────────────────────────────────────────
def get_hourly(frame, kpi):
    """Aggregate KPI by hour for a subset dataframe."""
    grp = frame.groupby("hour")[METRICS].sum().reset_index()
    grp = add_rates(grp)
    return grp.set_index("hour")[kpi].to_dict()
 
# ──────────────────────────────────────────────────────────────────────────────
# 6. CHART GENERATOR
# ──────────────────────────────────────────────────────────────────────────────
BLUE  = "#4472C4"
RED   = "#C0392B"
GREY  = "#888888"
PINK  = "#C0426A"
 
def fmt_k(v):
    """Format value for Y-axis tick labels (non-rate KPIs)."""
    if abs(v) >= 1_000_000: return f"{v/1_000_000:.1f}M"
    if abs(v) >= 1_000:     return f"{v/1_000:.0f}K"
    return f"{v:.3f}" if abs(v) < 10 else f"{v:.1f}"
 
def make_chart(delivery_type, demand_type_name, line_item_bonus_paid, kpi,
               rel_data, comp_data,
               release_hour=None, threshold=DROP_THRESHOLD):
    """
    Create a matplotlib figure matching the provided screenshot style.
    rel_data / comp_data: subsets of df for release/compare day, pre-filtered by dims + env.
    Returns path to saved PNG.
    """
    if release_hour is None:
        release_hour = RELEASE_HOUR
 
    is_rate  = kpi in RATE_KPIS
    is_money = kpi in ("revenue","cost","profits")
 
    # Get hourly series for this dim combo
    def hourly_for_dim(frame):
        sub = frame[
            (frame["delivery_type"]==delivery_type) &
            (frame["demand_type_name"]==demand_type_name) &
            (frame["line_item_bonus_paid"]==line_item_bonus_paid)
        ]
        return get_hourly(sub, kpi)
 
    rel_hourly  = hourly_for_dim(rel_data)
    comp_hourly = hourly_for_dim(comp_data)
 
    if not rel_hourly and not comp_hourly:
        return None
 
    # Scale rates to percentage (0.72 → 72.00)
    if is_rate:
        rel_hourly  = {h: v * 100 for h, v in rel_hourly.items()  if not pd.isna(v)}
        comp_hourly = {h: v * 100 for h, v in comp_hourly.items() if not pd.isna(v)}
 
    all_hours = sorted(set(list(rel_hourly.keys()) + list(comp_hourly.keys())))
    min_h, max_h = min(all_hours), max(all_hours)
 
    fig, ax = plt.subplots(figsize=(11, 4.8))
    fig.patch.set_facecolor("white")
    ax.set_facecolor("#f8f9fb")
 
    # ── Grey line: previous day ──────────────────────────────────────────
    ch = sorted(comp_hourly.keys())
    cv = [comp_hourly[h] for h in ch]
    ax.plot(ch, cv, color=GREY, linewidth=2.2, zorder=2, label=f"Prev day ({COMPARE_DATE})")
    ax.scatter(ch, cv, color=GREY, s=45, zorder=3)
 
    # ── Blue/Red line: release day ───────────────────────────────────────
    rh = sorted(rel_hourly.keys())
    rv = [rel_hourly[h] for h in rh]
 
    def point_color(h, v):
        y = comp_hourly.get(h, None)
        if h < release_hour:
            return BLUE
        if y is None or abs(y) < 1e-9:
            return BLUE
        return RED if (v - y) / abs(y) <= -threshold else BLUE
 
    point_colors = [point_color(h, v) for h, v in zip(rh, rv)]
 
    for i in range(len(rh)-1):
        seg_color = RED if (point_colors[i]==RED or point_colors[i+1]==RED) else BLUE
        ax.plot([rh[i], rh[i+1]], [rv[i], rv[i+1]],
                color=seg_color, linewidth=2.5, zorder=4, solid_capstyle="round")
 
    for h, v, c in zip(rh, rv, point_colors):
        ax.scatter([h], [v], color=c, s=55, zorder=5)
 
    # ── Annotations (absolute delta + %) ────────────────────────────────
    y_range = max((max(rv+cv) - min(rv+cv)), 1e-6)
    for h, v in zip(rh, rv):
        y_prev = comp_hourly.get(h, None)
        if y_prev is None: continue
        delta = v - y_prev
        pct   = (delta / abs(y_prev) * 100) if abs(y_prev) > 1e-6 else 0
 
        arr = "▲" if delta >= 0 else "▼"
        ann_color = "#1a6e2a" if delta >= 0 else RED
 
        # Format delta label
        if is_money:
            d_str = f"${abs(delta):,.2f}"
        elif is_rate:
            # Already scaled: delta is in percentage points
            d_str = f"{abs(delta):.2f}pp"
        elif abs(delta) >= 1000:
            d_str = f"{int(round(abs(delta))):,}"
        else:
            d_str = f"{abs(delta):.1f}"
 
        label = f"{d_str}\n{arr} {abs(pct):.2f}%"
        offset_y = 18 if v >= (min(rv+cv) + y_range*0.5) else -28
        va = "bottom" if offset_y > 0 else "top"
 
        ax.annotate(label, xy=(h, v), xytext=(0, offset_y),
                    textcoords="offset points",
                    ha="center", va=va, fontsize=7.5, fontweight="bold",
                    color=ann_color)
 
    # ── Deployment vertical line ─────────────────────────────────────────
    ax.axvline(x=release_hour, color="#333333", linewidth=1.8, linestyle="-", zorder=6)
    ylim = ax.get_ylim()
    ax.text(release_hour + 0.15, ylim[0] + (ylim[1]-ylim[0])*0.02,
            "Deployment Hour", fontsize=8, color="#555555")
 
    # ── Axes formatting ──────────────────────────────────────────────────
    ax.set_xlabel("Hour (ET)", fontsize=10, fontweight="bold")
    kpi_label = kpi.replace("_"," ").title()
    if is_rate:
        ax.set_ylabel(f"{kpi_label} (%)", fontsize=9)
        ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f"{x:.2f}%"))
    else:
        ax.set_ylabel(kpi_label, fontsize=9)
        ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: fmt_k(x)))
 
    title = f"{kpi_label}  —  {delivery_type} / {demand_type_name} / {line_item_bonus_paid}"
    ax.set_title(title, fontsize=12, fontweight="bold", color=PINK, pad=8)
 
    ax.set_xticks(all_hours)
    ax.tick_params(axis="both", labelsize=8)
    ax.grid(True, alpha=0.35, linestyle="--", color="#cccccc")
    ax.set_xlim(min_h - 0.5, max_h + 0.5)
    all_vals = [v for v in list(rel_hourly.values()) + list(comp_hourly.values()) if not pd.isna(v)]
    if all_vals and min(all_vals) >= 0:
        ax.set_ylim(bottom=0)
    else:
        # Allow negative values to show; add 10% padding below min
        data_min = min(all_vals) if all_vals else 0
        data_max = max(all_vals) if all_vals else 1
        pad = (data_max - data_min) * 0.10
        ax.set_ylim(bottom=data_min - pad)
 
    # ── Legend ───────────────────────────────────────────────────────────
    legend_elements = [
        Line2D([0],[0], color=GREY,  linewidth=2, label=f"Previous day ({COMPARE_DATE})"),
        Line2D([0],[0], color=BLUE,  linewidth=2, label=f"Release day — OK ({RELEASE_DATE})"),
        Line2D([0],[0], color=RED,   linewidth=2, label=f"Release day — DROP (>{int(threshold*100)}%)"),
    ]
    ax.legend(handles=legend_elements, loc="upper left", fontsize=8,
              framealpha=0.85, edgecolor="#cccccc")
 
    plt.tight_layout(pad=1.2)
 
    fname = os.path.join(TMP_DIR, f"chart_{delivery_type}_{demand_type_name}_{line_item_bonus_paid}_{kpi}.png"
                         .replace("/","_").replace(" ","_"))
    fig.savefig(fname, dpi=150, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return fname
 
# ──────────────────────────────────────────────────────────────────────────────
# 7. OVERALL TOTALS
# ──────────────────────────────────────────────────────────────────────────────
def total_rates(fa):
    s = fa[METRICS].sum(); eps=1e-9
    s["profits"]               = s["revenue"]-s["cost"]
    s["throttling_rate"]       = s["throttled_requests"]/(s["publisher_requests"]+eps) if s["publisher_requests"]>0 else np.nan
    s["response_rate"]         = s["responses"]/(s["delivery_requests"]+eps) if s["delivery_requests"]>0 else np.nan
    s["win_rate"]              = s["wins"]/(s["responses"]+eps) if s["responses"]>0 else np.nan
    s["impression_rate"]       = s["impressions"]/(s["wins"]+eps) if s["wins"]>0 else np.nan
    s["ctr"]                   = s["clicks"]/(s["impressions"]+eps) if s["impressions"]>0 else np.nan
    s["margin"]                = s["profits"]/(s["revenue"]+eps) if s["revenue"]>0 else np.nan
    s["video_completion_rate"] = s["video_completes"]/(s["video_impressions"]+eps) if s["video_impressions"]>0 else np.nan
    return s
 
totals = dict(post_rel=total_rates(rp_agg), post_comp=total_rates(cp_agg),
              pre_rel=total_rates(rpre_agg), pre_comp=total_rates(cpre_agg))
 
# ──────────────────────────────────────────────────────────────────────────────
# 8. PDF STYLES & HELPERS
# ──────────────────────────────────────────────────────────────────────────────
print("Building PDF …")
doc = SimpleDocTemplate(OUT_PATH, pagesize=landscape(A4),
                        rightMargin=0.4*inch, leftMargin=0.4*inch,
                        topMargin=0.4*inch, bottomMargin=0.4*inch)
styles = getSampleStyleSheet()
S = lambda n, **kw: ParagraphStyle(n, parent=styles["Normal"], **kw)
title_s  = S("ts",  fontSize=18, textColor=colors.HexColor("#1a2a4a"), spaceAfter=8, fontName="Helvetica-Bold")
h1_s     = S("h1",  fontSize=12, textColor=colors.HexColor("#1a2a4a"), spaceBefore=10, spaceAfter=4, fontName="Helvetica-Bold")
body_s   = S("bd",  fontSize=7.5, spaceAfter=3, leading=11)
small_s  = S("sm",  fontSize=7,   spaceAfter=1, leading=9)
ctr_s    = S("ct",  fontSize=7.5, alignment=TA_CENTER, leading=10)
# ── White-text styles for dark header cells (Paragraph ignores TableStyle TEXTCOLOR) ──
hdr_s    = S("hd",  fontSize=7,   textColor=colors.white, fontName="Helvetica-Bold",
             spaceAfter=0, leading=9)
hdr_ctr_s= S("hdc", fontSize=7.5, textColor=colors.white, fontName="Helvetica-Bold",
             alignment=TA_CENTER, spaceAfter=0, leading=10)
red_s   = S("rd", fontSize=9,  textColor=colors.HexColor("#8b0000"), fontName="Helvetica-Bold")
grn_s   = S("gn", fontSize=9,  textColor=colors.HexColor("#1a6e2a"), fontName="Helvetica-Bold")
org_s   = S("og", fontSize=9,  textColor=colors.HexColor("#b85c00"), fontName="Helvetica-Bold")
chart_cap_s = S("cc", fontSize=8, textColor=colors.HexColor("#555555"), spaceAfter=4, spaceBefore=2)
 
def fv(v, kpi):
    """Format a value for display in tables."""
    if pd.isna(v): return "N/A"
    if kpi in ("revenue","cost","profits"): return f"${v:,.2f}"
    if kpi in RATE_KPIS: return f"{v*100:.2f}%"
    return f"{int(round(v)):,}"
 
def fp(p):
    if pd.isna(p): return "N/A"
    return f"{'▲' if p>=0 else '▼'} {abs(p):.1f}%"
 
def pct_bg(pct, kpi):
    if pd.isna(pct): return colors.white
    cost_kpi = kpi=="cost"
    if cost_kpi:
        if pct>=RISE_THRESHOLD*100:  return colors.HexColor("#ffe0e0")
        if pct<=-DROP_THRESHOLD*100: return colors.HexColor("#e0ffe0")
    else:
        if pct<=-DROP_THRESHOLD*100: return colors.HexColor("#ffe0e0")
        if pct>=RISE_THRESHOLD*100:  return colors.HexColor("#e0ffe0")
    return colors.HexColor("#f5f5f5")
 
def base_style(hdr_color=colors.HexColor("#1a2a4a")):
    return [
        # NOTE: TEXTCOLOR is intentionally omitted for header — header uses white-text
        # Paragraph styles (hdr_s / hdr_ctr_s) instead, which Paragraphs actually respect.
        ("BACKGROUND",    (0,0), (-1,0),  hdr_color),
        ("FONTSIZE",      (0,0), (-1,-1), 7),
        ("VALIGN",        (0,0), (-1,-1), "MIDDLE"),
        ("TOPPADDING",    (0,0), (-1,-1), 4),
        ("BOTTOMPADDING", (0,0), (-1,-1), 4),
        ("LEFTPADDING",   (0,0), (-1,-1), 5),
        ("RIGHTPADDING",  (0,0), (-1,-1), 5),
        ("GRID",          (0,0), (-1,-1), 0.3, colors.HexColor("#cccccc")),
        ("ROWBACKGROUNDS",(0,1), (-1,-1), [colors.white, colors.HexColor("#f5f7fb")]),
        ("ALIGN",         (0,0), (0,-1),  "LEFT"),
        ("ALIGN",         (1,0), (-1,-1), "RIGHT"),
    ]
 
# Dynamic column headers using actual dates
DETAIL_COLS = [
    "Delivery Type", "Demand Type", "Bonus/Paid", "KPI",
    f"{rel_lbl} Post", f"{comp_lbl} Post", "Δ (abs)", "Δ%"
]
DETAIL_WIDTHS = [0.9*inch,1.4*inch,0.75*inch,1.3*inch,1.0*inch,1.0*inch,0.9*inch,0.65*inch]
 
def build_detail_table(df_in, hdr_color, row_alt, pct_bg_col, arrow="▼"):
    if df_in.empty: return None
    hdr = [Paragraph(h, hdr_s) for h in DETAIL_COLS]
    tdata=[hdr]; tstyle=base_style(hdr_color)
    tstyle[8]=("ROWBACKGROUNDS",(0,1),(-1,-1),[colors.white, row_alt])
    for i,(_,r) in enumerate(df_in.iterrows()):
        kpi=r["kpi"]
        delta=r.get("delta",np.nan); pct=r.get("pct",np.nan)
        is_money = kpi in ("revenue","cost","profits")
        is_rate  = kpi in RATE_KPIS
        if is_money:
            d_str = f"${delta:+,.2f}"
        elif is_rate:
            # delta is a decimal (e.g. 0.05); show as percentage points
            d_str = f"{delta*100:+.2f}pp"
        elif abs(delta) >= 1000:
            d_str = f"{int(round(delta)):,}"
        else:
            d_str = f"{delta:+.1f}"
        tdata.append([
            Paragraph(str(r.get("delivery_type","")), small_s),
            Paragraph(str(r.get("demand_type_name","")), small_s),
            Paragraph(str(r.get("line_item_bonus_paid","")), small_s),
            Paragraph(kpi.replace("_"," "), small_s),
            Paragraph(fv(r.get("today",np.nan),kpi), small_s),
            Paragraph(fv(r.get("yesterday",np.nan),kpi), small_s),
            Paragraph(d_str, small_s),
            Paragraph(f"{arrow} {abs(pct):.1f}%", small_s),
        ])
        tstyle.append(("BACKGROUND",(6,i+1),(6,i+1), pct_bg_col))
    t=Table(tdata, colWidths=DETAIL_WIDTHS, repeatRows=1)
    t.setStyle(TableStyle(tstyle))
    return t
 
# ──────────────────────────────────────────────────────────────────────────────
# 9. GENERATE CHARTS for release-caused drops
# ──────────────────────────────────────────────────────────────────────────────
print("Generating charts …")
chart_items = []   # list of (delivery_type, demand_type_name, kpi, png_path)
 
# Use full release & compare day data (all hours) for charts
rel_all  = df[df["date_str"]==RELEASE_DATE].copy()
comp_all = df[df["date_str"]==COMPARE_DATE].copy()
 
for _, row in df_drops_rel.iterrows():
    dt   = row["delivery_type"]
    dtn  = row["demand_type_name"]
    bp   = row["line_item_bonus_paid"]
    kpi  = row["kpi"]
    path = make_chart(dt, dtn, bp, kpi, rel_all, comp_all)
    if path:
        chart_items.append((dt, dtn, bp, kpi, path))
        print(f"  Chart: {dt} / {dtn} / {bp} / {kpi}")
 
# ──────────────────────────────────────────────────────────────────────────────
# 10. BUILD PDF
# ──────────────────────────────────────────────────────────────────────────────
story = []
 
# ── PAGE 1: Summary ──────────────────────────────────────────────────────────
story.append(Spacer(1, 0.15*inch))
story.append(Paragraph("AdServer Release Verification Report", title_s))
story.append(Spacer(1, 0.12*inch))
meta_style = S("meta", fontSize=7.5, textColor=colors.HexColor("#444444"),
               spaceAfter=5, leading=11,
               borderPad=4,
               backColor=colors.HexColor("#f0f4fa"),
               borderColor=colors.HexColor("#c0cce0"),
               borderWidth=0.5, borderRadius=3)
story.append(Paragraph(
    f"<b>Release:</b> {RELEASE_DATE} &nbsp;@ {RELEASE_HOUR:02d}:00 ET"
    f"&nbsp;&nbsp;|&nbsp;&nbsp;<b>Compare day:</b> {COMPARE_DATE} (same hours)"
    f"&nbsp;&nbsp;|&nbsp;&nbsp;<b>Environment:</b> {env_label}"
    f"&nbsp;&nbsp;|&nbsp;&nbsp;<b>Region:</b> {region_label}"
    f"&nbsp;&nbsp;|&nbsp;&nbsp;<b>Last hour excluded:</b> {'Yes' if EXCLUDE_LAST_HR else 'No'}"
    f"&nbsp;&nbsp;|&nbsp;&nbsp;<b>Dimensions:</b> delivery_type × demand_type_name × bonus/paid",
    meta_style))
story.append(HRFlowable(width="100%", thickness=1.5, color=colors.HexColor("#1a2a4a"), spaceAfter=6))
 
# Badge counts
n_rel=len(df_drops_rel); n_tre=len(df_drops_trend); n_inc=len(df_inc)
badge_lbl_s = S("bl",  fontSize=8,  fontName="Helvetica-Bold", alignment=TA_CENTER,
                textColor=colors.HexColor("#333333"), leading=11, spaceAfter=0)
badge_num_r = S("bnr", fontSize=26, fontName="Helvetica-Bold", alignment=TA_CENTER,
                textColor=colors.HexColor("#cc0000"),  leading=30, spaceAfter=0)
badge_num_o = S("bno", fontSize=26, fontName="Helvetica-Bold", alignment=TA_CENTER,
                textColor=colors.HexColor("#b85c00"),  leading=30, spaceAfter=0)
badge_num_g = S("bng", fontSize=26, fontName="Helvetica-Bold", alignment=TA_CENTER,
                textColor=colors.HexColor("#1a6e2a"),  leading=30, spaceAfter=0)
badge_data = [
    [Paragraph("RELEASE-CAUSED DROPS\n(≥10%, not pre-existing)",    badge_lbl_s),
     Paragraph("PRE-EXISTING TREND DROPS\n(started before release)", badge_lbl_s),
     Paragraph("POST-RELEASE INCREASES\n(≥10% improvement)",         badge_lbl_s)],
    [Paragraph(str(n_rel), badge_num_r),
     Paragraph(str(n_tre), badge_num_o),
     Paragraph(str(n_inc), badge_num_g)],
]
bt=Table(badge_data, colWidths=[3.63*inch]*3, rowHeights=[0.45*inch, 0.55*inch])
bt.setStyle(TableStyle([
    ("INNERGRID",    (0,0),(-1,-1), 0.5, colors.HexColor("#cccccc")),
    ("BOX",          (0,0),(-1,-1), 1,   colors.HexColor("#cccccc")),
    ("BACKGROUND",   (0,0),(0,-1),  colors.HexColor("#fff0f0")),
    ("BACKGROUND",   (1,0),(1,-1),  colors.HexColor("#fff8f0")),
    ("BACKGROUND",   (2,0),(2,-1),  colors.HexColor("#f0fff0")),
    ("ALIGN",        (0,0),(-1,-1), "CENTER"),
    ("VALIGN",       (0,0),(-1,-1), "MIDDLE"),
    ("TOPPADDING",   (0,0),(-1,-1), 10),
    ("BOTTOMPADDING",(0,0),(-1,-1), 10),
    ("LEFTPADDING",  (0,0),(-1,-1), 6),
    ("RIGHTPADDING", (0,0),(-1,-1), 6),
]))
story.append(bt)
story.append(Spacer(1, 0.1*inch))
 
# Overall summary table
story.append(Paragraph("Overall Performance (all combos aggregated)", h1_s))
story.append(Paragraph(
    f"POST: {RELEASE_DATE} {RELEASE_HOUR:02d}:00–{max_rel_hour:02d}:00 ET  vs  "
    f"{COMPARE_DATE} same hours.   PRE: {RELEASE_DATE} 00:00–{RELEASE_HOUR-1:02d}:59 ET  vs  "
    f"{COMPARE_DATE} same hours.", small_s))
 
sum_kpis=["impressions","wins","responses","clicks","revenue","cost","profits",
          "response_rate","win_rate","impression_rate","ctr","margin","video_completion_rate"]
 
col_w_sum = [2.1*inch, 1.55*inch, 1.55*inch, 1.07*inch, 1.55*inch, 1.55*inch, 1.07*inch]
 
sum_hdr = [Paragraph(h, hdr_s) for h in [
    "KPI",
    f"PRE {rel_lbl}",  f"PRE {comp_lbl}",  "Pre Δ%",
    f"POST {rel_lbl}", f"POST {comp_lbl}", "Post Δ%",
]]
sum_rows=[sum_hdr]
sum_style = base_style()
sum_style += [
    ("ALIGN", (0,0), (0,-1), "LEFT"),
    ("ALIGN", (1,0), (-1,-1), "RIGHT"),
    ("FONTNAME", (0,1), (0,-1), "Helvetica"),
]
 
for i, kpi in enumerate(sum_kpis):
    pre_t  = totals["pre_rel"].get(kpi, np.nan)
    pre_y  = totals["pre_comp"].get(kpi, np.nan)
    post_t = totals["post_rel"].get(kpi, np.nan)
    post_y = totals["post_comp"].get(kpi, np.nan)
    pre_pct  = ((pre_t-pre_y)/abs(pre_y)*100)   if (not pd.isna(pre_y)  and abs(pre_y)>1e-6)  else np.nan
    post_pct = ((post_t-post_y)/abs(post_y)*100) if (not pd.isna(post_y) and abs(post_y)>1e-6) else np.nan
    ri = i + 1
    sum_style.append(("BACKGROUND", (3,ri), (3,ri), pct_bg(pre_pct,  kpi)))
    sum_style.append(("BACKGROUND", (6,ri), (6,ri), pct_bg(post_pct, kpi)))
    sum_rows.append([
        Paragraph(kpi.replace("_"," "), small_s),
        Paragraph(fv(pre_t,  kpi), small_s), Paragraph(fv(pre_y,  kpi), small_s), Paragraph(fp(pre_pct),  small_s),
        Paragraph(fv(post_t, kpi), small_s), Paragraph(fv(post_y, kpi), small_s), Paragraph(fp(post_pct), small_s),
    ])
 
st = Table(sum_rows, colWidths=col_w_sum)
st.setStyle(TableStyle(sum_style))
story.append(st)
 
# ── PAGE 2: Drop tables ───────────────────────────────────────────────────────
story.append(PageBreak())
story.append(Paragraph("🔴  POST-RELEASE DROPS  (≥10% decline — post-release window)", h1_s))
story.append(Paragraph(
    f"Comparing {RELEASE_DATE} {RELEASE_HOUR:02d}:00–{max_rel_hour:02d}:00 ET  vs  "
    f"{COMPARE_DATE} same hours. Sorted worst first. Charts on following pages.", body_s))
story.append(Spacer(1, 0.06*inch))
 
story.append(Paragraph("⚠️  Release-Caused Drops (NOT present in pre-release window):", red_s))
if df_drops_rel.empty:
    story.append(Paragraph("✅  None detected.", grn_s))
else:
    t=build_detail_table(df_drops_rel, colors.HexColor("#8b0000"),
                          colors.HexColor("#fdf0f0"), colors.HexColor("#ffe0e0"))
    if t: story.append(t)
 
story.append(Spacer(1, 0.1*inch))
story.append(Paragraph("ℹ️  Pre-Existing Trend Drops (drop started before release — not release-caused):", org_s))
if df_drops_trend.empty:
    story.append(Paragraph("None.", body_s))
else:
    t=build_detail_table(df_drops_trend, colors.HexColor("#b85c00"),
                          colors.HexColor("#fffbe0"), colors.HexColor("#ffe0a0"))
    if t: story.append(t)
 
# ── CHART PAGES: 2 charts per page ───────────────────────────────────────────
if chart_items:
    story.append(PageBreak())
    story.append(Paragraph("📊  Hourly Charts — Release-Caused Drops", h1_s))
    story.append(Paragraph(
        f"Grey line = previous day ({COMPARE_DATE}).  "
        "Blue line = release day OK (today ≥ yesterday or within 10%).  "
        "Red line = release day DROP (>10% below previous day).  "
        "Annotations show absolute delta (pp for rates) and % change at each hour.",
        body_s))
    story.append(Spacer(1, 0.08*inch))
 
    chart_w = 10.8 * inch
    chart_h = 3.9  * inch
 
    for idx, (dt, dtn, bp, kpi, path) in enumerate(chart_items):
        img = RLImage(path, width=chart_w, height=chart_h)
        caption = Paragraph(
            f"<i>Drop: <b>{kpi.replace('_',' ')}</b> — "
            f"delivery_type=<b>{dt}</b>, demand_type_name=<b>{dtn}</b>, "
            f"bonus_paid=<b>{bp}</b> | "
            f"Vertical line = deployment @ {RELEASE_HOUR:02d}:00 ET</i>",
            chart_cap_s)
        story.append(KeepTogether([img, caption]))
        if (idx+1) % 2 == 0 and idx < len(chart_items)-1:
            story.append(PageBreak())
        else:
            story.append(Spacer(1, 0.15*inch))
 
# ── Increases page ────────────────────────────────────────────────────────────
story.append(PageBreak())
story.append(Paragraph("🟢  POST-RELEASE INCREASES  (≥10% improvement)", h1_s))
story.append(Paragraph(
    f"Comparing {RELEASE_DATE} {RELEASE_HOUR:02d}:00–{max_rel_hour:02d}:00 ET  vs  "
    f"{COMPARE_DATE} same hours. Sorted best gain first.", body_s))
story.append(Spacer(1, 0.06*inch))
if df_inc.empty:
    story.append(Paragraph("No significant increases detected.", body_s))
else:
    t=build_detail_table(df_inc, colors.HexColor("#1a6e2a"),
                          colors.HexColor("#f0fdf0"), colors.HexColor("#d0f0d0"), arrow="▲")
    if t: story.append(t)
 
# ── Pre-release trend page ────────────────────────────────────────────────────
story.append(PageBreak())
pre_end_lbl = f"00:00–{RELEASE_HOUR-1:02d}:59" if RELEASE_HOUR > 0 else "N/A"
story.append(Paragraph(
    f"ℹ️  PRE-RELEASE TREND  ({pre_end_lbl} on {RELEASE_DATE} vs {COMPARE_DATE} same hours)", h1_s))
story.append(Paragraph(
    "Drops already present before the release. These are organic/traffic trends "
    "unrelated to the deployment.", body_s))
story.append(Spacer(1, 0.06*inch))
if df_pre_drops.empty:
    story.append(Paragraph("No pre-release drops detected.", body_s))
else:
    t=build_detail_table(df_pre_drops, colors.HexColor("#5c4e1a"),
                          colors.HexColor("#fffbe0"), colors.HexColor("#ffe0a0"))
    if t: story.append(t)
 
# ── MARGIN CHARTS: all delivery_type × demand_type_name, Paid only ───────────
print("Generating margin charts (Paid only) …")
 
paid_combos = (
    df[df["line_item_bonus_paid"] == "Paid"]
    .groupby(["delivery_type", "demand_type_name"])
    .size()
    .reset_index()[["delivery_type", "demand_type_name"]]
    .drop_duplicates()
    .sort_values(["delivery_type", "demand_type_name"])
)
 
margin_chart_items = []
for _, combo_row in paid_combos.iterrows():
    dt  = combo_row["delivery_type"]
    dtn = combo_row["demand_type_name"]
    path = make_chart(dt, dtn, "Paid", "margin", rel_all, comp_all)
    if path:
        margin_chart_items.append((dt, dtn, path))
        print(f"  Margin chart: {dt} / {dtn}")
 
if margin_chart_items:
    story.append(PageBreak())
    story.append(Paragraph("📈  MARGIN OVERVIEW — All Combos  (line_item_bonus_paid = Paid)", h1_s))
    story.append(Paragraph(
        "Hourly margin % for every delivery_type × demand_type_name combination, "
        "filtered to Paid line items only. Grey = previous day, Blue = today OK, Red = today dropping >10%.",
        body_s))
    story.append(Spacer(1, 0.08*inch))
 
    for idx, (dt, dtn, path) in enumerate(margin_chart_items):
        img = RLImage(path, width=10.8*inch, height=3.9*inch)
        caption = Paragraph(
            f"<i>Margin % — delivery_type=<b>{dt}</b>, demand_type_name=<b>{dtn}</b>, "
            f"bonus_paid=<b>Paid</b> | "
            f"Vertical line = deployment @ {RELEASE_HOUR:02d}:00 ET</i>",
            chart_cap_s)
        story.append(KeepTogether([img, caption]))
        if (idx + 1) % 2 == 0 and idx < len(margin_chart_items) - 1:
            story.append(PageBreak())
        else:
            story.append(Spacer(1, 0.15*inch))
 
# ── Footer ────────────────────────────────────────────────────────────────────
story.append(Spacer(1, 0.12*inch))
story.append(HRFlowable(width="100%", thickness=0.5, color=colors.grey))
story.append(Paragraph(
    f"Generated: {RELEASE_DATE}  |  Env: {env_label}  |  Region: {region_label}  |  "
    f"Last hour excluded: {'Yes' if EXCLUDE_LAST_HR else 'No'}  |  "
    f"Threshold: {int(DROP_THRESHOLD*100)}%  |  {len(df):,} rows after filters",
    small_s))
 
# ── Build ─────────────────────────────────────────────────────────────────────
print("Writing PDF …")
doc.build(story)
print(f"\n✅  Done → {OUT_PATH}")
print(f"   {len(chart_items)} charts generated for release-caused drops")
 
# Cleanup temp pngs
import shutil
shutil.rmtree(TMP_DIR, ignore_errors=True)

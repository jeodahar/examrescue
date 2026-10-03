"""engine.py - the 'tools' of ExamRescue AI.

All numbers (priority, study debt, recovery categories, feasibility) are
calculated here in plain Python, so they are consistent and free.
The AI agents only EXPLAIN and PLAN using these numbers.
"""
from datetime import date

import pandas as pd

BANDS = [("🟢 Strong", 75), ("🟡 Developing", 60), ("🟠 Weak", 40), ("🔴 Critical", 0)]


def band(score):
    if score is None or pd.isna(score):
        return "⚪ Not assessed"
    for name, low in BANDS:
        if score >= low:
            return name
    return "🔴 Critical"


def band_counts(df):
    counts = {"🔴 Critical": 0, "🟠 Weak": 0, "🟡 Developing": 0, "🟢 Strong": 0, "⚪ Not assessed": 0}
    for s in df["score"]:
        counts[band(s)] += 1
    return counts


def days_left(prof):
    return max((date.fromisoformat(prof["exam_date"]) - date.today()).days, 0)


def _priority(row):
    weak = 0.6 if pd.isna(row["score"]) else 1 - row["score"] / 100
    need = row["hours_needed"] or 0
    left = 1.0 if need <= 0 else max(0.0, 1 - row["hours_done"] / need)
    return round(
        0.35 * row["importance"] / 5      # how important is the topic
        + 0.30 * weak                      # how weak is the student
        + 0.20 * row["past_freq"] / 5      # how often it appears in past papers
        + 0.15 * left,                     # how much is still unstudied
        3,
    )


def rank(df):
    d = df.copy()
    if d.empty:
        d["priority"] = []
        return d
    d["priority"] = d.apply(_priority, axis=1)
    return d.sort_values("priority", ascending=False).reset_index(drop=True)


def progress(prof, df, logs):
    start = date.fromisoformat(prof["start_date"])
    exam = date.fromisoformat(prof["exam_date"])
    total = max((exam - start).days, 1)
    elapsed = min(max((date.today() - start).days, 0), total)
    planned = elapsed / total * 100
    needed = float(df["hours_needed"].sum()) if not df.empty else 0.0
    done = min(float(df["hours_done"].sum()), needed) if not df.empty else 0.0
    actual = done / needed * 100 if needed > 0 else 0.0
    return {
        "planned_pct": round(planned, 1),
        "actual_pct": round(actual, 1),
        "study_debt_pct": round(max(planned - actual, 0), 1),
        "missed_days": int(sum(l["missed"] for l in logs)),
        "hours_done": round(done, 1),
        "hours_needed": round(needed, 1),
    }


def recovery_plan(prof, df):
    """Sort every topic into MUST RECOVER / COMPRESS / POSTPONE / SKIP."""
    d_left = days_left(prof)
    total_budget = round(d_left * prof["daily_hours"] * 0.85, 1)  # keep 15% as buffer
    budget = total_budget
    critical_need = 0.0
    rows = []
    for _, r in rank(df).iterrows():
        mastered = (not pd.isna(r["score"])) and r["score"] >= 80
        full = max(r["hours_needed"] - r["hours_done"], 1.0)
        p = r["priority"]
        if mastered:
            cat, hrs, why = "🟢 SKIP", 0.0, "Already mastered"
        else:
            if p >= 0.55:
                critical_need += full
            if p >= 0.55 and budget >= full:
                cat, hrs, why = "🔴 MUST RECOVER", full, "High importance / weak / frequent"
                budget -= hrs
            elif p >= 0.35 and budget >= full * 0.4:
                hrs = round(full * 0.4, 1)
                cat = "🟡 COMPRESS"
                why = "Important - short revision only" if p < 0.55 else "High priority but time is short"
                budget -= hrs
            elif p >= 0.35:
                cat, hrs, why = "🔵 POSTPONE", 0.0, "No time left in the budget"
            else:
                cat, hrs, why = "🟢 SKIP", 0.0, "Low value for the time remaining"
        rows.append({
            "subject": r["subject"], "topic": r["topic"], "priority": p,
            "category": cat, "hours": round(float(hrs), 1), "why": why,
        })
    plan = pd.DataFrame(rows)
    counts = {k: 0 for k in ["MUST RECOVER", "COMPRESS", "POSTPONE", "SKIP"]}
    for c in plan["category"] if not plan.empty else []:
        for k in counts:
            if k in c:
                counts[k] += 1
    summary = {
        "days_left": d_left,
        "total_budget_hours": total_budget,
        "critical_hours_needed": round(critical_need, 1),
        "feasible": critical_need <= total_budget,
        "shortfall_hours": round(max(critical_need - total_budget, 0), 1),
        "counts": counts,
    }
    return plan, summary


def audit(adf):
    """Compare first vs latest assessment for each topic."""
    rows = []
    if adf.empty:
        return pd.DataFrame(rows)
    for tid, g in adf.groupby("topic_id"):
        first, latest = float(g["score"].iloc[0]), float(g["score"].iloc[-1])
        if len(g) == 1:
            status = "🆕 BASELINE ONLY"
        elif latest >= 70:
            status = "✅ RECOVERED"
        elif latest - first >= 10:
            status = "📈 IMPROVING"
        else:
            status = "⚠️ STILL WEAK"
        rows.append({
            "subject": g["subject"].iloc[0], "topic": g["topic"].iloc[0],
            "before": first, "after": latest, "change": round(latest - first, 1),
            "tests": len(g), "status": status,
        })
    return pd.DataFrame(rows)

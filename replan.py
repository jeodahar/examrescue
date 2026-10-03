"""replan.py - rebuilds the recovery plan automatically.

Called whenever a missed day is logged (button, Orchestrator, or chatbot).
Steps: recalculate plan (Python) -> compare with the previous plan ->
ask the Recovery Planner agent to explain -> save everything.
"""
import json

import agents
import database as db
import engine


def log_missed_and_replan(day=None):
    """Record a missed day, then rebuild the plan. Returns a short message."""
    db.add_log(0, 1, None, day=day)
    result = auto_replan()
    if result is None:
        return "Missed day recorded."
    n = len(result["changes"])
    feas = "still possible" if result["summary"]["feasible"] else "NOT fully possible now"
    return (
        f"Missed day recorded. Plan rebuilt automatically: {n} topic(s) changed. "
        f"Recovery is {feas}."
    )


def auto_replan(use_ai=True):
    prof = db.get_profile()
    tdf = db.topics_df()
    if not prof or tdf.empty:
        return None

    plan, summ = engine.recovery_plan(prof, tdf)
    prev = db.latest_plan()
    old_records = json.loads(prev["plan_json"]) if prev else []
    changes = engine.plan_changes(old_records, plan)

    narrative = ""
    if use_ai:
        try:
            def names(tag, with_hours=False):
                sub = plan[plan["category"].str.contains(tag)]
                if with_hours:
                    return [f"{r.topic}:{r.hours}" for r in sub.itertuples()]
                return [r.topic for r in sub.itertuples()]

            ai_summary = {**summ, "what_changed": changes[:6]}
            narrative = agents.recovery_narrative(
                ai_summary, names("MUST", True), names("COMPRESS", True),
                names("POSTPONE"), names("SKIP"),
            )
        except Exception:
            narrative = ""  # the plan is still saved even if the AI is busy

    db.save_plan(summ, plan, narrative, changes)
    return {"summary": summ, "changes": changes, "narrative": narrative}

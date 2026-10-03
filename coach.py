"""coach.py - the Study Coach chatbot with voice.

Voice in : Streamlit mic recorder -> Groq Whisper (speech to text)
Brain    : CrewAI "Study Coach" agent (Groq gpt-oss-120b) using your real data
Voice out: gTTS (text to speech)
"""
import io
import json
import os
import re

import database as db
import engine
from llm_setup import run_agent

LANGS = {"English": {"whisper": "en", "tts": "en"}, "Urdu": {"whisper": "ur", "tts": "ur"}}

COACH = dict(
    role="ExamRescue AI Study Coach",
    goal="Act as the built-in coach of the ExamRescue AI app and answer using the student's own dashboard and recovery plan.",
    backstory=(
        "You are the Study Coach inside the ExamRescue AI app. You can see the student's Dashboard "
        "(days remaining, planned vs actual progress, study debt, missed days, topic strength) and their "
        "Recovery plan (MUST RECOVER, COMPRESS, POSTPONE, SKIP, feasibility, latest changes). "
        "When asked who you are, say you are the ExamRescue AI coach. Use ONLY the data you are given for "
        "numbers and never invent scores, topics or dates. You can also explain exam topics in simple words."
    ),
)


def build_context():
    """Everything the coach may know: dashboard + recovery plan + recent results."""
    prof = db.get_profile()
    tdf = db.topics_df()
    if not prof or tdf.empty:
        return {}
    prog = engine.progress(prof, tdf, db.get_logs())
    ranked = engine.rank(tdf)
    plan, summ = engine.recovery_plan(prof, tdf)

    def rows(tag, n, hours=True):
        sub = plan[plan["category"].str.contains(tag)].head(n)
        return [f"{r.topic} ({r.hours}h)" if hours else r.topic for r in sub.itertuples()]

    top = ranked.iloc[0]
    last = db.latest_plan()
    adf = db.assessments_df()
    recent = [
        {"topic": r.topic, "score": r.score, "day": r.day}
        for r in adf.tail(5).itertuples()
    ]
    return {
        "app": "ExamRescue AI",
        "dashboard": {
            "exam": prof["exam"],
            "days_remaining": engine.days_left(prof),
            "study_hours_per_day": prof["daily_hours"],
            "planned_progress_pct": prog["planned_pct"],
            "actual_progress_pct": prog["actual_pct"],
            "study_debt_pct": prog["study_debt_pct"],
            "missed_days": prog["missed_days"],
            "hours_done": prog["hours_done"],
            "hours_needed": prog["hours_needed"],
            "topic_strength_counts": engine.band_counts(tdf),
            "next_priority": f"{top['subject']} - {top['topic']}",
        },
        "recovery_plan": {
            "counts": summ["counts"],
            "feasible": summ["feasible"],
            "shortfall_hours": summ["shortfall_hours"],
            "budget_hours": summ["total_budget_hours"],
            "critical_hours_needed": summ["critical_hours_needed"],
            "must_recover": rows("MUST", 8),
            "compress": rows("COMPRESS", 6),
            "postponed": rows("POSTPONE", 5, False),
            "skipped": rows("SKIP", 5, False),
            "last_replan": last["created"] if last else None,
            "last_changes": json.loads(last["changes"] or "[]")[:6] if last else [],
        },
        "recent_quiz_scores": recent,
    }


def greeting():
    """First message shown in the chat (no AI call needed)."""
    ctx = build_context()
    if not ctx:
        return "Hi! I'm the ExamRescue AI coach. Add your exam and topics in Setup and I will see your dashboard."
    d, r = ctx["dashboard"], ctx["recovery_plan"]
    verdict = "Recovery is still possible." if r["feasible"] else "Recovery is tight, we need to talk about hours."
    return (
        f"Hi! I'm your ExamRescue AI coach. I can see your dashboard: {d['exam']} is in "
        f"{d['days_remaining']} days, you are at {d['actual_progress_pct']}% progress with "
        f"{d['study_debt_pct']}% study debt. Your recovery plan has {r['counts']['MUST RECOVER']} "
        f"must-recover topics. {verdict} Ask me anything, by voice or text."
    )


def ask_coach(question, history, language="English"):
    hist = "\n".join(f"{m['role'].upper()}: {m['content'][:300]}" for m in history[-6:])
    task = (
        f"EXAMRESCUE AI DATA (the student's dashboard and recovery plan): {json.dumps(build_context())}\n"
        f"CHAT SO FAR:\n{hist}\n"
        f"STUDENT QUESTION: {question}\n"
        f"Reply in {language}. Maximum 120 words. Plain text only: no markdown, no bullet symbols, "
        "because the answer will be read aloud. Speak as the ExamRescue AI coach who can see their dashboard "
        "and recovery plan. If the data does not contain the answer, say so."
    )
    return run_agent(COACH["role"], COACH["goal"], COACH["backstory"], task, "A short spoken-style answer.")


def missed_day_intent(text):
    """Return 'today' / 'yesterday' if the student says they missed a day, else None."""
    t = text.lower()
    if re.search(r"\b(if|what|should|when|how|can|will|would)\b", t):
        return None
    if re.search(r"\b(i|we)\s+(have\s+)?(missed|skipped)\b.*\byesterday\b", t):
        return "yesterday"
    if re.search(r"\b(i|we)\s+(have\s+)?(missed|skipped)\b.*\btoday\b", t) or re.search(r"\bmissed today\b", t):
        return "today"
    return None


def transcribe(audio_bytes, language="English"):
    from groq import Groq

    client = Groq(api_key=os.environ.get("GROQ_API_KEY", ""))
    res = client.audio.transcriptions.create(
        file=("question.wav", audio_bytes),
        model="whisper-large-v3-turbo",
        language=LANGS[language]["whisper"],
        temperature=0.0,
    )
    return (res if isinstance(res, str) else getattr(res, "text", "")).strip()


def clean_for_speech(text):
    text = re.sub(r"[*_`#>|~]", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:700]


def speak(text, language="English"):
    """Return MP3 bytes, or None if text-to-speech is not available."""
    try:
        from gtts import gTTS

        buf = io.BytesIO()
        gTTS(clean_for_speech(text), lang=LANGS[language]["tts"]).write_to_fp(buf)
        return buf.getvalue()
    except Exception:
        return None

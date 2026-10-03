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
    role="Study Coach",
    goal="Answer the student's exam-preparation questions using their real progress data.",
    backstory=(
        "You are a friendly, honest exam coach. You use ONLY the student data you are given for "
        "numbers and never invent scores or dates. You can also explain topics in simple words."
    ),
)


def build_context():
    prof = db.get_profile()
    tdf = db.topics_df()
    if not prof or tdf.empty:
        return {}
    logs = db.get_logs()
    prog = engine.progress(prof, tdf, logs)
    ranked = engine.rank(tdf).head(5)
    plan, summ = engine.recovery_plan(prof, tdf)
    return {
        "exam": prof["exam"],
        "days_left": engine.days_left(prof),
        "hours_per_day": prof["daily_hours"],
        "progress": prog,
        "top_priorities": [
            {"topic": r.topic, "subject": r.subject, "score": None if r.score != r.score else r.score,
             "priority": r.priority}
            for r in ranked.itertuples()
        ],
        "recovery": {"counts": summ["counts"], "feasible": summ["feasible"],
                     "shortfall_hours": summ["shortfall_hours"]},
    }


def ask_coach(question, history, language="English"):
    hist = "\n".join(f"{m['role'].upper()}: {m['content'][:300]}" for m in history[-6:])
    task = (
        f"STUDENT DATA: {json.dumps(build_context())}\n"
        f"CHAT SO FAR:\n{hist}\n"
        f"STUDENT QUESTION: {question}\n"
        f"Reply in {language}. Maximum 120 words. Plain text only: no markdown, no bullet symbols, "
        "because the answer will be read aloud. If the data does not contain the answer, say so."
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

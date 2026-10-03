"""agents.py - the AI agents of ExamRescue AI (CrewAI + Groq).

Numbers come from engine.py. Agents only reason in words and return
short, structured output. Every prompt is kept small for the Groq free plan.
"""
import json
import time

from llm_setup import run_agent

SPECS = {
    "orchestrator": dict(
        role="Orchestrator - student situation triage",
        goal="Turn a student's messy message into structured facts and decide which steps to run next.",
        backstory="You are a calm exam coach. You never invent facts the student did not state.",
    ),
    "syllabus": dict(
        role="Syllabus Agent",
        goal="Convert raw syllabus text into a clean list of study topics with importance and study hours.",
        backstory="You know how exam syllabi are organised. You output strict JSON only.",
    ),
    "past_paper": dict(
        role="Past Paper Agent",
        goal="Find how often each syllabus topic appears in past-paper text.",
        backstory="You are an exam-pattern analyst. You only use topic names you are given.",
    ),
    "recovery": dict(
        role="Recovery Planner Agent",
        goal="Explain a recovery plan so the student knows what to do first, what is cut, and why.",
        backstory="You are honest. If the plan is not feasible you say so clearly. You never change the numbers you are given.",
    ),
    "daily": dict(
        role="Daily Study Agent",
        goal="Turn today's recovery topics into a realistic timetable with practice and review.",
        backstory="You build focused study blocks of max 50 minutes with short breaks.",
    ),
    "assessment": dict(
        role="Assessment Agent",
        goal="Write exam-style questions on a topic.",
        backstory="You write clear questions in the style of the given exam. You output only the questions.",
    ),
    "evaluator": dict(
        role="Answer Evaluation Agent",
        goal="Score a student's answer fairly, classify the mistake type, and say how to improve.",
        backstory="You are a strict but kind examiner. You output strict JSON only.",
    ),
    "auditor": dict(
        role="Progress Auditor Agent",
        goal="Compare before/after results and say who is recovered and who needs another round.",
        backstory="You only talk about the numbers you are given.",
    ),
}


def _ask(name, task, expected):
    s = SPECS[name]
    return run_agent(s["role"], s["goal"], s["backstory"], task, expected)


def extract_json(text):
    """Find the first JSON object/array inside the model's text."""
    text = (text or "").strip()
    starts = [i for i in (text.find("{"), text.find("[")) if i != -1]
    if not starts:
        return None
    i = min(starts)
    closer = "}" if text[i] == "{" else "]"
    j = text.rfind(closer)
    if j <= i:
        return None
    try:
        return json.loads(text[i:j + 1])
    except Exception:
        return None


# ---------------- Syllabus Agent ----------------
def extract_syllabus(text, exam_name):
    chunks = [text[i:i + 4000] for i in range(0, min(len(text), 20000), 4000)]
    topics = []
    for n, chunk in enumerate(chunks):
        out = _ask(
            "syllabus",
            f"Exam: {exam_name}\nFrom the syllabus text below, list the study topics.\n"
            'Return ONLY a JSON array. Each item: {"subject": str, "topic": str, '
            '"importance": 1-5, "hours": estimated study hours 1-8}.\n'
            "Max 40 items. Short topic names. Ignore menus, ads, fees, dates and unrelated text.\n\nSYLLABUS:\n" + chunk,
            "A JSON array only.",
        )
        data = extract_json(out)
        if isinstance(data, list):
            topics += [d for d in data if isinstance(d, dict)]
        if n < len(chunks) - 1:
            time.sleep(12)  # stay under the Groq per-minute limit
    return topics


# ---------------- Past Paper Agent ----------------
def analyze_past_paper(paper_text, topic_names):
    names = topic_names[:60]
    out = _ask(
        "past_paper",
        "Below are syllabus topic names and the text of a past paper.\n"
        "For each topic that appears in the paper, give a frequency 1-3 "
        "(1 = once, 3 = heavily tested). Skip topics that do not appear.\n"
        'Return ONLY a JSON object like {"Topic name": 2}. Use the exact topic names.\n\n'
        f"TOPICS: {json.dumps(names)}\n\nPAPER:\n{paper_text[:4500]}",
        "A JSON object only.",
    )
    data = extract_json(out)
    return data if isinstance(data, dict) else {}


# ---------------- Orchestrator ----------------
def orchestrate(situation, context):
    out = _ask(
        "orchestrator",
        f"Student message: {situation}\nContext: {json.dumps(context)}\n"
        "Return ONLY JSON: {\"missed_days\": int (0 if not stated), "
        "\"weak_topics_mentioned\": [str], \"severity\": \"low|medium|high\", "
        "\"advice\": \"2 short sentences\", "
        "\"next_steps\": [subset of \"log\", \"recovery\", \"daily\", \"quiz\"]}",
        "A JSON object only.",
    )
    data = extract_json(out)
    return data if isinstance(data, dict) else {"advice": out, "missed_days": 0, "next_steps": []}


# ---------------- Recovery Planner ----------------
def recovery_narrative(summary, must, compress, postponed, skipped):
    return _ask(
        "recovery",
        "Explain this recovery plan to the student in under 180 words.\n"
        "Sections: 1) Situation 2) What changed (use what_changed if present) 3) Do first 4) What we cut and why 5) Honest warning (only if feasible=false).\n"
        "Do NOT change any numbers.\n"
        f"SUMMARY: {json.dumps(summary)}\nMUST (topic:hours): {json.dumps(must[:8])}\n"
        f"COMPRESS: {json.dumps(compress[:8])}\nPOSTPONE: {json.dumps(postponed[:6])}\nSKIP: {json.dumps(skipped[:6])}",
        "Short plain-language explanation.",
    )


# ---------------- Daily Study Agent ----------------
def daily_schedule(items, total_hours, start_time):
    return _ask(
        "daily",
        f"Build today's timetable. Start {start_time}. Total study time {total_hours} hours.\n"
        "For each topic use blocks: Concept review, Practice questions, Error review, Mini assessment.\n"
        "Blocks max 50 min, 10 min break after each. Format: HH:MM-HH:MM  Topic - activity.\n"
        f"TOPICS (topic, subject, hours): {json.dumps(items)}",
        "A timetable list.",
    )


# ---------------- Assessment Agent ----------------
def make_questions(exam, subject, topic, kind, n):
    style = {
        "MCQ": f"{n} multiple-choice questions with options A-D. Put the answer key at the end.",
        "Short questions": f"{n} short-answer questions (3-5 lines each).",
        "Long question": "1 long analytical question that needs introduction, arguments, evidence and conclusion.",
    }[kind]
    return _ask(
        "assessment",
        f"Exam: {exam}. Subject: {subject}. Topic: {topic}.\nWrite {style}\nOutput only the questions.",
        "Numbered questions.",
    )


# ---------------- Answer Evaluation Agent ----------------
def evaluate_answer(exam, subject, topic, question, answer):
    out = _ask(
        "evaluator",
        f"Exam: {exam}. Subject: {subject}. Topic: {topic}.\nQUESTION: {question[:1200]}\n"
        f"STUDENT ANSWER: {answer[:3000]}\n"
        "Pick a rubric that fits: essay -> introduction, arguments, evidence, critical analysis, conclusion; "
        "numerical -> concept, formula, calculation, application; recall subjects -> recall, understanding, application.\n"
        "Return ONLY JSON: {\"score\": 0-100, \"mistake_type\": one of "
        "[\"Concept gap\",\"Memory gap\",\"Application problem\",\"Calculation error\",\"Misinterpretation\",\"Careless mistake\",\"None\"], "
        "\"strengths\": [str], \"gaps\": [str], \"improvement\": \"2 sentences\"}",
        "A JSON object only.",
    )
    data = extract_json(out)
    return data if isinstance(data, dict) else None


# ---------------- Progress Auditor ----------------
def audit_report(rows):
    return _ask(
        "auditor",
        "Write a short progress audit (under 120 words). Say which topics are RECOVERED, which are "
        "IMPROVING, which are STILL WEAK and must go back to the Priority step. Use only these numbers.\n"
        f"DATA: {json.dumps(rows[:20])}",
        "Short audit.",
    )

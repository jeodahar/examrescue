# 🛟 ExamRescue AI

Multi-agent exam recovery: **Plan → Study → Assess → Analyze → Recover → Re-plan**.
Stack: Python · CrewAI · Groq (`openai/gpt-oss-120b`) · Streamlit · SQLite · GitHub.

## Improved agent design

Key idea: **numbers are calculated by Python (`engine.py`), words are written by agents.**
This makes plans consistent, cheaper, and fits the Groq free limit (~8,000 tokens/minute).

| Agent | Input | Tool / logic | Output |
|---|---|---|---|
| Orchestrator | Student's free text | LLM → JSON | missed days, severity, advice, next steps |
| Syllabus | Pasted text / PDF (PyMuPDF) | LLM → JSON | subject, topic, importance 1-5, hours |
| Past Paper | Paper text + topic names | LLM → JSON | topic frequency 0-5 |
| Progress | Logs + topics | `engine.progress` | planned %, actual %, study debt, missed days |
| Performance | Quiz scores | `engine.band` | 🟢 🟡 🟠 🔴 per topic + mistake type |
| Priority | Importance, weakness, past-paper frequency, unstudied hours | `engine.rank` | priority 0-1 |
| Recovery Planner | Priority + days left + hours/day | `engine.recovery_plan` + LLM explanation | MUST / COMPRESS / POSTPONE / SKIP + feasibility |
| Daily Study | MUST/COMPRESS topics | LLM | timetable with practice and review |
| Assessment | Topic + type | LLM | MCQ / short / long questions |
| Evaluator | Question + answer | LLM → JSON | score, mistake type, gaps, improvement |
| Progress Auditor | Assessment history | `engine.audit` + LLM | RECOVERED / IMPROVING / STILL WEAK |

**Priority formula:** 35% importance + 30% weakness + 20% past-paper frequency + 15% unstudied hours.
**Honesty rule:** if critical topics need more hours than you have, the app says so.
**The loop:** quiz → score saved → priority changes → new recovery plan.

## Files

```
app.py          Streamlit screens (incl. 💬 Coach tab)
agents.py       agent roles + prompts
coach.py        chatbot: voice in (Groq Whisper), coach agent, voice out (gTTS)
replan.py       auto re-plan when a missed day is logged
webfetch.py     finds a syllabus online (web search) and reads web pages / PDFs
engine.py       priority, recovery, progress, audit (plain Python)
database.py     SQLite memory + backup/restore
llm_setup.py    Groq connection + safe agent runner
requirements.txt
```

## Beginner steps (no installation needed)

### 1. Get a Groq key
1. Open console.groq.com and sign in.
2. API Keys → Create API Key → copy it (starts with `gsk_`).

### 2. Put the code on GitHub
1. github.com → **New repository** → name `examrescue` → Create.
2. **Add file → Upload files**.
3. Drag in all 9 files (`app.py`, `agents.py`, `coach.py`, `replan.py`, `webfetch.py`, `engine.py`, `database.py`, `llm_setup.py`, `requirements.txt`).
4. Click **Commit changes**. The files must be in the main folder, not inside a sub-folder.

### 3. Deploy on Streamlit Cloud
1. share.streamlit.io → **Create app** → choose your repo.
2. Branch `main`, main file `app.py`.
3. **Advanced settings** → Python version **3.11** → in **Secrets** paste:
   ```
   GROQ_API_KEY = "gsk_your_key_here"
   ```
4. Click **Deploy** (first build takes a few minutes).

### 4. Use it
1. **Setup**: save exam name/date/hours → paste syllabus → *Build topics*.
2. Edit the topic table if needed (importance, hours, scores).
3. **Check-in**: log study sessions or missed days.
4. **Recovery**: see the plan and the feasibility verdict.
5. **Today**: get a timetable.
6. **Quiz**: generate questions, answer, get scored.
7. **Audit**: see before/after.

## 🌐 Find the syllabus online
1. Setup → type the exam name (for example `MDCAT`) → **Find online** → **Search online**.
2. Pick a source (official sites and PDFs are listed first) or paste your own link.
3. **Read this page**, delete unrelated text if needed, then **Build topics**.
Always compare with the official exam website. Syllabi change every year.

## 💬 Coach chatbot with voice
- Open the **Coach** tab. Choose English or Urdu.
- Tap **Record your question**, speak, stop. Groq Whisper turns it into text, the Coach answers using your real data, and the answer is read aloud.
- You can also type. Turn off "Read answers aloud" if you only want text.
- Allow microphone access in your browser when asked.

## 🔄 Auto re-plan
- Pressing **I missed today**, accepting missed days from the Orchestrator, or telling the Coach "I missed today / yesterday" will log the day and rebuild the plan automatically.
- The Recovery tab shows what changed (for example `Algebra: COMPRESS -> MUST RECOVER`) plus a short explanation, and keeps the latest saved plan.
- Questions like "what if I miss today?" are NOT treated as a missed day.

## Important notes
- **Data can reset.** Streamlit Cloud storage is temporary. Use **Download backup** in the sidebar regularly. (Supabase can be added later for permanent storage.)
- **Keep the app private** (Streamlit → Share) because all visitors share one database.
- If Groq says rate limit, wait 1 minute. Agents run one at a time to stay within the free plan.
- To update code later: GitHub → open the file → pencil icon → edit → Commit. Streamlit redeploys itself.

## Next phase (not in this MVP)
Handwritten answer photos (OCR), PDF reports (ReportLab), multi-user login, Supabase storage.

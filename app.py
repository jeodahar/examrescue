import hashlib
import json
import os
from datetime import date, datetime, timedelta

import pandas as pd
import streamlit as st

st.set_page_config(page_title="ExamRescue AI", page_icon="🛟", layout="wide")

# Groq key: Streamlit Cloud "Secrets" (or an environment variable)
try:
    _key = st.secrets["GROQ_API_KEY"]
except Exception:
    _key = os.environ.get("GROQ_API_KEY", "")
if _key:
    os.environ["GROQ_API_KEY"] = _key

import agents  # noqa: E402
import coach  # noqa: E402
import database as db  # noqa: E402
import engine  # noqa: E402
import replan  # noqa: E402

db.init()


def flash(msg):
    st.session_state["flash"] = msg
    st.rerun()


def pdf_to_text(uploaded):
    import fitz  # PyMuPDF

    doc = fitz.open(stream=uploaded.read(), filetype="pdf")
    return "\n".join(page.get_text() for page in doc)


if "flash" in st.session_state:
    st.success(st.session_state.pop("flash"))

# ------------------------------------------------------------------ sidebar
with st.sidebar:
    st.title("🛟 ExamRescue AI")
    if not os.environ.get("GROQ_API_KEY"):
        st.error("GROQ_API_KEY is missing. Add it in Streamlit → Settings → Secrets.")
    st.caption("Plan → Study → Assess → Analyze → Recover → Re-plan")
    st.divider()
    st.markdown("**💾 Backup** (data can reset when the app sleeps)")
    st.download_button("⬇️ Download backup", db.export_json(), "examrescue_backup.json", "application/json")
    up = st.file_uploader("Restore a backup", type="json", key="restore_file")
    if up is not None and st.button("Restore now"):
        try:
            db.import_json(up.getvalue().decode("utf-8"))
            flash("Backup restored.")
        except Exception as e:
            st.error(f"Could not restore: {e}")

prof = db.get_profile()
tdf = db.topics_df()

tabs = st.tabs(["⚙️ Setup", "📊 Dashboard", "📝 Check-in", "🛟 Recovery", "📅 Today", "🧪 Quiz", "🔍 Audit", "💬 Coach"])


def need_setup():
    if not prof or tdf.empty:
        st.info("Go to **Setup** first: save exam details and add topics.")
        return True
    return False


# ------------------------------------------------------------------ SETUP
with tabs[0]:
    st.subheader("1️⃣ Exam details")
    c1, c2, c3 = st.columns(3)
    exam = c1.text_input("Exam name", prof["exam"] if prof else "CSS 2027")
    default_date = date.fromisoformat(prof["exam_date"]) if prof else date.today() + timedelta(days=60)
    exam_date = c2.date_input("Exam date", default_date)
    hours = c3.number_input("Study hours per day", 1.0, 16.0, float(prof["daily_hours"]) if prof else 4.0, 0.5)
    if st.button("💾 Save exam details"):
        db.save_profile(exam, exam_date, hours)
        flash("Exam details saved.")

    st.subheader("2️⃣ Syllabus → topics (Syllabus Agent)")
    mode = st.radio("How do you want to add the syllabus?", ["Paste text", "Upload PDF"], horizontal=True)
    syllabus_text = ""
    if mode == "Paste text":
        syllabus_text = st.text_area("Paste the syllabus", height=160)
    else:
        f = st.file_uploader("Syllabus PDF", type="pdf", key="syl_pdf")
        if f:
            syllabus_text = pdf_to_text(f)
            st.caption(f"Read {len(syllabus_text)} characters (first 16,000 are used).")
    if st.button("🤖 Build topics with the Syllabus Agent"):
        if not prof:
            st.warning("Save exam details first.")
        elif len(syllabus_text.strip()) < 30:
            st.warning("Add some syllabus text first.")
        else:
            with st.spinner("Syllabus Agent is reading... (can take 1-2 minutes)"):
                try:
                    found = agents.extract_syllabus(syllabus_text, prof["exam"])
                    n = db.add_topics(found)
                    flash(f"Added {n} new topics.")
                except Exception as e:
                    st.error(f"Agent error: {e}")

    st.subheader("3️⃣ Your topics (you can edit the table)")
    if tdf.empty:
        st.info("No topics yet. Use the Syllabus Agent above.")
    else:
        edited = st.data_editor(
            tdf, hide_index=True, disabled=["id", "subject", "topic"], key="topics_editor",
            column_config={
                "importance": st.column_config.NumberColumn("Importance 1-5", min_value=1, max_value=5, step=1),
                "hours_needed": st.column_config.NumberColumn("Hours needed", min_value=0.5, step=0.5),
                "hours_done": st.column_config.NumberColumn("Hours done", min_value=0.0, step=0.5),
                "score": st.column_config.NumberColumn("Score % (empty = not tested)", min_value=0, max_value=100),
                "past_freq": st.column_config.NumberColumn("Past-paper 0-5", min_value=0, max_value=5, step=1),
            },
        )
        b1, b2 = st.columns(2)
        if b1.button("💾 Save table changes"):
            db.update_topics(edited)
            flash("Table saved.")
        if b2.checkbox("I want to delete ALL topics") and b2.button("🗑️ Delete all topics"):
            db.clear_topics()
            flash("All topics deleted.")

        st.subheader("4️⃣ Past papers (Past Paper Agent) - optional")
        pp_mode = st.radio("Past paper input", ["Paste text", "Upload PDF"], horizontal=True)
        pp_text = ""
        if pp_mode == "Paste text":
            pp_text = st.text_area("Paste a past paper", height=140)
        else:
            pf = st.file_uploader("Past paper PDF", type="pdf", key="pp_pdf")
            if pf:
                pp_text = pdf_to_text(pf)
        if st.button("🤖 Analyse past paper") and pp_text.strip():
            with st.spinner("Past Paper Agent is working..."):
                try:
                    mapping = agents.analyze_past_paper(pp_text, tdf["topic"].tolist())
                    n = db.set_past_freq(mapping)
                    flash(f"Updated past-paper frequency for {n} topics.")
                except Exception as e:
                    st.error(f"Agent error: {e}")

# ------------------------------------------------------------------ DASHBOARD
with tabs[1]:
    if not need_setup():
        prog = engine.progress(prof, tdf, db.get_logs())
        st.subheader(f"🎯 {prof['exam']}")
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Days remaining", engine.days_left(prof))
        m2.metric("Planned progress", f"{prog['planned_pct']}%")
        m3.metric("Actual progress", f"{prog['actual_pct']}%")
        m4.metric("Study debt", f"{prog['study_debt_pct']}%", f"{prog['missed_days']} missed days", delta_color="off")
        st.progress(min(prog["actual_pct"] / 100, 1.0), text=f"{prog['hours_done']}h of {prog['hours_needed']}h studied")
        counts = engine.band_counts(tdf)
        st.bar_chart(pd.Series(counts))
        top = engine.rank(tdf).iloc[0]
        st.info(f"**Next priority:** {top['subject']} - {top['topic']}  (priority {top['priority']})")

# ------------------------------------------------------------------ CHECK-IN
with tabs[2]:
    if not need_setup():
        st.subheader("Log today")
        opts = {f"{r.subject} - {r.topic}": int(r.id) for r in tdf.itertuples()}
        sel = st.selectbox("Topic you studied", list(opts))
        hrs = st.number_input("Hours studied", 0.0, 12.0, 1.0, 0.5)
        l1, l2 = st.columns(2)
        if l1.button("✅ Log study session"):
            db.add_log(hrs, 0, opts[sel])
            flash("Study session logged.")
        if l2.button("❌ I missed today (auto re-plan)"):
            with st.spinner("Recording and rebuilding your plan..."):
                flash(replan.log_missed_and_replan())

        st.subheader("Tell the Orchestrator what happened")
        situation = st.text_area(
            "Example: I missed 5 days, my Mathematics score fell, and my exam is 25 days away.", height=100)
        if st.button("🤖 Ask the Orchestrator") and situation.strip():
            weak = [f"{r['topic']}" for _, r in engine.rank(tdf).head(5).iterrows()]
            ctx = {"days_left": engine.days_left(prof), "top_priority_topics": weak}
            with st.spinner("Orchestrator is thinking..."):
                try:
                    st.session_state["orch"] = agents.orchestrate(situation, ctx)
                except Exception as e:
                    st.error(f"Agent error: {e}")
        o = st.session_state.get("orch")
        if o:
            st.write(f"**Severity:** {o.get('severity', '-')}")
            st.write(o.get("advice", ""))
            st.write(f"**Suggested next steps:** {', '.join(o.get('next_steps', [])) or '-'}")
            miss = int(o.get("missed_days") or 0)
            if miss > 0 and st.button(f"Record {miss} missed days in my log"):
                with st.spinner("Recording and rebuilding your plan..."):
                    for i in range(miss):
                        db.add_log(0, 1, None)
                    replan.auto_replan()
                st.session_state.pop("orch", None)
                flash(f"{miss} missed days recorded. Plan rebuilt automatically.")

# ------------------------------------------------------------------ RECOVERY
with tabs[3]:
    if not need_setup():
        plan, summ = engine.recovery_plan(prof, tdf)
        k = summ["counts"]
        r1, r2, r3, r4 = st.columns(4)
        r1.metric("🔴 Must recover", k["MUST RECOVER"])
        r2.metric("🟡 Compress", k["COMPRESS"])
        r3.metric("🔵 Postpone", k["POSTPONE"])
        r4.metric("🟢 Skip", k["SKIP"])
        st.write(f"Study budget until the exam: **{summ['total_budget_hours']} h** "
                 f"(15% kept as buffer). Critical topics need **{summ['critical_hours_needed']} h**.")
        if summ["feasible"]:
            st.success("✅ Recovery is possible without moving the exam date.")
        else:
            st.error(f"⚠️ Not everything critical fits. You are short by about {summ['shortfall_hours']} h. "
                     "Add study hours, accept lower coverage, or consider moving the exam.")
        st.dataframe(plan)

        if st.button("🔄 Rebuild plan now"):
            with st.spinner("Recovery Planner is rebuilding the plan..."):
                replan.auto_replan()
            flash("Plan rebuilt.")

        last = db.latest_plan()
        if last:
            st.subheader(f"Latest auto re-plan ({last['created']})")
            changes = json.loads(last["changes"] or "[]")
            if changes:
                st.write("**What changed since the previous plan:**")
                for c in changes[:12]:
                    st.write(f"- {c}")
            else:
                st.caption("No category changes since the previous plan.")
            if last["narrative"]:
                st.markdown(last["narrative"])
        else:
            st.caption("No saved plan yet. It is created automatically when you log a missed day.")

# ------------------------------------------------------------------ TODAY
with tabs[4]:
    if not need_setup():
        plan, summ = engine.recovery_plan(prof, tdf)
        t1, t2 = st.columns(2)
        total = t1.number_input("Hours available today", 1.0, 16.0, float(prof["daily_hours"]), 0.5, key="today_hours")
        start = t2.time_input("Start time", datetime.strptime("09:00", "%H:%M").time())
        if st.button("🤖 Build today's schedule"):
            left, items = total, []
            for r in plan[plan["category"].str.contains("MUST|COMPRESS")].itertuples():
                if left <= 0:
                    break
                h = min(r.hours, left)
                items.append({"topic": r.topic, "subject": r.subject, "hours": round(h, 1)})
                left -= h
            if not items:
                st.info("Nothing urgent left - great job. Take a quiz to confirm.")
            else:
                with st.spinner("Daily Study Agent is planning..."):
                    try:
                        st.session_state["today"] = agents.daily_schedule(items, total, start.strftime("%H:%M"))
                    except Exception as e:
                        st.error(f"Agent error: {e}")
        if st.session_state.get("today"):
            st.markdown(st.session_state["today"])

# ------------------------------------------------------------------ QUIZ
with tabs[5]:
    if not need_setup():
        opts = {f"{r.subject} - {r.topic}": r for r in tdf.itertuples()}
        label = st.selectbox("Topic", list(opts), key="quiz_topic")
        row = opts[label]
        q1, q2 = st.columns(2)
        kind = q1.selectbox("Question type", ["MCQ", "Short questions", "Long question"])
        n = q2.number_input("How many", 1, 8, 4)
        if st.button("🤖 Generate questions"):
            with st.spinner("Assessment Agent is writing questions..."):
                try:
                    st.session_state["questions"] = agents.make_questions(
                        prof["exam"], row.subject, row.topic, kind, int(n))
                except Exception as e:
                    st.error(f"Agent error: {e}")
        if st.session_state.get("questions"):
            st.markdown(st.session_state["questions"])

        st.subheader("Answer one question")
        question = st.text_area("Copy the question here", height=80)
        answer = st.text_area("Type your answer", height=200)
        if st.button("🤖 Evaluate my answer"):
            if not question.strip() or not answer.strip():
                st.warning("Add the question and your answer.")
            else:
                with st.spinner("Evaluation Agent is marking..."):
                    try:
                        res = agents.evaluate_answer(prof["exam"], row.subject, row.topic, question, answer)
                    except Exception as e:
                        res = None
                        st.error(f"Agent error: {e}")
                if res and "score" in res:
                    score = float(res["score"])
                    db.add_assessment(row.id, score, res.get("mistake_type", "None"), res.get("improvement", ""))
                    st.metric("Score", f"{score:.0f}%", engine.band(score))
                    st.write(f"**Mistake type:** {res.get('mistake_type', '-')}")
                    st.write("**Strengths:** " + "; ".join(res.get("strengths", [])))
                    st.write("**Gaps:** " + "; ".join(res.get("gaps", [])))
                    st.write("**How to improve:** " + str(res.get("improvement", "")))
                    st.caption("Saved. The topic score and the recovery plan are updated.")
                elif res is None:
                    pass
                else:
                    st.warning("The agent did not return a score. Try again.")

# ------------------------------------------------------------------ AUDIT
with tabs[6]:
    if not need_setup():
        aud = engine.audit(db.assessments_df())
        if aud.empty:
            st.info("No assessments yet. Take a quiz first.")
        else:
            st.dataframe(aud)
            st.caption("Topics marked STILL WEAK automatically rank higher in the next Recovery plan - that is the loop.")
            if st.button("🤖 Ask the Progress Auditor"):
                with st.spinner("Auditor is writing..."):
                    try:
                        st.session_state["audit"] = agents.audit_report(aud.to_dict("records"))
                    except Exception as e:
                        st.error(f"Agent error: {e}")
            if st.session_state.get("audit"):
                st.markdown(st.session_state["audit"])

# ------------------------------------------------------------------ COACH (chatbot + voice)
with tabs[7]:
    if not need_setup():
        st.subheader("💬 Study Coach")
        cc1, cc2 = st.columns(2)
        language = cc1.radio("Voice language", ["English", "Urdu"], horizontal=True)
        speak_on = cc2.toggle("🔊 Read answers aloud", value=True)
        st.caption("Ask about your progress, priorities, or a topic. "
                   "Say or type \"I missed today\" and the plan rebuilds automatically.")

        if "chat" not in st.session_state:
            st.session_state["chat"] = []
        if not st.session_state["chat"]:
            st.chat_message("assistant").write(coach.greeting())
        for m in st.session_state["chat"]:
            st.chat_message(m["role"]).write(m["content"])

        # play the latest spoken answer (auto-play only once)
        voice = st.session_state.get("voice_reply")
        if voice:
            st.audio(voice["bytes"], format="audio/mp3", autoplay=not voice["played"])
            voice["played"] = True

        audio = st.audio_input("🎤 Record your question")
        with st.form("chat_form", clear_on_submit=True):
            typed = st.text_input("Or type your question")
            sent = st.form_submit_button("Send")

        question = None
        if sent and typed.strip():
            question = typed.strip()
        elif audio is not None:
            data = audio.getvalue()
            h = hashlib.md5(data).hexdigest()
            if h != st.session_state.get("last_audio"):
                st.session_state["last_audio"] = h
                with st.spinner("Transcribing your voice..."):
                    try:
                        question = coach.transcribe(data, language)
                    except Exception as e:
                        st.error(f"Could not transcribe: {e}")
                if question is not None and not question:
                    st.warning("I could not hear anything. Please record again.")
                    question = None

        if question:
            history = list(st.session_state["chat"])
            st.session_state["chat"].append({"role": "user", "content": question})
            when = coach.missed_day_intent(question)
            with st.spinner("Coach is thinking..."):
                try:
                    if when:
                        day = (date.today() - timedelta(days=1)).isoformat() if when == "yesterday" else None
                        reply = replan.log_missed_and_replan(day)
                    else:
                        reply = coach.ask_coach(question, history, language)
                except Exception as e:
                    reply = f"Sorry, something went wrong: {e}"
            st.session_state["chat"].append({"role": "assistant", "content": reply})
            if speak_on:
                mp3 = coach.speak(reply, language)
                st.session_state["voice_reply"] = {"bytes": mp3, "played": False} if mp3 else None
            st.rerun()

        if st.session_state["chat"] and st.button("🧹 Clear chat"):
            st.session_state["chat"] = []
            st.session_state["voice_reply"] = None
            st.rerun()

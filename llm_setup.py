"""llm_setup.py - connects CrewAI to Groq and runs ONE agent per call.

Why one agent per call? The Groq free plan allows only ~8,000 tokens per minute
for openai/gpt-oss-120b, so we keep every prompt small and run agents one by one.
"""
import os
import time

os.environ.setdefault("OTEL_SDK_DISABLED", "true")  # no telemetry
os.environ.setdefault("CREWAI_DISABLE_TELEMETRY", "true")

from crewai import LLM, Agent, Crew, Process, Task  # noqa: E402

MODEL = "groq/openai/gpt-oss-120b"

# ---- Compatibility patch -------------------------------------------------
# Some CrewAI + LiteLLM versions add keys that Groq rejects
# ("cache_breakpoint" / "is_litellm"). We strip them before the call.
try:
    import litellm

    if not getattr(litellm, "_examrescue_patched", False):
        _orig_completion = litellm.completion

        def _clean_messages(msgs):
            cleaned = []
            for m in msgs or []:
                if isinstance(m, dict):
                    m = {k: v for k, v in m.items() if k != "cache_breakpoint"}
                cleaned.append(m)
            return cleaned

        def _patched_completion(*args, **kwargs):
            if "messages" in kwargs:
                kwargs["messages"] = _clean_messages(kwargs["messages"])
            kwargs.pop("is_litellm", None)
            return _orig_completion(*args, **kwargs)

        litellm.completion = _patched_completion
        litellm._examrescue_patched = True
except Exception:
    pass
# --------------------------------------------------------------------------


def get_llm():
    return LLM(
        model=MODEL,
        api_key=os.environ.get("GROQ_API_KEY", ""),
        temperature=0.3,
        max_tokens=2000,
    )


def run_agent(role, goal, backstory, task, expected, retries=3):
    """Build a one-agent crew, run it, and return the text answer."""
    agent = Agent(
        role=role, goal=goal, backstory=backstory,
        llm=get_llm(), verbose=False, allow_delegation=False,
    )
    t = Task(description=task, expected_output=expected, agent=agent)
    crew = Crew(agents=[agent], tasks=[t], process=Process.sequential, verbose=False)
    last = None
    for attempt in range(retries):
        try:
            return str(crew.kickoff())
        except Exception as e:  # rate limit -> wait and retry
            last = e
            msg = str(e).lower()
            if "rate" in msg or "429" in msg or "tokens per minute" in msg:
                time.sleep(20 * (attempt + 1))
                continue
            raise
    raise RuntimeError(f"Groq is rate-limiting. Wait one minute and try again. ({last})")

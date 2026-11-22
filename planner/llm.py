"""LLM providers with auto-fallback. Tokens and model name come only from the API response."""
import os
import time
from pathlib import Path
import requests

ROOT = Path(__file__).resolve().parent.parent
# provider -> (url, api-key env var, default small model). Override model with <PROVIDER>_MODEL.
P = {"groq": ("https://api.groq.com/openai/v1/chat/completions", "GROQ_API_KEY", "openai/gpt-oss-20b"),
     "groq_alt": ("https://api.groq.com/openai/v1/chat/completions", "GROQ_API_KEY", "allam-2-7b"),
     "gemini": ("https://generativelanguage.googleapis.com/v1beta/openai/chat/completions", "GEMINI_API_KEY",
                "gemini-2.0-flash-lite"),
     "openai": ("https://api.openai.com/v1/chat/completions", "OPENAI_API_KEY", "gpt-4o-mini"),
     "anthropic": ("https://api.anthropic.com/v1/messages", "ANTHROPIC_API_KEY", "claude-haiku-4-5"),
     "ollama": ("/v1/chat/completions", None, "llama3.1:8b")}


class LLMError(Exception):
    pass


def _env():
    f = ROOT / ".env"
    if f.exists():
        for line in f.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.strip().startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"'))


def providers():
    _env()
    dflt = "groq,gemini,openai,anthropic"            # groq_alt (allam-2-7b) only if listed in PLANNER_PROVIDERS + (",ollama" if os.environ.get("OLLAMA_URL") else "")
    order = [p.strip() for p in os.environ.get("PLANNER_PROVIDERS", dflt).split(",")]
    return [p for p in order if p in P and (not P[p][1] or os.environ.get(P[p][1]))]


def model_of(p):
    return os.environ.get(p.upper() + "_MODEL", P[p][2])


def _call(p, prompt, timeout, json_mode=True):
    url, key, _ = P[p]
    model = model_of(p)
    if p == "anthropic":
        r = requests.post(url, timeout=timeout, headers={"x-api-key": os.environ[key], "anthropic-version": "2023-06-01"},
                          json={"model": model, "max_tokens": 4096, "temperature": 0,
                                "messages": [{"role": "user", "content": prompt}]})
        r.raise_for_status()
        j = r.json()
        u = j.get("usage")
        return ("".join(b.get("text", "") for b in j.get("content", [])), j.get("model", model),
                {"prompt": u.get("input_tokens"), "completion": u.get("output_tokens")} if u else None)
    if p == "ollama":
        url = os.environ.get("OLLAMA_URL", "http://localhost:11434") + url
    h = {"Authorization": "Bearer " + os.environ[key]} if key else {}
    body = {"model": model, "temperature": 0, "max_tokens": 3000, "messages": [{"role": "user", "content": prompt}]}
    if json_mode:
        body["response_format"] = {"type": "json_object"}
    if "gpt-oss" in model:
        body["reasoning_effort"] = "low"   # fewer hidden reasoning tokens
    r = requests.post(url, headers=h, timeout=timeout, json=body)
    r.raise_for_status()
    j = r.json()
    u = j.get("usage")
    return (j["choices"][0]["message"]["content"], j.get("model", model),
            {"prompt": u.get("prompt_tokens"), "completion": u.get("completion_tokens"),
             "total": u.get("total_tokens")} if u else None)


class Budget:
    """Hard cap on model calls per run; every attempt is a numbered call in the trace."""

    def __init__(self, st, tr, max_calls, timeout):
        self.st, self.tr, self.max, self.used, self.timeout = st, tr, max_calls, 0, timeout

    def left(self):
        return self.max - self.used

    def call(self, prompt, area):
        provs = providers()
        if not provs:
            raise LLMError("no LLM provider: set GROQ_API_KEY / GEMINI_API_KEY / OPENAI_API_KEY / "
                           "ANTHROPIC_API_KEY (env or .env) or set PLANNER_PROVIDERS=ollama")
        for p in provs:
            if self.left() <= 0:
                raise LLMError(f"call budget of {self.max} per run exhausted")
            self.used += 1
            self.st["calls"] += 1
            t = time.time()
            try:
                try:
                    text, model, usage = _call(p, prompt, self.timeout)
                except requests.HTTPError as e:      # rate limit: wait for the reset once if it is short
                    code = e.response.status_code if e.response is not None else 0
                    if code == 400 and p != "anthropic":   # strict JSON check failed: same model once, JSON mode off
                        self.tr.code(f"provider {p} returned 400 (JSON validation); retrying once without JSON mode "
                                     f"(same numbered call)")
                        text, model, usage = _call(p, prompt, self.timeout, json_mode=False)
                        self.tr.call(self.st["calls"], model, area, prompt, text, usage, secs=time.time() - t)
                        return text
                    wait = float(e.response.headers.get("retry-after", 99)) if e.response is not None else 99
                    if e.response is None or code != 429 or wait > 45:
                        raise
                    self.tr.code(f"provider {p} rate-limited (429); waiting {wait:g} s then retrying (same numbered call)")
                    time.sleep(wait)
                    text, model, usage = _call(p, prompt, self.timeout)
            except Exception as e:
                self.tr.call(self.st["calls"], f"{p}/{model_of(p)}", area, prompt, None, None,
                             err=f"{type(e).__name__}: {str(e)[:160]} -> fallback", secs=time.time() - t)
                continue
            self.tr.call(self.st["calls"], model, area, prompt, text, usage, secs=time.time() - t)
            return text
        raise LLMError("all providers failed")

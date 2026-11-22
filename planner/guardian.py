"""MTM Guardian: deterministic trust & security layer (pure Python, 0 model calls).

Flow: raw message text -> [scan: prompt injection / secret requests] -> AI reader -> [Guardian quarantine]
      -> resolver (authority matrix) -> planner -> six checks (commit only if valid) -> [audit: SHA-256 chain].

Notes
- Sender names in a text file are CLAIMED identities, not verified ones. Roles come from a keyword rule on the
  claimed name (reader.role_of) and the authority matrix (resolver.OWN); nothing is cryptographically proven.
- The audit chain is tamper-EVIDENT, not tamper-proof: anyone who can rewrite the whole state file can rebuild a
  valid chain. The chain head is printed into trace.txt each run (an external checkpoint once uploaded).
"""
import hashlib
import json
import os
import re
from datetime import datetime

# --- Feature A: prompt-injection patterns (instruction + target, so ordinary words like "ignore" alone pass) ---
INJECTION = [
    ("override instructions", r"\b(ignore|disregard|forget|override)\b[^.\n]{0,40}\b(previous|prior|above|all|earlier|system|your)\b[^.\n]{0,25}\b(instruction|rule|prompt|polic|guideline)"),
    ("role hijack", r"\byou are (now|no longer)\b|\bact as (the )?(system|admin|developer|root)\b|\b(admin|developer|god|jailbreak|dan) mode\b"),
    ("system prompt tampering", r"\b(change|reveal|show|print|repeat|update|replace)\b[^.\n]{0,25}\bsystem prompt\b"),
    ("hide from audit", r"\b(hide|conceal|don'?t (show|log|record)|do not (show|log|record)|remove|delete|skip|erase)\b[^.\n]{0,40}\b(trace|log|audit|record|history|this change)\b"),
    ("disable safeguards", r"\b(disable|turn off|bypass|skip|switch off)\b[^.\n]{0,30}\b(validation|check|guard|guardian|rule|security|verification)"),
    ("secret request", r"\b(reveal|show|send|share|print|give|tell|leak|bata\w*|de\s?do|bhej\w*)\b[^.\n]{0,40}\b(api[ _-]?key|password|secret|token|credential|\.env)"),
    ("secret request", r"\b(api[ _-]?key|password|credential)\b[^.\n]{0,40}\b(bata\w*|de\s?do|bhej\w*|send|reveal|share)\b"),
    ("override instructions (Roman Urdu)", r"\b(pichl\w*|pehl\w*|sab|tamam)\b[^.\n]{0,30}\b(hidayat|instructions?|rules?|qawaid|qanoon)\b[^.\n]{0,30}\b(ignore|bhool|nazar ?andaz|chhor|chor)"),
    ("hide from audit (Roman Urdu)", r"\b(trace|log|record|audit)\b[^.\n]{0,30}\b(mat|na|nahi?)\b[^.\n]{0,15}\b(dikha\w*|likh\w*|show|batao)|\b(chupa\w*|chhupa\w*)\b"),
    ("disable safeguards (Roman Urdu)", r"\b(validation|checks?|rules?)\b[^.\n]{0,25}\b(band kar\w*|off kar\w*|hata\w*|skip kar\w*)"),
]
SECRET = re.compile(r"\b(gsk_[A-Za-z0-9]{20,}|sk-[A-Za-z0-9_-]{20,}|AIza[0-9A-Za-z_-]{30,}|sk-ant-[A-Za-z0-9_-]{20,})\b")


def redact(s):
    """Feature E: strip API keys (known formats + any configured key value) from text shown or stored."""
    if not isinstance(s, str) or not s:
        return s
    s = SECRET.sub("[REDACTED-SECRET]", s)
    for k in ("GROQ_API_KEY", "GEMINI_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY"):
        v = os.environ.get(k)
        if v and len(v) > 8:
            s = s.replace(v, "[REDACTED-SECRET]")
    return s


def scan(text):
    """Return a list of (category, matched phrase) found in untrusted message text."""
    hits = []
    for cat, rx in INJECTION:
        for m in re.finditer(rx, text, re.I):
            hits.append((cat, m.group(0)[:80]))
    if SECRET.search(text):
        hits.append(("secret in message", "[REDACTED-SECRET]"))
    return hits


def paragraphs(chunk):
    return [p.strip() for p in re.split(r"\n\s*\n", chunk) if p.strip()]


def attribute(chunk, msgs):
    """Map each message (index in msgs) to the paragraph(s) of raw text that most likely belong to it."""
    paras, out = paragraphs(chunk), {}
    if len(msgs) == 1:
        return {0: chunk.strip()}
    if len(paras) == len(msgs):
        return {i: p for i, p in enumerate(paras)}
    used = set()
    for i, m in enumerate(msgs):
        name = str(m.get("frm", "")).lower()[:20]
        for j, p in enumerate(paras):
            if j not in used and name and name in p.lower():
                out[i] = p
                used.add(j)
                break
    return out


def screen(chunk, msgs, tr):
    """Feature A: run before the resolver. Messages with injection attempts are quarantined: none of their
    facts may change the plan. Returns {msg index: guardian record} for the audit."""
    texts, res = attribute(chunk, msgs), {}
    unassigned = scan("\n".join(p for p in paragraphs(chunk) if p not in texts.values())) if len(msgs) > 1 else []
    for i, m in enumerate(msgs):
        raw = texts.get(i, "")
        hits = scan(raw)
        res[i] = dict(raw=redact(raw), hits=hits, quarantined=bool(hits))
        if hits:
            m["quarantine"] = "; ".join(sorted({c for c, _ in hits}))
            tr.code(f"guardian  msg from '{m.get('frm')}' QUARANTINED: prompt-injection/secret pattern "
                    f"({m['quarantine']}: \"{hits[0][1]}\"); its facts cannot change the plan")
    if unassigned:
        tr.code(f"guardian  injection pattern in text not tied to one message: {unassigned[0][0]} (flagged)")
    return res


# --- Decisions (built on the resolver/planner/check results; no logic duplicated) ---
def decide(st, M, facts, infeasible, committed):
    """Classify one message: ACCEPTED / ACCEPTED (INFEASIBLE) / REJECTED / FLAGGED / QUARANTINED + risk."""
    S = [f["status"] for f in facts]
    if M.get("quarantine"):
        return "QUARANTINED", "high", f"prompt-injection defence: {M['quarantine']}; message treated as untrusted data, no facts applied"
    if "rejected" in S:
        why = next(f["reason"] for f in facts if f["status"] == "rejected")
        return "REJECTED", "medium", why
    if M["role"] == "unknown" or M.get("role_override"):
        note = "sender role unknown" if M["role"] == "unknown" else f"claimed sender role corrected ({M['role_override']})"
        if any(s == "applied" for s in S):
            return "FLAGGED", "low", f"{note}; applied facts kept but marked for human review"
        return "FLAGGED", "low", f"{note}; nothing applied"
    if any(s == "dropped" for s in S):
        return "FLAGGED", "low", "a number the model extracted is not in the message (hallucination dropped)"
    if M.get("status") == "no impact":
        return "ACCEPTED", "none", "no impact on the plan: " + (M.get("reason") or "no plan facts")[:160]
    if any(s == "applied" for s in S) and infeasible and all(x.startswith("provide: ") for x in st.get("infeasible") or []):
        return "ACCEPTED", "none", "applied; plan started, details still needed: " + "; ".join(
            x[len("provide: "):] for x in st["infeasible"])
    if any(s == "applied" for s in S) and infeasible:
        return "ACCEPTED (INFEASIBLE)", "none", f"legitimate change applied, but no valid plan exists: {infeasible}; last valid plan kept"
    if any(s in ("applied", "request") for s in S):
        return "ACCEPTED", "none", "authorised by the authority matrix; plan re-validated with the six checks" + (
            "" if committed else "; plan not committed")
    return "ACCEPTED", "none", "no plan facts (no impact)"


# --- Feature D: SHA-256 hash-chained audit log ---
def canon(o):
    return json.dumps(o, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def h(entry):
    body = {k: v for k, v in entry.items() if k != "hash"}
    return hashlib.sha256(canon(body).encode("utf-8")).hexdigest()


def append(st, entry):
    chain = st.setdefault("audit", [])
    entry = dict(entry, seq=len(chain) + 1, prev=chain[-1]["hash"] if chain else "0" * 64)
    entry["hash"] = h(entry)
    chain.append(entry)
    return entry


def verify(chain, checkpoint=None):
    """Detect modification, deletion or reordering inside the retained chain; optional external head check."""
    prev = "0" * 64
    for i, e in enumerate(chain):
        if e.get("seq") != i + 1:
            return dict(ok=False, at=i + 1, problem=f"entry {i + 1}: sequence number {e.get('seq')} (deleted or reordered)")
        if e.get("prev") != prev:
            return dict(ok=False, at=i + 1, problem=f"entry {i + 1}: prev-hash does not match entry {i} (deleted or reordered)")
        if h(e) != e.get("hash"):
            return dict(ok=False, at=i + 1, problem=f"entry {i + 1}: content changed after it was written (hash mismatch)")
        prev = e["hash"]
    if checkpoint and chain and checkpoint != chain[-1]["hash"]:
        return dict(ok=False, at=len(chain), problem="chain head differs from the external checkpoint (whole chain replaced or truncated)")
    return dict(ok=True, at=len(chain), problem="", head=chain[-1]["hash"] if chain else None)


def audit_run(st, tr, run_msgs, screened, calls, areas):
    """Write one audit entry per message processed in this run."""
    infeasible = "; ".join(st.get("infeasible") or [])
    committed = not st.get("infeasible")
    out = []
    for idx, M in enumerate(run_msgs):
        facts = [f for f in st["facts"] if f["msg"] == M["n"]]
        dec, risk, why = decide(st, M, facts, infeasible, committed)
        M["guardian"] = dict(decision=dec, risk=risk, reason=why)
        g = screened.get(idx, {})
        e = append(st, dict(
            msg=M["n"], ts=datetime.now().isoformat(timespec="seconds"), run=tr.run,
            sender=dict(name=M["frm"], role=M["role"], identity="claimed (text file, not verified)"),
            text=g.get("raw", ""), text_sha256=hashlib.sha256(g.get("raw", "").encode()).hexdigest(),
            facts=[dict(k=f["k"], v=f["v"], status=f["status"]) for f in facts],
            injection=[c for c, _ in g.get("hits", [])], decision=dec, risk=risk, reason=why,
            areas=areas if dec.startswith("ACCEPTED") else [], model_calls=calls))
        out.append(e)
        tr.code(f"guardian  msg {M['n']} {dec} (risk {risk}): {why}  [audit #{e['seq']} {e['hash'][:12]}]")
    if st.get("audit"):
        v = verify(st["audit"])
        tr.code(f"guardian  audit chain {'VERIFIED' if v['ok'] else 'BROKEN: ' + v['problem']} · "
                f"{len(st['audit'])} entries · head {st['audit'][-1]['hash'][:16]}")
    return out

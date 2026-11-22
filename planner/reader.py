"""Reader: the only language step. Prompt fill, schema check, one repair, number grounding, escape hatch."""
import json
import re
from pathlib import Path
from .llm import LLMError
from .plan import FEAT

ROOT = Path(__file__).resolve().parent.parent
PROMPT = (ROOT / "prompts/reader.txt").read_text(encoding="utf-8")
AREA_PROMPT = (ROOT / "prompts/area.txt").read_text(encoding="utf-8")
REPAIR = 'Fix this into valid JSON of the form {"msgs":[...]} exactly as described. Output JSON only.\n'
ROLES = {"organizer", "authority", "finance", "venue", "caterer", "judging", "judge", "student", "vendor", "official", "unknown"}
AREAS = ("venue", "schedule", "food", "judging", "budget")
INT_KEYS = {"students", "team_size", "teams", "duration_min", "staff", "judges_available", "honorarium",
            "min_per_team", "max_teams_per_judge", "judges_per_team", "budget"}
STR_KEYS = {"start_time", "end_time", "event_type"}
DICT_KEYS = {"skip", "extra_people", "reserve", "seat_factor", "venue", "venue_require", "venue_exclude", "block",
             "window", "late", "food", "food_require", "diet", "judges_change", "cost", "claim"}
NUMF = ("seats", "price", "amount", "n", "min", "delta", "pct", "price_per_head", "fee", "min_order", "value")
WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
         "ten": 10, "eleven": 11, "twelve": 12, "fifteen": 15, "twenty": 20, "thirty": 30, "forty": 40,
         "fifty": 50, "sixty": 60, "hundred": 100, "half": 0.5, "hour": 1, "ghanta": 1, "dozen": 12,
         "ek": 1, "do": 2, "teen": 3, "char": 4, "chaar": 4, "panch": 5, "paanch": 5, "chay": 6, "chhe": 6,
         "saat": 7, "aath": 8, "nau": 9, "das": 10, "bees": 20, "pachees": 25, "tees": 30, "chalees": 40,
         "pachas": 50, "pachaas": 50, "saath": 60, "sattar": 70, "assi": 80, "sau": 100, "dedh": 1.5,
         "dhai": 2.5, "adha": 0.5, "aadha": 0.5}
MULT = {"k": 1e3, "thousand": 1e3, "hazaar": 1e3, "hazar": 1e3, "hajar": 1e3, "lakh": 1e5, "lac": 1e5,
        "lacs": 1e5, "lakhs": 1e5, "laakh": 1e5, "crore": 1e7, "million": 1e6, "sau": 100, "hundred": 100}


# Sender-name keywords -> role (first match wins). Generic role words, not pack data.
ROLE_RULES = [("organizer", r"planner ui|\(you\)"),
              ("official", r"disabilit|accessib|welfare|safety|security office|health|medical|administration"), ("student", r"student|society|club|\bclass\b|batch"),
              ("judging", r"judg\w*\s+(coord|panel|lead|head)|coordinator"),
              ("judge", r"\bjudge\b"), ("finance", r"financ|account|treasur|bursar"),
              ("caterer", r"cater|food|kitchen|restaurant"), ("venue", r"venue|\bhall\b|auditorium|facilit|estate"),
              ("official", r"iesco|wapda|police|\bcda\b|govt|government|municipal|utility|electric|notice"),
              ("authority", r"dean|principal|registrar|rector|\bvc\b|vice.?chancellor|director|organi[sz]er|admin|\bhod\b|head of"),
              ("unknown", r"volunteer|anonymous|unknown|someone")]


def role_of(sender, model_role):
    for role, rx in ROLE_RULES:
        if re.search(rx, sender, re.I):
            return role
    return model_role if model_role in ROLES else "unknown"


def numbers(text):
    """Every number the text could mean, after normalising commas, k, lakh, hazaar, words, hours."""
    t = re.sub(r"(?<=\d),(?=\d)", "", text.lower())
    toks = re.findall(r"\d+(?:\.\d+)?|[a-z]+", t)
    base = []
    for i, tok in enumerate(toks):
        n = float(tok) if tok[0].isdigit() else WORDS.get(tok)
        if n is None:
            continue
        base.append(n)
        if i + 1 < len(toks) and toks[i + 1] in MULT:
            base.append(n * MULT[toks[i + 1]])
    out = set()
    for n in base:
        out |= {n, n * 60}
    return out


DERIVED_WORDS = r"box|headcount|people|meal|plate|order|quantity|qty|units|count|judges_needed|total|rounds"


def tonum(x):
    if isinstance(x, bool) or x is None:
        return None
    if isinstance(x, (int, float)):
        return x
    try:
        n = float(re.sub(r"(?i)rs\.?|,|\s|%", "", str(x)))
        return int(n) if n == int(n) else n
    except ValueError:
        return None


def clean(f):
    k, v = f.get("k"), f.get("v")
    if k in INT_KEYS:
        v = tonum(v)
        if v is None:
            return None, f"{k}: value {f.get('v')!r} is not a number"
    elif k in STR_KEYS:
        v = str(v)
    elif k in DICT_KEYS:
        if not isinstance(v, dict):
            n = tonum(v)
            SKEY = {"skip": "area", "venue_require": "feature", "venue_exclude": "name", "food_require": "name", "diet": "type"}
            if k in SKEY and isinstance(v, str):
                v = {SKEY[k]: v}
            elif n is None or k not in ("reserve", "seat_factor", "judges_change"):
                return None, f"{k}: expected an object, got {v!r}"
            else:
                v = {"reserve": {"amount": n}, "seat_factor": {"pct": n}, "judges_change": {"delta": n}}[k]
        v = dict(v)
        for fld in NUMF:
            if fld in v and v[fld] is not None:
                n = tonum(v[fld])
                if n is None:
                    return None, f"{k}.{fld}: {v[fld]!r} is not a number"
                v[fld] = n
    elif re.search(DERIVED_WORDS, str(k), re.I) and tonum(v) is not None:
        return dict(k="claim", v={"key": str(k), "value": tonum(v)}, q=str(f.get("q", ""))[:80], req=False), None
    else:
        return None, f"unknown key {k!r} (not in vocabulary)"
    return dict(k=k, v=v, q=str(f.get("q", ""))[:80], req=bool(f.get("req"))), None


BREAK = re.compile(r"break|prayer|namaz|lunch|tea|session|opening|closing|ceremony|min", re.I)


def repair(f, role):
    """Generic key repairs for common small-model slips (no pack data). Returns a note or None."""
    k, v = f["k"], f["v"]
    if k == "extra_people" and BREAK.search(str(v.get("who", ""))):
        f["k"], f["v"] = "block", {"name": str(v.get("who")), "min": v.get("n"), "required": True}
        return "extra_people that names a break/session -> block"
    if k == "duration_min" and (role == "judging" or re.search(r"per (team|presentation|pitch)|each team|to judge", f.get("q", ""), re.I)):
        f["k"] = "min_per_team"
        return "duration from the judging coordinator -> min_per_team"
    if k == "block" and re.search(r"per (team|presentation|pitch)|each team", str(v.get("name", "")) + " " + f.get("q", ""), re.I)             and tonum(v.get("min")) and role in ("judging", "authority", "organizer"):
        f["k"], f["v"] = "min_per_team", tonum(v.get("min"))
        return "judging time per team written as a schedule block -> min_per_team"
    if k == "food" and v.get("fee") and v.get("price_per_head") is None and (
            re.search(r"\d\s*%|percent|fees?d?\b.*%", f.get("q", ""), re.I) or re.search(r"charge|tax|service|gst", str(v.get("name", "")), re.I)
            and tonum(v.get("fee")) <= 100 and re.search(r"%", f.get("q", ""))):
        f["k"], f["v"] = "cost", {"name": str(v.get("name") or "service charge"), "amount": tonum(v["fee"]),
                                  "basis": "pct_of:food", "status": "required"}
        return "percentage charge written as a food fee -> cost pct_of:food"
    if k == "food" and tonum(v.get("price_per_head")) == 0:
        f["v"] = {x: y for x, y in v.items() if x not in ("price_per_head", "min_order")}
        return "food item priced 0 per head -> fee-only line"
    if k == "late" and role == "judge" and "judg" not in str(v.get("who", "")).lower():
        f["v"] = {**v, "who": "judge"}
        return "late sender is a judge -> who=judge"
    return None


def ungrounded(f, nums):
    v = f["v"]
    vals = [v] if not isinstance(v, dict) else [v[x] for x in NUMF if tonum(v.get(x)) is not None]
    for x in vals:
        x = tonum(x)
        if x is None or x == 0 or (f["k"] == "judges_per_team" and x == 1):
            continue
        if not any(abs(abs(x) - n) < 0.01 for n in nums):
            return x
    return None


def parse(raw):
    if not raw:
        return None
    s = re.sub(r"^```(?:json)?|```$", "", raw.strip(), flags=re.M)
    i, j = s.find("{"), s.rfind("}")
    try:
        return json.loads(s[i:j + 1])
    except (ValueError, TypeError):
        return None


def _facts(lst):
    good, bad = [], []
    for f in lst or []:
        c, err = clean(f) if isinstance(f, dict) else (None, "not an object")
        (good.append(c) if c else bad.append(dict(raw=f, err=err)))
    return good, bad


def read(chunk, known, budget, tr):
    prompt = PROMPT.replace("{known_names}", known or "none").replace("{messages}", chunk.strip())
    raw = budget.call(prompt, "reading")
    d = parse(raw)
    if not (isinstance(d, dict) and isinstance(d.get("msgs"), list)) and budget.left() > 0:
        tr.code("reader output is not valid JSON/schema -> one repair call")
        raw = budget.call(REPAIR + raw if raw else prompt, "reading")
        d = parse(raw)
    if not (isinstance(d, dict) and isinstance(d.get("msgs"), list)):
        raise LLMError("reader output invalid after repair")
    msgs = []
    for m in d["msgs"]:
        if not isinstance(m, dict):
            continue
        good, bad = _facts(m.get("facts"))
        date = m.get("date") if re.match(r"^\d{4}-\d{2}-\d{2}$", str(m.get("date"))) else None
        frm = str(m.get("from") or "?")
        hdr = re.match(r"^\s*(?:\d+\)\s*)?([^:,\n]{2,60}?)\s*[,:]", chunk)
        if frm.strip() in ("?", "", "sender", "<sender name or the notice header>") and len(d["msgs"]) == 1 and hdr:
            tr.code(f"sender: model gave none; taken from the message header -> {hdr[1].strip()!r}")
            frm = hdr[1].strip()
        role = role_of(frm, m.get("role"))
        if role != m.get("role"):
            tr.code(f"role  sender '{frm}': model said {m.get('role')!r}, sender-name rule says {role!r} -> {role}")
        msgs.append(dict(role_override=f"model said {m.get('role')}, name rule says {role}"
                         if role != m.get("role") and role != "organizer" else None,
                         frm=frm, role=role,
                         date=date, facts=good, dropped=bad, other=m.get("other") or [], note="" if str(m.get("note") or "").lower().startswith("why no facts") else str(m.get("note") or "")))
    venue_features(chunk, msgs, tr)
    if not any(m["facts"] for m in msgs) and len(re.findall(r"\d", chunk)) >= 6:
        raise LLMError("reader returned no facts for a message full of numbers (bad model output); text not consumed")
    if len(msgs) == 1 and budget.left() > 0:
        reread(chunk, msgs[0], prompt.rsplit("<<<MESSAGES", 1)[0], budget, tr)
    tr.code(f"reader: {len(msgs)} message(s), {sum(len(m['facts']) for m in msgs)} fact(s), "
            f"{sum(len(m['dropped']) for m in msgs)} dropped by schema check")
    return msgs


AREA_WORDS = [("venue", r"venue|hall|room|seat|power|generator|parking|access"), ("food", r"food|lunch|meal|tea|cater|diet|veg"),
              ("judging", r"judg|score|jury"), ("budget", r"\brs\b|rupee|cost|price|tax|gst|budget|fee|pay")]


def infer_area(text):
    return next((a for a, rx in AREA_WORDS if re.search(rx, str(text), re.I)), "schedule")


def venue_features(chunk, msgs, tr):
    """Code reading: a sentence naming venues ("Halls 2 and 3 ... ramp access") gives exactly those venues that feature."""
    for m in msgs:
        names = [f["v"]["name"] for f in m["facts"] if f["k"] == "venue" and isinstance(f["v"], dict) and f["v"].get("name")]
        if len(names) < 2:
            continue
        for sent in re.split(r"(?<=[.!?])\s+|\n", chunk):
            ft = next((b for a, b in FEAT.items() if a in sent.lower()), None)
            if not ft or not re.search(r"\b(only|have|has|with|are|is)\b", sent, re.I):
                continue
            hit = []
            for n in names:
                parts = n.split()
                pre, tok = (" ".join(parts[:-1]), parts[-1]) if len(parts) > 1 else (n, "")
                if re.search(rf"\b{re.escape(n)}\b", sent, re.I) or (tok and re.search(
                        rf"\b{re.escape(pre)}s?\b[^.]*?\b{re.escape(tok)}\b", sent, re.I)):
                    hit.append(n)
            if 0 < len(hit) < len(names):
                for n in hit:
                    f = next(f for f in m["facts"] if f["k"] == "venue" and f["v"].get("name") == n)
                    f["v"]["features"] = sorted(set(f["v"].get("features") or []) | {ft})
                tr.code(f"venue features (code, 0 tokens): '{sent.strip()[:70]}' -> {ft} for {', '.join(hit)}")


def fact_numbers(facts):
    out = set()
    for f in facts:
        v = f["v"]
        for x in ([v] if not isinstance(v, dict) else [v.get(k) for k in NUMF]):
            if tonum(x) is not None:
                out.add(abs(float(tonum(x))))
    return out


def unread_lines(chunk, facts):
    """Lines that carry numbers none of which made it into a fact (headers, years and list numbers ignored)."""
    used, out = fact_numbers(facts), []
    for line in chunk.splitlines():
        body = re.sub(r"^\s*(\d+[).]|[-*•])\s*", "", line)
        body = re.sub(r"\b(19|20)\d\d\b|\b\d{1,2} (jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\w*", "", body, flags=re.I)
        body = re.sub(r"^organizer \(planner ui\)[^:]*:", "", body, flags=re.I)
        if not re.search(r"\d", body):
            continue
        mentions = re.findall(r"\d[\d,]*(?:\.\d+)?\s*(?:k|lakh|lac|lacs|hazaar|hazar|thousand|crore)?\b", body, re.I)
        if any(not any(abs(n - u) < 0.01 for n in numbers(x) for u in used) for x in mentions):
            out.append(line.strip())             # some number on this line was not used by any fact
    return out


def reread(chunk, m, head, budget, tr):
    """Completeness check: if some lines with numbers produced no fact, one extra reading call on just those lines."""
    lines = unread_lines(chunk, m["facts"])
    if not lines:
        return
    tr.code(f"completeness: {len(lines)} line(s) with numbers were not read -> one extra reading call: {lines[:3]}")
    text = f"{m['frm']}: " + "\n".join(lines)
    try:
        d = parse(budget.call(head.replace("{known_names}", "none") + "<<<MESSAGES\n" + text + "\nMESSAGES>>>", "reading"))
    except LLMError as e:
        tr.code(f"completeness re-read failed: {e}")
        return
    got = []
    for mm in (d or {}).get("msgs") or []:
        g, b = _facts(mm.get("facts"))
        got += [f for f in g if f["k"] not in ("event_type",)]
    have = {(f["k"], json.dumps(f["v"], sort_keys=True)) for f in m["facts"]}
    new = [f for f in got if (f["k"], json.dumps(f["v"], sort_keys=True)) not in have]
    m["facts"] += new
    tr.code(f"completeness: re-read added {len(new)} fact(s): {[f['k'] for f in new]}")


def escape(other, M, budget, tr, facts=()):
    """Area call for constraints outside the vocabulary (max 2 per message, inside the call budget)."""
    out = []
    names = {str(f["v"].get("name", "")).lower() for f in facts if isinstance(f.get("v"), dict) and f["v"].get("name")}
    for it in other[:2]:
        text = it.get("t") if isinstance(it, dict) else str(it)
        if names and len(str(text)) < 40 and any(n and n in str(text).lower() for n in names):
            tr.code(f"escape hatch skipped (code, 0 tokens): '{text}' repeats an item already read from this message")
            continue
        m = re.search(r"(\d+)\s*(?:-\s*)?min", str(text), re.I)
        if m and BREAK.search(str(text)):        # obvious timed break: map in code, no model call
            out.append(dict(k="block", v={"name": str(text), "min": int(m[1]), "required": True}, q=str(text)[:80], req=False))
            tr.code(f"escape hatch (code, 0 tokens) '{text}' -> block {m[1]} min")
            continue
        if isinstance(it, dict) and str(it.get("a", "")).lower() == "skip":    # model tagged it as a skip
            out.append(dict(k="skip", v={"area": str(text).lower()}, q=str(text)[:80], req=False))
            tr.code(f"escape hatch (code, 0 tokens) skip '{text}'")
            continue
        area = it.get("a") if isinstance(it, dict) and it.get("a") in AREAS else infer_area(text)
        sk = re.search(r"\b(skip|not needed|no need|ourselves|khud|zaroorat nahi|nahi chahiye)\b", str(text), re.I)
        ar = re.search(r"venue|hall|marquee|cater|food|meal|lunch|khana|judg", str(text), re.I)
        if sk and ar:                            # "skip the venue / no catering needed": map in code, no model call
            out.append(dict(k="skip", v={"area": ar[0].lower()}, q=str(text)[:80], req=False))
            tr.code(f"escape hatch (code, 0 tokens) '{text}' -> skip {ar[0].lower()}")
            continue
        ft = next((b for a, b in FEAT.items() if a in str(text).lower()), None)
        if ft:                                   # known venue feature: map in code, no model call
            out.append(dict(k="venue_require", v={"feature": ft}, q=str(text)[:80], req=False))
            tr.code(f"escape hatch (code, 0 tokens) '{text}' -> venue_require {ft}")
            continue
        if budget.left() <= 0:
            tr.code(f"escape hatch skipped (call budget used up): {text}")
            break
        prompt = AREA_PROMPT.replace("{area}", area).replace("{role}", M["role"]).replace("{text}", str(text))
        try:
            d = parse(budget.call(prompt, area)) or {}
        except LLMError as e:
            tr.code(f"escape hatch failed: {e}")
            break
        good, bad = _facts(d.get("facts"))
        tr.code(f"escape hatch [{area}] '{text}' -> {len(good)} fact(s)" + (f"; note: {d.get('note')}" if d.get("note") else ""))
        out += good
    return out

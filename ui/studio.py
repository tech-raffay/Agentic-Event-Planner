"""Planner Studio server: serves the approved 'Planner Studio.dc.html' UI with live planner data.

    python ui/studio.py [messages.txt]      -> http://localhost:8600

GET  /api/state    view model built from state/<file>.json (same state the CLI writes)
POST /api/add      {"text": ...} appends the message to the same file and calls the same engine.run()
GET  /api/presets  test messages from tests/messages/*.txt (data files, not code)
"""
import json
import re
import sys
from datetime import datetime
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from planner import engine, report, state as S  # noqa: E402
from planner.resolver import fmt  # noqa: E402
from planner.trace import line  # noqa: E402

STUDIO = ROOT / "ui" / "studio"
PACK = Path(sys.argv[1] if len(sys.argv) > 1 else ROOT / "pack.txt").resolve()
N = lambda x: f"{x:,.0f}" if isinstance(x, (int, float)) else "—" if x is None else str(x)
SENDER = re.compile(r"^\s*(\d+\)\s*)?([A-Z][\w'’.&\- ]{1,40})(,[^:\n]{0,40})?:")


def as_message(text):
    """Text typed in the UI comes from the organiser unless it is a pasted message with its own sender line."""
    m = SENDER.match(text)
    label = m.group(2).lower() if m else ""
    sender_words = r"caterer|manager|dean|financ|office|coordinator|judge|society|student|notice|principal|registrar|"                    r"director|admin|organi[sz]er|volunteer|vendor|iesco|wapda|police|hall\b|whatsapp|email"
    if m and len(label.split()) <= 4 and re.search(sender_words, label) and not re.search(
            r"quote|update|option|detail|price|skip", label):
        return text.strip()
    return f"Organizer (planner UI), {datetime.now():%d %b %Y}: {text.strip()}"


EVENT_WORDS = re.compile(r"\b(wedding|shadi|shaadi|nikah|walima|valima|mehndi|mehendi|baraat|barat|engagement|mangni|"
                         r"birthday|conference|seminar|workshop|hackathon|concert|festival|meetup|gala|expo|exhibition|"
                         r"convocation|tournament)\b", re.I)
NEW_WORDS = re.compile(r"\b(new (event|plan)|naya (event|plan)|start over|another event)\b", re.I)
SIZE_WORDS = re.compile(r"\b(people|guests|persons|log|participants|students|attendees|budget|lakh|lac|crore)\b", re.I)


def is_new_event(text, old):
    """Typed text that describes a different event than the one in the current file starts a fresh plan."""
    if not as_message(text).startswith("Organizer") or not old.strip():
        return False
    if NEW_WORDS.search(text):
        return True
    m = EVENT_WORDS.search(text)
    return bool(m and SIZE_WORDS.search(text) and m.group(1).lower() not in old.lower())


LABEL = {"skip": "Skipped", "students": "Guests / participants", "team_size": "Team size", "teams": "Teams", "duration_min": "Event length (min)",
         "staff": "Staff", "budget": "Budget (Rs)", "judges_available": "Judges available", "honorarium": "Judge fee (Rs)",
         "min_per_team": "Minutes per team", "max_teams_per_judge": "Max teams per judge", "event_type": "Event type",
         "start_time": "Start time", "end_time": "End time"}


def human(f):
    """One readable line per fact (no JSON)."""
    k, v = f["k"], f["v"]
    if not isinstance(v, dict):
        return f"{LABEL.get(k, k)}: {N(v) if isinstance(v, (int, float)) else v}"
    if k == "venue":
        bits = [f"{N(v['seats'])} seats" if v.get("seats") else "", f"Rs {N(v['price'])}" + ("/hour" if v.get("basis") == "per_hour" else "")
                if v.get("price") is not None else "", ", ".join(v.get("features") or []), "not available" if v.get("available") is False else ""]
        return f"Venue {v.get('name')}: " + " · ".join(b for b in bits if b)
    if k == "food":
        return f"Catering {v.get('name')}: " + " · ".join(b for b in [f"Rs {N(v['price_per_head'])} per person" if v.get("price_per_head") else "",
                                                                       f"fee Rs {N(v['fee'])}" if v.get("fee") else ""] if b)
    if k == "cost":
        return f"Cost {v.get('name')}: Rs {N(v.get('amount'))} ({v.get('status', 'required')})"
    if k == "claim":
        return f"Claims {v.get('key')} = {N(v.get('value'))}"
    if k == "block":
        return f"Schedule item {v.get('name')}: {N(v.get('min'))} min"
    if k == "late":
        return f"{v.get('who')} late by {N(v.get('min'))} min"
    if k == "judges_change":
        return f"Judges change: {N(v.get('delta'))}"
    if k == "skip":
        return f"Skipped: {v.get('area')}"
    if k == "venue_require":
        return f"Venue must have: {v.get('feature')}"
    return f"{LABEL.get(k, k)}: " + ", ".join(f"{a} {N(b) if isinstance(b, (int, float)) else b}" for a, b in v.items())


def status_key(m, infeasible_runs):
    s = m["status"]
    if s.startswith("request"):
        return "request"
    if s == "no impact":
        return "noimpact"
    if s == "applied" and m["run"] in infeasible_runs:
        return "infeasible"
    return s if s in ("applied", "rejected", "superseded") else "noimpact"


def view(st):
    p = st.get("plan")
    inf_runs = {r["run"] for r in st["runs"] if r.get("infeasible")}
    facts = {}
    for f in st["facts"]:
        facts.setdefault(f["msg"], []).append(f)
    msgs = []
    audit_text = {a["msg"]: a.get("text", "") for a in st.get("audit", [])}
    for m in st["msgs"]:
        fs = facts.get(m["n"], [])
        msgs.append(dict(i=m["n"], frm=m["frm"], role=m["role"], date=m["date"] or "undated", run=m["run"],
                         status=status_key(m, inf_runs), statusText=m["status"], reason=m["reason"],
                         ch="whatsapp" if "whatsapp" in m["frm"].lower() else "pasted" if m["role"] == "organizer" else "email",
                         text=audit_text.get(m["n"], ""),
                         decision=((m.get("guardian") or {}).get("decision", "") + ". " if (m.get("guardian") or {}).get("decision")
                                   in ("QUARANTINED", "FLAGGED") else "") + m["reason"],
                         quotes="\n".join(f"“{f['q']}”" for f in fs if f.get("q")) or m.get("note") or "(no quote)",
                         facts="\n".join(f"{human(f)}   [{f['status']}]" for f in fs) or "none",
                         guardian=m.get("guardian") or {}))
    runs = []
    cum = 0
    for r in st["runs"]:
        ev = [e for e in st["trace"] if e["run"] == r["run"]]
        head = next((e["text"] for e in ev if e["t"] == "head"), "")
        calls = [dict(n=e["n"], model=e["model"], area=e["area"], secs=e.get("secs", 0), error=e.get("error"),
                      input=e["input"], output=e.get("output") or "", **(e.get("usage") or
                      {"prompt": None, "completion": None, "total": None})) for e in ev if e["t"] == "call"]
        cum += r.get("tokens", 0)
        new = [m for m in msgs if m["run"] == r["run"]]
        if r["mode"] == "full":
            title, icon, color = "Full run", "flag", "#16A34A"
        else:
            st0 = new[0]["status"] if new else "noimpact"
            title = (new[0]["frm"] if new else "Update") + (f" +{len(new) - 1}" if len(new) > 1 else "")
            icon, color = {"rejected": ("octagon-x", "#DC2626"), "infeasible": ("triangle-alert", "#DC2626"),
                           "applied": ("circle-check", "#16A34A"), "superseded": ("history", "#71717A")}.get(
                st0, ("circle-minus", "#71717A"))
        runs.append(dict(r=r["run"], kind=r["mode"], time=(re.findall(r"\d{2} \w{3} [\d:]{8}", head) or [""])[0],
                         title=title, icon=icon, color=color, calls=calls, tokens=r.get("tokens", 0), cum=cum,
                         areas=r.get("areas", []), changed=r.get("changed", []), failed=bool(r.get("failed")),
                         infeasible=r.get("infeasible"), before=r.get("before", {}), after=r.get("after", {}),
                         code="\n".join(e["text"] for e in ev if e["t"] == "code"),
                         decisions="\n".join(e["text"] for e in ev if e["t"] == "code" and re.match(
                             r"(resolver|superseded|repair|role|grounding|impact|schema|lever|INFEAS)", e["text"]))))
    from planner import guardian
    v = guardian.verify(st.get("audit", []))
    needs = (p or {}).get("needs") or [x[len("provide: "):] for x in st.get("infeasible") or [] if x.startswith("provide: ")]
    out = dict(needs=needs, complete=bool(p) and not st.get("infeasible"), audit=dict(ok=v["ok"], entries=len(st.get("audit", [])), problem=v["problem"]), file=PACK.name, nmsgs=len(msgs), msgs=msgs, runs=runs, calls=st["calls"], tokens=st["tokens"],
               infeasible="; ".join(st.get("infeasible") or []), planMd=report.plan_md(st),
               traceTxt="\n".join(line(e) for e in st["trace"]) +
                        f"\n=== SESSION TOTAL: {st['calls']} model calls · {st['tokens']:,} tokens ===\n")
    if p:
        F, B, V, FD, SC = p["figures"], p["budget"], p["venue"], p["food"], p["schedule"]
        out.update(checks=[dict(name=c["name"], ok=c["ok"], detail=c["detail"]) for c in st["checks"] or []], plan=dict(
            headcount=F["headcount"], teams=F["teams"], judges=f"{F['judges_used']} / {F['judges_available']}",
            total=N(B["total"]), remaining=N(B["remaining"]), budget=N(B["budget"]),
            venue=f"{V.get('name')} · {N(V.get('cost'))}", schedule=f"{F['duration_min']} min · {len(SC['blocks'])} blocks",
            food=f"{FD.get('boxes')} × {N(FD.get('pph'))}", judging=f"{F['judges_used']} of {F['judges_available']} · {F['rounds']} rounds",
            budgetLine=f"{N(B['total'])} / {N(B['budget'])}",
            derived="\n".join([f"teams = ceil({F['students']} / {F['team_size']}) = {F['teams']}",
                               f"judges needed = ceil({F['teams']} × {F['judges_per_team']} / {F['max_teams_per_judge']}) = {F['judges_needed']}",
                               f"rounds = ceil({F['teams']} / {F['judges_used']}) = {F['rounds']} → {F['judging_min']} min",
                               f"headcount = {F['students']} + {F['judges_used']} + {F['staff']}" + (f" + {F['extra']}" if F["extra"] else "") + f" = {F['headcount']}",
                               f"venue = cheapest with seats ≥ {F['headcount']}" + (f" + {', '.join(V['required'])}" if V["required"] else "") + f" → {V.get('name')}",
                               f"food = {FD.get('qty')} × {N(FD.get('pph'))}" + (f" + {N(FD['fee'])}" if FD.get("fee") else "") + f" = {N(FD.get('cost'))}"]
                              + [f"rejected: {r['name']} ({r['why']})" for r in V["rejected"]]),
            budgetTxt="\n".join(f"{l['line'][:26]:<26} {N(l['amount']):>9}   {l['src']}" for l in B["lines"]) +
                      f"\n{'total':<26} {N(B['total']):>9}\n{'reserve':<26} {N(B['reserve']):>9}\n{'remaining':<26} {N(B['remaining']):>9}",
            scheduleTxt="\n".join(f"{b['time']}  {b['name'][:34]:<34} {b['min']:>3}" for b in SC["blocks"]) +
                        ("\nStart time is a planner assumption." if SC["assumed"] else ""),
            gridTxt="\n".join(f"J{i + 1:<3} {', '.join(t)}" for i, t in enumerate(p["judging"]["grid"])),
            decisions="\n".join(p["levers"] + p["notes"]) or "none"))
        tidy(out["plan"], F, V, FD)
    return out


def tidy(P, F, V, FD):
    """Plain wording when an event has no venue/food yet, skipped parts, or no judging."""
    sk = F.get("skipped", [])
    if not V.get("name"):
        P["venue"] = "Arranged separately" if "venue" in sk else "Details needed"
    if not FD.get("name"):
        P["food"] = "Skipped" if "food" in sk else "Details needed"
    lines = P["derived"].split("\n")
    if not F.get("judging", True):
        P["judging"] = "Not needed"
        P["judges"] = "Not needed"
        lines = [f"event = {F.get('event')} · no teams or judging"] + [l for l in lines if not l.startswith(("teams", "judges", "rounds"))]
    lines = [("venue = " + P["venue"].lower()) if l.startswith("venue") and not V.get("name") else
             ("food = " + P["food"].lower()) if l.startswith("food") and not FD.get("name") else l for l in lines]
    P["derived"] = "\n".join(lines)


def md_html(md):
    """Tiny Markdown -> HTML for plan.md (headings, tables, lists, quotes, bold)."""
    import html as _h
    out, rows = [], []

    def flush():
        if rows:
            out.append("<table>" + "".join("<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>" for r in rows) + "</table>")
            rows.clear()
    for line in md.splitlines():
        t = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", _h.escape(line))
        if line.startswith("|"):
            cells = [c.strip() for c in t.strip("|").split("|")]
            if not all(set(c) <= set("-: ") for c in cells):
                rows.append(cells)
            continue
        flush()
        if line.startswith("## "):
            out.append(f"<h2>{t[3:]}</h2>")
        elif line.startswith("# "):
            out.append(f"<h1>{t[2:]}</h1>")
        elif line.startswith("- "):
            out.append(f"<div>• {t[2:]}</div>")
        elif line.startswith("&gt; "):
            out.append(f"<blockquote>{t[5:]}</blockquote>")
        elif line.strip():
            out.append(f"<p>{t}</p>")
    flush()
    return "".join(out)


class H(SimpleHTTPRequestHandler):
    def __init__(self, *a, **k):
        super().__init__(*a, directory=str(STUDIO), **k)

    def log_message(self, *a):
        pass

    def send_json(self, obj, code=200):
        b = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            self.send_response(302)
            self.send_header("Location", "/Planner%20Studio.dc.html")
            self.end_headers()
        elif self.path.startswith("/api/state"):
            st = S.load(PACK)
            self.send_json(view(st) if st else {"empty": True, "file": PACK.name})
        elif self.path.startswith("/plan"):          # the current plan as a readable page
            st = S.load(PACK)
            md = report.plan_md(st) if st else "# No plan yet"
            body = ("<!doctype html><meta charset='utf-8'><title>Event plan</title><style>body{font-family:Inter,system-ui,sans-serif;"
                    "max-width:860px;margin:40px auto;padding:0 20px;color:#18181B;line-height:1.5}table{border-collapse:collapse;width:100%;"
                    "margin:8px 0 18px}td,th{border-bottom:1px solid #E4E4E7;padding:6px 8px;text-align:left;font-size:14px}"
                    "h1{font-size:26px}h2{font-size:18px;margin-top:28px}blockquote{background:#FEF3C7;margin:0;padding:8px 12px;border-radius:8px}</style>"
                    + md_html(md))
            b = body.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(b)
        elif self.path.startswith("/api/presets"):
            fs = sorted((ROOT / "tests" / "messages").glob("*.txt"))
            self.send_json([dict(label=f.stem.split("_", 1)[-1].replace("_", " "), text=f.read_text(encoding="utf-8").strip())
                            for f in fs])
        else:
            super().do_GET()

    def do_POST(self):
        global PACK
        if self.path.startswith("/api/delete"):     # delete the current plan: file moved to events/trash, state removed
            import shutil
            (ROOT / "events" / "trash").mkdir(parents=True, exist_ok=True)
            if PACK.exists():
                shutil.move(str(PACK), str(ROOT / "events" / "trash" / f"{datetime.now():%H%M%S}-{PACK.name}"))
            S.path_for(PACK).unlink(missing_ok=True)
            PACK = ROOT / "events" / f"event-{datetime.now():%Y%m%d-%H%M%S}.txt"
            return self.send_json({"empty": True, "file": PACK.name, "deleted": True})
        if not self.path.startswith("/api/add"):
            return self.send_json({"error": "not found"}, 404)
        text = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}").get("text", "").strip()
        if not PACK.exists() and text:            # first message after a delete starts the new file
            PACK.parent.mkdir(exist_ok=True)
        if not text:                              # empty: just (re)run the file as it is
            engine.run(str(PACK), echo=False)
            st = S.load(PACK)
            return self.send_json(view(st) if st else {"empty": True, "file": PACK.name})
        old = PACK.read_text(encoding="utf-8") if PACK.exists() else ""
        new_event = is_new_event(text, old)
        if new_event:                              # fresh plan in its own file; the old file is kept as it was
            word = (EVENT_WORDS.search(text) or re.search(r"\w+", "event"))[0].lower()
            (ROOT / "events").mkdir(exist_ok=True)
            PACK = ROOT / "events" / f"{word}-{datetime.now():%Y%m%d-%H%M%S}.txt"
            old = ""
        with open(PACK, "a", encoding="utf-8") as fh:
            fh.write(("" if not old or old.endswith("\n\n") else "\n" if old.endswith("\n") else "\n\n") + as_message(text) + "\n")
        engine.run(str(PACK), echo=False)        # the same code path as `python run.py <file>`
        st = S.load(PACK)
        self.send_json(dict(view(st), newEvent=new_event) if st else {"empty": True, "file": PACK.name})


if __name__ == "__main__":
    port = int(__import__("os").environ.get("PORT", 8600))
    print(f"Planner Studio: http://localhost:{port}   (file: {PACK})")
    ThreadingHTTPServer(("127.0.0.1", port), H).serve_forever()

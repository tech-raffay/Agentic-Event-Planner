"""The one code path: read file -> diff vs state -> reader call -> resolver -> planner -> checks -> outputs."""
import copy
import json
import math
from pathlib import Path
import yaml
from . import reader, resolver, plan as planner, checks, report, state, guardian
from .llm import Budget, LLMError
from .trace import Trace

ROOT = Path(__file__).resolve().parent.parent
CLAIM = {"box": "headcount", "headcount": "headcount", "people": "headcount", "meal": "headcount",
         "food": "headcount", "plate": "headcount", "team": "teams", "judge": "judges_used", "round": "rounds",
         "judging_min": "judging_min", "total": "total", "cost": "total", "spend": "total"}


def config():
    return yaml.safe_load((ROOT / "config/defaults.yaml").read_text(encoding="utf-8"))


def known_names(st):
    out = {}
    for f in st["facts"]:
        if f["k"] in ("venue", "food", "cost") and isinstance(f["v"], dict) and f["v"].get("name"):
            out.setdefault(f["k"], set()).add(str(f["v"]["name"]))
    return "; ".join(f"{k}: {', '.join(sorted(v))}" for k, v in out.items())


def run(path, echo=True):
    C = config()
    text = Path(path).read_text(encoding="utf-8")
    st = state.load(path)
    if st and text.startswith(st["text"]) and st["text"]:
        new, mode = text[len(st["text"]):], "update"
    else:
        if st and echo:
            print("[code] file differs from the processed text (new pack) -> full run from scratch")
        st, new, mode = state.fresh(path), text, "full"
    if not new.strip():
        if echo:
            print("No new messages since the last run; plan unchanged (0 model calls).")
            report.show(st)
        return st
    n_msgs = len(st["msgs"])
    tr = Trace(st, mode, "full pack" if mode == "full" else "new text appended", echo)
    budget = Budget(st, tr, C["max_calls_per_run"], C["timeout_s"])
    try:
        msgs = reader.read(new, known_names(st), budget, tr)
    except LLMError as e:
        tr.code(f"READ FAILED: {e}. Text not consumed; fix and rerun the same command.")
        tr.end()
        st["runs"].append(dict(run=tr.run, mode=mode, calls=tr.calls, tokens=tr.tokens, failed=True))
        state.save(st)
        report.write(st)
        return st
    apply(st, msgs, new, tr, C, budget, mode)
    st["text"] = text
    tr.end()
    state.save(st)
    report.write(st)
    if echo:
        report.show(st, since=n_msgs)
    return st


def headline(p):
    if not p:
        return {}
    F, B = p["figures"], p["budget"]
    return dict(headcount=F["headcount"], teams=F["teams"], judges=f"{F['judges_used']}/{F['judges_available']}",
                venue=p["venue"].get("name"), food=p["food"].get("name"), judging_min=F["judging_min"],
                total=B["total"], remaining=B["remaining"])


def eval_claim(st, r, p, tr):
    v = r["v"]
    key, val = (str(v.get("key", "")), v.get("value")) if r["k"] == "claim" else ("teams", v)
    tgt = next((t for c, t in CLAIM.items() if c in key.lower()), None)
    who = f"{r['from']} ({r['role']})"
    if not p or tgt is None or reader.tonum(val) is None:
        r["status"], r["reason"] = "no_impact", f"states {key}={val}; not a value the planner computes"
        return
    F = p["figures"]
    actual = p["budget"]["total"] if tgt == "total" else F[tgt]
    ex = {"headcount": f"headcount {F['headcount']} = {F['students']} students + {F['judges_used']} judges + "
                       f"{F['staff']} staff" + (f" + {F['extra']} others" if F["extra"] else ""),
          "teams": f"ceil({F['students']} students / {F['team_size']} per team)",
          "judges_used": f"ceil({F['teams']} teams × {F['judges_per_team']} / max {F['max_teams_per_judge']} per judge)",
          "rounds": f"ceil({F['teams']} / {F['judges_used']} judges)",
          "judging_min": f"{F['rounds']} rounds × {F['min_per_team']} min", "total": "sum of budget lines"}[tgt]
    if abs(reader.tonum(val) - actual) < 0.5:
        r["status"] = "applied" if r["k"] == "teams" else "no_impact"
        r["reason"] = f"states {key}={val}; matches computed value ({ex})"
    else:
        r["status"] = "rejected"
        r["reason"] = (f"derived-value claim: {who} says {key} = {resolver.fmt(val)}; {key} is computed = "
                       f"{resolver.fmt(actual)} ({ex}). Plan keeps {resolver.fmt(actual)}.")
    tr.code(f"resolver  {resolver.desc(r)}  {r['status'].upper()} ({r['reason']})")


def msg_status(st):
    p = st.get("plan") or {}
    opt = {l["line"].replace(" (optional)", "").lower() for l in (p.get("budget") or {}).get("lines", [])
           if l["kind"] == "optional"}
    for M in st["msgs"]:
        fs = [f for f in st["facts"] if f["msg"] == M["n"]]
        S = [f["status"] for f in fs]
        live = [f for f in fs if f["status"] not in ("dropped",)]
        if "rejected" in S or M.get("quarantine"):
            s = "rejected"
        elif not live or all(f["status"] == "no_impact" or f.get("impact") is False for f in live):
            s = "no impact"
        elif all(x == "superseded" for x in (f["status"] for f in live)):
            s = "superseded"
        elif "applied" in S:
            s = "applied"
        else:
            s = "request"
            names = [str(f["v"].get("name", "")).lower() for f in fs if f["k"] == "cost"]
            if names:
                s = "request → included" if any(n in opt for n in names) else "request → not included"
        M["status"] = s
        M["reason"] = "; ".join(f"{f['k']}: {f['reason']}" for f in fs) or M.get("note") or "no plan facts"


def apply(st, msgs, chunk, tr, C, budget=None, mode="full"):
    nums = reader.numbers(chunk)
    prev = copy.deepcopy(st.get("plan"))
    first = len(st["msgs"]) + 1
    touched, run_facts, run_msgs = [], [], []
    screened = guardian.screen(chunk, msgs, tr)          # Guardian A: untrusted text scanned before any fact counts
    for m in msgs:
        n = len(st["msgs"]) + 1
        date = m.get("date")
        if date:
            st["maxdate"] = max(st["maxdate"], date)
        M = dict(n=n, frm=m.get("frm", "?"), role=m.get("role", "unknown"), date=date, run=tr.run,
                 note=m.get("note", ""), status="", reason="")
        M["quarantine"], M["role_override"] = m.get("quarantine"), m.get("role_override")
        st["msgs"].append(M)
        run_msgs.append(M)
        for d in m.get("dropped", []):
            tr.code(f"schema check dropped msg {n} fact {d['raw']}: {d['err']}")
        facts = list(m.get("facts", []))
        if m.get("other"):
            if budget:
                facts += reader.escape(m["other"], M, budget, tr, facts)
            else:
                tr.code(f"msg {n} has constraints outside the vocabulary: {m['other']}")
        recs = []
        for f in facts:
            f = dict(f)
            note = reader.repair(f, M["role"])
            if note:
                tr.code(f"repair  msg {n} {note}")
            st["order"] += 1
            r = dict(id=len(st["facts"]) + len(recs) + 1, msg=n, k=f["k"], v=f["v"], q=f.get("q", ""),
                     req=bool(f.get("req")), role=M["role"], date=date, run=tr.run, status="", reason="",
                     eff=[date or st["maxdate"], st["order"]], **{"from": M["frm"]})
            r["slot"] = resolver.slot(r["k"], r["v"], r["id"])
            bad = reader.ungrounded(r, nums)
            if bad is not None:                                                  # rule 1
                r["status"], r["reason"] = "dropped", f"ungrounded: extracted {bad:g} but the message has no such number; ignored"
                tr.code(f"grounding  {resolver.desc(r)}  DROPPED ({r['reason']})")
            recs.append(r)
        if M["quarantine"]:
            for r in recs:
                if not r["status"]:
                    r["status"], r["reason"] = "rejected", f"guardian quarantine: {M['quarantine']} in this message"
                    tr.code(f"resolver  {resolver.desc(r)}  REJECTED ({r['reason']})")
        V = {r["k"]: r["v"] for r in recs if not r["status"]}
        if all(isinstance(V.get(k), (int, float)) for k in ("students", "team_size", "teams")):   # rule 5
            c = math.ceil(V["students"] / V["team_size"])
            if c != V["teams"]:
                for r in recs:
                    if r["k"] in ("students", "team_size", "teams"):
                        r["status"] = "rejected"
                        r["reason"] = (f"internally inconsistent: {V['teams']} teams × {V['team_size']} ≠ "
                                       f"{V['students']} students (would be {c} teams)")
                        tr.code(f"resolver  {resolver.desc(r)}  REJECTED ({r['reason']})")
        for r in recs:
            if not r["status"]:
                resolver.resolve(st, r, tr)
            st["facts"].append(r)
            run_facts.append(r)
            if r["status"] in ("applied", "request") and r.get("use", True):
                touched.append(r["k"])
        if not recs:
            tr.code(f"msg {n} ({M['frm']}): no plan facts -> no impact" + (f"; {M['note']}" if M["note"] else ""))

    p, probs = planner.build(st, C)
    for r in run_facts:
        if r["status"] == "pending":
            eval_claim(st, r, p, tr)
        if r["k"] == "late" and r["status"] == "applied" and p:
            who, mins = str(r["v"].get("who", "")).lower(), planner.num(r["v"].get("min"))
            kind = "judging" if "judg" in who else "lunch" if any(w in who for w in ("cater", "food")) else None
            b = next((b for b in p["schedule"]["blocks"] if b["kind"] == kind), None)
            if b:
                off = b["s"] - p["schedule"]["blocks"][0]["s"]
                if off >= mins:
                    r["impact"] = False
                    r["reason"] += f"; {kind} starts at +{off // 60}:{off % 60:02d}, so {mins:g} min late has no effect"
                    tr.code(f"impact  {resolver.desc(r)}  NO IMPACT ({r['reason']})")
            else:
                r["impact"] = False
    if p:
        res = checks.run(p, st)
        ok = sum(c["ok"] for c in res)
        for lv in p["levers"]:
            tr.code(f"lever  {lv}")
        if p["feasible"]:
            st["plan"], st["checks"], st["infeasible"], st["plan_ok"] = p, res, None, True
        else:
            st["infeasible"] = p["problems"]
            keep = st.get("plan_ok", bool(st["plan"] and not st["runs"][-1:] == [] and st["plan"].get("feasible")))
            tr.code("INFEASIBLE: " + "; ".join(p["problems"]) + (" -> keeping last valid plan" if keep else ""))
            if not keep:                         # no valid plan yet: show the newest partial plan
                st["plan"], st["checks"] = p, res
        tr.code(f"checks {ok}/6 {'PASS' if ok == 6 else 'FAIL'}  total {p['budget']['total']:,} / "
                f"{p['budget']['budget']:,}" + ("" if ok == 6 else "  failed: " + ", ".join(
                    c["name"] for c in res if not c["ok"])))
    else:
        st["infeasible"] = probs
        tr.code("cannot plan yet: " + "; ".join(probs))
    areas = planner.affected(set(touched))
    changed = [a for a in planner.AREAS if prev and st["plan"] and
               json.dumps(prev.get(a), sort_keys=True) != json.dumps(st["plan"].get(a), sort_keys=True)]
    if mode == "update":
        tr.code(f"dependency map: {sorted(set(touched)) or 'no applied facts'} -> recompute "
                f"{', '.join(areas) or 'nothing'}; unchanged: {', '.join(a for a in planner.AREAS if a not in changed) or 'none'}")
    msg_status(st)
    calls = [e["n"] for e in st["trace"] if e["t"] == "call" and e["run"] == tr.run]
    guardian.audit_run(st, tr, run_msgs, screened, calls, areas)
    st["runs"].append(dict(run=tr.run, mode=mode, msgs=list(range(first, len(st["msgs"]) + 1)), calls=tr.calls,
                           tokens=tr.tokens, areas=areas, changed=changed, before=headline(prev),
                           after=headline(st["plan"]), infeasible=st["infeasible"],
                           facts=[f"{resolver.desc(f)} -> {f['status']}" for f in run_facts]))

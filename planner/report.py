"""Outputs: out/plan.md, out/trace.txt, out/trace.jsonl, and the rich terminal view."""
import json
from pathlib import Path
from .trace import line

OUT = Path(__file__).resolve().parent.parent / "out"
rs = lambda x: f"{x:,.0f}" if isinstance(x, (int, float)) else str(x)


def token_rows(st):
    rows = [e for e in st["trace"] if e["t"] == "call"]
    return [(e["n"], e["run"], e["model"], e["area"], *(((e["usage"] or {}).get(k, "-") for k in
             ("prompt", "completion", "total")) if e.get("usage") else ("not reported",) * 3),
             "failed" if e.get("error") else "ok") for e in rows]


def plan_md(st):
    p, L = st.get("plan"), []
    if not p:
        return "# Hackathon plan\n\nNo plan yet: " + "; ".join(st.get("infeasible") or []) + "\n"
    F, V, FD, B, SC = p["figures"], p["venue"], p["food"], p["budget"], p["schedule"]
    ok = sum(c["ok"] for c in st["checks"] or [])
    L += ["# Hackathon plan", f"Run {len(st['runs'])} · checks {ok}/6 · session model calls {st['calls']} · "
                              f"session tokens {st['tokens']:,}", ""]
    if st.get("infeasible"):
        L += [f"> **INFEASIBLE after latest message:** {'; '.join(st['infeasible'])}. Showing the last valid plan.", ""]
    L += ["## Key figures", "| Figure | Value |", "|---|---|"] + [f"| {a} | {b} |" for a, b in (
        ("Teams", f"ceil({F['students']} / {F['team_size']}) = {F['teams']}"),
        ("Judges", f"{F['judges_used']} used of {F['judges_available']} available ({F['standby']} standby)"),
        ("Judging", f"{F['rounds']} rounds × {F['min_per_team']} min = {F['judging_min']} min"),
        ("Headcount", f"{F['students']} + {F['judges_used']} + {F['staff']}" + (f" + {F['extra']}" if F["extra"] else "")
         + f" = {F['headcount']}"))]
    L += ["", "## Venue", f"**{V.get('name')}** — {V.get('seats')} seats, Rs {rs(V.get('cost'))} ({V.get('basis')}, "
                          f"{V.get('src')}). Cheapest option that fits {F['headcount']} people"
          + (f" with {', '.join(V['required'])}" if V["required"] else "") + "."]
    L += [f"- {r['name']}: rejected, {r['why']}" for r in V["rejected"]]
    L += ["", "## Schedule" + (" (start time not given: 10:00 is a planner assumption)" if SC["assumed"] else ""),
          "| Time | Block | Min | Source |", "|---|---|---|---|"]
    L += [f"| {b['time']} | {b['name']} | {b['min']} | {b['src']} |" for b in SC["blocks"]]
    L += ["", "## Food", f"**{FD.get('name')}**: {FD.get('boxes')} boxes (= headcount) × Rs {rs(FD.get('pph'))}"
          + (f" + fee {rs(FD['fee'])}" if FD.get("fee") else "") + f" = Rs {rs(FD.get('cost'))}"]
    L += [f"- Diet: {d['type']} {d.get('n') or ''}{'%' if d.get('pct') else ''} ({d['src']})" for d in FD["diet"]]
    L += ["", "## Judging", f"{p['judging']['judges']} judges, round-robin:"]
    L += [f"- J{i + 1}: {', '.join(t)}" for i, t in enumerate(p["judging"]["grid"])]
    L += ["", "## Budget", "| Line | Basis | Rs |", "|---|---|---|"]
    L += [f"| {l['line']} | {l['basis']} | {rs(l['amount'])} |" for l in B["lines"]]
    L += [f"| **Total** | | **{rs(B['total'])}** |", f"| Reserve | | {rs(B['reserve'])} |",
          f"| Remaining of {rs(B['budget'])} | | {rs(B['remaining'])} |"]
    if p["levers"] or p["notes"]:
        L += ["", "## Decisions"] + [f"- {x}" for x in p["levers"] + p["notes"]]
    L += ["", "## Checks"] + [f"- {'PASS' if c['ok'] else 'FAIL'} **{c['name']}**: {c['detail']}" for c in st["checks"] or []]
    L += ["", "## Message ledger", "| Msg | From | Status | Reason |", "|---|---|---|---|"]
    L += [f"| {m['n']} | {m['frm']} | {m['status']} | {m['reason'].replace('|', '/')} |" for m in st["msgs"]]
    L += ["", "## Model calls and tokens (as reported by the API)", "| # | Run | Model | Area | Prompt | Completion | Total |",
          "|---|---|---|---|---|---|---|"] + [f"| {' | '.join(map(str, r[:7]))} |" for r in token_rows(st)]
    L += [f"| | | | **Total** | | | **{st['tokens']:,}** |"]
    return "\n".join(L) + "\n"


def write(st):
    OUT.mkdir(exist_ok=True)
    (OUT / "trace.txt").write_text("\n".join(line(e) for e in st["trace"]) +
                                   f"\n=== SESSION TOTAL: {st['calls']} model calls · {st['tokens']:,} tokens ===\n",
                                   encoding="utf-8")
    (OUT / "trace.jsonl").write_text("\n".join(json.dumps(e, ensure_ascii=False) for e in st["trace"]) + "\n",
                                     encoding="utf-8")
    (OUT / "plan.md").write_text(plan_md(st), encoding="utf-8")
    (OUT / "submission.txt").write_text(submission(st), encoding="utf-8")


def show(st, since=0):
    try:
        from rich.console import Console
        from rich.table import Table
    except ImportError:
        print(plan_md(st))
        return
    c, p = Console(highlight=False), st.get("plan")
    if st.get("infeasible"):
        c.print(f"INFEASIBLE: {'; '.join(st['infeasible'])} -> last valid plan kept", style="bold white on red", markup=False)
    if not p:
        return
    F, B = p["figures"], p["budget"]
    c.print(f"\nHeadcount {F['headcount']} · Teams {F['teams']} · Judges {F['judges_used']}/{F['judges_available']} · "
            f"Venue {p['venue'].get('name')} · Food {p['food'].get('name')} · Total Rs {B['total']:,} / {B['budget']:,}",
            style="bold green", markup=False)

    def table(title, cols, rows):
        t = Table(title=title, title_justify="left")
        for col in cols:
            t.add_column(col)
        for r in rows:
            t.add_row(*map(str, r))
        c.print(t)
    table("Budget", ["Line", "Basis", "Rs"], [(l["line"], l["basis"], rs(l["amount"])) for l in B["lines"]] +
          [("TOTAL", "", rs(B["total"])), ("Remaining", f"reserve {rs(B['reserve'])}", rs(B["remaining"]))])
    table("Schedule", ["Time", "Block", "Min", "Source"], [(b["time"], b["name"], b["min"], b["src"])
                                                            for b in p["schedule"]["blocks"]])
    table("Checks", ["Check", "Result", "Detail"], [(x["name"], "PASS" if x["ok"] else "FAIL", x["detail"])
                                                    for x in st["checks"] or []])
    table("Message ledger", ["Msg", "From", "Status", "Reason"],
          [(m["n"], m["frm"], m["status"], m["reason"][:160]) for m in st["msgs"]
           if m["n"] > since or m["status"] not in ("applied",)])
    table("Model calls and tokens (reported by API)", ["#", "Run", "Model", "Area", "Prompt", "Completion", "Total", ""],
          token_rows(st) + [("", "", "", "TOTAL", "", "", f"{st['tokens']:,}", "")])


AREA_NAME = {"reading": "reading messages", "venue": "venue constraint", "food": "food constraint",
             "schedule": "schedule constraint", "judging": "judging constraint", "budget": "budget constraint"}


def submission(st):
    """Upload file: the plan in five areas + one trace line per AI call + total."""
    p, L = st.get("plan"), []
    if p:
        F, V, FD, B, SC = p["figures"], p["venue"], p["food"], p["budget"], p["schedule"]
        hon = next((l for l in B["lines"] if l["line"].startswith("Judges")), None)
        ok = sum(c["ok"] for c in st.get("checks") or [])
        ev = F.get("event") if F.get("event") not in (None, "event") else ""
        L += [f"EVENT PLAN{' — ' + ev if ev else ''} · {F['headcount']} people · budget Rs {rs(B['budget'])}", ""]
        L += ["1. VENUE", f"   {V.get('name') or 'not chosen'} — {V.get('seats', '-')} seats — Rs {rs(V.get('cost', 0))}"
              f" (needs {F['headcount']} seats)"] + [f"   not chosen: {r['name']} ({r['why']})" for r in V["rejected"]]
        L += ["", "2. SCHEDULE" + (" (start time assumed)" if SC["assumed"] else "")]
        L += [f"   {b['time']}  {b['name']} ({b['min']} min)" for b in SC["blocks"]]
        L += ["", "3. FOOD", f"   {FD.get('name') or 'not chosen'} — quantity {FD.get('boxes', '-')} (everyone attending) — "
              f"Rs {rs(FD.get('pph', 0))} each" + (f" + fee Rs {rs(FD['fee'])}" if FD.get("fee") else "") + f" = Rs {rs(FD.get('cost', 0))}"]
        L += ["", "4. JUDGING", (f"   {F['judges_used']} judges (of {F['judges_available']} available) for {F['teams']} teams — "
              f"{F['rounds']} rounds × {F['min_per_team']} min — cost Rs {rs(hon['amount']) if hon else 0}")
              if F.get("judging", True) else "   no judging for this event"]
        L += ["", "5. BUDGET"] + [f"   {l['line']:<32} Rs {rs(l['amount']):>10}" for l in B["lines"]]
        L += [f"   {'TOTAL':<32} Rs {rs(B['total']):>10}  of Rs {rs(B['budget'])} — "
              + ("FITS" if B["total"] + B["reserve"] <= B["budget"] else "DOES NOT FIT") + f" (Rs {rs(B['remaining'])} left)",
              "", f"CHECKS: {ok}/6 passed" + ("" if not st.get("infeasible") else " · " + "; ".join(st["infeasible"]))]
    L += ["", "TRACE (one line per AI call)"]
    for e in [e for e in st["trace"] if e["t"] == "call"]:
        u = e.get("usage")
        tok = f"prompt {u['prompt']} + completion {u['completion']} = {u['total']} tokens" if u else "tokens not reported"
        L.append(f"#{e['n']} | model {e['model']} | {AREA_NAME.get(e['area'], e['area'])} | "
                 + (f"FAILED ({e['error'][:60]})" if e.get("error") else tok))
    L.append(f"TOTAL: {st['calls']} AI call(s) · {st['tokens']:,} tokens")
    return "\n".join(L) + "\n"

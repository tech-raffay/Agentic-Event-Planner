"""Streamlit UI: reads state/*.json only; 'Add message' appends to the same file and calls the same run()."""
import json
import sys
from pathlib import Path
import streamlit as st

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from planner import engine, report, guardian  # noqa: E402

st.set_page_config(page_title="Hackathon Planner", layout="wide")
st.markdown("""<style>
@import url('https://fonts.googleapis.com/css2?family=Hanken+Grotesk:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap');
html,body,[class*="css"],.stMarkdown,.stMetric{font-family:'Hanken Grotesk',system-ui,sans-serif}
code,pre,.stCode{font-family:'JetBrains Mono',ui-monospace,monospace!important}
[data-testid="stMetric"]{background:#fff;border:1px solid #E3E1DA;border-radius:10px;padding:10px 14px}
[data-testid="stMetricLabel"]{color:#565A63}
.chip{padding:2px 10px;border-radius:12px;font-size:.8rem;font-weight:600;color:#fff}
.applied{background:#1E7A4C}.rejected{background:#B42318}.superseded,.noimpact{background:#7C7F86}
.request{background:#8A5300}.badge{display:inline-block;margin:2px 4px;padding:4px 10px;border-radius:6px;
font-weight:600;color:#fff;font-size:.85rem}.ok{background:#1E7A4C}.bad{background:#B42318}
</style>""", unsafe_allow_html=True)

files = sorted((ROOT / "state").glob("*.json"), key=lambda f: f.stat().st_mtime, reverse=True)
if not files:
    st.info("No runs yet. Run:  python run.py <messages.txt>")
    st.stop()
states = [json.loads(f.read_text(encoding="utf-8")) for f in files]
idx = st.sidebar.selectbox("Message file", range(len(states)), format_func=lambda i: Path(states[i]["path"]).name)
S = states[idx]

with st.sidebar:
    st.subheader("Add message")
    new = st.text_area("Paste the new message exactly as given", height=150)
    if st.button("Add & re-plan", type="primary", disabled=not new.strip()):
        with open(S["path"], "a", encoding="utf-8") as fh:
            fh.write(("\n\n" if not S["text"].endswith("\n\n") else "") + new.strip() + "\n")
        with st.spinner("Running the same pipeline as the CLI..."):
            n0 = len(S["msgs"])
            ns = engine.run(S["path"], echo=False)
        st.session_state["last"] = [m.get("guardian", {}) | {"n": m["n"], "frm": m["frm"]} for m in ns["msgs"][n0:]]             or [{"decision": "READ FAILED", "reason": "model call failed; message kept in the file, rerun to retry"}]
        st.rerun()
    out = ROOT / "out"
    for fn in ("plan.md", "trace.txt"):
        if (out / fn).exists():
            st.download_button(f"Download {fn}", (out / fn).read_bytes(), file_name=fn)

for g in st.session_state.pop("last", []):
    d, msg = g.get("decision", ""), f"Msg {g.get('n', '')} · {g.get('frm', '')}: {g.get('decision', '')} — {g.get('reason', '')}"
    icon = "✅" if d == "ACCEPTED" else "🛡️" if d == "QUARANTINED" else "⛔" if d == "REJECTED" else "⚠️"
    st.toast(msg, icon=icon)
    (st.success if d == "ACCEPTED" else st.error if d in ("REJECTED", "QUARANTINED", "READ FAILED") else st.warning)(f"{icon} {msg}")

p = S.get("plan")
if S.get("infeasible"):
    st.error("INFEASIBLE after the latest message: " + "; ".join(S["infeasible"]) +
             (" — showing the last valid plan." if p else ""))
if not p:
    st.stop()
F, B, V, FD, SC = p["figures"], p["budget"], p["venue"], p["food"], p["schedule"]
cols = st.columns(6)
for c, (lab, val) in zip(cols, [("Headcount", F["headcount"]), ("Teams", F["teams"]),
                                ("Judges", f"{F['judges_used']}/{F['judges_available']}"),
                                ("Total (Rs)", f"{B['total']:,} / {B['budget']:,}"),
                                ("Run", len(S["runs"])), ("Session tokens", f"{S['tokens']:,}")]):
    c.metric(lab, val)
st.markdown("".join(f"<span class='badge {'ok' if c['ok'] else 'bad'}' title='{c['detail']}'>"
                    f"{'✔' if c['ok'] else '✘'} {c['name']}</span>" for c in S["checks"] or []), unsafe_allow_html=True)

t1, t2, t3, t4, t5, t6 = st.tabs(["Plan", "Messages", "Trace", "Changes", "Tokens", "🛡️ MTM Guardian"])
with t1:
    a, b = st.columns(2)
    with a:
        st.subheader(f"🏛 Venue: {V.get('name')}")
        st.write(f"{V.get('seats')} seats · Rs {V.get('cost', 0):,} ({V.get('basis')}) · from {V.get('src')}")
        st.caption(f"Cheapest option that fits {F['headcount']} people" +
                   (f" with {', '.join(V['required'])}" if V["required"] else ""))
        for r in V["rejected"]:
            st.write(f"✘ {r['name']} — {r['why']}")
        st.subheader(f"🍱 Food: {FD.get('name')}")
        st.write(f"{FD.get('boxes')} boxes (= headcount) × Rs {FD.get('pph', 0):,}" +
                 (f" + fee {FD['fee']:,}" if FD.get("fee") else "") + f" = **Rs {FD.get('cost', 0):,}** · {FD.get('src')}")
        for d in FD["diet"]:
            st.write(f"Diet: {d['type']} {d.get('n') or ''}{'%' if d.get('pct') else ''} ({d['src']})")
        st.subheader("⚖ Judging")
        st.write(f"{F['judges_used']} judges used, {F['standby']} standby · {F['rounds']} rounds × "
                 f"{F['min_per_team']} min = {F['judging_min']} min")
        st.dataframe([{"Judge": f"J{i + 1}", **{f"Round {k + 1}": t for k, t in enumerate(g)}}
                      for i, g in enumerate(p["judging"]["grid"])], hide_index=True, height=250)
    with b:
        st.subheader("🕒 Schedule" + (" (10:00 start is an assumption)" if SC["assumed"] else ""))
        st.dataframe([{"Time": x["time"], "Block": x["name"], "Min": x["min"], "Source": x["src"]}
                      for x in SC["blocks"]], hide_index=True)
        st.progress(1.0, text=" | ".join(f"{x['name'].split(' (')[0]} {x['min']}" for x in SC["blocks"]))
        st.subheader("💰 Budget")
        st.dataframe([{"Line": l["line"], "Basis": l["basis"], "Rs": f"{l['amount']:,}", "From": l["src"]}
                      for l in B["lines"]], hide_index=True)
        st.write(f"**Total Rs {B['total']:,}** · reserve Rs {B['reserve']:,} · remaining Rs {B['remaining']:,} "
                 f"of {B['budget']:,}")
        st.progress(min(1.0, (B["total"] + B["reserve"]) / max(1, B["budget"])), text="spent vs budget")
    if p["levers"] or p["notes"]:
        st.subheader("Decisions")
        for x in p["levers"] + p["notes"]:
            st.write("• " + x)

with t2:
    for m in reversed(S["msgs"]):
        cls = m["status"].split(" ")[0].replace("no", "noimpact") if m["status"] != "no impact" else "noimpact"
        with st.expander(f"Msg {m['n']} · {m['frm']} ({m['role']}) · {m['date'] or 'undated'} — {m['status'].upper()}",
                         expanded=m["status"] == "rejected"):
            st.markdown(f"<span class='chip {cls}'>{m['status']}</span>", unsafe_allow_html=True)
            st.write(m["reason"])
            facts = [f for f in S["facts"] if f["msg"] == m["n"]]
            if facts:
                st.dataframe([{"key": f["k"], "value": json.dumps(f["v"], ensure_ascii=False), "quote": str(f["q"]),
                               "status": f["status"], "reason": f["reason"]} for f in facts], hide_index=True)

with t3:
    runs = sorted({e["run"] for e in S["trace"]})
    r = st.selectbox("Run", ["all"] + runs)
    areas = sorted({e["area"] for e in S["trace"] if e["t"] == "call"})
    af = st.multiselect("Area", areas, default=areas)
    for e in S["trace"]:
        if r != "all" and e["run"] != r:
            continue
        if e["t"] == "call":
            if e["area"] not in af:
                continue
            u = e.get("usage")
            tok = f"prompt {u['prompt']} · completion {u['completion']} · total {u['total']}" if u else "not reported"
            with st.expander(f"#{e['n']} · {e['model']} · area={e['area']} · {tok}" + (" · FAILED" if e.get("error") else "")):
                st.caption("INPUT")
                st.code(e["input"], language=None)
                st.caption("OUTPUT")
                st.code(e.get("output") or e.get("error"), language="json")
        elif e["t"] == "code":
            st.markdown(f"<span style='color:#6e7781;font-family:monospace;font-size:.85rem'>[code] {e['text']}</span>",
                        unsafe_allow_html=True)
        else:
            st.markdown(f"**{e['text']}**")

with t4:
    for run in reversed(S["runs"]):
        st.subheader(f"Run {run['run']} · {run['mode']} · {run.get('calls', 0)} model call(s) · {run.get('tokens', 0):,} tokens")
        if run.get("failed"):
            st.warning("Read failed; text not consumed.")
            continue
        st.write(f"Areas recomputed (dependency map): **{', '.join(run['areas']) or 'none'}** · "
                 f"actually changed: **{', '.join(run['changed']) or 'none'}**")
        if run["before"]:
            st.dataframe([{"figure": k, "before": str(run["before"].get(k, "")), "after": str(run["after"].get(k, ""))}
                          for k in run["after"]], hide_index=True)
        for f in run["facts"]:
            st.write("• " + f)

with t5:
    rows = report.token_rows(S)
    st.subheader("Model calls and tokens (as reported by the API)")
    st.table([{k: str(v) for k, v in zip(("#", "Run", "Model", "Area", "Prompt", "Completion", "Total",
                                          "Status"), r)} for r in rows] +
             [{"#": "", "Run": "", "Model": "", "Area": "TOTAL", "Prompt": "", "Completion": "",
               "Total": f"{S['tokens']:,}", "Status": f"{S['calls']} calls"}])

with t6:
    A = S.get("audit", [])
    st.caption("Deterministic Python layer, 0 model calls: prompt-injection scan → authority matrix → six checks "
               "(commit only if valid) → SHA-256 hash-chained audit. Sender names are claimed identities, not verified.")
    dec = [a["decision"] for a in A]
    c = st.columns(6)
    for col, (lab, val) in zip(c, [("Messages processed", len(A)), ("Accepted", sum(d.startswith("ACCEPTED") for d in dec)),
                                   ("Rejected", dec.count("REJECTED")), ("Flagged", dec.count("FLAGGED")),
                                   ("Injection attempts", dec.count("QUARANTINED")),
                                   ("Audit chain", "✔ intact" if guardian.verify(A)["ok"] else "✘ BROKEN")]):
        col.metric(lab, val)
    if st.button("🔍 Verify Audit Integrity", type="primary"):
        fresh = json.loads(files[idx].read_text(encoding="utf-8")).get("audit", [])   # re-read the stored chain
        v = guardian.verify(fresh)
        if v["ok"]:
            st.success(f"✅ Audit chain verified: {v['at']} entries, every SHA-256 link matches. Head {str(v['head'])[:24]}…")
            st.balloons()
        else:
            st.error(f"⛔ Audit chain BROKEN at entry {v['at']}: {v['problem']}")
    risk_icon = {"high": "🔴 high", "medium": "🟠 medium", "low": "🟡 low", "none": "🟢 none"}
    st.subheader("Security decisions")
    st.dataframe([{"Msg": a["msg"], "Sender (claimed)": a["sender"]["name"], "Role": a["sender"]["role"],
                   "Risk": risk_icon.get(a["risk"], a["risk"]), "Decision": a["decision"], "Reason": a["reason"],
                   "Areas": ", ".join(a["areas"]) or "-", "Model calls": ", ".join(f"#{n}" for n in a["model_calls"])}
                  for a in reversed(A)], hide_index=True)
    st.subheader("Security event details")
    if A:
        pick = st.selectbox("Message", [a["msg"] for a in reversed(A)], format_func=lambda n: f"Msg {n} · " + next(
            a["sender"]["name"] + " · " + a["decision"] for a in A if a["msg"] == n))
        a = next(x for x in A if x["msg"] == pick)
        (st.success if a["decision"] == "ACCEPTED" else st.error if a["decision"] in ("REJECTED", "QUARANTINED")
         else st.warning)(f"**{a['decision']}** (risk {a['risk']}): {a['reason']}")
        l, r = st.columns(2)
        l.write(f"**Sender:** {a['sender']['name']} · role `{a['sender']['role']}` · {a['sender']['identity']}")
        l.write(f"**Injection patterns:** {', '.join(a['injection']) or 'none'}")
        l.write(f"**Run:** {a['run']} · **time:** {a['ts']} · **model calls:** {', '.join(f'#{n}' for n in a['model_calls']) or 'none'}")
        l.code(a["text"] or "(raw text not separable from the batch; see trace)", language=None)
        r.write("**Extracted facts**")
        r.dataframe([{"key": f["k"], "value": json.dumps(f["v"], ensure_ascii=False), "status": f["status"]}
                     for f in a["facts"]], hide_index=True)
        r.caption(f"audit #{a['seq']} · prev {a['prev'][:16]}… · hash {a['hash'][:16]}…")

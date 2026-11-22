"""Planner: every figure and decision in deterministic code. Same facts in -> same plan out."""
import math
import re
from itertools import combinations
from .resolver import norm

AREAS = ["venue", "schedule", "food", "judging", "budget"]
ALL = AREAS
# Dependency map: fact key -> plan areas it can change.
DEPS = {**{k: ALL for k in ("students", "team_size", "judges_available", "judges_change",
                            "max_teams_per_judge", "min_per_team", "judges_per_team")},
        **{k: ["venue", "food", "budget"] for k in ("staff", "extra_people")},
        "honorarium": ["budget"],
        **{k: ["venue", "budget"] for k in ("venue", "venue_require", "venue_exclude", "seat_factor")},
        **{k: ["food", "budget"] for k in ("food", "diet", "food_require")},
        **{k: ["schedule"] for k in ("block", "window", "late", "duration_min", "start_time", "end_time")},
        **{k: ["budget"] for k in ("cost", "budget", "reserve")}}
FEAT = {"backup power": "generator", "power backup": "generator", "ups": "generator", "generator": "generator",
        "genset": "generator", "ramp": "accessible", "lift": "accessible", "elevator": "accessible", "step-free": "accessible", "step free": "accessible", "wheelchair": "accessible", "ramp": "accessible", "accessib": "accessible",
        "air condition": "ac", "air-condition": "ac", "a/c": "ac", "projector": "projector", "wifi": "wifi"}


def affected(keys):
    return [a for a in AREAS if any(a in DEPS.get(k, []) for k in keys)]


def feat(s):
    s = str(s).lower().strip()
    return next((b for a, b in FEAT.items() if a in s), s)


def num(x, d=0):
    return x if isinstance(x, (int, float)) and not isinstance(x, bool) else d


def hm(s):
    m = re.match(r"^\s*(\d{1,2})(?::(\d{2}))?\s*(am|pm)?\s*$", str(s or "").lower())
    if not m:
        return None
    h, mi = int(m[1]), int(m[2] or 0)
    h += 12 if m[3] == "pm" and h < 12 else 0
    h = 0 if m[3] == "am" and h == 12 else h
    return h * 60 + mi


def clock(m):
    return f"{m // 60 % 24:02d}:{m % 60:02d}"


def gather(st):
    """Current values: scalars S[key]=(value, msg); named dict slots merged in date order."""
    S, D = {}, {}
    use = [f for f in st["facts"] if f["status"] in ("applied", "request") and f.get("use", True)
           and f["k"] not in ("claim", "teams")]
    for f in sorted(use, key=lambda f: f["eff"]):
        if f["slot"] == f["k"]:
            S[f["k"]] = (f["v"], f["msg"])
        else:
            d = D.setdefault(f["slot"], {"_k": f["k"], "_src": []})
            d.update(f["v"])
            d["_src"].append(f["msg"])
            d["_status"] = f["status"]
    return S, list(D.values())


def srcs(d):
    return "msg " + ",".join(str(x) for x in sorted(set(d.get("_src", []))))


def lay(seq, fixed, start, notes):
    out, t = [], start
    for b in seq:
        out.append({**b, "s": t, "e": t + b["min"]})
        t += b["min"]
    for fb in sorted(fixed, key=lambda b: b["at"]):
        a, new, sh = fb["at"], [], 0
        for b in out:
            b = {**b, "s": b["s"] + sh, "e": b["e"] + sh}
            if not sh and b["s"] < a < b["e"] and b["kind"] == "build":
                new += [{**b, "e": a, "min": a - b["s"]}, {**fb, "s": a, "e": a + fb["min"]},
                        {**b, "name": b["name"] + " (cont.)", "s": a + fb["min"], "e": b["e"] + fb["min"],
                         "min": b["e"] - a}]
                sh = fb["min"]
                continue
            if not sh and b["s"] >= a:
                if b["s"] != a:
                    notes.append(f"{fb['name']} placed at {clock(b['s'])}, not {clock(a)}")
                new.append({**fb, "s": b["s"], "e": b["s"] + fb["min"]})
                sh = fb["min"]
                b = {**b, "s": b["s"] + sh, "e": b["e"] + sh}
            new.append(b)
        if not sh:
            new.append({**fb, "s": new[-1]["e"], "e": new[-1]["e"] + fb["min"]})
        out = new
    return out


def window_problems(blocks, wins, lates, start):
    P = []
    jb = next((b for b in blocks if b["kind"] == "judging"), None)
    lb = next((b for b in blocks if b["kind"] == "lunch"), None)
    end = blocks[-1]["e"] if blocks else start
    for w in wins:
        what = str(w.get("what", "")).lower()
        fr, un = hm(w.get("from")), hm(w.get("until"))
        s, e = (jb["s"], jb["e"]) if "judg" in what and jb else (start, end)
        if fr is not None and s < fr:
            P.append(f"{w.get('what')}: starts {clock(s)}, window opens {clock(fr)}")
        if un is not None and e > un:
            P.append(f"{w.get('what')}: ends {clock(e)}, window closes {clock(un)}")
    for l in lates:
        who, m = str(l.get("who", "")).lower(), num(l.get("min"))
        b = jb if "judg" in who else lb if re.search("cater|food|lunch", who) else None
        if b and b["s"] - start < m:
            P.append(f"{l.get('who')} up to {m:g} min late but {b['name']} starts at +{b['s'] - start} min")
    return P


def rounds_txt(jname):
    m = re.search(r"\((\d+ rounds × \d+ min)", jname)
    return m[1] if m else "derived"


def schedule(cfg, dur, jname, jmin, of, g, main="Build (hacking)"):
    B, notes, probs = cfg["blocks"], [], []
    start, assumed = hm(g("start_time")), False
    wins = of("window")
    if start is None:
        vf = [hm(w.get("from")) for w in wins if hm(w.get("from")) is not None
              and "judg" not in str(w.get("what", "")).lower()]
        if vf:
            start = max(vf)
            notes.append(f"start {clock(start)} taken from availability window")
        else:
            start, assumed = hm(cfg["start_time"]), True
    mk = lambda name, m, src, kind: dict(name=name, min=int(m), src=src, kind=kind)
    df = {k: mk(v["name"], v["min"], "planner default", k) for k, v in B.items()}
    pre, mid, fixed = [], [], []
    for d in of("block"):
        if d.get("required") is False:
            continue
        n = str(d.get("name") or "block")
        low, b = n.lower(), mk(n, num(d.get("min")), srcs(d), "msg")
        if "lunch" in low:
            df["lunch"].update(name=n, min=b["min"], src=b["src"])
        elif re.search(r"clos|prize|award", low):
            df["closing"].update(name=n, min=b["min"], src=b["src"])
        elif "judg" in low:
            continue
        elif hm(d.get("at")) is not None:
            fixed.append({**b, "at": hm(d.get("at"))})
        elif re.search(r"open|inaug|welcome|recit|tilawat|keynote|registr|check.?in|arrival", low):
            pre.append(b)
        else:
            mid.append(b)
    judging = [mk(jname, jmin, "derived", "judging")] if jmin else []
    given_j = [num(d.get("min")) for d in of("block") if "judg" in str(d.get("name", "")).lower()]
    if given_j and jmin and max(given_j) != jmin:
        notes.append(f"judging block given as {max(given_j):g} min; planned {jmin} min = {rounds_txt(jname)}")
    opening = [] if pre else [df["opening"]]                 # user's registration/opening replaces the default
    main_given = any(re.search(r"coding|hack|build|competition|contest|session|workshop|programme|program|"
                               r"ceremony|main|talk|performance|activit|game|match", b["name"], re.I) for b in mid)
    others = pre + opening + mid + [df["lunch"], *judging, df["closing"]] + fixed
    build = dur - sum(b["min"] for b in others)
    min_build = 0 if main_given else cfg["min_build"]   # the user's own main activity is the build time
    for k in ("lunch", "opening"):
        s = B[k].get("shrink_to")
        if build < min_build and s and df[k]["src"] == "planner default" and df[k]["min"] > s:
            notes.append(f"build under {min_build} min: {k} shrunk {df[k]['min']}->{s} min")
            build += df[k]["min"] - s
            df[k]["min"] = s
    if build < 0:
        probs.append(f"schedule needs {-build} more minutes than the event has")
        build = 0
    bb = mk("Buffer / free time" if main_given else main, build, f"filler = {dur} - other blocks", "build")
    lates = of("late")
    seqs = ([[*pre, *opening, *mid, df["lunch"], *judging, bb, df["closing"]],
             [*pre, *opening, *mid, *judging, df["lunch"], bb, df["closing"]]] if main_given else
            [[*pre, *opening, bb, *mid, df["lunch"], *judging, df["closing"]],
             [*pre, *opening, bb, *mid, *judging, df["lunch"], df["closing"]]])
    for seq in seqs:
        blocks = lay(seq, fixed, start, notes)
        wp = window_problems(blocks, wins, lates, start)
        if not wp:
            break
    probs += wp
    for b in blocks:
        b["time"] = f"{clock(b['s'])}-{clock(b['e'])}"
    return dict(start=clock(start), assumed=assumed, blocks=blocks, duration=dur), notes, probs


def build(st, cfg):
    S, D = gather(st)
    g = lambda k, d=None: S[k][0] if k in S else d
    src = lambda k: f"msg {S[k][1]}" if k in S else "planner default"
    of = lambda k: [d for d in D if d["_k"] == k]
    notes, levers, probs = [], [], []
    st_, en_ = hm(g("start_time")), hm(g("end_time"))
    dur = g("duration_min") or (en_ - st_ if st_ is not None and en_ is not None else None)
    missing = [n for k, n in (("students", "how many guests / participants"), ("budget", "the total budget"))
               if not g(k)]
    if missing:
        return None, [f"provide: {m}" for m in missing]
    if not dur:
        dur = int(cfg["default_duration_min"])
        notes.append(f"event length not given: planner assumption {dur // 60} h")
    students, dur, budget = int(g("students")), int(dur), int(g("budget"))
    ts = int(g("team_size") or 0)
    teams = math.ceil(students / ts) if ts else 0
    jpt = int(g("judges_per_team", cfg["judges_per_team"]))
    mx, avail = g("max_teams_per_judge"), g("judges_available")
    if avail is not None:
        avail = int(avail) + int(sum(num(d.get("delta")) for d in of("judges_change")))
    skipped = set()
    for d in of("skip"):
        a = str(d.get("area", "")).lower()
        skipped.add("food" if any(w in a for w in ("food", "cater", "lunch", "meal", "khana")) else
                    "judging" if "judg" in a else "venue" if any(w in a for w in ("venue", "hall", "marquee")) else a)
    # Judging only for competitions: teams, or any judging fact. A wedding or seminar has none.
    judging = (bool(ts) or any(k in S for k in ("judges_available", "max_teams_per_judge", "min_per_team"))) \
        and "judging" not in skipped
    need = used = rounds = jmin = 0
    mpt = g("min_per_team")
    if judging:
        if not teams:
            probs.append("provide: team size (judging needs teams)")
        elif mx:
            need = math.ceil(teams * jpt / int(mx))
        else:
            need = avail or 0
            if need:
                notes.append("no max teams per judge given: all available judges are used")
        if teams and avail is None:
            probs.append("provide: how many judges are available (plus fee, minutes per team, max teams per judge)")
        elif teams and need > avail:
            probs.append(f"needs {need - avail} more judge(s): {need} needed for {teams} teams at max {mx}/judge, "
                         f"only {avail} available")
        used = need or (1 if teams else 0)
        if mpt is None:
            mpt = cfg["min_per_team"]
            notes.append(f"minutes per team not given: planner assumption {mpt}")
        rounds = math.ceil(teams * jpt / used) if used else 0
        jmin = rounds * int(mpt)
    staff = int(g("staff", 0))
    extra = sum(int(num(d.get("n"))) for d in of("extra_people"))
    hc = students + used + staff + extra
    fig = dict(event=g("event_type") or "event", judging=judging, skipped=sorted(skipped), students=students, team_size=ts, teams=teams, judges_available=avail, judges_needed=need,
               judges_used=used, standby=max(0, (avail or 0) - used), judges_per_team=jpt,
               max_teams_per_judge=mx, min_per_team=mpt, rounds=rounds, judging_min=jmin, staff=staff,
               extra=extra, headcount=hc, duration_min=dur, budget=budget)
    if fig["standby"]:
        notes.append(f"decision: {used} judges used, {fig['standby']} on standby (not paid or fed)")

    # Venue: available, not excluded, fits, has required features; cheapest wins (tie: more seats)
    rv, reserve = g("reserve"), 0
    if isinstance(rv, dict):
        reserve = round(num(rv.get("amount")) or budget * num(rv.get("pct")) / 100)
    elif rv:
        reserve = int(num(rv))
    sf = g("seat_factor")
    pct = num(sf.get("pct"), 100) if isinstance(sf, dict) else num(sf, 100)
    vnames = {norm(d.get("name", "")) for d in of("venue")}
    is_name = lambda f: norm(f) in vnames or re.search(r"\b(hall|room|marquee|lawn|auditorium|banquet)\b", str(f), re.I)
    bad_req = [d.get("feature") for d in of("venue_require") if is_name(d.get("feature", ""))]
    if bad_req:
        notes.append(f"ignored venue requirement(s) {', '.join(map(str, bad_req))}: a venue name is not a feature")
    req = sorted({feat(d.get("feature", "")) for d in of("venue_require") if not is_name(d.get("feature", ""))})
    excl = {norm(d.get("name", "")) for d in of("venue_exclude")}
    valid, rejected = [], []
    for d in of("venue"):
        name, seats, price = d.get("name", "?"), int(num(d.get("seats"))), d.get("price")
        feats = sorted({feat(x) for x in d.get("features") or []})
        eff = int(seats * pct / 100)
        why = ("not available" if d.get("available") is False else "excluded" if norm(name) in excl
               else "no price given" if num(price, None) is None
               else f"{eff} seats < {hc} people" if eff < hc else None)
        miss = [r for r in req if r not in feats]
        if not why and miss:
            why = f"lacks {', '.join(miss)} (not mentioned for this venue)"
        per_hour = str(d.get("basis", "fixed")) == "per_hour"
        cost = round(num(price) * dur / 60) if per_hour else int(num(price))
        v = dict(name=name, seats=seats, eff_seats=eff, cost=cost, features=feats, src=srcs(d),
                 basis=f"{num(price):,.0f}/h × {dur / 60:g} h" if per_hour else "fixed")
        (rejected.append({**v, "why": why}) if why else valid.append(v))
    valid.sort(key=lambda v: (v["cost"], -v["seats"]))
    if not of("venue") and "venue" in skipped:
        notes.append("venue skipped: arranged separately by the organiser")
        valid = [None]
    elif not of("venue"):
        probs.append(f"provide: venue options with seats and price, at least {hc} seats"
                     + (f" with {', '.join(req)}" if req else "") + " (e.g. 'Marquee X seats 300 for Rs 2 lakh')")
        valid = [None]
    elif not valid:
        probs.append(f"no venue fits {hc} people" + (f" with {', '.join(req)}" if req else "")
                     + ": provide a bigger venue option or reduce the guest list")

    # Food: tiers are alternatives; boxes always = headcount
    gfee = sum(num(d.get("fee")) for d in of("food") if d.get("price_per_head") is None)
    fo_all = []
    for d in of("food"):
        if num(d.get("price_per_head"), None) is None:
            continue
        pph, qty = num(d["price_per_head"]), max(hc, int(num(d.get("min_order"))))
        fee = int(num(d.get("fee")) + gfee)
        fo_all.append(dict(name=d.get("name"), pph=int(pph), boxes=hc, qty=qty, fee=fee,
                           cost=int(qty * pph + fee), src=srcs(d)))
    freq = {norm(d.get("name", "")) for d in of("food_require")}
    fopts = [f for f in fo_all if norm(f["name"]) in freq] or fo_all
    if not fopts:
        if "food" in skipped:
            notes.append("catering skipped by the organiser")
        else:
            probs.append("provide: catering price per person (e.g. 'menu Rs 2,500 per head')")
        fopts = [None]
    diet = [dict(type=d.get("type"), n=d.get("n"), pct=d.get("pct"), src=srcs(d)) for d in of("diet")]

    # Budget optimiser: venue x food x optional subsets; prefer better food, more extras, lower total
    hon = int(num(g("honorarium")))
    costs = of("cost")
    pctc = [c for c in costs if str(c.get("basis", "")).startswith("pct")]
    reqc = [c for c in costs if c not in pctc and c.get("status") != "optional" and c["_status"] == "applied"]
    opt = [c for c in costs if c not in pctc and c not in reqc]

    def amount(c):
        a, b = num(c.get("amount")), str(c.get("basis") or "fixed")
        mult = {"per_head": hc, "per_team": teams, "per_judge": used}.get(b)
        return round(a * mult) if mult else round(a), (f"{a:,.0f} × {mult}" if mult else b)

    def lines(v, fo, sub):
        L = [dict(line=f"{str(c.get('status', 'required')).title()}: {c.get('name')}", basis=amount(c)[1],
                  amount=amount(c)[0], kind="required", src=srcs(c)) for c in reqc]
        if v:
            L.append(dict(line=f"Venue: {v['name']}", basis=v["basis"], amount=v["cost"], kind="required", src=v["src"]))
        if hon:
            L.append(dict(line="Judges' honorarium", basis=f"{used} × {hon:,}", amount=used * hon,
                          kind="required", src=src("honorarium")))
        if fo:
            L.append(dict(line=f"Food: {fo['name']}", basis=f"{fo['qty']} × {fo['pph']:,}" +
                          (f" + fee {fo['fee']:,}" if fo["fee"] else ""), amount=fo["cost"], kind="required", src=fo["src"]))
        base = sum(x["amount"] for x in L)
        for c in pctc:
            tgt = str(c.get("basis")).split(":")[-1] if ":" in str(c.get("basis")) else "all"
            t = {"venue": v["cost"] if v else 0, "food": fo["cost"] if fo else 0, "judges": used * hon}.get(tgt, base)
            L.append(dict(line=str(c.get("name")), basis=f"{num(c.get('amount')):g}% of {tgt}",
                          amount=round(t * num(c.get("amount")) / 100), kind="required", src=srcs(c)))
        L += [dict(line=f"{c.get('name')} (optional)", basis=amount(c)[1], amount=amount(c)[0],
                   kind="optional", src=srcs(c)) for c in sub]
        return L

    best = cheapest = None
    for v in valid:
        for fo in fopts:
            for r in range(len(opt) + 1):
                for sub in combinations(opt, r):
                    L = lines(v, fo, sub)
                    tot = sum(x["amount"] for x in L)
                    if r == 0 and (cheapest is None or tot < cheapest[0]):
                        cheapest = (tot, v, fo, (), L)
                    key = (fo["pph"] if fo else 0, r, -tot)
                    if tot + reserve <= budget and (best is None or key > best[0]):
                        best = (key, v, fo, sub, L)
    if best:
        _, v, fo, sub, L = best
    elif cheapest:
        _, v, fo, sub, L = cheapest
        probs.append(f"over budget: needs Rs {cheapest[0] + reserve - budget:,} more "
                     f"(cheapest valid plan Rs {cheapest[0]:,}" + (f" + reserve {reserve:,}" if reserve else "") +
                     f" vs budget {budget:,})")
    else:
        v = fo = None
        sub, L = (), []
    total = sum(x["amount"] for x in L)
    if fo:
        top = max((f for f in fopts if f), key=lambda f: f["pph"])
        if fo["pph"] < top["pph"]:
            levers.append(f"cheaper food tier: {fo['name']} (Rs {fo['pph']:,}) because {top['name']} does not fit")
        for c in opt:
            if c not in sub:
                levers.append(f"dropped optional {c.get('name')} (Rs {amount(c)[0]:,}): does not fit the budget")
            else:
                notes.append(f"optional {c.get('name')} included; headroom Rs {budget - reserve - total:,}")

    jname = f"Judging ({rounds} rounds × {mpt} min, {used} judges in parallel)"
    sched, n2, p2 = schedule(cfg, dur, jname, jmin, of, g, "Build (hacking)" if teams else "Main programme")
    notes += n2
    probs += p2
    grid = [[] for _ in range(used)]
    for i in range(teams * jpt if used else 0):
        grid[i % used].append(f"T{i // jpt + 1}")
    req_costs = sum(x["amount"] for x in L if x["kind"] == "required")
    needs = [x[len("provide: "):] for x in probs if x.startswith("provide: ")]
    p = dict(feasible=not probs, problems=probs, needs=needs, figures=fig, levers=levers, notes=notes,
             venue=dict(v or {}, required=req, rejected=rejected, pct=pct),
             food=dict(fo or {}, options=fo_all, diet=diet),
             judging=dict(judges=used, grid=grid, min_per_team=mpt, rounds=rounds),
             budget=dict(lines=L, required=req_costs, optional=total - req_costs, total=total, budget=budget,
                         reserve=reserve, remaining=budget - reserve - total),
             schedule=sched)
    return p, probs

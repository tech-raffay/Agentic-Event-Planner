"""Resolver: decides each fact's status with ordered rules (pure code, 0 tokens)."""
import re

EVENT = "event_type students team_size duration_min start_time end_time staff extra_people block window".split()
JUDGING = "judges_available min_per_team max_teams_per_judge judges_per_team".split()
# Authority matrix: key -> roles that own it (a design rule, not pack data). None = anyone.
OWN = {**{k: {"authority"} for k in EVENT}, **{k: {"judging", "authority"} for k in JUDGING},
       "budget": {"authority", "finance"}, "reserve": {"authority", "finance"},
       "honorarium": {"judging", "authority", "finance"},
       "venue": {"venue"}, "seat_factor": {"venue", "authority"},
       "venue_require": {"authority", "venue", "official", "finance"},
       "venue_exclude": {"authority", "venue", "official"},
       "food": {"caterer"}, "food_require": {"authority"}, "diet": {"authority", "caterer"},
       "judges_change": {"judging", "authority", "judge"}, "late": None, "skip": {"authority"}}
NAMED = {"skip": "area", "venue": "name", "food": "name", "cost": "name", "block": "name", "diet": "type",
         "venue_require": "feature", "venue_exclude": "name", "extra_people": "who",
         "late": "who", "window": "what", "food_require": "name"}
FILLER = r"\b(box|boxes|lunch|meal|meals|wala|wali|package|option|the|bill|charges?|cost)\b"


def norm(s):
    s = str(s).lower()
    return " ".join(re.sub(FILLER, " ", s).split()) or " ".join(s.split())


def slot(k, v, fid):
    if k in ("judges_change", "claim", "teams"):
        return f"{k}#{fid}"
    f = NAMED.get(k)
    return f"{k}:{norm(v.get(f, ''))}" if f and isinstance(v, dict) else k


def fmt(v):
    if isinstance(v, dict):
        return "{" + ", ".join(f"{a}={fmt(b)}" for a, b in v.items() if not str(a).startswith("_")) + "}"
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return f"{v:,.0f}" if abs(v) >= 1000 else f"{v:g}"
    return str(v)


def desc(f):
    return f"msg {f['msg']} {f['k']}={fmt(f['v'])}"


def venue_names(st):
    return {str(f["v"].get("name", "")).lower() for f in st["facts"] if f["k"] == "venue" and isinstance(f["v"], dict)}


def current(st, s):
    c = [f for f in st["facts"] if f["slot"] == s and f["status"] in ("applied", "request")]
    return max(c, key=lambda f: f["eff"]) if c else None


def covers(new, old):
    return not isinstance(old, dict) or all(k in new for k in old)


def _set(f, status, reason, tr):
    f["status"], f["reason"] = status, reason
    tr.code(f"resolver  {desc(f)}  {status.upper()} ({reason})")


def resolve(st, f, tr):
    k, v, role = f["k"], f["v"], f["role"]
    # The person using the planner UI is the organiser: full authority, and may enter vendor quotes.
    eff = {"authority", "venue", "caterer", "finance", "judging"} if role == "organizer" else {role}
    who = f"{f['from']} ({role})"
    if k in ("claim", "teams"):           # rule 2 is checked after planning
        f["status"] = "pending"
        return
    if k == "cost":
        status = v.get("status", "required")
        if status == "optional" and not eff & {"finance", "authority"}:   # rule 8
            return _set(f, "request", f"optional request from {who}; included only if it fits", tr)
        owners = None if status == "optional" else {"finance", "authority"} if status == "committed" \
            else {"finance", "authority", "venue", "caterer", "vendor"}
    else:
        owners = OWN.get(k)
    if k == "window" and not re.search(r"venue|hall|event|hackathon|judg|room|centre|center|marquee|auditorium|"
                                       r"competition|programme|program", str(v.get("what", "")), re.I) \
            and not any(n and n in str(v.get("what", "")).lower() for n in venue_names(st)):
        return _set(f, "no_impact", f"about {v.get('what')}, not this event or its venue; no effect on the plan", tr)
    if k == "extra_people" and re.search(r"registered|participant|student|wheelchair|already", f.get("q", "") + " "
                                         + str(v.get("who", "")), re.I):
        return _set(f, "no_impact", "these people are already counted among the participants", tr)
    if k == "judges_change" and role == "judge" and v.get("delta", 0) not in (-1, -1.0):
        return _set(f, "rejected", f"a judge may only report their own withdrawal (-1), not {v.get('delta')}", tr)
    if owners is not None and not eff & owners:                              # rule 3 / 4
        cur = current(st, f["slot"])
        rule = f"; standing rule {k}={fmt(cur['v'])} (msg {cur['msg']}) stays" if cur else ""
        own = "/".join(sorted(owners))
        if k == "diet":
            return _set(f, "request", f"dietary request from {who}; noted as a food line", tr)
        if f.get("req"):
            f["use"] = False
            return _set(f, "request", f"request from {who}; {k} is set by {own}; noted, not applied{rule}", tr)
        return _set(f, "rejected", f"no authority: {who} cannot set {k}; owner is {own}{rule}", tr)
    cur = current(st, f["slot"])
    if cur and cur["eff"] > f["eff"]:                                        # rule 6
        return _set(f, "superseded", f"stale: dated {f['date'] or 'undated'}; current value from msg "
                                     f"{cur['msg']} ({cur['date'] or 'undated'}) stands", tr)
    reason = f"{who} owns {k}" if owners else f"accepted from {who}"
    if cur:                                                                  # rule 7
        reason = f"newer value from {who}: {fmt(cur['v'])} -> {fmt(v)}"
        for o in st["facts"]:
            if o["slot"] == f["slot"] and o["status"] == "applied" and covers(v, o["v"]):
                o["status"], o["reason"] = "superseded", f"replaced by msg {f['msg']} (newer, same owner group)"
                tr.code(f"superseded {desc(o)}")
    _set(f, "applied", reason, tr)

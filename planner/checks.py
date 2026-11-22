"""The six checks, recomputed independently from the current facts."""
import math
from .plan import gather, window_problems, num


def run(p, st):
    S, D = gather(st)
    g = lambda k, d=None: S[k][0] if k in S else d
    of = lambda k: [d for d in D if d["_k"] == k]
    F, B, V, FD, J, SC = (p[k] for k in ("figures", "budget", "venue", "food", "judging", "schedule"))
    R = []
    add = lambda n, ok, d: R.append(dict(name=n, ok=bool(ok), detail=d))

    students, ts = int(g("students", 0)), int(g("team_size") or 0)
    teams = math.ceil(students / ts) if ts else 0
    jpt, mx = F["judges_per_team"], g("max_teams_per_judge")
    jn = math.ceil(teams * jpt / int(mx)) if mx and teams else F["judges_used"]
    hc = students + jn + int(g("staff", 0)) + sum(int(num(d.get("n"))) for d in of("extra_people"))
    s = sum(l["amount"] for l in B["lines"])
    food = bool(FD.get("name"))
    fok = not food or FD.get("cost") == FD.get("qty", 0) * FD.get("pph", 0) + FD.get("fee", 0)
    add("Correct figures", teams == F["teams"] and jn == F["judges_used"] and hc == F["headcount"]
        and (not food or FD.get("boxes") == hc) and s == B["total"] and fok,
        f"teams {teams}, judges {jn}, headcount {hc} = boxes {FD.get('boxes')}, lines sum {s:,} = total {B['total']:,}")

    add("Within budget", B["total"] + B["reserve"] <= int(g("budget", 0)),
        f"{B['total']:,} + reserve {B['reserve']:,} <= {int(g('budget', 0)):,}")

    feats = V.get("features", [])
    if not V.get("name") and "venue" in F.get("skipped", []):
        add("Venue fits", True, "venue arranged separately (skipped)")
    else:
        add("Venue fits", V.get("name") and V.get("eff_seats", 0) >= hc and all(r in feats for r in V["required"]),
            f"{V.get('name')}: {V.get('eff_seats')} seats >= {hc}; features ok" if V.get("name") else "no venue")

    bl = SC["blocks"]
    contiguous = all(bl[i]["e"] == bl[i + 1]["s"] for i in range(len(bl) - 1))
    total_min = sum(b["min"] for b in bl)
    names = {b["name"] for b in bl}
    req = [str(d.get("name")) for d in of("block") if d.get("required") is not False
           and "judg" not in str(d.get("name")).lower()]
    have_req = all(any(r == n or r in n for n in names) or any(
        b["src"].startswith("msg") for b in bl if r.lower() in b["name"].lower()) for r in req)
    jb = next((b for b in bl if b["kind"] == "judging"), {"min": 0})
    wp = window_problems(bl, of("window"), of("late"), bl[0]["s"] if bl else 0)
    add("Schedule valid", total_min == F["duration_min"] and contiguous and have_req and
        jb["min"] >= F["rounds"] * int(F["min_per_team"] or 0) and not wp and all(b["min"] >= 0 for b in bl),
        f"{total_min}/{F['duration_min']} min, no overlaps, required blocks present, judging {jb['min']} min"
        + (f"; {'; '.join(wp)}" if wp else ""))

    av = F["judges_available"]
    if not F.get("judging", True):
        add("Enough judges", True, "no judging for this event")
    else:
        add("Enough judges", av is not None and F["judges_used"] <= av and
            (not mx or F["judges_used"] * int(mx) >= teams * jpt),
            f"{F['judges_used']} used <= {av} available; {F['judges_used']} × {mx} >= {teams * jpt} team slots")

    sk = F.get("skipped", [])
    areas = dict(venue=V.get("name") or ("venue" in sk), schedule=bl, food=FD.get("name") or ("food" in sk), budget=B["lines"])
    if F.get("judging", True):
        areas["judging"] = J["grid"]
    add("All areas covered", all(areas.values()), ", ".join(k for k, v in areas.items() if v) or "none")
    return R

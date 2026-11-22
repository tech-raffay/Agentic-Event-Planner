# Hackathon plan
Run 1 · checks 6/6 · session model calls 2 · session tokens 3,103

## Key figures
| Figure | Value |
|---|---|
| Teams | ceil(120 / 4) = 30 |
| Judges | 8 used of 15 available (7 standby) |
| Judging | 4 rounds × 20 min = 80 min |
| Headcount | 120 + 8 + 8 = 136 |

## Venue
**Hall 2** — 180 seats, Rs 110,000 (fixed, msg 2). Cheapest option that fits 136 people with accessible.
- Seminar Room: rejected, 100 seats < 136 people
- Hall 1: rejected, lacks accessible (not mentioned for this venue)
- Hall 3: rejected, not available

## Schedule (start time not given: 10:00 is a planner assumption)
| Time | Block | Min | Source |
|---|---|---|---|
| 10:00-10:15 | Opening / welcome | 15 | planner default |
| 10:15-11:35 | Build (hacking) | 80 | filler = 240 - other blocks |
| 11:35-11:55 | prayer break | 20 | msg 1 |
| 11:55-12:25 | Meal break | 30 | planner default |
| 12:25-13:45 | Judging (4 rounds × 20 min, 8 judges in parallel) | 80 | derived |
| 13:45-14:00 | Closing | 15 | planner default |

## Food
**biryani box**: 136 boxes (= headcount) × Rs 850 = Rs 115,600

## Judging
8 judges, round-robin:
- J1: T1, T9, T17, T25
- J2: T2, T10, T18, T26
- J3: T3, T11, T19, T27
- J4: T4, T12, T20, T28
- J5: T5, T13, T21, T29
- J6: T6, T14, T22, T30
- J7: T7, T15, T23
- J8: T8, T16, T24

## Budget
| Line | Basis | Rs |
|---|---|---|
| Committed: trophies | fixed | 60,000 |
| Committed: banners | fixed | 15,000 |
| Venue: Hall 2 | fixed | 110,000 |
| Judges' honorarium | 8 × 4,000 | 32,000 |
| Food: biryani box | 136 × 850 | 115,600 |
| service charge | 10% of food | 11,560 |
| photo booth (optional) | fixed | 30,000 |
| **Total** | | **374,160** |
| Reserve | | 0 |
| Remaining of 400,000 | | 25,840 |

## Decisions
- decision: 8 judges used, 7 on standby (not paid or fed)
- optional photo booth included; headroom Rs 25,840

## Checks
- PASS **Correct figures**: teams 30, judges 8, headcount 136 = boxes 136, lines sum 374,160 = total 374,160
- PASS **Within budget**: 374,160 + reserve 0 <= 400,000
- PASS **Venue fits**: Hall 2: 180 seats >= 136; features ok
- PASS **Schedule valid**: 240/240 min, no overlaps, required blocks present, judging 80 min
- PASS **Enough judges**: 8 used <= 15 available; 8 × 4 >= 30 team slots
- PASS **All areas covered**: venue, schedule, food, budget, judging

## Message ledger
| Msg | From | Status | Reason |
|---|---|---|---|
| 1 | Registrar's office | applied | students: Registrar's office (authority) owns students; team_size: Registrar's office (authority) owns team_size; duration_min: Registrar's office (authority) owns duration_min; budget: Registrar's office (authority) owns budget; staff: Registrar's office (authority) owns staff; block: Registrar's office (authority) owns block |
| 2 | Faisal Convention Centre | applied | venue: Faisal Convention Centre (venue) owns venue; venue: Faisal Convention Centre (venue) owns venue; venue: Faisal Convention Centre (venue) owns venue; venue: Faisal Convention Centre (venue) owns venue; venue_require: Faisal Convention Centre (venue) owns venue_require |
| 3 | Student disability office | applied | extra_people: these people are already counted among the participants; venue_require: Student disability office (official) owns venue_require |
| 4 | Caterer | superseded | food: replaced by msg 5 (newer, same owner group) |
| 5 | Caterer | applied | food: newer value from Caterer (caterer): {name=biryani box, price_per_head=700, fee=0, min_order=0} -> {name=biryani box, price_per_head=850, fee=0, min_order=0}; food: Caterer (caterer) owns food; cost: Caterer (caterer) owns cost |
| 6 | Judging lead | applied | judges_available: Judging lead (judging) owns judges_available; honorarium: Judging lead (judging) owns honorarium; min_per_team: Judging lead (judging) owns min_per_team; max_teams_per_judge: Judging lead (judging) owns max_teams_per_judge |
| 7 | Finance | applied | cost: Finance (finance) owns cost; cost: Finance (finance) owns cost |
| 8 | Student society | request → included | cost: optional request from Student society (student); included only if it fits |
| 9 | Faisal Convention Centre | applied | venue: newer value from Faisal Convention Centre (venue): {name=Hall 3, seats=250, price=160,000, basis=fixed, features=['accessible'], available=True} -> {name=Hall 3, available=False} |
| 10 | Library | no impact | no plan facts (notice about the library, not this event) |

## Model calls and tokens (as reported by the API)
| # | Run | Model | Area | Prompt | Completion | Total |
|---|---|---|---|---|---|---|
| 1 | 1 | openai/gpt-oss-20b | reading | 1853 | 1250 | 3103 |
| 2 | 1 | groq/openai/gpt-oss-20b | venue | not reported | not reported | not reported |
| | | | **Total** | | | **3,103** |

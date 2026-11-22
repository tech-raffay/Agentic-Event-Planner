# PRD — Mind to Machine Hackathon Planner Agent

Nov 18, 2026 · @asiya

## TL;DR — the winning strategy

Build **one small-model reading call that turns messages into typed facts, and do everything else in plain code**. Code resolves conflicts, computes the plan, runs the six checks and rejects bad messages with a printed reason. This design is aimed at every scoring line at once: it has the fewest tokens, qualifies for the +10 small-model bonus, and makes changes predictable (an update makes one model call, tagged `reading`).

- **The LLM only reads.** A full run is one batched `reading` call. An update is one `reading` call for the new message. Area-tagged calls (`venue`, `food`, …) happen only when a message has a constraint the fact schema cannot express. That is the escape hatch for unseen constraint kinds.
- **Code does arithmetic and decisions.** That covers headcount, teams, judges needed, venue choice, food tier, optional extras, schedule, judge assignment and budget.
- **Derived numbers are never taken from messages.** Headcount, box count, judges needed and totals are always computed. Any message that asserts a different value is rejected. This alone catches the sample wrong message (100 boxes vs 177 people).
- **Who sent it matters.** Each fact key has owner roles. A non-owner can make a *request* (optional, included only if it fits) but cannot change a *rule*.
- **Latest dated message from the owner wins.** Older ones are marked *superseded* in the trace and the UI.
- **One command, no flags:** `python run.py <messages.txt>`. New messages are pasted onto the end of the same file and the same command is run again. The system diffs against saved state and runs an update.
- **The UI** (Streamlit) shows a plan with 6/6 check badges, a numbered trace with tokens, and a message ledger: applied / superseded / rejected / request / irrelevant, each with its reason.

Time check: it is 10:50 and code freeze is 1:25. That leaves about 2 h 35 min. The timeline in the last section is cut to fit.

## 1. The brief, decoded

The goal is an agent system that reads about 10 messages (email, WhatsApp, notices; English + Roman Urdu) and plans a 4-hour hackathon in Islamabad for 150 students in 50 teams. The plan covers **venue, schedule, food, judging and budget**. The judging pack is unseen and uses new numbers, wording, senders and kinds of constraint.

### Hard requirements (each one is a disqualification or points risk)

| # | Requirement | What it means for the build |
| --- | --- | --- |
| R1 | Read every message from a text file, exactly as given; no facts typed into code | Raw file text goes to the model. No pack numbers, names or examples in `.py` files or prompts; few-shot examples use invented data |
| R2 | Same command for every message; no flags, hints or edits | `python run.py <file>`; updates = paste new message at the end of the file, rerun |
| R3 | Trace: every model call numbered, model name, ONE area tag, input, output, tokens as the model reports them; total at end | Log the API's `usage` fields, never estimate. Wrong tokens, model names or areas in the trace = disqualification |
| R4 | Accept new messages after the first run and update the plan | Persist state; incremental update path |
| R5 | Conflict with a rule or other facts → keep the plan valid, print the reason in the trace | Code validator + resolver with explicit reasons |
| L1 | Full run cut off at 2 min | One batched call, per-call timeout, fallback provider |
| L2 | Update: max 5 model calls, cut off at 1 min | Hard call-budget counter = 5 per update |
| L3 | UI is scored | Plan + trace + rejected messages, all clear |

### Scoring and how this design earns each point

| Component | Pts | How we earn it |
| --- | --- | --- |
| Output (6 checks) | 30 | Code computes every figure and runs the same six checks before printing: correct figures, within budget, venue fits, schedule valid, enough judges, all areas covered |
| Catching the wrong message | 20 | Resolver rules (derived-value claims, authority, staleness, rule violations); reason printed in trace + UI |
| Understanding | 20 | Small system; every member can explain each part and what breaks without it (Q&A sheet at the end) |
| Handling change | 10 | Dependency map recomputes only affected areas; one `reading` call per update |
| UI | 10 | Three-tab Streamlit app + rich terminal output |
| Predicting a change | 5 | The rule is simple: `reading` only, plus an area tag only if the message has an unmappable constraint |
| Token use | 5 | One batched call, compact prompt, short JSON keys |
| Bonus: small models only | +10 | Every call uses a model on the organizers' small-model list (or a local model) |

Tie-breaks, in order: catching the wrong message, handling change, token use. All three favour this design.

### Traps hidden in the brief

- **177, not 180, people to feed.** 50 teams ÷ max 3 teams per judge = 17 judges needed (not all 20 confirmed). So 150 students + 17 judges + 10 staff = 177. The system must *derive* how many judges to use.
- **Out-of-date message.** The caterer's 20 Oct price (Rs 1,000) is superseded by the 12 Nov Roman Urdu message (standard Rs 1,200, basic Rs 800).
- **Irrelevant messages.** The judge 10 min late is noise *if* judging isn't in the first 10 min. Check it in code; don't ignore it blindly.
- **Requests vs rules.** The student society's DJ (Rs 50,000) is a request, not an approved cost.
- **"Constraints of a kind you have not seen".** A fixed list of fields will fail. You need a generic fact vocabulary plus an escape hatch.
- **Two of three test messages are real changes; one is plausible but wrong.** Rejecting a real change loses Output points. Accepting the wrong one loses 20.
- **Prediction slip.** Your system's model-call behaviour must be simple enough to predict on paper.
- **`git status` must be clean before the test run.** State and output files must be in `.gitignore`. API keys go in env vars, never committed.
- **Code review of the top 5.** No pack facts in code, no code changes after 1:25, honest trace.

## 2. Expected answer on the sample pack (your regression test)

On the sample pack the plan should come out at **177 people, 17 judges, Hall A, standard lunch, Rs 597,400 of Rs 650,000**. It should pass 6/6 checks. Use these numbers as your acceptance test; they live in a test fixture file, never in code.

### Message ledger

| Msg | Status | Reason the trace should print |
| --- | --- | --- |
| 1 Dean | Applied | Authority: students 150, team size 3, 4 h, budget Rs 650,000, staff 10, prayer break 15 min |
| 2 Venue | Applied | Venue owner: 4 options with seats, price, generator |
| 3 Caterer 20 Oct | Superseded | Same key (standard box price) from the same owner, newer message dated 12 Nov |
| 4 Caterer 12 Nov | Applied | Standard Rs 1,200, basic Rs 800, delivery Rs 0 |
| 5 Judging coord. | Applied | 20 available, Rs 5,000 each, 15 min/team, max 3 teams/judge |
| 6 Finance | Applied | Committed: prizes 100,000, internet 20,000, printing 10,000 |
| 7 Student society | Request → included | Optional DJ Rs 50,000; fits after all required costs |
| 8 A judge | No impact | Judge up to 10 min late; judging starts at +3:00, so no effect |

### Derived figures (all computed in code)

- Teams = ceil(150 ÷ 3) = **50**
- Judges needed = ceil(50 × 1 judge per team ÷ 3) = **17** (≤ 20 available; 3 on standby, not paid)
- Judging rounds = ceil(50 ÷ 17) = 3 → 3 × 15 min = **45 min** judging block
- Headcount = 150 + 17 + 10 = **177**
- Venue = cheapest option with seats ≥ 177 and all required features → **Hall A (200 seats, Rs 120,000)**

### Budget

| Line | Basis | Rs |
| --- | --- | --- |
| Committed: prizes | Finance | 100,000 |
| Committed: backup internet | Finance | 20,000 |
| Committed: printing | Finance | 10,000 |
| Venue: Hall A | fixed | 120,000 |
| Judges' honorarium | 17 × 5,000 | 85,000 |
| Food: standard box | 177 × 1,200 | 212,400 |
| **Required subtotal** |  | **547,400** |
| DJ (optional request) | fixed | 50,000 |
| **Total** |  | **597,400** |
| Remaining of 650,000 |  | 52,600 |

### Schedule (start time not given in the pack → shown as 10:00 and labelled an assumption)

| Time | Block | Min | Source |
| --- | --- | --- | --- |
| 10:00–10:15 | Opening and briefing | 15 | planner default |
| 10:15–12:15 | Build | 120 | filler = 240 − the rest |
| 12:15–12:30 | Prayer break | 15 | Msg 1 |
| 12:30–13:00 | Lunch | 30 | planner default |
| 13:00–13:45 | Judging (3 rounds × 15 min, 17 judges in parallel) | 45 | derived |
| 13:45–14:00 | Closing, prizes, DJ | 15 | planner default |

The total is 240 min, with no overlaps and all required blocks present. The judging grid assigns 16 judges × 3 teams + 1 judge × 2 teams = 50 teams.

### Practice messages

- **Printing Rs 15,000 (Finance).** Finance owns committed spend and the message is newer, so the old value is superseded. Only budget is recomputed. Total becomes **602,400**, remaining 47,600. Model calls: 1 (`reading`).
- **Caterer "rounded down to 100 boxes".** Rejected. Box count is a derived value (= headcount 177: 150 + 17 + 10). A vendor cannot set our order quantity. The plan is unchanged. Model calls: 1 (`reading`).

## 3. Architecture

The system makes one model call to read the messages. Everything after that is plain, deterministic code that prints the reason for each decision.

&#91;embedded content: system architecture · 2 model steps, 7 code steps\]

A message moves along the top row and back along the bottom. Only the shaded boxes cost tokens. The dashed area call fires only when a constraint is a kind the schema has no key for.

```text
run.py                  the one command: python run.py <messages.txt>
planner/llm.py          providers, auto-fallback, usage capture, timeouts
planner/reader.py       prompt fill, schema validation, repair, number grounding
planner/state.py        per-file state, diff to find new text
planner/resolver.py     rules 1-9, authority matrix, ledger
planner/deps.py         fact key -> affected areas
planner/plan.py         derived figures, venue, food, budget optimiser
planner/schedule.py     blocks, judging grid
planner/checks.py       the six checks
planner/escape.py       area call for 'other' constraints
planner/trace.py        numbered calls + [code] events -> terminal, trace.txt, trace.jsonl
prompts/reader.txt      reader prompt (invented examples only)
prompts/area.txt        area-call prompt
config/defaults.yaml    planner assumptions: opening 15, lunch 30, closing 15
ui/app.py               Streamlit
tests/messages/         self-written test messages (data, not code)
.gitignore              state/  out/  .env
```

## 4. The reader: prompt and fact schema

The reader is the only part that needs language understanding. It turns raw messages into a flat list of typed facts and does no arithmetic and no deciding. Keep the prompt in `prompts/reader.txt`, about 450 tokens. Every example in it must be invented: no pack names, numbers or wording.

### Output shape (short keys save tokens)

```json
{"msgs":[{"i":1,"from":"Registrar office","role":"authority","date":"2026-11-02",
  "facts":[{"k":"budget","v":400000,"q":"budget is 4 lakh"}],
  "other":[]}]}
```

- `role` ∈ `authority` (dean, principal, organizer, admin) · `finance` · `venue` · `caterer` · `judging` (coordinator) · `judge` (an individual) · `student` · `vendor` (other supplier) · `unknown`
- `date` = ISO or `null`. An undated message counts as newer than everything before it (arrival order).
- `q` = a quote of at most 8 words from the message. It is evidence for the UI and powers the number check below.
- `other` = constraints the vocabulary below cannot express. This is the trigger for an area call.

### Fact vocabulary (`k` → `v`)

| Group | Keys | Notes |
| --- | --- | --- |
| Event params | `students`, `team_size`, `teams`, `duration_min`, `start_time`, `end_time`, `staff`, `extra_people` {who, n} | `teams` is checked against ceil(students ÷ team\_size) |
| Budget | `budget`, `reserve` {amount or pct} |  |
| Venue | `venue` {name, seats, price, basis: fixed\|per\_hour, features\[\], available: bool} · `venue_require` {feature} · `venue_exclude` {name} · `seat_factor` {pct} | Features are free words: generator, accessible, AC, projector… |
| Schedule | `block` {name, min, at?, required: bool} · `window` {who/what, from?, until?} · `late` {who, min} | Prayer break, opening by VC, venue closes at, judges leave by |
| Food | `food` {name, price\_per\_head, fee?, min\_order?} · `food_require` {name or tier} · `diet` {type, n or pct} | Lunch tiers, tea, dietary needs |
| Judging | `judges_available`, `judges_change` {delta}, `honorarium`, `min_per_team`, `max_teams_per_judge`, `judges_per_team` |  |
| Costs | `cost` {name, amount, basis: fixed\|per\_head\|per\_team\|per\_judge\|pct\_of:‹item/all›, status: committed\|required\|optional} | Prizes, printing, DJ, photographer, tax |
| Claims | `claim` {key, value} | When a message states a *derived* value (boxes, headcount, judges needed, totals). Never applied; always validated |
| Noise | (no facts) + `note` | Irrelevant message |

### Prompt skeleton

```text
You extract facts for an event planner. Output JSON only, matching the schema.
Rules:
- One entry per message, in order. Copy sender as written; pick role from the list.
- Numbers as plain integers in rupees/minutes/people. "lakh"=100000, "k"/"hazaar"=1000.
- Roman Urdu: "ab ... hoga" = new value from now; "wala" = option.
- Use only keys in the vocabulary. Anything else -> "other" with the exact phrase.
- A request ("can we", "we would like") -> cost status "optional".
- A vendor stating how many units they will supply, or anyone stating a total/count
  we compute -> "claim". Do not judge whether it is right.
- Reuse these existing names where they match: {known_names}
- No arithmetic, no opinions.
Example (invented): "Sky Lounge holds 60 for Rs 9,000; has AC" ->
 {"k":"venue","v":{"name":"Sky Lounge","seats":60,"price":9000,"basis":"fixed","features":["AC"],"available":true},"q":"Sky Lounge holds 60 for Rs 9,000"}
Schema: {compact schema}
Messages:
{raw text exactly as in the file}
```

### Guard rails around the reader (code, 0 tokens)

1. **Schema validation** with Pydantic. On failure: one repair call (counted and logged in the trace), then per-message fallback for only the bad messages.
2. **Number grounding.** Every number in a fact must appear in its message after normalising commas, "k", "lakh" and "hazaar". A number that does not appear is a hallucination: drop the fact and flag it in the trace. This cheap check protects the Output score from small-model mistakes.
3. **Known names.** On updates, the prompt includes existing entity names (venues, food options, cost names). Then "printing bill" maps to the existing `printing` cost and does not create a duplicate.

## 5. Resolver: conflicts and the wrong message (worth 20 pts + the first tie-break)

Every extracted fact goes through the same ordered rules in plain code. The **first rule that fires decides the fact's status**, and its reason is printed in the trace and shown in the UI. A message's status is the worst status of its facts: if any fact is rejected, the message shows as rejected and lists which fact and why.

| Order | Rule | Status | Example reason printed |
| --- | --- | --- | --- |
| 1 | **Ungrounded:** a number not found in the message text | dropped (flagged) | "Extracted 1500 but message says 150; ignored" |
| 2 | **Derived claim:** asserts a value we compute (boxes, headcount, teams, judges needed, totals) and it differs | REJECTED | "Caterer set boxes = 100; boxes are derived = headcount 177 (150 students + 17 judges + 10 staff). Order stays 177." |
| 3 | **No authority:** the sender's role does not own this key (matrix below) | REJECTED, or REQUEST if phrased as a request | "A judge cannot change max teams per judge; owner is the judging coordinator" |
| 4 | **Breaks a standing rule** from a higher authority (e.g. a judge offering to cover 5 teams when max is 3) | REJECTED | "Conflicts with rule max 3 teams/judge (msg 5)" |
| 5 | **Internally inconsistent** ("150 students in 40 teams of 3") | REJECTED | "40 teams × 3 ≠ 150 students" |
| 6 | **Stale:** same key, same owner, older date than the current value | SUPERSEDED (not applied) | "Dated 1 Nov; current value from 3 Nov stands" |
| 7 | **Newer value** for the same key from the owner | APPLIED; the old value is marked SUPERSEDED | "Printing 10,000 → 15,000 (Finance, newer)" |
| 8 | **Request** from a non-owner ("can we get…") | REQUEST: optional, included only if it fits | "DJ optional; included, Rs 52,600 headroom" |
| 9 | **No facts** | IRRELEVANT / NO IMPACT | "Judge late 10 min; judging starts at +3:00, no effect" |

### Authority matrix (by role; a design rule, not a pack fact)

| Key group | Owner roles | Others may… |
| --- | --- | --- |
| students, team size, duration, start/end, staff, required blocks, event rules | authority | request |
| budget, reserve | authority, finance | request |
| committed costs | finance, authority | request |
| venue options, prices, seats, features, availability | venue | authority may add a `venue_require` / `venue_exclude` |
| food prices, fees, minimum order | caterer | authority/student may add `diet` (a requirement from authority, a request from students) |
| judges available, honorarium, min/team, max teams/judge | judging, authority | a judge may report only their own lateness or withdrawal (`judges_change` = −1, `late`) |
| derived values (boxes, headcount, judges needed, totals) | nobody: always computed | — |

### After applying: replan, and keep the plan valid

- If an applied, legitimate change makes the current plan invalid, the solver re-searches. It may pick a cheaper venue, drop optional extras, or switch to the cheaper food tier. Each lever used is logged.
- If **no** valid plan exists (e.g. budget cut below the required minimum, or judges drop below need), the message was legitimate, so it is not rejected. Keep showing the **last valid plan** with a red banner and an exact fix, e.g. "INFEASIBLE: needs Rs 34,600 more" or "needs 2 more judges".
- The plausible-but-wrong message almost always falls under rules 2–6. Rehearse every one of them with your own messages (section 9).

## 6. Planner (plain code) and the six checks

The planner is deterministic Python: same facts in, same plan out. Any figure a judge checks can be traced to a formula and to the message it came from.

### Derived figures

- `teams = ceil(students / team_size)`. If a message gives `teams`, it must match, or rule 5 fires.
- `judges_needed = ceil(teams × judges_per_team / max_teams_per_judge)`, where `judges_per_team` defaults to 1. It is feasible only if ≤ `judges_available`.
- `judges_used = judges_needed`. Standby judges are listed but not paid or fed. State this as a decision.
- `rounds = ceil(teams × judges_per_team / judges_used)` and `judging_min = rounds × min_per_team`.
- `headcount = students + judges_used + staff + Σ extra_people`.

### Venue

Filter for: available, not excluded, `seats × (seat_factor or 100%) ≥ headcount`, and has every `venue_require` feature. Then pick the **cheapest**. Cost = price, or price × hours if `per_hour`. Tie-break: more seats. If a required feature isn't mentioned for a venue, treat it as *not present* and say so.

### Food

Options = food facts. Cost = `headcount × price_per_head + fee`, respecting `min_order`. Boxes are always = headcount. Diet requirements become line items (e.g. "vegetarian: 20 of 177") at the same price unless a separate price is given.

### Budget optimiser (tiny brute force)

Enumerate venue × food option × subsets of optional requests (≤ a few hundred combos, microseconds). Keep the ones where required costs + chosen extras ≤ budget − reserve. Choose with an explicit preference order, and print it in the trace:

1. Satisfy every hard constraint.
2. Keep the **better food tier** (the one the authority asked for, or else the highest-priced "standard") if affordable. Feeding people beats extras.
3. Include **optional requests** if they still fit, cheapest first.
4. Lowest total cost among what remains.

The levers used, in order, when the budget gets tight: drop optional extras → cheaper food tier → (venue is already cheapest-valid). Percentage costs (tax, service charge) are applied to their target after the base costs.

### Schedule builder

- Blocks: required blocks from messages (prayer, opening by VC, etc.) + judging (`judging_min`) + planner defaults (opening 15, lunch 30, closing 15). Keep the defaults in `config/defaults.yaml`, labelled "planner assumption", not message facts.
- **Build** is the filler: `duration − Σ other blocks`. It must be ≥ 60 min, or the planner shrinks defaults (lunch 30→20, opening 15→10) and logs it.
- Fixed-time blocks (`at`) are placed first; the rest follow in a fixed order. `window`/`late` facts are checked; e.g. judging must start ≥ latest judge arrival.
- Start time comes from the messages. If there is none, show 10:00 and label it an assumption.

### Judging assignment

Round-robin: team *t* → judge `t mod judges_used`, slot `t div judges_used`. This guarantees ≤ max teams per judge. Display it as a grid in the UI.

### The six checks (run after every plan; shown as badges; printed at the end of the trace)

| Check | Code test |
| --- | --- |
| Correct figures | Recompute every derived figure from facts and compare with the plan; boxes = headcount; budget lines sum to total |
| Within budget | total + reserve ≤ budget |
| Venue fits | effective seats ≥ headcount, all required features, available |
| Schedule valid | blocks sum to duration, no overlaps, all required blocks present, judging ≥ rounds × min, windows and lateness respected |
| Enough judges | judges\_used ≤ available and judges\_used × max ≥ teams × judges\_per\_team |
| All areas covered | venue, schedule, food, judging and budget are each non-empty |

## 7. Updates, state, trace, models and tokens

### One command, no flags

`python run.py messages.txt`. State is stored per input file (`state/<hash of path>.json`, which is gitignored).

- **No state for this file** → full run: one batched `reading` call over the whole text.
- **File starts with the text already processed** → the leftover tail is the new message(s) → update run.
- **File changed in the middle** → treated as a new pack → full run from scratch.
- The unseen pack goes in a new file and starts fresh automatically, with no reset step. Each released message is pasted at the end of that file exactly as given, and the same command is run again.
- The UI's "Add message" box appends to the same file and calls the same `run()` function. Only one code path exists.

### Update path (≤ 5 calls, < 1 min)

1. `reading` call on the new text only, plus the known-names list: **1 call**.
2. Resolver applies, supersedes or rejects facts: code.
3. A dependency map gives the affected areas. The planner recomputes only those and copies the rest from the previous plan: code.
4. Escape hatch: an area call only if the message produced `other` constraints, at most 2 calls. Optional repair retry: 1 call. A hard counter stops at 5.
5. Checks, then save and print.

| Fact changed | Areas recomputed (code) |
| --- | --- |
| students, team\_size, staff, extra\_people | judging → schedule, venue, food, budget (headcount ripples everywhere) |
| judges\_available, max\_teams\_per\_judge, min\_per\_team, judges\_per\_team | judging, schedule, food, venue, budget |
| honorarium | budget |
| venue / venue\_require / seat\_factor | venue, budget |
| food / diet | food, budget |
| block / window / late / duration / start | schedule |
| cost / budget / reserve | budget |
| rejected or no-impact message | none (the plan is untouched; the trace says so) |

**Prediction slip rule:** the model-call areas are always `reading`. An area tag (e.g. `venue`) is added *only if* the message contains a constraint outside the vocabulary. Write the slip by reading the message: is it a new kind of thing? The trace also prints code recomputes, so the volunteer sees exactly what changed.

### Trace format (terminal, `out/trace.txt`, and the UI — all from one source)

```text
=== RUN 2 · update · 1 new message · 18 Nov 13:41:07 ===
[#3] model=llama-3.1-8b-instant  area=reading
  INPUT : <full prompt as sent>
  OUTPUT: <raw model output>
  TOKENS: prompt 512 · completion 96 · total 608   (reported by API)
[code] resolver  msg 10 printing 10,000 -> 15,000  APPLIED (finance owns committed costs; newer)
[code] superseded msg 6 fact printing=10,000
[code] recompute budget  (venue, schedule, food, judging unchanged)
[code] checks 6/6 PASS  total 602,400 / 650,000
--- run tokens 608 · calls 1 · cumulative tokens 3,214 · cumulative calls 3 ---
```

- Model calls are numbered across the whole session. `[code]` lines are not model calls and are never numbered, so nobody can claim you misreported.
- Tokens come **only** from the API response: OpenAI-style `usage.prompt_tokens` / `completion_tokens`, or Ollama `prompt_eval_count` / `eval_count`. If a provider omits them, print `not reported`. Never estimate.
- The model name is the one the API reports back (`response.model`), so fallbacks are logged truthfully.
- `out/plan.md` + `out/trace.txt` are rewritten after every run. Upload both to the form.

### Model choice (+10 bonus, 2-min cutoff, whole room at once)

- Confirm the organizers' small-model list at the help desk **now**. Use only models on it, plus a local model as backup.
- Primary: a fast hosted small model with JSON mode (a Groq-hosted 8B Llama, Gemini Flash-Lite, a GPT "mini/nano", Claude Haiku — whichever are on the list and your keys work for). Test latency and rate limits in the first 15 min.
- Fallback: Ollama on a laptop (an 8B instruct model, JSON format). Time a full run; it must finish in < 2 min.
- Auto-fallback on timeout (40 s) or a 429 error. The fallback call is a new numbered call in the trace, so a retry is honest.
- Temperature 0. Use JSON/structured-output mode where available.

### Token budget

| Run | Calls | Expected tokens |
| --- | --- | --- |
| Full run (\~10 msgs) | 1 | \~1,000 prompt + \~900 output ≈ 2,000 |
| Update (1 msg) | 1 | \~550 prompt + \~100 output ≈ 650 |

Keep tokens low by using: one batched call, short JSON keys, no verbose reasoning in the output, a quote of ≤ 8 words, and no per-area LLM planners. If the small model is inaccurate on 10 messages at once, split the batch into 2 calls. Output accuracy (30 pts) beats tokens (5 pts).

## 8. UI (10 pts, scored by both judges)

Use Streamlit (`streamlit run ui/app.py`). It only **reads** `state/*.json` and `out/trace.jsonl`, and "Add message" calls the same `run()`. The UI can never disagree with the CLI. Run the official test from the CLI, then show judges the UI.

**Header strip (always visible):** Headcount 177 · Teams 50 · Judges 17/20 · Total Rs 597,400 / 650,000 · six green/red check badges · run number · session tokens.

| Tab | Shows | Why it scores |
| --- | --- | --- |
| **Plan** | Five area cards. Venue: chosen hall + why + rejected options. Schedule: timeline bar. Food: tier, boxes, cost. Judging: 17 × 3 assignment grid. Budget: table + bar of spent vs headroom. Each figure has a hover "from msg N" | Judges verify the six checks at a glance |
| **Messages** | Every message with a status chip: Applied (green), Superseded (grey), Rejected (red), Request (blue), No impact (grey). Shows the reason, the 8-word quote, and the extracted facts | "Show rejected messages clearly" is literally in the brief |
| **Trace** | Numbered model calls: model, area, tokens; expand for full input/output. `[code]` events greyed in between. Per-run and session totals. Filter by run and area | Walk the judge through any decision |
| **Changes** | A diff per update run: which facts changed, which areas recomputed, before → after figures, model calls made | Proves "only affected areas" |

The sidebar has a text box to paste a new message, plus an Add & re-plan button and a download button for `plan.md` + `trace.txt`. An infeasible plan shows a red banner with the exact shortfall.

Terminal output (the backup if the UI breaks): use `rich` to print the trace, then the plan tables, then a ledger of rejected and superseded messages.

## 9. Test plan: your own messages

Keep test messages in `tests/messages/*.txt` (data files, never in `.py`). Run each one as an update after the sample pack. Pass = expected status + 6/6 checks (or a correct infeasible banner) + expected model-call areas.

### Real changes (must be accepted and re-planned)

| Test message | Expected |
| --- | --- |
| "Dean's office: budget revised to Rs 520,000." | Applied. Required costs alone are 547,400 > 520,000, so the solver drops the DJ and switches to basic lunch (177 × 800 = 141,600 → total 476,600). Recomputes budget and food |
| "IESCO notice: load-shedding on the event day, venue must have backup power." | Applied as `venue_require` generator → Hall B (+30,000). Venue + budget |
| "Coordinator: 4 judges withdrew." | Applied. 16 available ≥ 17 needed? No → INFEASIBLE banner "needs 1 more judge"; last valid plan kept |
| "Coordinator: a judge can now cover 4 teams." | Applied: judges 13, headcount 173, judging 4 rounds = 60 min, build shrinks |
| "Dean: teams will be of 4." | 38 teams, 13 judges, headcount 173; everything recomputed |
| "Venue: Hall A under maintenance, not available." | Hall A excluded → next cheapest that fits |
| "Caterer: delivery charge Rs 5,000." (Roman Urdu variant too) | Food fee added; budget |
| "Dean: VC will open the event, 20 minutes." | New required block; schedule only |
| "Hall prices exclude 16% GST." | `cost` pct\_of venue; budget |
| "Finance: keep 10% contingency." | `reserve` 65,000; DJ may drop |
| "Venue: Hall A is Rs 30,000 per hour." | Per-hour basis: 4 h × 30,000 = 120,000 |

### Plausible but wrong (must be rejected with a reason; plan unchanged)

| Test message | Rule that should fire |
| --- | --- |
| "Caterer: I've packed 150 boxes, one per student." | 2: derived claim (boxes ≠ 177) |
| "Student society: budget increased to Rs 900,000." | 3: no authority over budget |
| "A judge: I'll take 6 teams so we need fewer judges." | 3/4: judges can't change the max; breaks rule |
| "Venue, dated 1 Nov: Hall A now Rs 90,000." | 6: older than the 3 Nov price → superseded |
| "Caterer: 177 people means 59 tables of 3, so order is 160." | 2: derived claim |
| "Volunteer: we've only got 120 students registered, plan for 120." | 3: only the authority sets students |
| "Dean: 150 students in 45 teams of 3." | 5: internally inconsistent |
| "Venue: Room D can fit everyone, 180 seats." (contradicts its own earlier 80) | Owner update → applied. Discuss: owner changes are legitimate, so decide in advance if a same-source contradiction needs a flag |

### Robustness

- Roman Urdu numbers ("dedh lakh", "pachas hazaar"), "50k", "Rs. 1.2 lac".
- Shuffled message order, missing dates, duplicate messages, a message with two facts, an empty line between messages, a different file format (numbered vs. blank-line separated).
- Kill the network mid-run: the fallback model must take over, and the trace must show it.
- Time it: full run < 60 s on the venue Wi-Fi; update < 20 s.

## 10. Build plan to the 1:25 freeze, test run, and judge prep

### Roles (3 people)

| Person | Owns | Files |
| --- | --- | --- |
| A — Pipeline | LLM client, fallback, token capture, reader prompt + validation, state/diff, trace writer | `llm.py`, `reader.py`, `state.py`, `trace.py`, `prompts/reader.txt` |
| B — Brain | Resolver rules, authority matrix, planner, schedule, judging grid, six checks, dependency map | `resolver.py`, `planner.py`, `schedule.py`, `checks.py`, `deps.py` |
| C — Face + QA | Streamlit UI, rich CLI output, test message files, timing, README, rehearsal | `ui/app.py`, `tests/messages/`, `README.md` |

The interface between A and B is the fact JSON. Agree on it at 11:05 (section 4) and B can work from a hand-made `facts.json` with no LLM.

### Timeline (now → 1:25)

1. **10:50–11:05** Repo + `.gitignore` (`state/`, `out/`, `.env`), confirm the small-model list at the help desk, test keys, latency and rate limits on 2 providers + Ollama.
2. **11:05–11:50** A: reader working on the sample pack, JSON validated. B: planner + checks on hand-made facts → reproduces 177 / 17 / Hall A / 597,400. C: UI skeleton reading a stub state file.
3. **11:50–12:30** Integrate end to end: one command, state, update path, resolver rules, trace file. Both practice messages behave as in section 2. *Push.*
4. **12:30–13:00** Run the section 9 tests; fix the worst failures first (wrong-message rules, Roman Urdu numbers). Trim prompt tokens. *Push.*
5. **13:00–13:10** Feature freeze. Each member explains the whole system to the other two (Q&A below).
6. **13:10–13:20** Fresh clone into a new folder, run it from scratch with keys from env, final push. Note the commit hash, `git status` clean. Submit the repo link + hash.
7. **13:20–13:25** Buffer. No code changes.

### Test-run checklist (1:30)

- [ ] `git status` clean, `git log -1` = submitted hash
- [ ] API keys exported in the shell (not in repo); Ollama running as fallback
- [ ] Save the pack exactly as released into a new file `pack.txt`; run `python run.py pack.txt`
- [ ] For each of the 3 messages: paste it at the end of `pack.txt` exactly as given, run the same command
- [ ] Before the chosen message: read it, write the slip (`reading`, plus an area only if it is a new kind of constraint)
- [ ] Check the UI: plan 6/6, ledger shows the rejected one with its reason
- [ ] Upload `out/plan.md` and `out/trace.txt`

### Judge Q&A: every member must be able to say this

| Part | What it is for | What breaks without it |
| --- | --- | --- |
| Reader (LLM) | Turns messy English/Roman Urdu into typed facts | Code can't read "ab Rs 1,200 hoga"; any regex fails on the unseen wording |
| Number grounding check | Rejects numbers the model invented | One hallucinated digit fails "correct figures" silently |
| Resolver + authority matrix | Decides which fact wins and why | Wrong message gets applied (−20), stale prices used, no reason in trace |
| Derived-value rule | Headcount/boxes/judges are computed, never accepted | Caterer's "100 boxes" leaves 77 people unfed |
| Planner (code) | All arithmetic and choices, deterministic | LLM arithmetic is unreliable and costs tokens; results change run to run |
| Six checks | Self-verify before printing | We would ship an invalid plan without knowing |
| Dependency map | Recompute only affected areas | Updates touch everything; can't predict or prove "only affected areas" |
| State + diff | Updates without re-reading the pack | Every update re-runs the full pack: >5 calls, more tokens, over 1 min |
| Escape hatch (area call) | Handles constraint kinds we never saw | An unseen constraint is silently ignored |
| Trace | Honest record of every call + every code decision | Requirement R3; misreporting is disqualification |
| Fallback model | Survives rate limits/Wi-Fi at the test moment | A 429 at 1:30 = zero Output points |

Likely questions: Why 17 judges, not 20? Why is the reader the only model call? How do you know message 3 is out of date? What if a legitimate change makes the plan impossible? How are tokens counted? What if the model returns broken JSON? Where would a new constraint kind go?

### Do not build

No multi-agent framework (LangChain/CrewAI) and no per-area LLM planners: "the number of agents earns nothing" and every unjustified part costs points. No LLM arithmetic. No hard-coded pack facts. No reset flags.

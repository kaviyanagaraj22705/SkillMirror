# AI Study Planner — Design

A local web app that turns a learning goal into a realistic week-by-week study plan, then
keeps the plan honest as you fall behind or move faster than expected.

> This describes a **new, separate project** — not SkillMirror, which lives in this folder
> today. It is written as a standalone spec so it can be built in its own directory.

---

## 1. Problem

Generic study advice is easy; a plan that survives contact with a real week is not. People
pick a goal, get a 12-week roadmap, miss week 2, and abandon it. The missing piece is not
more content — it is **re-planning**: adjusting the remaining weeks to what actually happened.

## 2. Goals

| Goal | Non-goal |
|---|---|
| Produce a plan that fits the hours the user actually has | Being a course platform or content library |
| Make weekly progress a one-click update | LMS features: grading, cohorts, instructors |
| Re-plan automatically when the user slips | Multi-user accounts, sharing, teams |
| Run locally with one SQLite file | Mobile apps (v1 is responsive web) |
| Work without an API key (degraded mode) | Being a general calendar or todo app |

## 3. User & core loop

One user, on their own machine. The loop:

1. **Set a goal** — "Pass AWS SAA in 8 weeks", "Learn FastAPI", "Prepare for calculus final".
2. **State constraints** — deadline, hours/week, which days, current level, preferred style
   (reading / video / hands-on), optional known topics to skip.
3. **Get a plan** — weeks → topics → tasks → a checkpoint per week.
4. **Check in weekly** — mark each task done / partial / skipped, optionally add a note.
5. **Re-plan** — remaining weeks are regenerated around what is left, with the same deadline.

The plan is a living document, not a one-time PDF.

## 4. Features

### v1 (build this)
- Goal + constraint form
- Generated plan rendered as week cards with checkboxes
- Weekly check-in: complete / partial / skip per task
- Re-plan remaining weeks (manual button, plus an offer after a missed week)
- Plan history — one row per active/archived plan
- Export plan to Markdown

### Later (explicitly out of v1)
- Resource links with quality ranking
- Calendar (.ics) export and reminders
- Spaced-repetition quizzes per topic
- Adaptive difficulty per task
- Sharing / accounts

## 5. Data model

SQLite, forward-only migrations via `PRAGMA user_version` (same pattern as SkillMirror).

```
plans
  id            INTEGER PK
  goal          TEXT        -- free text, user's words
  goal_type     TEXT        -- exam | skill | project | other
  deadline      DATE NULL
  hours_per_week INTEGER
  days          TEXT        -- JSON array, e.g. ["Mon","Wed","Sat"]
  level         TEXT        -- beginner | some | confident
  style         TEXT        -- JSON array of preferences
  known_topics  TEXT        -- JSON array, skipped in generation
  status        TEXT        -- active | completed | archived
  created_at, updated_at

weeks
  id            INTEGER PK
  plan_id       INTEGER FK
  week_no       INTEGER
  theme         TEXT        -- "HTTP basics and routing"
  goal          TEXT        -- one-sentence outcome for the week
  estimated_hours REAL
  status        TEXT        -- upcoming | current | done | missed
  generated_at  DATETIME    -- which generation produced this week

tasks
  id            INTEGER PK
  week_id       INTEGER FK
  title         TEXT
  detail        TEXT
  kind          TEXT        -- read | watch | build | practice | review
  est_minutes   INTEGER
  checkpoint    INTEGER     -- 1 if this task verifies the week's goal
  status        TEXT        -- todo | done | partial | skipped

checkins
  id            INTEGER PK
  plan_id       INTEGER FK
  week_no       INTEGER
  note          TEXT
  created_at
```

Ratios matter: `hours_per_week` and `days` bound total task minutes per week. The generator
is told the budget, and validation rejects any week whose `Σ est_minutes` exceeds it by >10%.

## 6. Architecture

Local FastAPI app, Jinja pages, vanilla ES modules — no build step.

```
Browser ──► FastAPI routes ──► services ──► SQLite
              │                   │
              │                   ├── planner.py      (deterministic budgeting + ordering)
              │                   ├── ai_plan.py      (LLM calls, schema validation)
              │                   └── replan.py       (diff old vs actual → new weeks)
              └── jobs/ (in-process asyncio) ──► OpenRouter
```

```
app/
  main.py, config.py, errors.py
  api/            routes_pages.py, routes_plans.py, routes_checkins.py, routes_health.py
  services/       planner.py, ai_plan.py, replan.py, progress.py, export.py
  llm/            client.py, prompts.py, json_schemas.py, validate.py
  db/             connection.py, migrate.py, migrations/, repositories/
  jobs/           runner.py, recovery.py
  static/         css + js
  templates/      index, plan, history, help + partials
data/             planner.db (gitignored)
tests/            unit / integration / e2e
```

Same shape as SkillMirror so patterns carry over — but a **separate database and repo**.

## 7. The AI boundary

The rule: **the model chooses content; Python owns arithmetic.**

| Decision | Owner | Why |
|---|---|---|
| Topics, task wording, ordering within a week | LLM | Requires judgement |
| Total minutes per week | Python (budget) | Must be exact, testable |
| Which week is "current" | Python (dates) | No model needed |
| What to carry over after a slip | Python decides *what*, LLM phrases *how* | Deterministic and explainable |
| Whether a check-in is "on track" | Python (progress %) | Same |

### Calls

1. **Outline** — input: goal, level, style, deadline, hours/week, known topics.
   Output: ordered topic list with rough hours per topic. Small, cheap model.
2. **Week detail** — input: one week's theme + exact minute budget + style.
   Output: tasks with `kind`, `est_minutes`, `checkpoint`. One call per week, run in
   parallel, each validated independently so one bad week doesn't poison the plan.
3. **Re-plan** — input: completed/partial/skipped tasks, remaining topics, remaining weeks,
   remaining hours. Output: new weeks only. Old weeks are never rewritten.

Every call uses a JSON schema plus a validator:

- retry once on schema failure, then fall back to the week template
- clamp `est_minutes` to the week budget
- reject unknown task `kind` values
- `LLM_CACHE_ENABLED` — identical inputs reuse stored output (hash-keyed)

### Degraded mode

With no `OPENROUTER_API_KEY`, the app uses a **static topic template** per `goal_type` and a
fixed task shape per week (learn → practice → build → review). The plan is plain but real,
and the UI shows a "degraded — no AI key" banner. This keeps demos, tests, and offline use
working.

## 8. Re-planning logic (the heart of the app)

Triggered by the user, or offered when a week ends with unfinished tasks.

```
remaining_topics = topics not covered by done tasks
                 + partial tasks (kept at 50% of original minutes)
                 - skipped tasks the user marked "drop it"
remaining_weeks  = weeks until deadline, at hours_per_week
```

If `remaining_weeks` can't hold `remaining_topics`:
- if there is slack, distribute it
- if not, surface a choice — **extend deadline**, **raise hours/week**, or **cut scope** —
  never silently overload the plan

The old weeks stay as history; new rows get a fresh `generated_at`. The user sees a short
"what changed" summary: moved, added, dropped.

## 9. API

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/api/plans` | Create plan; enqueues generation, returns `plan_id` + `job_id` |
| `GET` | `/api/plans/{id}` | Plan with weeks and tasks |
| `GET` | `/api/plans/{id}/jobs/{job_id}` | Generation progress (SSE or poll) |
| `PATCH` | `/api/tasks/{id}` | Mark task done / partial / skipped |
| `POST` | `/api/plans/{id}/checkins` | Save weekly note + roll week status |
| `POST` | `/api/plans/{id}/replan` | Regenerate remaining weeks |
| `GET` | `/api/plans/{id}/export.md` | Markdown export |
| `DELETE` | `/api/plans/{id}` | Archive (soft delete) |
| `GET` | `/api/health` | DB + key + model status |

Long generation runs as a background job; the page shows a progress partial. If the server
restarts mid-job, the job is marked `interrupted` on startup and can be resubmitted.

## 10. Screens

| Screen | Contents |
|---|---|
| **New plan** | Form: goal, deadline, hours/week, days, level, style, known topics |
| **Plan** | Header (goal, progress bar, weeks left), week cards, checkboxes, "Re-plan" button |
| **Check-in** | Modal per week: task states + optional note + "what got in the way" |
| **History** | List of plans with status and completion % |
| **Help** | How re-planning works, what is sent to the model, privacy note |

## 11. Edge cases

| Case | Behaviour |
|---|---|
| Deadline in the past | Reject on create with a clear message |
| Hours/week < 2 | Warn; allow, but cap topics per week |
| Goal too vague ("learn everything") | Ask one clarifying question before generating |
| LLM returns more topics than weeks | Merge adjacent topics; show what was merged |
| LLM returns fewer topics than weeks | Add review/practice weeks at the end |
| User skips 3+ weeks | Offer "restart from here" — keeps history, regenerates forward |
| Plan completed early | Mark done, offer "extend with advanced topics" |
| Duplicate submit | Reuse the active job for the same plan |

## 12. Non-functional

- **Local only.** Bind `127.0.0.1`; no auth, single user by design.
- **Privacy.** Only the goal, constraints, and topic list go to the model. Notes from
  check-ins are stored locally and never sent unless the user explicitly includes them in a
  re-plan (off by default). Prompt content is never logged.
- **Cost.** Outline call is small; week calls are parallel and cached. A 12-week plan should
  cost cents, and the UI shows the model before generating.
- **Determinism.** Same plan + same check-ins = same re-plan output structure, even if task
  wording differs.
- **Speed.** Plan generated in < 30s typical; cached re-plans < 2s.
- **Tests.** Planner arithmetic, budget clamping, re-plan math, and degraded mode are pure
  Python and unit-tested without a network.

## 13. Milestones

| # | Deliverable | Done when |
|---|---|---|
| 1 | Skeleton | App boots, DB migrates, health endpoint reports config |
| 2 | Deterministic planner | Degraded-mode plan generated from a goal, tested |
| 3 | AI generation | Outline + parallel week calls with validation and fallback |
| 4 | Plan UI | Week cards, checkboxes, progress bar |
| 5 | Check-ins + re-plan | Slip a week, press re-plan, remaining weeks change correctly |
| 6 | Export + history + polish | Markdown export, archive, help page, error states |

## 14. Open questions

1. Should "days" constrain task placement to specific days, or only the weekly total? (v1:
   total only; days are advisory text.)
2. Do partial tasks carry forward automatically, or only when the user says so? (v1: auto,
   at half minutes, shown explicitly in the change summary.)
3. Is one check-in per week enough, or should long tasks have their own progress notes?
4. Should the topic outline be user-editable before weeks are generated? (Probably yes —
   it is the cheapest place to correct a bad plan.)

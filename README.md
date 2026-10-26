# SkillMirror

Paste a resume and a job description. SkillMirror tells you **how well you match**,
**which skills you're missing**, and **what to learn first** — as a week-by-week plan
with real resources.

Runs locally on Windows. One SQLite file. Your resume never leaves the machine except
for the OpenRouter call that extracts skills and writes the roadmap.

---

## Run it (2 minutes)

```powershell
# 1. Environment
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .

# 2. Configuration
Copy-Item .env.example .env
notepad .env          # paste your key into OPENROUTER_API_KEY

# 3. Start
.\scripts\dev.ps1
```

Open <http://127.0.0.1:8000>.

**No key?** Leave `OPENROUTER_API_KEY` blank. The app still runs: skills are extracted
by dictionary matching, the score and gap list are real, and the roadmap stage is
skipped with a visible "degraded mode" banner. Useful for demos and for tests.

Get a key at <https://openrouter.ai/keys>. Verify it with:

```powershell
.\.venv\Scripts\python.exe scripts\smoke_openrouter.py
```

---

## What it does

| Step | What happens | Where |
|---|---|---|
| 1. Ingest | PDF / DOCX / pasted text → clean text (NFKC, page furniture removed, section-aware JD truncation) | `app/services/parsing_*.py`, `text_clean.py` |
| 2. Extract | LLM pulls skills from resume and JD **in parallel**; every label is resolved against a 179-entry dictionary (aliases → fuzzy → LLM-only) | `app/services/extract.py`, `normalization.py` |
| 3. Score | Pure Python, no model involved. `score = round(100 × Σ(w·s) / Σ(w))` | `app/services/scoring.py` |
| 4. Roadmap | LLM receives **only the gap list** — never the resume — and writes N weeks of tasks | `app/services/roadmap.py` |

The score is deterministic and explainable: same inputs always produce the same number,
and every gap carries the reason it was flagged.

### Bands

| Score | Band | Meaning |
|---|---|---|
| 80–100 | Strong | Apply now; polish the story |
| 65–79 | Competitive | Apply; close one or two gaps |
| 45–64 | Stretch | Worth it if you learn the critical gaps |
| 0–44 | Foundational gap | Reconsider, or plan a longer runway |

Weights: required = 3, preferred = 2, mentioned = 1. Strength: matched = 1.0,
name-only match = 0.75, adjacent skill = 0.25, absent = 0.

---

## Project layout

```
app/
  main.py             app factory, lifespan, middleware
  config.py           typed settings from .env
  api/                HTTP routes (pages, analyses, jobs, skills, health)
  services/           parsing, normalization, scoring, roadmap, pipeline
  llm/                OpenRouter client, prompts, JSON schemas, validation
  db/                 connection, migrations, repositories
  jobs/               in-process asyncio job runner
  static/             css + vanilla ES modules (no build step)
  templates/          Jinja2 pages and partials
seeds/skills_seed.json  the skill dictionary
scripts/              dev.ps1, check.ps1, build_seed.py, smoke_openrouter.py
tests/                unit / integration / e2e
data/                 SQLite DB + uploads (gitignored, auto-created)
```

---

## Development

```powershell
.\scripts\dev.ps1 -Reload    # auto-reload on save
.\scripts\check.ps1          # ruff + pytest
```

Migrations run automatically at startup (`PRAGMA user_version`, forward-only).
The skill dictionary reloads itself when `seeds/skills_seed.json` changes.

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| `Activate.ps1 cannot be loaded` | `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` |
| `No module named 'multipart'` | `pip install python-multipart` |
| Analysis stuck on `queued` | Server was restarted mid-job. Stale rows are marked `interrupted` on startup; resubmit. |
| Roadmap missing, banner says degraded | `OPENROUTER_API_KEY` is empty or `LLM_ENABLED=false` |
| `LLM_AUTH_FAILED` | Key is wrong or has no credit — run `scripts\smoke_openrouter.py` |
| `LLM_MODEL_UNAVAILABLE` | Model slug changed on OpenRouter — update `.env` from <https://openrouter.ai/models> |
| Scanned PDF (`PDF_SCANNED_NO_TEXT` / `PDF_OCR_UNAVAILABLE`) | Scanned resumes need OCR. Set `OCR_ENABLE=true` and install Tesseract (see below). If OCR is off, paste the text instead. |
| `.doc` upload rejected (415) | Save as `.docx` or `.pdf` |
| Port already in use | `.\scripts\dev.ps1 -Port 8020` |

### Enabling OCR for scanned PDFs

Resumes that are image-only (scans, phone photos of a paper résumé) have no text
layer for the parsers to read. When `OCR_ENABLE=true` (in `.env`), SkillMirror
renders each page and reads it with Tesseract before giving up:

1. Install Tesseract on Windows (choose **64-bit**): download from
   <https://github.com/UB-Mannheim/tesseract/wiki> and tick the *Add to PATH*
   option, or run `choco install tesseract -y` in an admin shell.
2. Set `OCR_ENABLE=true` in `.env` (and adjust `OCR_DPI` / `OCR_LANG` if needed).
3. Restart the app and re-upload the scanned resume.

If Tesseract is missing or fails to run, the upload fails with a clear
`PDF_OCR_UNAVAILABLE` / `PDF_PARSE_FAILED` message and asks you to paste the
text instead — it never silently returns empty text.

---

## Privacy

- Binds to `127.0.0.1` only; no authentication, by design — this is a single-user app.
- Uploads are parsed in memory and deleted. Only extracted text is stored, in `data/skillmirror.db`.
- Prompt and document text are never logged (`LOG_PROMPT_CONTENT=false`).
- OpenRouter is called with `provider.data_collection: deny`.
- Resume text **is** sent to the model vendor during analysis. That is the trade-off; the
  app tells you so on the form and on the Help page.

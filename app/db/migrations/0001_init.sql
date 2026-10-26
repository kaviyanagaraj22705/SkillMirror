-- SkillMirror schema v1
-- All timestamps: ISO-8601 UTC text, e.g. '2026-10-23T14:02:11.482Z'

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS app_meta (
  key   TEXT PRIMARY KEY,
  value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS analyses (
  id                 TEXT PRIMARY KEY,
  created_at         TEXT NOT NULL,
  updated_at         TEXT NOT NULL,
  status             TEXT NOT NULL
                     CHECK (status IN ('queued','running','completed','partial','failed')),
  resume_source      TEXT NOT NULL CHECK (resume_source IN ('paste','pdf','docx')),
  resume_filename    TEXT,
  resume_text        TEXT NOT NULL,
  resume_chars       INTEGER NOT NULL CHECK (resume_chars >= 0),
  resume_truncated   INTEGER NOT NULL DEFAULT 0 CHECK (resume_truncated IN (0,1)),
  resume_parse_meta  TEXT CHECK (resume_parse_meta IS NULL OR json_valid(resume_parse_meta)),
  jd_text            TEXT NOT NULL,
  jd_chars           INTEGER NOT NULL CHECK (jd_chars >= 0),
  jd_truncated       INTEGER NOT NULL DEFAULT 0 CHECK (jd_truncated IN (0,1)),
  jd_title           TEXT,
  jd_company         TEXT,
  target_role        TEXT,
  roadmap_weeks      INTEGER NOT NULL DEFAULT 6 CHECK (roadmap_weeks BETWEEN 2 AND 12),
  hours_per_week     INTEGER NOT NULL DEFAULT 8 CHECK (hours_per_week BETWEEN 1 AND 40),
  match_score        INTEGER CHECK (match_score IS NULL OR match_score BETWEEN 0 AND 100),
  match_band         TEXT CHECK (match_band IS NULL OR
                     match_band IN ('strong','competitive','stretch','foundational_gap')),
  score_breakdown    TEXT CHECK (score_breakdown IS NULL OR json_valid(score_breakdown)),
  model_extract      TEXT,
  model_roadmap      TEXT,
  prompt_version     TEXT NOT NULL,
  input_hash         TEXT NOT NULL,
  total_tokens_in    INTEGER NOT NULL DEFAULT 0 CHECK (total_tokens_in >= 0),
  total_tokens_out   INTEGER NOT NULL DEFAULT 0 CHECK (total_tokens_out >= 0),
  cost_usd           REAL NOT NULL DEFAULT 0 CHECK (cost_usd >= 0),
  error_code         TEXT,
  error_message      TEXT,
  CHECK ((match_score IS NULL) = (match_band IS NULL))
);

CREATE INDEX IF NOT EXISTS idx_analyses_created
  ON analyses(created_at DESC);

CREATE INDEX IF NOT EXISTS idx_analyses_input_hash
  ON analyses(input_hash, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_analyses_status
  ON analyses(status, created_at DESC);

CREATE TABLE IF NOT EXISTS jobs (
  id             TEXT PRIMARY KEY,
  analysis_id    TEXT NOT NULL REFERENCES analyses(id) ON DELETE CASCADE,
  kind           TEXT NOT NULL CHECK (kind IN ('full_analysis','roadmap_only')),
  status         TEXT NOT NULL
                 CHECK (status IN ('queued','running','succeeded','failed','interrupted')),
  stage          TEXT CHECK (stage IS NULL OR stage IN
                 ('extract_resume','extract_jd','score','generate_roadmap')),
  progress       INTEGER NOT NULL DEFAULT 0 CHECK (progress BETWEEN 0 AND 100),
  attempts       INTEGER NOT NULL DEFAULT 0 CHECK (attempts >= 0),
  error_code     TEXT,
  error_message  TEXT,
  created_at     TEXT NOT NULL,
  started_at     TEXT,
  finished_at    TEXT,
  heartbeat_at   TEXT
);

CREATE INDEX IF NOT EXISTS idx_jobs_status
  ON jobs(status, created_at);

CREATE INDEX IF NOT EXISTS idx_jobs_analysis
  ON jobs(analysis_id, created_at DESC);

CREATE TABLE IF NOT EXISTS skills (
  id               INTEGER PRIMARY KEY AUTOINCREMENT,
  canonical_name   TEXT NOT NULL UNIQUE,
  display_name     TEXT NOT NULL,
  category         TEXT NOT NULL CHECK (category IN
                   ('language','framework','database','cloud','devops','data','ml',
                    'frontend','backend','mobile','testing','tool','soft','domain','other')),
  aliases_json     TEXT NOT NULL DEFAULT '[]' CHECK (json_valid(aliases_json)),
  related_json     TEXT NOT NULL DEFAULT '[]' CHECK (json_valid(related_json)),
  confusables_json TEXT NOT NULL DEFAULT '[]' CHECK (json_valid(confusables_json)),
  is_seeded        INTEGER NOT NULL DEFAULT 1 CHECK (is_seeded IN (0,1)),
  created_at       TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_skills_category ON skills(category);

CREATE TABLE IF NOT EXISTS analysis_skills (
  id                 INTEGER PRIMARY KEY AUTOINCREMENT,
  analysis_id        TEXT NOT NULL REFERENCES analyses(id) ON DELETE CASCADE,
  side               TEXT NOT NULL CHECK (side IN ('resume','jd')),
  raw_label          TEXT NOT NULL,
  canonical_name     TEXT NOT NULL,
  display_name       TEXT NOT NULL,
  category           TEXT NOT NULL DEFAULT 'other',
  importance         TEXT CHECK (importance IS NULL OR
                     importance IN ('required','preferred','mentioned')),
  proficiency        TEXT CHECK (proficiency IS NULL OR
                     proficiency IN ('expert','advanced','intermediate','basic','unknown')),
  evidence           TEXT,
  confidence         REAL NOT NULL DEFAULT 0.5 CHECK (confidence BETWEEN 0 AND 1),
  extraction_source  TEXT NOT NULL CHECK (extraction_source IN ('llm','alias','fuzzy','seed')),
  verified           INTEGER NOT NULL DEFAULT 1 CHECK (verified IN (0,1)),
  created_at         TEXT NOT NULL,
  UNIQUE (analysis_id, side, canonical_name),
  CHECK (side = 'jd' OR importance IS NULL),
  CHECK (side = 'resume' OR proficiency IS NULL)
);

CREATE INDEX IF NOT EXISTS idx_analysis_skills_analysis
  ON analysis_skills(analysis_id, side);

CREATE TABLE IF NOT EXISTS skill_gaps (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  analysis_id     TEXT NOT NULL REFERENCES analyses(id) ON DELETE CASCADE,
  canonical_name  TEXT NOT NULL,
  display_name    TEXT NOT NULL,
  category        TEXT NOT NULL,
  priority        TEXT NOT NULL CHECK (priority IN ('critical','high','medium','low')),
  jd_importance   TEXT NOT NULL CHECK (jd_importance IN ('required','preferred','mentioned')),
  resume_strength REAL NOT NULL CHECK (resume_strength BETWEEN 0 AND 1),
  weight          REAL NOT NULL CHECK (weight > 0),
  impact          REAL NOT NULL CHECK (impact BETWEEN 0 AND 1),
  gap_reason      TEXT NOT NULL,
  estimated_hours INTEGER NOT NULL CHECK (estimated_hours BETWEEN 1 AND 200),
  sort_order      INTEGER NOT NULL CHECK (sort_order >= 1),
  created_at      TEXT NOT NULL,
  UNIQUE (analysis_id, canonical_name)
);

CREATE INDEX IF NOT EXISTS idx_skill_gaps_analysis
  ON skill_gaps(analysis_id, sort_order);

CREATE TABLE IF NOT EXISTS roadmap_weeks (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  analysis_id     TEXT NOT NULL REFERENCES analyses(id) ON DELETE CASCADE,
  week_number     INTEGER NOT NULL CHECK (week_number >= 1),
  theme           TEXT NOT NULL,
  objective       TEXT NOT NULL,
  hours           INTEGER NOT NULL CHECK (hours BETWEEN 1 AND 40),
  focus_skills    TEXT NOT NULL DEFAULT '[]' CHECK (json_valid(focus_skills)),
  items           TEXT NOT NULL CHECK (json_valid(items)),
  created_at      TEXT NOT NULL,
  UNIQUE (analysis_id, week_number)
);

CREATE INDEX IF NOT EXISTS idx_roadmap_weeks_analysis
  ON roadmap_weeks(analysis_id, week_number);

CREATE TABLE IF NOT EXISTS llm_cache (
  cache_key         TEXT PRIMARY KEY,
  stage             TEXT NOT NULL,
  model             TEXT NOT NULL,
  prompt_version    TEXT NOT NULL,
  response_json     TEXT NOT NULL CHECK (json_valid(response_json)),
  prompt_tokens     INTEGER NOT NULL DEFAULT 0 CHECK (prompt_tokens >= 0),
  completion_tokens INTEGER NOT NULL DEFAULT 0 CHECK (completion_tokens >= 0),
  hit_count         INTEGER NOT NULL DEFAULT 0 CHECK (hit_count >= 0),
  created_at        TEXT NOT NULL,
  expires_at        TEXT
);

CREATE INDEX IF NOT EXISTS idx_llm_cache_expires ON llm_cache(expires_at);

CREATE TABLE IF NOT EXISTS llm_calls (
  id                INTEGER PRIMARY KEY AUTOINCREMENT,
  analysis_id       TEXT REFERENCES analyses(id) ON DELETE SET NULL,
  job_id            TEXT REFERENCES jobs(id) ON DELETE SET NULL,
  stage             TEXT NOT NULL CHECK (stage IN
                    ('extract_resume','extract_jd','disambiguate','generate_roadmap')),
  model_requested   TEXT NOT NULL,
  model_resolved    TEXT,
  prompt_version    TEXT NOT NULL,
  request_hash      TEXT NOT NULL,
  http_status       INTEGER,
  latency_ms        INTEGER CHECK (latency_ms IS NULL OR latency_ms >= 0),
  prompt_tokens     INTEGER,
  completion_tokens INTEGER,
  cost_usd          REAL NOT NULL DEFAULT 0 CHECK (cost_usd >= 0),
  retry_count       INTEGER NOT NULL DEFAULT 0 CHECK (retry_count >= 0),
  repair_attempted  INTEGER NOT NULL DEFAULT 0 CHECK (repair_attempted IN (0,1)),
  cache_hit         INTEGER NOT NULL DEFAULT 0 CHECK (cache_hit IN (0,1)),
  error_code        TEXT,
  error_message     TEXT,
  created_at        TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_llm_calls_analysis
  ON llm_calls(analysis_id, created_at);

CREATE INDEX IF NOT EXISTS idx_llm_calls_stage
  ON llm_calls(stage, created_at DESC);

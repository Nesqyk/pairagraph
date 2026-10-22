CREATE TABLE IF NOT EXISTS reading_attempts (
 id INTEGER PRIMARY KEY, institute_id INTEGER NOT NULL REFERENCES institutes(id),
 activity_id INTEGER NOT NULL REFERENCES activities(id), learner_id INTEGER NOT NULL REFERENCES learners(id),
 transcript TEXT NOT NULL, reviewed_transcript TEXT NOT NULL, analysis TEXT NOT NULL,
 confirmed_issues TEXT NOT NULL DEFAULT '[]', reviewed INTEGER NOT NULL DEFAULT 0,
 reviewed_by INTEGER REFERENCES teachers(id), model TEXT NOT NULL, language TEXT NOT NULL,
 created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_reading_activity ON reading_attempts(institute_id,activity_id,learner_id);
CREATE TABLE IF NOT EXISTS practice_stories (
 id INTEGER PRIMARY KEY, institute_id INTEGER NOT NULL REFERENCES institutes(id),
 attempt_id INTEGER NOT NULL REFERENCES reading_attempts(id), title TEXT NOT NULL,
 story TEXT NOT NULL, rationale TEXT NOT NULL, targets TEXT NOT NULL, model TEXT NOT NULL,
 document_id INTEGER REFERENCES documents(id), created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

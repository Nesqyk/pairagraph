CREATE TABLE IF NOT EXISTS student_readings (
 id INTEGER PRIMARY KEY, institute_id INTEGER NOT NULL REFERENCES institutes(id),
 learner_id INTEGER NOT NULL REFERENCES learners(id), chunk_id INTEGER NOT NULL REFERENCES chunks(id),
 status TEXT NOT NULL DEFAULT 'reading' CHECK(status IN ('reading','analyzed')),
 transcript TEXT NOT NULL DEFAULT '', origin TEXT NOT NULL DEFAULT '',
 flags TEXT NOT NULL DEFAULT '[]', next_chunk_id INTEGER REFERENCES chunks(id),
 next_kind TEXT NOT NULL DEFAULT '', next_draft TEXT,
 created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, analyzed_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_student_readings ON student_readings(institute_id,learner_id,id);

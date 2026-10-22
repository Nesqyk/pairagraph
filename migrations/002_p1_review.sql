-- Audio is deliberately absent: recordings exist only in temporary memory.
CREATE TABLE IF NOT EXISTS transcripts (
 id INTEGER PRIMARY KEY, institute_id INTEGER NOT NULL REFERENCES institutes(id),
 activity_id INTEGER NOT NULL REFERENCES activities(id), learner_id INTEGER NOT NULL REFERENCES learners(id),
 role TEXT NOT NULL CHECK(role IN ('mentor','buddy')),
 origin TEXT NOT NULL CHECK(origin IN ('manual','provider')), provider_model TEXT NOT NULL DEFAULT '',
 original_text TEXT NOT NULL, text TEXT NOT NULL,
 status TEXT NOT NULL DEFAULT 'draft' CHECK(status IN ('draft','reviewed')),
 revision INTEGER NOT NULL DEFAULT 1, reviewed_by INTEGER REFERENCES teachers(id), reviewed_at TEXT,
 created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS reading_flags (
 id INTEGER PRIMARY KEY, transcript_id INTEGER NOT NULL REFERENCES transcripts(id) ON DELETE CASCADE,
 kind TEXT NOT NULL CHECK(kind IN ('skip','substitution','insertion')),
 expected TEXT NOT NULL, heard TEXT NOT NULL, word_start INTEGER NOT NULL, word_end INTEGER NOT NULL,
 decision TEXT NOT NULL DEFAULT 'pending' CHECK(decision IN ('pending','accepted','rejected')),
 teacher_note TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS result_reading_flags (
 result_id INTEGER NOT NULL REFERENCES results(id), flag_id INTEGER NOT NULL REFERENCES reading_flags(id),
 PRIMARY KEY(result_id,flag_id)
);
CREATE INDEX IF NOT EXISTS idx_transcripts_activity ON transcripts(institute_id,activity_id);
CREATE INDEX IF NOT EXISTS idx_reading_flags_transcript ON reading_flags(transcript_id);

CREATE TABLE IF NOT EXISTS institutes (id INTEGER PRIMARY KEY, name TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS teachers (
 id INTEGER PRIMARY KEY, institute_id INTEGER NOT NULL REFERENCES institutes(id),
 email TEXT NOT NULL UNIQUE, password_hash TEXT NOT NULL, name TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS learners (
 id INTEGER PRIMARY KEY, institute_id INTEGER NOT NULL REFERENCES institutes(id),
 alias TEXT NOT NULL, role TEXT NOT NULL CHECK(role IN ('mentor','buddy')), goal TEXT NOT NULL,
 UNIQUE(institute_id, alias)
);
CREATE TABLE IF NOT EXISTS pairs (
 id INTEGER PRIMARY KEY, institute_id INTEGER NOT NULL REFERENCES institutes(id),
 mentor_id INTEGER NOT NULL REFERENCES learners(id), buddy_id INTEGER NOT NULL REFERENCES learners(id),
 UNIQUE(institute_id, mentor_id, buddy_id)
);
CREATE TABLE IF NOT EXISTS documents (
 id INTEGER PRIMARY KEY, institute_id INTEGER NOT NULL REFERENCES institutes(id),
 title TEXT NOT NULL, source TEXT NOT NULL, filename TEXT NOT NULL,
 approved INTEGER NOT NULL DEFAULT 0, approved_by INTEGER REFERENCES teachers(id),
 created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS pages (
 id INTEGER PRIMARY KEY, document_id INTEGER NOT NULL REFERENCES documents(id),
 page_number INTEGER NOT NULL, text TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS chunks (
 id INTEGER PRIMARY KEY, document_id INTEGER NOT NULL REFERENCES documents(id),
 page_number INTEGER NOT NULL, chunk_number INTEGER NOT NULL, text TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS activities (
 id INTEGER PRIMARY KEY, institute_id INTEGER NOT NULL REFERENCES institutes(id),
 pair_id INTEGER NOT NULL REFERENCES pairs(id), chunk_id INTEGER NOT NULL REFERENCES chunks(id),
 mentor_goal TEXT NOT NULL, buddy_goal TEXT NOT NULL, tasks TEXT NOT NULL,
 status TEXT NOT NULL DEFAULT 'draft' CHECK(status IN ('draft','approved','completed')),
 stage INTEGER NOT NULL DEFAULT 0 CHECK(stage BETWEEN 0 AND 3),
 approved_by INTEGER REFERENCES teachers(id), created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS sessions (
 id INTEGER PRIMARY KEY, institute_id INTEGER NOT NULL REFERENCES institutes(id),
 activity_id INTEGER NOT NULL UNIQUE REFERENCES activities(id), teacher_id INTEGER NOT NULL REFERENCES teachers(id),
 notes TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS results (
 id INTEGER PRIMARY KEY, session_id INTEGER NOT NULL REFERENCES sessions(id),
 learner_id INTEGER NOT NULL REFERENCES learners(id), role TEXT NOT NULL, goal TEXT NOT NULL,
 rating TEXT NOT NULL CHECK(rating IN ('Needs support','Practicing','Demonstrated')),
 evidence TEXT NOT NULL, UNIQUE(session_id, learner_id)
);
CREATE TABLE IF NOT EXISTS login_attempts (key TEXT PRIMARY KEY, attempts INTEGER NOT NULL, since REAL NOT NULL);
CREATE INDEX IF NOT EXISTS idx_learners_tenant ON learners(institute_id);
CREATE INDEX IF NOT EXISTS idx_documents_tenant ON documents(institute_id);
CREATE INDEX IF NOT EXISTS idx_activities_tenant ON activities(institute_id);
CREATE INDEX IF NOT EXISTS idx_results_learner ON results(learner_id);

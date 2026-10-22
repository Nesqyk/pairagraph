CREATE TABLE IF NOT EXISTS learner_availability (
 learner_id INTEGER NOT NULL REFERENCES learners(id), slot TEXT NOT NULL,
 PRIMARY KEY(learner_id, slot)
);
CREATE TABLE IF NOT EXISTS material_languages (
 document_id INTEGER PRIMARY KEY REFERENCES documents(id),
 language TEXT NOT NULL CHECK(language IN ('en','fil','ceb')),
 reviewed_by INTEGER NOT NULL REFERENCES teachers(id), notes TEXT NOT NULL,
 reviewed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

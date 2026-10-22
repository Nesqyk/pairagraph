# Pairagraph — MVP Workload Breakdown

> Implementation work split into Core Functions (P0), Important Features (P1), and Improvements (P2).
> Originally based on `PAIRAGRAPH_MVP_BUILD_SPEC.md` (not present in this repository). This workload is the available implementation checklist. The goal is a real, working teacher → reading pair → approved material → shared activity → evaluation → progress loop.

## Rules for the coding AI
- Implement **all P0** before beginning P1 or P2. Keep every slice runnable.
- Use real storage, correct permissions, and source attribution. Do not simulate successful features without labeling demo data.
- Manual teacher assessment is valid for P0. Do not present automated voice grading as complete unless an actual model/provider is connected and tested.
- Every generated/adapted activity must originate from teacher-approved content, show its source, and require teacher review before use.
- Never collect or retain minors' voice recordings by default.

## 1. MVP Core Functions — P0 (Must Work)

| ID | Module | Scope / definition of done | Suggested owner |
|---|---|---|---|
| C01 | App foundation and auth | App runs locally; teacher login/logout; institute-scoped access; seeded demo account | Backend |
| C02 | Student management | Add/list/edit pseudonymous mentor and buddy learners; record separate learning goals | Full-stack |
| C03 | Pair management | Create/select a mentor–buddy pair; show both goals side by side | Full-stack |
| C04 | Material library | Upload text-based PDF/TXT; extract/preview text; teacher approves; handle unreadable scans | Backend / AI |
| C05 | Document retrieval | Chunk/index *approved* text; select relevant excerpts; retain document/page/chunk attribution | AI / Backend |
| C06 | Dual-adaptive activity builder | From one retrieved passage, create mentor vocabulary task, buddy comprehension task and teach-back prompt; deterministic fallback without AI key | AI / Backend |
| C07 | Story Relay screen | Guide learners through **Read → Retell → Teach-back** using one shared activity | Frontend |
| C08 | Teacher evaluation | Teacher manually records mentor observations, buddy answers, notes, and confirms session | Full-stack |
| C09 | Session persistence and progress | Save session; display independent mentor/buddy histories and goal-level counts | Full-stack |
| C10 | Reliability and privacy baseline | Validation, tenant authorization, no default audio storage, responsive layouts, errors/empty states, happy-path tests | All |

### P0 acceptance demonstration
1. Teacher signs in and creates/selects two pseudonymous learners with different goals.
2. Teacher makes a pair and uploads/selects approved reading content.
3. The app retrieves an actual passage with visible attribution.
4. The app produces **one shared activity with two different learning tasks** (works without an AI API key).
5. Learners complete Read → Retell → Teach-back; teacher enters results.
6. Saved session appears under both learners with **separate results** even after refreshing.

### P0 implementation status — 2026-10-22

The P0 reading workflow is implemented in the local Flask/SQLite application. At the user's request, login was replaced with a single teacher workspace that opens directly. See [README.md](README.md) for setup and the runnable acceptance walkthrough.

| ID | Status | Implementation / verification |
|---|---|---|
| C01 | Updated scope | Local startup applies the schema and seeds a fictional demo teacher; server-selected single-teacher workspace opens without login. Records remain institute scoped. |
| C02 | Complete | Add/list/edit pseudonyms with role-specific learning goals; existing activities retain their original goals. |
| C03 | Complete | Create/select mentor–buddy pairs and display the two goals side by side. |
| C04 | Complete | Extract and preview UTF-8 TXT/text-based PDF content; explicit teacher approval; reject unreadable scans and unsupported uploads. |
| C05 | Complete | Index approved text only; keyword retrieval with an explicitly labeled first-passage fallback; document/page/chunk attribution. Numeric-only pages are excluded. |
| C06 | Updated | RAG generation with the configured shared model: up to three approved source chunks, separate goals, teacher-confirmed reading observations, validated source quotes, and mandatory activity approval. Goal-based templates remain the no-key/error fallback. |
| C07 | Complete | Persisted, ordered Read → Retell → Teach-back stages on one shared activity. |
| C08 | Complete | Teacher-entered mentor observations, buddy answers, individual ratings, notes, and mandatory confirmation. |
| C09 | Complete | Atomic session/result saves, separate learner histories, goal-level counts, and persistence after application restart. |
| C10 | Implemented | Server-side validation, institute scoping, CSRF, responsive styles, errors/empty states, optional authorized microphone use, no retained audio files, and automated acceptance tests. |

Verification: `python -m unittest discover -s tests -v` covers the complete acceptance journey, restart persistence, institute scoping, approval gates, upload validation, page attribution, original goal preservation, malformed CSRF rejection, and duplicate/out-of-order submission protection. Voice tests also cover consent, separate learner attempts, transcript correction, confirmation gates, provider failure, and generated-story approval. Provider responses are mocked; live voice/model accuracy is not verified. Use the virtual-environment command in the README on Windows.

Browser verification: completed sign-in → material approval → activity draft/review → Read → Retell → Teach-back → evaluation → separate progress, including a page refresh. Checked the activity at 390 px phone width and progress at 1440 px desktop width. The local demo session is explicitly labeled as fictional QA data.

Updated product goal: **English read-aloud → speech transcription → source comparison → teacher-confirmed observations → individual guidance → targeted AI practice story → teacher approval → next session**. Filipino follows after separate language validation.

RAG integration: `claude-haiku-5-5` now generates the mentor vocabulary task, buddy comprehension task, and shared teach-back from locally retrieved approved chunks. Source quotations and vocabulary are checked against retrieved text. Keyword retrieval is used; embeddings/vector search are not implemented. The RAG provider passed a live fictional-context test with three validated citations. The full suite has 25 passing tests, including rejection of unapproved context, unretrieved citations, fabricated quotes, and invented vocabulary. Model failure produces a labeled template draft.

The English voice capture, transcription provider integration, possible-miscue review, coaching guidance, and targeted-story draft/review loop now have code and automated coverage. Story generation has passed a live fictional-text check through the supplied compatible gateway using `claude-haiku-5-5`. That gateway cannot transcribe speech; the separate Gemini key in `voice.env` now enables `gemini-3.8-flash` audio transcription. A live synthetic English recording was transcribed exactly, with no word differences from the synthetic reference. The suite has 30 passing tests, including Gemini routing, error handling, key isolation, and transcript validation. Learner speech accuracy has not yet been established. Audio is processed in memory; this app retains text and confirmed observations, not recordings. Transcript comparison does not assess pronunciation, phonemes, pace, or prosody. OCR, dedicated pronunciation/fluency assessment, Filipino validation, and P2 remain deferred.

## 2. MVP Important Features — P1 (Only After P0)

| ID | Feature | Scope / definition of done | Suggested owner |
|---|---|---|---|
| I01 | LLM-assisted activity adaptation | Optional AI provider; adapt approved source into age-appropriate tasks; JSON validation, explicit adaptation labeling, teacher approval | AI |
| I02 | Voice recording | Visible record/stop/playback controls with explicit authorization; recording off by default; safe handling/deletion | Frontend / Backend |
| I03 | Speech-to-text | Convert recording to editable transcript with actual provider, failure states, and source/passage comparison view | AI / Backend |
| I04 | Possible reading error flags | Surface potential skips/substitutions as **unconfirmed suggestions**, not diagnosis; teacher accepts/rejects | AI / Frontend |
| I05 | Next-session recommendation | Suggest practice based on saved teacher-confirmed observations and approved material | AI / Backend |
| I06 | AI review workspace | Teacher edits/approves generated adaptations and suggested reading observations before recording as evidence | Full-stack |
| I07 | Session summary | Compact summary of each learner's goals, practiced skills, and observations | Frontend |

### P1 acceptance demonstration
- AI output is attributed to an approved source and can be edited or rejected.
- Transcript and possible miscues clearly distinguish model output from teacher-confirmed observations.
- The app still works when AI/transcription services fail or keys are absent.

## 3. MVP Improvements — P2 (After MVP Works)

| ID | Improvement | Scope | Suggested owner |
|---|---|---|---|
| M01 | Gentle gamification | Shared milestones; no public ranking of learners | Frontend |
| M02 | Richer progress insights | Charts after enough sessions; distinguish observations from proven improvement | Frontend / Backend |
| M03 | Visual refinements | Improved typography, transitions, stories and accessibility refinements | Frontend |
| M04 | Device optimization | Further Android and low-bandwidth improvements beyond P0 responsiveness | Frontend |
| M05 | Suggested pair matching | Teacher-reviewed matches based on goals and availability | AI / Backend |
| M06 | Offline-first workflows | Cache approved activity with deliberate synchronization/conflict handling | Full-stack |
| M07 | Report export | Teacher-friendly PDF/CSV reports | Backend |
| M08 | Additional languages | Validate reading content and speech models language by language | AI / Product |

## Parallel team workload (suggested)

| Workstream | First responsibility | Can start when |
|---|---|---|
| Backend / Database | C01–C03 schemas/APIs, session storage C08–C09, permissions C10 | Immediately |
| Frontend / UX | C02–C03 UI, C07 session, C08 review, C09 progress | Immediately with mocked typed API contracts; connect to real backend before declaring done |
| AI / Retrieval | C04 extraction, C05 retrieval, C06 deterministic generation | Immediately with test documents |
| QA / Integration (shared) | C10 checks, test fixture, end-to-end C01–C09 demo | From first working vertical slice |

**Dependency order:** auth/data models → learners/pairs + approved materials → retrieval → activity generation → session/review → progress. Build P1 afterward. P2 does not block an MVP release.

## Suggested implementation sequence
- **Milestone A — Foundation:** C01–C03, a seeded demo, and data models.
- **Milestone B — Distinctive engine:** C04–C06, with working approved-document retrieval and two different tasks.
- **Milestone C — Usable end-to-end flow:** C07–C09, teacher confirmation, saved progress.
- **Milestone D — Hardening:** C10 and an end-to-end test of the exact demo journey.
- **Optional next:** I01 → I06 → I05; only then I02–I04 if there is time and authorized test audio.

## Ready-to-paste coding instruction

> Use this workload breakdown together with `PAIRAGRAPH_MVP_BUILD_SPEC.md`. Implement all **P0 core functions** as a working application before P1 or P2. First inspect the repository, then create migrations, auth, learners, pairs, approved document ingestion, retrieval, deterministic dual-adaptive activity generation, Story Relay, teacher review, and separate progress records. Add realistic demo seeds and automated tests. If a feature cannot be implemented honestly, list it as deferred rather than presenting fake functionality. Keep the implementation runnable after each milestone.

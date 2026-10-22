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

The P0 reading workflow is implemented in the local Flask/SQLite application. The current branch opens a server-selected local teacher workspace without login; the original C01 login/logout requirement is not active in this mode. See [README.md](README.md) for setup and the runnable acceptance walkthrough.

| ID | Status | Implementation / verification |
|---|---|---|
| C01 | Local-mode scope | Startup applies the schema and seeds a fictional teacher workspace. Institute filtering remains; login/logout is not active in the current branch. Multi-user authentication remains required before a shared deployment. |
| C02 | Complete | Add/list/edit pseudonyms with role-specific learning goals; existing activities retain their original goals. |
| C03 | Complete | Create/select mentor–buddy pairs and display the two goals side by side. |
| C04 | Complete | Extract and preview UTF-8 TXT/text-based PDF content; explicit teacher approval; reject unreadable scans and unsupported uploads. |
| C05 | Complete | Index approved text only; keyword retrieval with an explicitly labeled first-passage fallback; document/page/chunk attribution. Numeric-only pages are excluded. |
| C06 | Complete | Deterministic goal-specific mentor vocabulary and buddy comprehension tasks plus teach-back from one passage; explicit teacher review before use; no API key. |
| C07 | Complete | Persisted, ordered Read → Retell → Teach-back stages on one shared activity. |
| C08 | Complete | Teacher-entered mentor observations, buddy answers, individual ratings, notes, and mandatory confirmation. |
| C09 | Complete | Atomic session/result saves, separate learner histories, goal-level counts, and persistence after application restart. |
| C10 | Complete for local mode | Server-side validation, institute filtering, CSRF, responsive styles, errors/empty states, and acceptance tests. Microphone access is denied by default and enabled only on the opt-in reading page; no server audio storage. |

Verification: `python -m unittest discover -s tests -v` runs 41 tests covering P0, P1, and P2, including the complete reading journey, restart persistence, institute isolation, approval gates, upload validation, attribution, original goal preservation, malformed CSRF rejection, and duplicate/out-of-order submission protection. Use the virtual-environment command in the README on Windows.

Initial P0 browser verification completed material approval → activity draft/review → Read → Retell → Teach-back → evaluation → separate progress, including a page refresh, at phone and desktop widths. The current branch opens the workspace directly. Local QA session evidence is explicitly labeled as fictional.

P1 and P2 implementation and verification are recorded below. OCR and automated voice grading remain out of scope. Teacher assessment and deterministic templates remain available without providers.

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

### P1 implementation audit — 2026-10-22

The initial audit correctly found 0 of 7 features complete. The implementation below supersedes that audit. **I01, I02, and I04–I07 are implemented. I03 has integration and fallback code but awaits the separate voice provider for live acceptance.** The supplied `claude-haiku-5-5` model is used only for RAG-grounded activity generation, as requested.

| ID | Status | Evidence / remaining work |
|---|---|---|
| I01 | Implemented; live RAG verified | Optional provider uses one retrieved approved passage, goals, and age band; validates task JSON and source vocabulary, labels AI output, retains original suggestions, and requires teacher approval. Live validated generation succeeded against the supplied model server. Provider failure produces a labeled deterministic fallback. |
| I02 | Implemented; synthetic-audio browser verified | Explicit recording authorization; Start/Stop/Playback/Delete; off by default; 60-second/5 MB cap; browser-memory audio with object-URL cleanup and track shutdown. No server audio files. |
| I03 | Integration ready; voice provider pending | A separate configurable transcription endpoint/key/model, opt-in submission, editable attributed transcript drafts, passage comparison, upload validation, and failure paths are implemented and tested with provider fixtures. Live speech-to-text is not claimed complete; the user will supply a separate voice model. Until then, sending audio is disabled and manual transcripts work. |
| I04 | Implemented | Word alignment surfaces possible skips, substitutions, and insertions as unconfirmed suggestions. Teacher accepts/rejects each; acceptance requires a teacher-written note. No automatic diagnosis or grade. |
| I05 | Implemented | Rule-based next-session practice uses the latest confirmed results for each current goal, shows its evidence, and ranks approved passages with visible attribution. No-history and no-material states are explicit. Teacher selects a passage to create a new draft. |
| I06 | Implemented | Teacher can edit/reject AI task drafts before approval, edit transcripts, accept/reject comparison suggestions, and explicitly select confirmed notes for learner evidence. Edits reset comparison review; stale forms are rejected; completed-session evidence is frozen. |
| I07 | Implemented | A combined session summary shows both learners' original goals, practiced skills/tasks, individual ratings and observations, shared teach-back/notes, confirming teacher, and passage attribution. Linked from saved activities and learner history. |

Verification: 33 automated tests pass, including provider protocol/JSON/error handling, fallback, authorization/consent, no-default recording, in-memory uploads, transcript revisions, accepted/rejected evidence boundaries, tenant isolation, recommendations, and summary persistence. Chromium recording QA used a synthetic stream to verify authorization → record → stop → playback → delete and ended audio tracks. No learner audio was used. Voice recognition remains pending its separate model and endpoint.

Browser acceptance also completed live RAG generation → teacher edit/approval → manual transcript comparison/review → explicit evidence selection → combined summary → next-session recommendations. The saved summary survived refresh and had no horizontal overflow at 375, 768, and 1440 px.

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

### P2 implementation status — 2026-10-22

| ID | Status | Implementation / limits |
|---|---|---|
| M01 | Implemented | Shared milestones at 1, 3, 5, and 10 confirmed sessions per pair. No learner leaderboard, ability score, or public ranking. Drafts and unfinished relays do not earn milestones. |
| M02 | Implemented | Learner assessment distribution charts after three confirmed sessions, accessible numerical labels and session evidence table. Reports distinguish recorded observations from proven improvement; they do not plot ratings as a measured reading score. |
| M03 | Implemented | Standard/large/extra-large passage text, device-local size preference, focus reading with an exit control, keyboard focus outlines, reduced-motion support, and language tags on tasks. |
| M04 | Implemented; real Android QA pending | Touch-sized controls, wrapping actions and long content, a horizontally scrollable evidence table, local assets without external fonts/CDNs, and an offline shell. Chromium viewport checks passed at 375, 768, and 1440 px; physical Android and field bandwidth testing remain pending. |
| M05 | Implemented | Persistent teacher-entered availability; rule-based mentor/buddy suggestions show both current learning goals and shared time slots. Existing pairs are excluded; unknown/disjoint availability produces no suggestion. A teacher explicitly chooses a pair and confirms its actual schedule. |
| M06 | Implemented for the relay | Explicit device-storage authorization saves only an unfinished approved activity and its attributed passage. Read/Retell/Teach-back work offline, including reloads. Explicit online synchronization checks workspace, source approval, and a revision fingerprint; changed or completed activities are rejected without overwriting either copy. Teacher evaluation, transcripts, and recording remain online. Individual/all-copy deletion is available. Copies remain on the device until deleted; no background sync. |
| M07 | Implemented | Learner CSV and paginated PDF reports contain historical goals, ratings, observations, shared notes, dates, and source/page/chunk attribution. CSV formula prefixes are neutralized. Reports use institute-scoped reads, preserve original evidence, and handle empty histories. |
| M08 | Partial — language validation pending | Teacher content-language review and Filipino/Cebuano task templates are implemented, with Unicode vocabulary extraction and preserved language on draft rejection. Non-English AI requests use an explicitly labeled localized-template fallback. UI administration remains English; passage translation is not provided. Fluent-speaker acceptance of task wording and live speech-model evaluation per language are still required before this item can be marked complete. |

Verification: **41 automated tests passed** (the 33 existing P0/P1 tests plus 8 P2 tests). New checks cover confirmed-only milestones, chart thresholds, matching availability, tenant boundaries, CSV formula safety, PDF pagination, migration persistence, offline approval/CSRF/revision gates, and language review/fallback behavior. Browser QA used fictional data and verified save → offline reload → all three relay steps → reload persistence → explicit sync, deletion, display controls, language form submission, and responsive screens at 375/768/1440 px without JavaScript errors. A three-page PDF with long fictional evidence was rendered and visually inspected. No learner audio or live AI calls were used for P2 validation.

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

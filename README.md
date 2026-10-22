# Pairagraph

A local, teacher-led paired-reading MVP built with Flask and SQLite. One approved passage supports a mentor vocabulary task, a buddy comprehension task, and a shared teach-back. Teachers assess each learner separately.

## Run locally

Requires Python 3.10 or later. From this directory in PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe app.py
```

Open <http://127.0.0.1:5000>. The current branch opens the local teacher workspace directly, without login. Template activities need no AI key.

Startup applies the SQL files in `migrations/` without deleting existing data, and creates a fictional demo institute on an empty database:

- Teacher: Demo Teacher (server-selected local workspace)
- Mentor: Maple; buddy: Robin
- Material: **The Seed Library**, an original fictional passage that still requires teacher approval

The database and persistent session secret are created in the ignored `instance/` directory. Learners, approvals, relay steps, transcripts, review decisions, and confirmed results survive restarts. The built-in server and direct teacher access are for local evaluation. Keep it bound to localhost; this mode is not a multi-user deployment with authentication.

## Try the P0 workflow

1. Open the workspace. In **Learners**, add or edit pseudonyms and choose separate goals.
2. In **Reading pairs**, create a mentor–buddy pair, then select **Build a shared activity**.
3. In **Material library**, review the demo passage or upload a UTF-8 TXT/text-based PDF. Enter source attribution and approve the extracted text. Files are limited to 5 MB; PDFs to 100 pages. Scans need OCR before upload. Only extracted text is retained.
4. In **Build activity**, select the pair and approved material. Optionally enter topic keywords. The app retrieves a passage and shows its document, page, and chunk attribution.
5. Review both goal-specific tasks and approve the activity. Template tasks work without a provider; optional AI adaptation is described below. The source passage is not rewritten.
6. Guide **Read → Retell → Teach-back**, then record mentor observations, buddy answers, individual ratings, and optional shared notes. Confirm to save both results together.
7. Saving opens a **Session summary** with both learners' goals, practiced skills, ratings, evidence, notes, and source. In **Learner progress**, select a learner for separate history and goal-level counts. Changing a current goal preserves the original goals on existing activities and results.

Activity approval is separate from material approval. Draft activities cannot start a relay, and incomplete relays cannot be evaluated. Confirmed sessions cannot be submitted twice.

## P1 workflows

- **RAG-assisted task adaptation:** On **Build activity**, opt into AI and choose an age band. Only a retrieved approved passage, the two goals, and age band go to the model. JSON and vocabulary attribution are validated. Failures produce a clearly labeled template fallback. On the draft, use **Edit or reject draft tasks**, then approve it. Original AI suggestions remain available during review. Approved tasks are frozen.
- **Optional recording:** In **Story Relay**, open **Reading & transcript review**. Explicitly authorize recording, then use Start, Stop, Playback, and Delete. Audio stays in browser memory and is deleted on leaving the page. The app requests no microphone access by default. Recording requires localhost or HTTPS and a browser with MediaRecorder.
- **Transcript review:** Enter what was read manually, or send a recording only after a separate transcription provider has been configured and you explicitly authorize sending it. Provider output is saved as an unconfirmed draft with its origin. Compare it with the original passage, edit it, and accept or reject each possible difference. Accepting requires a teacher-written observation. Editing resets all decisions. These comparisons do not grade pronunciation or diagnose a reading difficulty.
- **Confirmed evidence:** During evaluation, explicitly select any accepted teacher notes to include in that learner's result. Pending and rejected flags cannot enter results. Draft transcripts and their flags can be deleted before session confirmation; confirmed sessions preserve their evidence.
- **Next-session practice:** In **Reading pairs**, choose **Suggest next practice**, or use **Plan the next session** on a summary. Suggestions show the latest confirmed result for each current goal and attributed approved passages ranked by overlap with the evidence. The recommendation is rule-based and requires teacher review.

Voice recognition is **pending the separate voice model/endpoint**. The submitted RAG model is used only for source-grounded task generation. It is not used for audio. Manual transcripts and all P0 functionality work while voice recognition is unavailable.

## P2 workflows

- **Shared milestones:** Open the sidebar's Shared milestones page to celebrate 1, 3, 5, and 10 confirmed sessions together. These are practice milestones, not ability rankings.
- **Practice insights and exports:** In Learner progress, select a learner and open Practice insights & reports. Charts appear after three confirmed sessions; the session table remains available before that. Export CSV or PDF for that learner. Historical goals and source attribution are preserved; ratings describe teacher observations rather than measured improvement.
- **Reading display:** On a page with a passage, choose Standard, Large, or Extra large text and toggle Focus reading. Text size is remembered on the device; keyboard focus and reduced-motion preferences are supported.
- **Suggested pairs:** In Reading pairs, open Find a reading partner. Set general local-time availability slots for each learner, then review suggestions with shared availability and both learning goals. Choose a pair explicitly; confirm the exact schedule yourself. Suggestions are rule-based, not AI predictions of compatibility.
- **Offline reading:** On an approved, unfinished Story Relay, authorize storage on a trusted device and click Save for offline reading. Open Offline reading before disconnecting. You can complete Read → Retell → Teach-back offline and reload without losing local steps. Reconnect and click Synchronize relay progress, then return online for teacher evaluation. Nothing synchronizes in the background. If the online activity, pair goals, approval, or passage changed, the app keeps your local copy and rejects the update; inspect the online activity, then explicitly replace the saved copy if appropriate. Do not delete a copy until you have synchronized progress you want to keep. Device copies contain pseudonyms/passages and remain until deleted. Delete individual copies or all offline data from Offline reading. Recording and assessments stay online.
- **Language review (partial M08):** Material library → a document → Review material language lets a teacher review content as English, Filipino, or Cebuano. In Build activity, choose the matching task language. Filipino/Cebuano tasks use local templates and require teacher wording review; they do not translate the source passage. AI adaptation and speech-model accuracy in these languages have not been validated. A fluent speaker and a configured speech provider must complete language-by-language acceptance before M08 is complete.

P2 browser checks used Chromium at 375/768/1440 px and offline mode. Physical Android devices and field bandwidth behavior still need testing. PDF export adds ReportLab; rerun `pip install -r requirements.txt` after updating.

## Provider configuration

Text generation supports OpenAI-compatible Chat Completions and the OpenAI Responses API. The local RAG service has been verified with `claude-haiku-5-5` at `http://192.168.106.122:8080/api/chat/completions`. Its key is stored only in ignored `instance/provider.json`; never commit that file or paste a real key into the example below.

Environment variables override local configuration:

```powershell
$env:PAIRAGRAPH_AI_BASE_URL = "http://192.168.106.122:8080/api"
$env:PAIRAGRAPH_AI_MODE = "chat"
$env:PAIRAGRAPH_AI_MODEL = "claude-haiku-5-5"
$env:PAIRAGRAPH_AI_KEY = "YOUR_RAG_KEY"
.\.venv\Scripts\python.exe app.py
```

For OpenAI Responses, use mode `responses`, base URL `https://api.openai.com/v1`, and a compatible text model. `OPENAI_API_KEY` is also accepted for text generation. Restart after configuration changes.

When the voice model is available, configure `PAIRAGRAPH_STT_URL` (the complete transcription URL), `PAIRAGRAPH_STT_MODEL`, and `PAIRAGRAPH_STT_KEY`. The adapter sends multipart `file`, `model`, and `response_format=json` and expects a JSON `text` field. Until a transcription URL and voice key are explicitly configured, no voice request is enabled. Voice credentials are configured separately; RAG credentials are never automatically reused for audio. If the forthcoming voice service uses another protocol, its adapter must be adjusted before enabling it.

Requests have a 30-second timeout. Errors show safe messages without provider payloads or credentials. The app sends audio only on explicit request and processes uploads in memory, up to 5 MB. An external transcription service may apply its own retention policy; check it before sending learner audio. Pairagraph retains only authorized transcript text and review decisions, not audio files.

API references: [Open WebUI Chat Completions](https://docs.openwebui.com/reference/api-endpoints/), [OpenAI Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs), [OpenAI transcription](https://developers.openai.com/api/docs/guides/speech-to-text).

## Verify

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

The 41 tests use temporary databases and mocked provider calls. They cover the complete reading journey, restart persistence, CSRF, institute boundaries, upload errors, attributed generation and fallback, task edits/rejection, stale reviews, consent and audio validation, transcript decisions, evidence selection, recommendations, summaries, both API protocols, and the P2 milestone/chart/matching/export/offline/language gates. Earlier P1 checks verified live RAG generation against the configured server and Chromium recording with synthetic audio. Live speech-to-text remains pending.

## Scope and privacy

See [the workload and verification status](PAIRAGRAPH_MVP_WORKLOAD.md) for feature-by-feature scope. P1 I01, I02, and I04–I07 are implemented; I03 awaits the separate voice provider for live acceptance. P2 M01–M07 are implemented within the local-workspace scope; M08 has language-review/template foundations but still needs fluent-speaker and speech-model validation. Real Android QA is pending. There is no automated voice grading. Teacher assessments are observations, not proof of measured improvement.

All database operations use the institute of the server-selected teacher (`LOCAL_TEACHER_ID`, default 1). Browser cookies cannot choose another teacher. The current local mode has no login/logout; institute/account administration is not included. The SQLite database and local provider configuration are not encrypted at rest.

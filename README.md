# Pairagraph

Pairagraph is a local reading-practice app built with Flask and SQLite. The student experience uses a simple sequence: start a story, read aloud, review a few practice words, and choose another story.

## Student experience

Open <http://localhost:5000> or <http://localhost:5000/student>. The app uses the current demo reader automatically; there is no reader-selection dialog or teacher approval step in this flow.

1. **Start:** press the centered **Start Reading** button.
2. **Get ready:** review the microphone consent checkbox, tick it, and press **Record**. Allow microphone access when the browser asks. The story stays hidden until recording starts.
3. **Read:** read the story out loud. The passage uses large text, with a **Text size** control to enlarge it. **Stop** stays at the bottom center of the screen. Recording stops automatically after three minutes.
4. **Finish:** after stopping, choose the peach **Record again** button or the green **See how I did** button. You can also listen back to the recording. Submitting shows a spinning circle and **Loading your results…** until the results arrive.
5. **Review:** the results page confirms the reading was saved and shows up to five practice words when available. **Look at my reading** expands the story/transcript comparison. **Next story** continues the flow.
6. **Continue:** the next-story page presents one story with a **Read this story** button. When practice words and a story provider are available, **Make a story for me** creates a practice story. **Take a break** returns home.
7. **Progress:** **My progress** shows saved readings and suggested practice words.

The student interface is recording-only; **Type instead** has been removed. Existing backend transcript support remains for compatibility and automated tests.

The AI can mishear words. Suggestions are for practice, not pronunciation grades or a diagnosis. Analysis happens after submission, not live during recording.

## Run locally

Requires Python 3.10 or later. From this directory in PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe app.py
```

Open <http://127.0.0.1:5000>. The homepage opens the student reading room. The earlier teacher workspace remains at <http://127.0.0.1:5000/workspace>.

The local startup command reloads edited templates on the next request. Refresh your browser after UI changes; use **Ctrl + Shift + R** if old styles remain. Restart the app after Python or provider-configuration changes. Keep the same hostname while reading so your browser retains its session.

Startup applies the SQL files in `migrations/` without deleting existing data, and creates a fictional demo institute on an empty database:

- Teacher: Demo Teacher (server-selected local workspace)
- Mentor: Maple; buddy: Robin
- Material: **The Seed Library**, an original fictional passage that still requires teacher approval

The database and persistent session secret are created in the ignored `instance/` directory. Learners, approvals, relay steps, transcripts, review decisions, and confirmed results survive restarts. The built-in server and direct teacher access are for local evaluation. Keep it bound to localhost; this mode is not a multi-user deployment with authentication.

## Student provider setup

Student voice transcription uses Gemini. Set `GEMINI_API_KEY` in the environment or in the ignored `voice.env` file at the project root:

```dotenv
GEMINI_API_KEY=your_gemini_key
```

`PAIRAGRAPH_TRANSCRIPTION_MODEL` can override the voice model through the environment or `voice.env`. Recording requires a compatible browser with microphone access on localhost or HTTPS. If the voice key is missing, Record is disabled. Submitted audio is limited to 5 MB.

Optional student story generation uses the ignored `instance/ai_config.json` file. Configure `api_key`, `base_url`, `story_model`, and `story_api_style` for your provider. `PAIRAGRAPH_AI_KEY` overrides the student story key. The student flow reads its story model, base URL, and API style from that JSON file; the legacy workspace environment variables below are separate.

Three original built-in stories are seeded automatically. Without story generation, readers can continue with approved library stories or reread a story. Student readings are stored in `student_readings`, introduced by `migrations/003_student_ui.sql`.

Keys stay on the server. Pairagraph processes submitted audio in memory and does not retain audio files; transcripts and reading results are saved. External providers have their own data-handling policies. Do not commit credentials, `voice.env`, or files under `instance/`.

## Legacy teacher workspace

The following workflows belong to `/workspace`, rather than the simplified student pages. Template activities do not require an AI key.

### P0 workflow

1. Open the workspace. In **Learners**, add or edit pseudonyms and choose separate goals.
2. In **Reading pairs**, create a mentor–buddy pair, then select **Build a shared activity**.
3. In **Material library**, review the demo passage or upload a UTF-8 TXT/text-based PDF. Enter source attribution and approve the extracted text. Files are limited to 5 MB; PDFs to 100 pages. Scans need OCR before upload. Only extracted text is retained.
4. In **Build activity**, select the pair and approved material. Optionally enter topic keywords. The app retrieves a passage and shows its document, page, and chunk attribution.
5. Review both goal-specific tasks and approve the activity. Template tasks work without a provider; optional AI adaptation is described below. The source passage is not rewritten.
6. Guide **Read → Retell → Teach-back**, then record mentor observations, buddy answers, individual ratings, and optional shared notes. Confirm to save both results together.
7. Saving opens a **Session summary** with both learners' goals, practiced skills, ratings, evidence, notes, and source. In **Learner progress**, select a learner for separate history and goal-level counts. Changing a current goal preserves the original goals on existing activities and results.

Activity approval is separate from material approval. Draft activities cannot start a relay, and incomplete relays cannot be evaluated. Confirmed sessions cannot be submitted twice.

### P1 workflows

- **RAG-assisted task adaptation:** On **Build activity**, opt into AI and choose an age band. Only a retrieved approved passage, the two goals, and age band go to the model. JSON and vocabulary attribution are validated. Failures produce a clearly labeled template fallback. On the draft, use **Edit or reject draft tasks**, then approve it. Original AI suggestions remain available during review. Approved tasks are frozen.
- **Optional recording:** In **Story Relay**, open **Reading & transcript review**. Explicitly authorize recording, then use Start, Stop, Playback, and Delete. Audio stays in browser memory and is deleted on leaving the page. The app requests no microphone access by default. Recording requires localhost or HTTPS and a browser with MediaRecorder.
- **Transcript review:** Enter what was read manually, or send a recording only after a separate transcription provider has been configured and you explicitly authorize sending it. Provider output is saved as an unconfirmed draft with its origin. Compare it with the original passage, edit it, and accept or reject each possible difference. Accepting requires a teacher-written observation. Editing resets all decisions. These comparisons do not grade pronunciation or diagnose a reading difficulty.
- **Confirmed evidence:** During evaluation, explicitly select any accepted teacher notes to include in that learner's result. Pending and rejected flags cannot enter results. Draft transcripts and their flags can be deleted before session confirmation; confirmed sessions preserve their evidence.
- **Next-session practice:** In **Reading pairs**, choose **Suggest next practice**, or use **Plan the next session** on a summary. Suggestions show the latest confirmed result for each current goal and attributed approved passages ranked by overlap with the evidence. The recommendation is rule-based and requires teacher review.

The legacy transcript-review flow uses a separate transcription endpoint. Its manual transcript option remains available. This is separate from Gemini recording in the student flow.

### Legacy provider configuration

Legacy text generation supports OpenAI-compatible Chat Completions and the OpenAI Responses API. Configuration can be stored in the ignored `instance/provider.json`; never commit credentials. Use the endpoint and model supplied by your provider.

Environment variables override local configuration:

```powershell
$env:PAIRAGRAPH_AI_BASE_URL = "https://your-provider.example/v1"
$env:PAIRAGRAPH_AI_MODE = "chat"
$env:PAIRAGRAPH_AI_MODEL = "YOUR_MODEL"
$env:PAIRAGRAPH_AI_KEY = "YOUR_RAG_KEY"
.\.venv\Scripts\python.exe app.py
```

For OpenAI Responses, use mode `responses`, base URL `https://api.openai.com/v1`, and a compatible text model. `OPENAI_API_KEY` is also accepted for text generation. Restart after configuration changes.

For legacy transcript review, configure `PAIRAGRAPH_STT_URL` (the complete transcription URL), `PAIRAGRAPH_STT_MODEL`, and `PAIRAGRAPH_STT_KEY`. The adapter sends multipart `file`, `model`, and `response_format=json` and expects a JSON `text` field. Until a transcription URL and voice key are explicitly configured, no voice request is enabled. Voice credentials are configured separately; RAG credentials are never automatically reused for audio. If the service uses another protocol, its adapter must be adjusted before enabling it.

The legacy provider timeout is configured with `PAIRAGRAPH_AI_TIMEOUT`. Student transcription and story generation allow up to 300 seconds per provider call. Errors show safe messages without provider payloads or credentials. The app sends audio only on explicit request and processes uploads in memory, up to 5 MB. An external transcription service may apply its own retention policy; check it before sending learner audio. Pairagraph retains only authorized transcript text and review decisions, not audio files.

## Verify

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Tests use temporary databases and mocked provider calls. They cover student reading persistence, voice validation, transcript comparison, story generation, and legacy workspace workflows. They do not replace browser checks with an actual microphone.

Some existing student tests still assert wording from the earlier interface and need updating for the simplified pages. Do not treat historical test counts or browser checks as validation of the current UI.

For a manual UI check, start at the homepage and verify consent before recording, story visibility after Record, the bottom-centered Stop button, the two colored follow-up buttons, the loading spinner, results, and next-story navigation. Check both desktop and narrow mobile layouts, and verify that microphone denial and submission errors leave a useful message.

## Scope and privacy

[PAIRAGRAPH_MVP_WORKLOAD.md](PAIRAGRAPH_MVP_WORKLOAD.md) documents the earlier teacher-workspace scope and milestones. The student experience above describes the current UI.

All database operations use the institute of the server-selected teacher (`LOCAL_TEACHER_ID`, default 1). Browser cookies cannot choose another teacher. The current local mode has no login/logout; institute/account administration is not included. The SQLite database and local provider configuration are not encrypted at rest.

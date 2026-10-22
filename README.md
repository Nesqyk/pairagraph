# Pairagraph

A local, teacher-led paired-reading app built with Flask and SQLite. Learners read approved passages aloud; an optional speech provider transcribes their readings, and the app compares each transcript with the source. Teacher-confirmed observations guide individual feedback and AI-generated practice stories. English is the first supported reading language; Filipino is planned next.

## Run locally

Requires Python 3.10 or later. From this directory in PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe app.py
```

Open <http://127.0.0.1:5000>. The local teacher workspace opens directly, without a login. The manual reading workflow needs no AI key; voice analysis and generated stories require one.

The first startup applies `migrations/001_initial.sql` and creates a fictional demo institute:

- Teacher: Demo Teacher (selected by the server; no sign-in)
- Mentor: Maple; buddy: Robin
- Material: **The Seed Library**, an original fictional passage that still requires teacher approval

The database and persistent session secret are created in the ignored `instance/` directory. Learners, approvals, relay steps, transcripts, reviewed observations, stories, and confirmed results survive application restarts. This is a single-teacher local workspace, not a public multi-user service.

## Try the P0 workflow

1. In **Learners**, add or edit pseudonyms and choose separate goals.
2. In **Reading pairs**, create a mentor–buddy pair, then select **Build a shared activity**.
3. In **Material library**, review the demo passage or upload a UTF-8 TXT/text-based PDF. Enter source attribution and approve the extracted text. Files are limited to 5 MB; PDFs to 100 pages. Scans need OCR before upload. Only extracted text is retained.
4. In **Build activity**, select the pair and approved material. Optionally enter topic keywords. The app retrieves a passage and shows its document, page, and chunk attribution.
5. Leave **Use claude-haiku-5-5** checked to generate RAG tasks, or uncheck it for goal-based templates. Review both tasks and their source evidence, then approve the activity. The source passage is not rewritten.
6. Guide **Read → Retell → Teach-back**, then record mentor observations, buddy answers, individual ratings, and optional shared notes. Confirm to save both results together.
7. In **Learner progress**, select each learner to see separate evidence and counts for each practiced goal. Refresh or restart the app to verify persistence. Changing a current goal preserves the original goals on existing activities and results.

Activity approval is separate from material approval. Draft activities cannot start a relay, and incomplete relays cannot be evaluated. Confirmed sessions cannot be submitted twice.

## RAG with the shared model

`claude-haiku-5-5` is the generation model in the RAG pipeline. SQLite stores approved document chunks; local keyword ranking selects a primary passage plus up to two supporting chunks from the chosen approved material. This is lexical retrieval, not semantic/vector search, and the chat model does not generate embeddings.

The prompt combines retrieved text with separate mentor/buddy goals and each learner’s latest teacher-confirmed reading observations, when available. It excludes learner aliases and audio. The model drafts a vocabulary task, a comprehension task, a teach-back prompt, vocabulary from the primary passage, and source quotations. The application rejects invented vocabulary, citations to unretrieved chunks, and quotations that do not match source text. It preserves the retrieved context and model name in the draft for attribution.

Teachers must review the generated activity before use. Exact quotations do not guarantee that every model claim is correct. On provider errors or invalid output, the app creates a clearly labeled template fallback rather than presenting it as AI output. Existing template activities remain usable. Speech recognition remains a separate integration.

## Verify

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Tests use temporary databases and cover the complete acceptance journey, restart persistence, direct workspace access, CSRF, institute boundaries, upload errors, PDF page attribution, goal-specific tasks, ordered relay steps, and duplicate evaluation protection. Voice tests cover consent, learner attribution, transcript correction, review, provider errors, and the practice-story approval loop. Provider calls are mocked in automated tests; they do not establish real speech-recognition accuracy.

## Enable English voice analysis and targeted stories

### Gemini voice (current workstation)

The app automatically reads `voice.env` at startup. `GEMINI_API_KEY` (or `GOOGLE_API_KEY`) selects Google Gemini for voice; the current default is `gemini-3.8-flash`, verified as available to the supplied key. `voice.env` is ignored by Git and read only on the server. Its keys are not exported into the story provider configuration. Optional voice-only overrides in this file or the process environment are `PAIRAGRAPH_SPEECH_PROVIDER=gemini`, `PAIRAGRAPH_TRANSCRIPTION_MODEL`, and `PAIRAGRAPH_TRANSCRIPTION_BASE_URL`. Restart the server after changing the file.

Gemini receives audio inline over HTTPS to its official API, using [Google's audio-understanding API](https://ai.google.dev/gemini-api/docs/generate-content/audio). No persistent Google Files upload is created by this integration. The prompt requests verbatim English transcription, preserving repetitions and false starts, without supplying the expected passage. The existing comparison and teacher-review flow then handles possible miscues. This does not constitute acoustic pronunciation scoring.

A live test with a Windows-generated synthetic recording passed: “The garden has a red flower. I can see a little bird.” was transcribed exactly. This verifies connectivity and transcription for that sample, not recognition accuracy across children, accents, noise, or reading difficulties. Learner recordings still require explicit authorization. The app limits remain three-minute browser recordings, 5 MB uploads, and a 300-second provider timeout on this workstation.

RAG and targeted stories continue to use the independently configured `claude-haiku-5-5` shared gateway.

### Shared gateway configuration

The current workstation uses the supplied shared gateway at `http://192.168.106.122:8080/api`, model `claude-haiku-5-5`, chat completions, and a 300-second timeout. Its key is kept in the ignored `instance/ai_config.json`; it is never sent to browser JavaScript or tracked in Git. Environment variables can override the local settings. In SDK code, `os.environ["OPENAI_API_KEY"]` reads a named variable; a literal key is not the variable name.

A live fictional-text generation check passed. The gateway advertised `hackathon-assistant` and `claude-haiku-5-5`; POST to `/audio/transcriptions` returned HTTP 405. Therefore `transcription_enabled` remains false for that gateway, preventing its key from being reused for speech. The separately loaded Gemini key now provides speech transcription.

To use a separate speech service implementing the transcription API, configure these server environment variables before restarting:

```powershell
$env:PAIRAGRAPH_TRANSCRIPTION_BASE_URL = 'https://api.openai.com/v1'
$env:PAIRAGRAPH_TRANSCRIPTION_MODEL = 'gpt-transcribe'
$env:PAIRAGRAPH_SPEECH_API_KEY = [System.Net.NetworkCredential]::new('', (Read-Host 'Speech provider API key' -AsSecureString)).Password
.\.venv\Scripts\python.exe app.py
```

Use a key issued by that speech provider; the shared gateway key is not automatically valid at another provider. The gateway continues to handle stories independently. Optional overrides: `OPENAI_BASE_URL`, `OPENAI_API_KEY`, `PAIRAGRAPH_STORY_MODEL`, `PAIRAGRAPH_STORY_API_STYLE` (`chat_completions` or `responses`), and `PAIRAGRAPH_AI_TIMEOUT`.

### Direct OpenAI setup

Configure an OpenAI API key in the server environment, then restart the app. Do not put the key in source code or browser JavaScript, or send it in chat. In PowerShell, this prompts without echoing the key:

```powershell
$env:OPENAI_API_KEY = [System.Net.NetworkCredential]::new('', (Read-Host 'OpenAI API key' -AsSecureString)).Password
.\.venv\Scripts\python.exe app.py
```

Without workstation overrides, the speech model defaults to `gpt-transcribe` and the story model to `gpt-4o-mini`. Set `OPENAI_BASE_URL=https://api.openai.com/v1`, `PAIRAGRAPH_STORY_API_STYLE=responses`, `PAIRAGRAPH_STORY_MODEL=gpt-4o-mini`, and `PAIRAGRAPH_TRANSCRIPTION_ENABLED=true` when switching this workstation entirely to direct OpenAI. The endpoints follow the official [file-transcription](https://developers.openai.com/api/docs/guides/speech-to-text) and [structured-output](https://developers.openai.com/api/docs/guides/structured-outputs) documentation. Direct Responses requests use `store: false`; compatible chat gateways have their own retention policies. Both paths validate story length, required fields, and target-word repetition locally.

1. Approve an activity and open **Read aloud & analyze** during the relay’s Read step.
2. Select the learner and explicitly confirm authorization. Record just that learner reading the passage, stop, and listen back. You can also upload authorized audio. Recording is limited to three minutes in the browser and 5 MB on the server.
3. Send the audio for transcription. The app compares the recognized words with the reference, suggesting omissions, additions/repetitions, or substitutions. A missing ending is labeled incomplete, rather than automatically treated as an error.
4. Correct recognition mistakes in the transcript, update the comparison, and confirm only observations you actually heard. No suggestions are automatically accepted. The original transcript remains available.
5. Complete the relay and save the separate teacher evaluations. Open each learner’s reading feedback for short coaching steps selected from their confirmed observations.
6. Request a targeted story. Only the approved passage and confirmed observations are sent for generation, not the learner’s identity. The generated English story must have 70–160 words and repeat selected target words; invalid output is rejected.
7. Review or edit the draft, then approve it into the material library. Its original source/page/chunk and adaptation label remain attached. Build the next activity using that approved practice material. Each learner’s progress page links to their own reading attempts.

Recording works on localhost or HTTPS in supported browsers. The microphone starts only after authorization and a user click. Stop, discard, navigation, and the automatic limit release the microphone. The app holds uploads in memory and never saves original audio to disk or the database. Transcripts and teacher-confirmed observations are retained locally; external provider policies govern audio sent to that service.

Without a speech key, the app displays an explicit disconnected state and preserves manual evaluation. It never substitutes fake transcripts or generated stories. Gemini speech passed the synthetic-audio test described above; real learner recognition quality remains to be evaluated. Gateway story generation has been verified separately with fictional text.

## Scope and privacy

The P0 manual workflow and the English voice-to-practice integration are implemented; see [the workload and verification status](PAIRAGRAPH_MVP_WORKLOAD.md). Gemini speech connectivity has been verified with synthetic audio; broad learner accuracy has not been established.

Transcript alignment is not acoustic pronunciation assessment: recognition can hide or introduce mistakes. This version does not score pronunciation, phonemes, prosody, reading pace, or comprehension from voice. Feedback is rule-based coaching tied to teacher-confirmed differences; the model creates the next story. Dedicated pronunciation/fluency assessment and Filipino validation remain future work.

Application records remain scoped to the server-selected teacher’s institute. Login was removed at the user’s request; anyone with access to this local app uses that workspace. The database is local storage, not encrypted storage. Teacher assessments are observations, not proof of measured improvement.

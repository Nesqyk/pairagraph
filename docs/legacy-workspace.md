# Legacy teacher workspace

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


[Back to the project overview](../README.md)

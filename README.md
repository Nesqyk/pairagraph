# Pairagraph

A local, teacher-led paired-reading MVP built with Flask and SQLite. One approved passage supports a mentor vocabulary task, a buddy comprehension task, and a shared teach-back. Teachers assess each learner separately.

## Run locally

Requires Python 3.10 or later. From this directory in PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe app.py
```

Open <http://127.0.0.1:5000>. No AI API key is needed.

The first startup applies `migrations/001_initial.sql` and creates a fictional demo institute:

- Email: `teacher@pairagraph.local`
- Password: `PairagraphDemo!2026`
- Mentor: Maple; buddy: Robin
- Material: **The Seed Library**, an original fictional passage that still requires teacher approval

The database and persistent session secret are created in the ignored `instance/` directory. Learners, approvals, relay steps, and confirmed results survive application restarts. The built-in server and published demo credentials are intended for local evaluation.

## Try the P0 workflow

1. Sign in. In **Learners**, add or edit pseudonyms and choose separate goals.
2. In **Reading pairs**, create a mentor–buddy pair, then select **Build a shared activity**.
3. In **Material library**, review the demo passage or upload a UTF-8 TXT/text-based PDF. Enter source attribution and approve the extracted text. Files are limited to 5 MB; PDFs to 100 pages. Scans need OCR before upload. Only extracted text is retained.
4. In **Build activity**, select the pair and approved material. Optionally enter topic keywords. The app retrieves a passage and shows its document, page, and chunk attribution.
5. Review both goal-specific tasks and approve the activity. Tasks use deterministic templates; the source passage is not rewritten.
6. Guide **Read → Retell → Teach-back**, then record mentor observations, buddy answers, individual ratings, and optional shared notes. Confirm to save both results together.
7. In **Learner progress**, select each learner to see separate evidence and counts for each practiced goal. Refresh or restart the app to verify persistence. Changing a current goal preserves the original goals on existing activities and results.

Activity approval is separate from material approval. Draft activities cannot start a relay, and incomplete relays cannot be evaluated. Confirmed sessions cannot be submitted twice.

## Verify

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Tests use temporary databases and cover the complete acceptance journey, restart persistence, authentication/logout, CSRF, sign-in throttling, institute boundaries, upload errors, PDF page attribution, goal-specific tasks, ordered relay steps, and duplicate evaluation protection.

## Scope and privacy

P0 modules C01–C10 are implemented; see [the workload and verification status](PAIRAGRAPH_MVP_WORKLOAD.md). There is no microphone access, audio storage, speech transcription, automated grading, or external AI provider. Teacher assessments are observations, not proof of measured improvement. P1 and P2 remain future work.

All application data belongs to an institute and is available only to signed-in teachers in that institute. The local MVP seeds one account; institute/account administration is not included. The database is local storage, not encrypted storage.

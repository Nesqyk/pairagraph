"""Reading capture, review, feedback, and a teacher-approved practice-story loop."""
import json

from flask import abort, flash, g, redirect, render_template, request, url_for

from reading_ai import ProviderError, audio_extension, compare_reading, generate_story, guidance, transcribe
from gemini_voice import transcribe_gemini


def register_voice(app, db, owned, activity_info, chunk_text):
    def attempt_info(ident):
        row = dict(owned('reading_attempts', ident))
        row['activity'] = activity_info(row['activity_id'])
        row['learner'] = owned('learners', row['learner_id'])
        row['analysis'] = json.loads(row['analysis'])
        row['confirmed_issues'] = json.loads(row['confirmed_issues'])
        return row

    @app.route('/activities/<int:ident>/voice', methods=['GET', 'POST'])
    def voice_capture(ident):
        act = activity_info(ident)
        if act['status'] == 'draft':
            abort(409, 'Approve the activity before recording a reading.')
        if request.method == 'POST':
            if act['status'] != 'approved' or act['stage'] != 0:
                abort(409, 'Record each learner during the Read step, before moving to Retell.')
            if request.form.get('consent') != 'yes':
                abort(400, 'Teacher authorization is required before sending audio for transcription and saving its text.')
            if request.form.get('role') not in ('mentor', 'buddy'):
                abort(400, 'Choose which learner is reading.')
            if not app.config['SPEECH_API_KEY']:
                abort(503, 'Speech transcription is not connected. Configure a speech-capable endpoint and PAIRAGRAPH_SPEECH_API_KEY on the server.')
            upload = request.files.get('audio')
            if not upload or not upload.filename:
                abort(400, 'Record or choose an audio file first.')
            raw = upload.read(5 * 1024 * 1024 + 1)
            if len(raw) > 5 * 1024 * 1024:
                abort(413, 'Audio must be 5 MB or smaller. Record a shorter reading.')
            try:
                extension = audio_extension(raw, upload.filename)
                provider = app.config['SPEECH_PROVIDER']
                if provider not in ('gemini', 'openai'):
                    raise ProviderError('Choose gemini or openai for the speech provider.')
                speech_call = transcribe_gemini if provider == 'gemini' else transcribe
                text = speech_call(app.config['SPEECH_API_KEY'], app.config['TRANSCRIPTION_MODEL'], raw, extension,
                                  base_url=app.config['TRANSCRIPTION_BASE_URL'], timeout=app.config['AI_TIMEOUT'])
                analysis = compare_reading(act['source']['text'], text)
            except ProviderError as e:
                abort(502, str(e))
            except ValueError as e:
                abort(400, str(e))
            finally:
                # No original file, audio blob, or filename enters the database.
                raw = b''
                upload.close()
            with db():
                # Recheck the relay after the external request; it may have advanced in another tab.
                db().execute('UPDATE activities SET id=id WHERE id=?', (ident,))
                current = db().execute('SELECT status,stage FROM activities WHERE id=?', (ident,)).fetchone()
                if current['status'] != 'approved' or current['stage'] != 0:
                    abort(409, 'The relay advanced while audio was processing. No transcript was saved.')
                attempt_id = db().execute('''INSERT INTO reading_attempts(institute_id,activity_id,learner_id,transcript,
                    reviewed_transcript,analysis,model,language) VALUES (?,?,?,?,?,?,?,?)''',
                    (g.teacher['institute_id'], ident, act['pair'][request.form['role'] + '_id'], text, text,
                     json.dumps(analysis), app.config['TRANSCRIPTION_MODEL'], 'en')).lastrowid
            return redirect(url_for('voice_review', ident=attempt_id))
        attempts = db().execute('''SELECT r.*, l.alias FROM reading_attempts r JOIN learners l ON l.id=r.learner_id
            WHERE r.activity_id=? AND r.institute_id=? ORDER BY r.id DESC''', (ident, g.teacher['institute_id'])).fetchall()
        return render_template('voice_capture.html', activity=act, attempts=attempts, ai_ready=bool(app.config['SPEECH_API_KEY']),
                               ai_timeout=app.config['AI_TIMEOUT'], speech_provider=app.config['SPEECH_PROVIDER'], speech_model=app.config['TRANSCRIPTION_MODEL'])

    @app.route('/voice/<int:ident>', methods=['GET', 'POST'])
    def voice_review(ident):
        attempt = attempt_info(ident)
        if request.method == 'POST':
            if attempt['reviewed']:
                abort(409, 'This review is already confirmed. Make a new reading attempt to record new evidence.')
            if request.form.get('action') == 'correct':
                text = request.form.get('transcript', '').strip()
                if not 1 <= len(text) <= 12000:
                    abort(400, 'A corrected transcript must contain 1–12,000 characters.')
                try:
                    analysis = compare_reading(attempt['activity']['source']['text'], text)
                except ValueError as e:
                    abort(400, str(e))
                with db():
                    db().execute('UPDATE reading_attempts SET reviewed_transcript=?,analysis=? WHERE id=? AND reviewed=0',
                                 (text, json.dumps(analysis), ident))
                flash('Comparison updated. Review the new suggestions before confirming.', 'success')
            elif request.form.get('action') == 'confirm':
                if request.form.get('confirm') != 'yes':
                    abort(400, 'Confirm that you reviewed the transcript and selected observations.')
                # Reject stale comparisons from an older browser tab.
                if request.form.get('reviewed_transcript') != attempt['reviewed_transcript']:
                    abort(409, 'The transcript changed. Refresh and review the current suggestions.')
                selected = request.form.getlist('issue')
                valid = {str(issue['id']): issue for issue in attempt['analysis']['issues']}
                if any(key not in valid for key in selected):
                    abort(400, 'Select valid observations from this reading attempt.')
                confirmed = [valid[key] for key in dict.fromkeys(selected)]
                with db():
                    changed = db().execute('''UPDATE reading_attempts SET reviewed=1,reviewed_by=?,confirmed_issues=?
                        WHERE id=? AND reviewed=0 AND reviewed_transcript=?''',
                        (g.teacher['id'], json.dumps(confirmed), ident, attempt['reviewed_transcript'])).rowcount
                    if not changed:
                        abort(409, 'This review changed. Refresh before continuing.')
                flash('Reading review saved. Feedback uses only the observations you confirmed.', 'success')
            else:
                abort(400, 'Choose a valid review action.')
            return redirect(url_for('voice_review', ident=ident))
        stories = db().execute('SELECT * FROM practice_stories WHERE attempt_id=? AND institute_id=? ORDER BY id DESC',
                              (ident, g.teacher['institute_id'])).fetchall()
        return render_template('voice_review.html', attempt=attempt, tips=guidance(attempt['confirmed_issues']),
                               stories=stories, ai_ready=bool(app.config['OPENAI_API_KEY']))

    @app.post('/voice/<int:ident>/story')
    def voice_story(ident):
        attempt = attempt_info(ident)
        if not attempt['reviewed'] or not attempt['confirmed_issues']:
            abort(409, 'Confirm at least one reading observation before requesting a targeted story.')
        if attempt['activity']['status'] != 'completed':
            abort(409, 'Save the teacher session evaluation before generating the next practice story.')
        if request.form.get('confirm') != 'yes':
            abort(400, 'Confirm sending the approved passage and confirmed observations for story generation.')
        try:
            draft = generate_story(app.config['OPENAI_API_KEY'], app.config['STORY_MODEL'],
                                   attempt['activity']['source']['text'], attempt['confirmed_issues'],
                                   base_url=app.config['OPENAI_BASE_URL'], timeout=app.config['AI_TIMEOUT'], api_style=app.config['STORY_API_STYLE'])
        except ProviderError as e:
            abort(502 if app.config['OPENAI_API_KEY'] else 503, str(e))
        with db():
            story_id = db().execute('''INSERT INTO practice_stories(institute_id,attempt_id,title,story,rationale,targets,model)
                VALUES (?,?,?,?,?,?,?)''', (g.teacher['institute_id'], ident, draft['title'], draft['story'], draft['rationale'],
                                           json.dumps(draft['targets']), app.config['STORY_MODEL'])).lastrowid
        return redirect(url_for('practice_story', ident=story_id))

    @app.route('/practice/<int:ident>', methods=['GET', 'POST'])
    def practice_story(ident):
        story = dict(owned('practice_stories', ident))
        attempt = attempt_info(story['attempt_id'])
        if request.method == 'POST':
            if request.form.get('confirm') != 'yes':
                abort(400, 'Review and approve the adapted story before learners use it.')
            if story['document_id']:
                return redirect(url_for('document', ident=story['document_id']))
            title, text = request.form.get('title', '').strip(), request.form.get('story', '').strip()
            if not 1 <= len(title) <= 160 or not 1 <= len(text) <= 4000:
                abort(400, 'Enter a title (1–160 characters) and story (1–4,000 characters).')
            original = attempt['activity']['source']
            attribution = f'AI-adapted practice ({story["model"]}); teacher reviewed. Based on {original["title"]}, page {original["page_number"]}, chunk {original["chunk_number"]}. Source: {original["source"]}'
            with db():
                # Acquire the write transaction before checking approval again.
                db().execute('UPDATE practice_stories SET id=id WHERE id=?', (ident,))
                current = db().execute('SELECT document_id FROM practice_stories WHERE id=?', (ident,)).fetchone()
                if current['document_id']:
                    return redirect(url_for('document', ident=current['document_id']))
                document_id = db().execute('''INSERT INTO documents(institute_id,title,source,filename,approved,approved_by)
                    VALUES (?,?,?,?,1,?)''', (g.teacher['institute_id'], title, attribution, f'ai-practice-{ident}.txt', g.teacher['id'])).lastrowid
                db().execute('INSERT INTO pages(document_id,page_number,text) VALUES (?,1,?)', (document_id, text))
                for n, chunk in enumerate(chunk_text(text), 1):
                    db().execute('INSERT INTO chunks(document_id,page_number,chunk_number,text) VALUES (?,1,?,?)', (document_id, n, chunk))
                db().execute('UPDATE practice_stories SET document_id=?,title=?,story=? WHERE id=?', (document_id, title, text, ident))
            flash('Practice story approved and added to the library. Build the next activity from this material.', 'success')
            return redirect(url_for('document', ident=document_id))
        story['targets'] = json.loads(story['targets'])
        return render_template('practice_story.html', story=story, attempt=attempt)

    @app.get('/activities/<int:ident>/feedback')
    def reading_feedback(ident):
        act = activity_info(ident)
        attempts = db().execute('''SELECT r.*, l.alias FROM reading_attempts r JOIN learners l ON l.id=r.learner_id
            WHERE r.activity_id=? AND r.institute_id=? ORDER BY r.learner_id,r.id DESC''', (ident, g.teacher['institute_id'])).fetchall()
        return render_template('reading_feedback.html', activity=act, attempts=attempts)

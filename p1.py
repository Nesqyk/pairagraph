"""Teacher review workflows; only explicitly confirmed observations enter results."""
import json
import re
import hashlib
from difflib import SequenceMatcher

from flask import abort, flash, g, jsonify, redirect, render_template, request, url_for

from providers import ProviderError, validate_tasks


AGE_BANDS = ['6–8', '9–11', '12–14', '15–18']


def compare_reading(passage, transcript):
    """Word alignment is a review aid, never a diagnosis or automatic grade."""
    tokenize = lambda text: re.findall(r"\w+(?:['’]\w+)*", text.casefold().replace('’', "'"))
    expected, heard = tokenize(passage), tokenize(transcript)
    flags = []
    for tag, start, end, heard_start, heard_end in SequenceMatcher(None, expected, heard, autojunk=False).get_opcodes():
        if tag == 'equal':
            continue
        flags.append(dict(kind={'delete': 'skip', 'replace': 'substitution', 'insert': 'insertion'}[tag],
                          expected=' '.join(expected[start:end]), heard=' '.join(heard[heard_start:heard_end]),
                          word_start=start + 1, word_end=max(start + 1, end)))
    return flags


def confirmed_flags(db, activity_id):
    return db().execute('''SELECT f.*, t.role, t.learner_id, t.id transcript_id FROM reading_flags f
        JOIN transcripts t ON t.id=f.transcript_id WHERE t.activity_id=? AND t.institute_id=?
        AND t.status='reviewed' AND f.decision='accepted' ORDER BY t.id,f.id''',
        (activity_id, g.teacher['institute_id'])).fetchall()


def register_p1(app, db, owned, pair_info, activity_info, text_field, make_tasks):
    provider = app.extensions['reading_provider']

    def editable(activity):
        if activity['status'] != 'approved':
            abort(409, 'Only an approved, unfinished activity can have reading drafts or reviews changed.')

    def lock_editable(activity_id):
        db().execute('BEGIN IMMEDIATE')
        editable(activity_info(activity_id))

    def version():
        try:
            return int(request.form.get('revision', ''))
        except ValueError:
            abort(400, 'Refresh the review before submitting it.')

    def add_flags(ident, passage, text):
        for flag in compare_reading(passage, text):
            db().execute('''INSERT INTO reading_flags(transcript_id,kind,expected,heard,word_start,word_end)
                VALUES (?,?,?,?,?,?)''', (ident, flag['kind'], flag['expected'], flag['heard'], flag['word_start'], flag['word_end']))

    def save_transcript(activity, role, text, origin='manual', model=''):
        with db():
            lock_editable(activity['id'])
            ident = db().execute('''INSERT INTO transcripts(institute_id,activity_id,learner_id,role,origin,
                provider_model,original_text,text) VALUES (?,?,?,?,?,?,?,?)''',
                (g.teacher['institute_id'], activity['id'], activity['pair'][role + '_id'], role, origin, model, text, text)).lastrowid
            add_flags(ident, activity['source']['text'], text)
        return ident

    @app.route('/activities/<int:ident>/review', methods=['GET', 'POST'])
    def review_activity(ident):
        act = activity_info(ident)
        if act['status'] != 'draft':
            abort(409, 'Approved activities are frozen. Build a new draft to change the tasks.')
        error = None
        values = {key: act['tasks'][key] for key in ('mentor', 'buddy', 'teach_back', 'vocabulary')}
        revision = hashlib.sha256(json.dumps(act['tasks']).encode()).hexdigest()
        if request.method == 'POST':
            if request.form.get('revision') != revision:
                abort(409, 'This draft changed. Refresh before editing it.')
            if request.form.get('action') not in ('save', 'reject'):
                abort(400, 'Choose whether to save or reject the draft.')
            tasks = dict(act['tasks'])
            if request.form.get('action') == 'reject':
                tasks.update(make_tasks(act['source']['text'], act['mentor_goal'], act['buddy_goal']))
                tasks.update(origin='template', adaptation_review='rejected', teacher_edited=False)
            else:
                values = {key: request.form.get(key, '').strip() for key in ('mentor', 'buddy', 'teach_back')}
                values['vocabulary'] = [word.strip() for word in request.form.get('vocabulary', '').split(',') if word.strip()]
                try:
                    tasks.update(validate_tasks(values, act['source']['text']))
                    tasks.update(teacher_edited=True, adaptation_review='edited')
                except ProviderError as exc:
                    error = str(exc)
            if not error:
                with db():
                    changed = db().execute("UPDATE activities SET tasks=? WHERE id=? AND status='draft' AND tasks=?",
                        (json.dumps(tasks), ident, json.dumps(act['tasks']))).rowcount
                    if not changed:
                        abort(409, 'This draft changed in another tab. Refresh and review it again.')
                flash('Draft updated. Review and approve it before learners begin.', 'success')
                return redirect(url_for('activity', ident=ident))
        return render_template('review_activity.html', activity=act, values=values, error=error, revision=revision), 400 if error else 200

    @app.route('/activities/<int:ident>/reading', methods=['GET', 'POST'])
    def reading(ident):
        act = activity_info(ident)
        editable(act)
        if request.method == 'POST':
            role = request.form.get('role')
            if role not in ('mentor', 'buddy'):
                abort(400, 'Choose the learner who read this passage.')
            if request.form.get('confirm') != 'yes':
                abort(400, 'Confirm authorization to save this transcript draft.')
            text = text_field('transcript', 6000)
            tid = save_transcript(act, role, text)
            return redirect(url_for('review_transcript', ident=tid))
        transcripts = db().execute('SELECT * FROM transcripts WHERE activity_id=? AND institute_id=? ORDER BY id DESC',
                                   (ident, g.teacher['institute_id'])).fetchall()
        return render_template('reading.html', activity=act, transcripts=transcripts, provider_ready=provider.transcription_configured)

    @app.post('/activities/<int:ident>/transcribe')
    def transcribe(ident):
        act = activity_info(ident)
        editable(act)
        if request.form.get('authorize') != 'yes' or request.form.get('consent') != 'yes':
            return jsonify(error='Authorize recording and sending this audio before transcription.'), 400
        role = request.form.get('role')
        if role not in ('mentor', 'buddy'):
            return jsonify(error='Choose the learner who is reading.'), 400
        if not provider.transcription_configured:
            return jsonify(error='Transcription is not configured. Enter a manual transcript until a voice provider is connected.'), 503
        upload = request.files.get('audio')
        if not upload:
            return jsonify(error='Record a reading first.'), 400
        mime = upload.mimetype
        if mime not in ('audio/webm', 'audio/ogg', 'audio/mp4', 'audio/wav', 'audio/mpeg'):
            return jsonify(error='This audio format is unsupported. Use WebM, OGG, MP4, WAV or MP3.'), 400
        audio = upload.read(5 * 1024 * 1024 + 1)
        if not 44 <= len(audio) <= 5 * 1024 * 1024:
            return jsonify(error='Use a nonempty recording up to 5 MB. Try a shorter passage.'), 400
        signatures = {'audio/webm': audio.startswith(b'\x1aE\xdf\xa3'), 'audio/ogg': audio.startswith(b'OggS'),
                      'audio/mp4': audio[4:8] == b'ftyp', 'audio/wav': audio.startswith(b'RIFF') and audio[8:12] == b'WAVE',
                      'audio/mpeg': audio.startswith(b'ID3') or audio[:1] == b'\xff'}
        if not signatures[mime]:
            return jsonify(error='The recording does not match its audio format. Record it again.'), 400
        try:
            text = provider.transcribe(audio, mime)
        except ProviderError as exc:
            return jsonify(error=str(exc)), 502
        finally:
            upload.close()
        # Recheck after the provider call in case the session was completed in another tab.
        editable(activity_info(ident))
        tid = save_transcript(act, role, text, 'provider', provider.transcription_model)
        return jsonify(redirect=url_for('review_transcript', ident=tid)), 201

    @app.route('/transcripts/<int:ident>', methods=['GET', 'POST'])
    def review_transcript(ident):
        transcript = owned('transcripts', ident)
        act = activity_info(transcript['activity_id'])
        flags = db().execute('SELECT * FROM reading_flags WHERE transcript_id=? ORDER BY id', (ident,)).fetchall()
        if request.method == 'POST':
            editable(act)
            expected_revision = version()
            if transcript['revision'] != expected_revision:
                abort(409, 'This transcript changed in another tab. Refresh before reviewing it.')
            action = request.form.get('action')
            if action == 'edit':
                text = text_field('transcript', 6000)
                with db():
                    lock_editable(act['id'])
                    changed = db().execute('''UPDATE transcripts SET text=?,status='draft',reviewed_by=NULL,
                        reviewed_at=NULL,revision=revision+1 WHERE id=? AND revision=?''',
                        (text, ident, expected_revision)).rowcount
                    if not changed:
                        abort(409, 'The transcript changed. Refresh and try again.')
                    db().execute('DELETE FROM reading_flags WHERE transcript_id=?', (ident,))
                    add_flags(ident, act['source']['text'], text)
                flash('Transcript saved. All comparison decisions reset and need review.', 'success')
            elif action == 'confirm':
                if request.form.get('confirm') != 'yes':
                    abort(400, 'Confirm that you reviewed the transcript and comparison suggestions.')
                decisions = []
                for flag in flags:
                    decision = request.form.get(f'decision_{flag["id"]}')
                    note = request.form.get(f'note_{flag["id"]}', '').strip()
                    if decision not in ('accepted', 'rejected') or len(note) > 500 or (decision == 'accepted' and not note):
                        abort(400, 'Accept or reject each suggestion. Accepted observations need a teacher-written note (up to 500 characters).')
                    decisions.append((decision, note, flag['id']))
                with db():
                    lock_editable(act['id'])
                    changed = db().execute('''UPDATE transcripts SET status='reviewed',reviewed_by=?,
                        reviewed_at=CURRENT_TIMESTAMP,revision=revision+1 WHERE id=? AND revision=?''',
                        (g.teacher['id'], ident, expected_revision)).rowcount
                    if not changed:
                        abort(409, 'The transcript changed. Refresh and try again.')
                    db().executemany('UPDATE reading_flags SET decision=?,teacher_note=? WHERE id=?', decisions)
                flash('Review confirmed. Accepted teacher notes can be selected during evaluation.', 'success')
            else:
                abort(400, 'Choose a valid review action.')
            return redirect(url_for('review_transcript', ident=ident))
        return render_template('review_transcript.html', transcript=transcript, activity=act, flags=flags)

    @app.post('/transcripts/<int:ident>/delete')
    def delete_transcript(ident):
        transcript = owned('transcripts', ident)
        act = activity_info(transcript['activity_id'])
        if act['status'] == 'completed':
            abort(409, 'A confirmed session preserves its evidence. Drafts can be deleted before session confirmation.')
        if request.form.get('confirm') != 'yes':
            abort(400, 'Confirm transcript deletion.')
        with db():
            lock_editable(act['id'])
            db().execute('DELETE FROM transcripts WHERE id=?', (ident,))
        flash('Transcript and comparison suggestions deleted. The app retained no audio.', 'success')
        return redirect(url_for('reading', ident=transcript['activity_id']))

    @app.get('/pairs/<int:ident>/recommendations')
    def recommendations(ident):
        pair = pair_info(ident)
        histories = {}
        query_terms = []
        for role in ('mentor', 'buddy'):
            result = db().execute('''SELECT r.*, s.created_at,s.activity_id FROM results r JOIN sessions s ON s.id=r.session_id
                WHERE r.learner_id=? AND r.goal=? AND s.institute_id=? ORDER BY s.id DESC LIMIT 1''',
                (pair[role + '_id'], pair[role + '_goal'], g.teacher['institute_id'])).fetchone()
            histories[role] = result
            if result:
                query_terms.extend(re.findall(r'\b[a-z]{5,}\b', result['evidence'].lower()))
        chunks = db().execute('''SELECT c.*,d.title,d.source,d.filename FROM chunks c JOIN documents d ON d.id=c.document_id
            WHERE d.institute_id=? AND d.approved=1 ORDER BY d.id,c.page_number,c.chunk_number''',
            (g.teacher['institute_id'],)).fetchall()
        terms = set(query_terms) - {'words', 'using', 'needed', 'support', 'teacher', 'confirmed', 'reading', 'observation'}
        ranked = sorted(chunks, key=lambda row: -len(terms.intersection(re.findall(r'\w+', row['text'].lower()))))[:3]
        return render_template('recommendations.html', pair=pair, histories=histories, passages=ranked,
                               has_history=any(histories.values()))

    @app.get('/sessions/<int:ident>')
    def session_summary(ident):
        saved = owned('sessions', ident)
        act = activity_info(saved['activity_id'])
        results = db().execute('''SELECT r.*,l.alias FROM results r JOIN learners l ON l.id=r.learner_id
            WHERE r.session_id=? ORDER BY CASE r.role WHEN 'mentor' THEN 0 ELSE 1 END''', (ident,)).fetchall()
        teacher = db().execute('SELECT name FROM teachers WHERE id=?', (saved['teacher_id'],)).fetchone()
        return render_template('session_summary.html', saved=saved, activity=act, results=results, teacher=teacher)

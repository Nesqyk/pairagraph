"""A local student workspace: read, submit, reflect, and choose the next approved story."""
from collections import Counter
from difflib import SequenceMatcher
import json
import os
from pathlib import Path
import re
import secrets

from flask import abort, flash, g, jsonify, redirect, render_template, request, session, url_for

from providers import ProviderError
from reading_ai import audio_extension, compare_reading, generate_story, guidance, words
from gemini_voice import transcribe_gemini
from voice_config import load_voice_env


def highlighted_comparison(reference, transcript):
    pattern = r"\w+(?:['’]\w+)*"
    reference_tokens, heard_tokens = list(re.finditer(pattern, reference)), list(re.finditer(pattern, transcript))
    normalize = lambda token: token.group().casefold().replace('’', "'")
    matcher = SequenceMatcher(None, [normalize(t) for t in reference_tokens], [normalize(t) for t in heard_tokens], autojunk=False)
    def fragment(text, tokens, start, end):
        if start == end:
            return ''
        begin = 0 if start == 0 else tokens[start].start()
        finish = tokens[end].start() if end < len(tokens) else len(text)
        return text[begin:finish]
    result = []
    for kind, start, end, hstart, hend in matcher.get_opcodes():
        result.append(dict(kind=kind, original=fragment(reference, reference_tokens, start, end),
                           heard=fragment(transcript, heard_tokens, hstart, hend)))
    return result


def initialize_student_library(conn, institute_id, chunk_text):
    stories = [
        ('The Little Garden', 'garden', 'Lina found a small patch of soil beside her house. She planted three seeds and gave them a little water each morning. At first, the garden looked empty. Lina waited. One day, a green shoot pushed through the soil. Soon, a red flower opened beside it. A little bird landed on the fence and began to sing. Lina smiled. She did not need a big garden to make a happy place. She only needed a little care, a little patience, and room for things to grow.'),
        ('The Paper Boat', 'boat', 'Noah folded a sheet of blue paper into a little boat. After the rain stopped, he carried it to a shallow stream near his home. The boat moved slowly over the water. A small leaf landed inside, like a tiny passenger. Noah followed it along the path. When the boat reached a fallen branch, he carefully lifted it free. Then he took it home to dry in the sun. That evening, the paper boat sat beside his bed. It was a small boat with a very big adventure.'),
        ('A Light for the Path', 'light', 'Mila and her brother walked home as the sun began to set. They carried a small lantern between them. Its warm light showed the stones on the path. Near the gate, they noticed a kitten hiding under a bush. Mila set down the lantern and waited quietly. The kitten stepped into the light. Her brother found a little bowl of water. Soon, their neighbor came looking for the kitten. She thanked them and smiled. On the way home, Mila held the lantern a little higher. A small light could help more than one traveler.')]
    with conn:
        for title, slug, text in stories:
            filename = f'pairagraph-builtin-{slug}.txt'
            if conn.execute('SELECT 1 FROM documents WHERE institute_id=? AND filename=?', (institute_id, filename)).fetchone():
                continue
            doc = conn.execute('INSERT INTO documents(institute_id,title,source,filename,approved) VALUES (?,?,?,?,1)',
                (institute_id, title, 'Original built-in Pairagraph story, written for reading practice.', filename)).lastrowid
            conn.execute('INSERT INTO pages(document_id,page_number,text) VALUES (?,1,?)', (doc,text))
            for number, part in enumerate(chunk_text(text),1):
                conn.execute('INSERT INTO chunks(document_id,page_number,chunk_number,text) VALUES (?,1,?,?)',(doc,number,part))


def register_student(app, db, owned, chunk_text):
    root = Path(app.root_path)
    voice = load_voice_env(root / 'voice.env')
    provider_file = root / 'instance' / 'ai_config.json'
    settings = json.loads(provider_file.read_text(encoding='utf-8-sig')) if provider_file.exists() else {}
    app.config.setdefault('STUDENT_GEMINI_KEY', os.environ.get('GEMINI_API_KEY') or voice.get('GEMINI_API_KEY') or voice.get('GOOGLE_API_KEY', ''))
    app.config.setdefault('STUDENT_VOICE_MODEL', os.environ.get('PAIRAGRAPH_TRANSCRIPTION_MODEL') or voice.get('PAIRAGRAPH_TRANSCRIPTION_MODEL', 'gemini-3.8-flash'))
    app.config.setdefault('STUDENT_STORY_KEY', os.environ.get('PAIRAGRAPH_AI_KEY') or settings.get('api_key', ''))
    app.config.setdefault('STUDENT_STORY_MODEL', settings.get('story_model', 'claude-haiku-5-5'))
    app.config.setdefault('STUDENT_STORY_BASE', settings.get('base_url', 'https://api.openai.com/v1'))
    app.config.setdefault('STUDENT_STORY_STYLE', settings.get('story_api_style', 'responses'))

    def library():
        return db().execute('''SELECT c.*,d.title,d.source,d.filename FROM chunks c JOIN documents d ON d.id=c.document_id
            WHERE d.institute_id=? AND d.approved=1 ORDER BY d.id,c.page_number,c.chunk_number''', (g.teacher['institute_id'],)).fetchall()

    def learner():
        ident = session.get('student_learner_id')
        if ident:
            row = db().execute('SELECT * FROM learners WHERE id=? AND institute_id=?', (ident, g.teacher['institute_id'])).fetchone()
            if row:
                return row
        return db().execute("SELECT * FROM learners WHERE institute_id=? ORDER BY CASE role WHEN 'buddy' THEN 0 ELSE 1 END,id LIMIT 1",
                            (g.teacher['institute_id'],)).fetchone()

    def reading_info(ident):
        row = dict(owned('student_readings', ident))
        if session.get('student_learner_id') != row['learner_id']:
            abort(404)
        row['learner'] = owned('learners', row['learner_id'])
        row['source'] = db().execute('''SELECT c.*,d.title,d.source,d.filename FROM chunks c JOIN documents d ON d.id=c.document_id
            WHERE c.id=? AND d.institute_id=? AND d.approved=1''', (row['chunk_id'], g.teacher['institute_id'])).fetchone()
        if not row['source']:
            abort(404)
        row['analysis'] = json.loads(row['flags']) if row['flags'] != '[]' else {'issues': []}
        row['draft'] = json.loads(row['next_draft']) if row['next_draft'] else None
        return row

    def save_analysis(reading, text, origin):
        analysis = compare_reading(reading['source']['text'], text)
        with db():
            changed = db().execute('''UPDATE student_readings SET status='analyzed',transcript=?,origin=?,flags=?,analyzed_at=CURRENT_TIMESTAMP
                WHERE id=? AND status='reading' ''', (text, origin, json.dumps(analysis), reading['id'])).rowcount
            if not changed:
                abort(409, 'This reading has already been submitted. Open its analysis to continue.')

    @app.get('/student')
    def student_home():
        selected = learner()
        learners = db().execute('SELECT * FROM learners WHERE institute_id=? ORDER BY alias', (g.teacher['institute_id'],)).fetchall()
        passages = library()
        recent = db().execute('''SELECT r.*,d.title FROM student_readings r JOIN chunks c ON c.id=r.chunk_id JOIN documents d ON d.id=c.document_id
            WHERE r.institute_id=? AND r.learner_id=? AND r.status='analyzed' ORDER BY r.id DESC LIMIT 3''',
            (g.teacher['institute_id'], selected['id'])).fetchall() if selected else []
        return render_template('student/home.html', learner=selected, learners=learners, featured=passages[0] if passages else None,
                               recent=recent, nav='home', voice_ready=bool(app.config['STUDENT_GEMINI_KEY']))

    @app.post('/student/start')
    def student_start():
        try:
            learner_id = int(request.form.get('learner_id', ''))
        except ValueError:
            abort(400, 'Choose a reader before starting.')
        selected = owned('learners', learner_id)
        passages = library()
        if not passages:
            flash('No reading stories are available yet. Please try again shortly.', 'error')
            return redirect(url_for('student_home'))
        requested = request.form.get('chunk_id', type=int)
        chosen = next((p for p in passages if p['id'] == requested), None) if requested else passages[0]
        if not chosen:
            abort(404)
        with db():
            ident = db().execute('INSERT INTO student_readings(institute_id,learner_id,chunk_id) VALUES (?,?,?)',
                (g.teacher['institute_id'], selected['id'], chosen['id'])).lastrowid
        session['student_learner_id'] = selected['id']
        return redirect(url_for('student_reading', ident=ident))

    @app.get('/student/reading/<int:ident>')
    def student_reading(ident):
        reading = reading_info(ident)
        if reading['status'] == 'analyzed':
            return redirect(url_for('student_analysis', ident=ident))
        return render_template('student/reading.html', reading=reading, learner=reading['learner'], nav='reading',
                               voice_ready=bool(app.config['STUDENT_GEMINI_KEY']), word_count=len(words(reading['source']['text'])))

    @app.post('/student/reading/<int:ident>/submit')
    def student_submit(ident):
        reading = reading_info(ident)
        if reading['status'] != 'reading':
            return jsonify(error='This reading is already submitted.', redirect=url_for('student_analysis', ident=ident)), 409
        if request.form.get('consent') != 'yes':
            return jsonify(error='Confirm that you agree to process the recording and save its transcript.'), 400
        text = request.form.get('transcript', '').strip()
        upload = request.files.get('audio')
        origin = 'manual'
        try:
            if upload:
                if not app.config['STUDENT_GEMINI_KEY']:
                    return jsonify(error='Voice analysis is not connected. You can use a manual transcript instead.'), 503
                audio = upload.read(5 * 1024 * 1024 + 1)
                try:
                    if not 1 <= len(audio) <= 5 * 1024 * 1024:
                        return jsonify(error='Choose a nonempty audio file up to 5 MB.'), 413
                    extension = audio_extension(audio, upload.filename or '')
                    text = transcribe_gemini(app.config['STUDENT_GEMINI_KEY'], app.config['STUDENT_VOICE_MODEL'], audio, extension, timeout=300)
                finally:
                    audio = b''
                    upload.close()
                origin = 'gemini'
            if not 1 <= len(text) <= 12000:
                return jsonify(error='Record a reading or enter a manual transcript of up to 12,000 characters.'), 400
            save_analysis(reading, text, origin)
        except ProviderError as error:
            return jsonify(error=str(error)), 502
        except ValueError as error:
            return jsonify(error=str(error)), 400
        return jsonify(redirect=url_for('student_analysis', ident=ident)), 201

    @app.get('/student/analysis/<int:ident>')
    def student_analysis(ident):
        reading = reading_info(ident)
        if reading['status'] != 'analyzed':
            return redirect(url_for('student_reading', ident=ident))
        issues = reading['analysis']['issues']
        targets = list(dict.fromkeys(w for issue in issues for w in words(issue['expected']) if len(w)>2))[:8]
        return render_template('student/analysis.html', reading=reading, learner=reading['learner'], nav='reading', issues=issues,
            comparison=highlighted_comparison(reading['source']['text'], reading['transcript']), targets=targets, tips=guidance(issues), story_ready=bool(app.config['STUDENT_STORY_KEY']))

    def publish_story(reading, draft):
        source, ident = reading['source'], reading['id']
        with db():
            db().execute('UPDATE student_readings SET id=id WHERE id=?', (ident,))
            current = db().execute('SELECT next_draft FROM student_readings WHERE id=?', (ident,)).fetchone()[0]
            if current:
                return
            attribution = f'AI-generated practice adapted from {source["title"]}, page {source["page_number"]}, passage {source["chunk_number"]}. {source["source"]}'
            doc = db().execute('INSERT INTO documents(institute_id,title,source,filename,approved) VALUES (?,?,?,?,1)',
                (g.teacher['institute_id'],draft['title'],attribution,f'student-practice-{ident}.txt')).lastrowid
            db().execute('INSERT INTO pages(document_id,page_number,text) VALUES (?,1,?)',(doc,draft['story']))
            next_chunk = None
            for n,part in enumerate(chunk_text(draft['story']),1):
                chunk = db().execute('INSERT INTO chunks(document_id,page_number,chunk_number,text) VALUES (?,1,?,?)',(doc,n,part)).lastrowid
                next_chunk = next_chunk or chunk
            draft['ready'] = True
            db().execute("UPDATE student_readings SET next_draft=?,next_chunk_id=?,next_kind='generated' WHERE id=?",(json.dumps(draft),next_chunk,ident))

    @app.route('/student/next/<int:ident>', methods=['GET','POST'])
    def student_next(ident):
        reading = reading_info(ident)
        if reading['status'] != 'analyzed':
            return redirect(url_for('student_reading', ident=ident))
        issues = reading['analysis']['issues']
        if request.method == 'POST':
            if not issues or not app.config['STUDENT_STORY_KEY'] or reading['draft']:
                return redirect(url_for('student_next', ident=ident))
            if request.form.get('consent') != 'yes':
                abort(400, 'Confirm creating a practice story from the passage and possible reading differences.')
            try:
                draft = generate_story(app.config['STUDENT_STORY_KEY'], app.config['STUDENT_STORY_MODEL'], reading['source']['text'], issues,
                    base_url=app.config['STUDENT_STORY_BASE'], timeout=300, api_style=app.config['STUDENT_STORY_STYLE'])
                publish_story(reading, draft)
                return redirect(url_for('student_next', ident=ident))
            except ProviderError as error:
                flash(str(error) + ' You can still practice with a library passage below.', 'error')
        passages = library()
        target_words = set(w for issue in issues for w in words(issue['expected']) if len(w)>2)
        candidates = [p for p in passages if p['id'] != reading['chunk_id']]
        if not reading['next_chunk_id']:
            if issues:
                ranked = sorted(candidates, key=lambda p: len(target_words & set(words(p['text']))), reverse=True)
                candidate = ranked[0] if ranked and target_words & set(words(ranked[0]['text'])) else reading['source']
                kind = 'targeted' if candidate['id'] != reading['chunk_id'] else 'reread'
            else:
                candidate = secrets.choice(candidates) if candidates else reading['source']
                kind = 'random' if candidates else 'reread'
            with db():
                db().execute("UPDATE student_readings SET next_chunk_id=?,next_kind=? WHERE id=? AND next_chunk_id IS NULL AND next_kind!='generated'",
                             (candidate['id'],kind,ident))
            reading = reading_info(ident)
        chosen = next((p for p in passages if p['id']==reading['next_chunk_id']), reading['source'])
        return render_template('student/next.html', reading=reading, learner=reading['learner'], nav='reading', chosen=chosen,
            has_issues=bool(issues), targets=list(target_words)[:8], story_ready=bool(app.config['STUDENT_STORY_KEY']))

    @app.get('/student/progress')
    def student_progress():
        selected = learner()
        readings = db().execute('''SELECT r.*,d.title FROM student_readings r JOIN chunks c ON c.id=r.chunk_id JOIN documents d ON d.id=c.document_id
            WHERE r.institute_id=? AND r.learner_id=? AND r.status='analyzed' ORDER BY r.id DESC''',
            (g.teacher['institute_id'],selected['id'])).fetchall() if selected else []
        counts = Counter()
        for item in readings:
            issues = json.loads(item['flags']).get('issues',[])
            counts.update(set(w for issue in issues if issue['kind'] != 'Unheard ending / incomplete reading'
                              for w in words(issue['expected']) if len(w)>2))
        return render_template('student/progress.html',learner=selected,readings=readings,
                               difficult=counts.most_common(10),recurring=sum(1 for n in counts.values() if n>1),nav='progress')

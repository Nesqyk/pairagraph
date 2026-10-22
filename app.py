"""Pairagraph: teacher-led paired reading and reviewed adaptations, backed by SQLite."""
from __future__ import annotations

import io
import json
import os
from pathlib import Path
import re
import secrets
import sqlite3
from datetime import timedelta

from flask import Flask, Request, abort, flash, g, redirect, render_template, request, session, url_for
from pypdf import PdfReader
from werkzeug.security import generate_password_hash
from werkzeug.exceptions import HTTPException

from providers import OpenAIProvider, ProviderError
from p1 import AGE_BANDS, confirmed_flags, register_p1
from student import initialize_student_library, register_student
from voice_config import load_voice_env
from voice_routes import register_voice
from rag import generate_rag_activity

ROOT = Path(__file__).resolve().parent
GOALS = {
    'mentor': ['Explain word meanings', 'Use context clues', 'Teach vocabulary clearly'],
    'buddy': ['Find key details', 'Retell in sequence', 'Make supported inferences'],
}
RATINGS = ['Needs support', 'Practicing', 'Demonstrated']
SAMPLE = '''The Seed Library

Every Saturday, Mina and her brother Leo visited the community garden. One morning, they found a small wooden cabinet beside the gate. Inside were envelopes filled with seeds. A sign said, "Take a few seeds. Grow a plant. Bring back seeds to share."

Leo wanted to take every envelope. Mina explained that the seeds were a shared resource. If they took only what they needed, other neighbors could grow plants too. They chose bean seeds because the gardener said beans grew quickly in warm soil.

At home, they planted the seeds near a sunny window. Leo watered them each morning, while Mina checked that the soil was damp but not flooded. For several days, nothing seemed to happen. Leo felt impatient. Mina reminded him that roots could be growing beneath the surface.

On the sixth morning, a green shoot appeared. The children measured it carefully and wrote down its height. Weeks later, their plants produced beans. They saved some seeds in a paper envelope and returned them to the cabinet. The seed library now had something new to offer, and Leo understood why sharing a little could help a whole community grow.'''


def db():
    if 'db' not in g:
        g.db = sqlite3.connect(g.app_db, timeout=10)
        g.db.row_factory = sqlite3.Row
        g.db.execute('PRAGMA foreign_keys=ON')
    return g.db


class MemoryUploadRequest(Request):
    # Flask normally spools larger uploads to disk. Keep opt-in audio in RAM only.
    def _get_file_stream(self, total_content_length, content_type, filename=None, content_length=None):
        return io.BytesIO()


def create_app(test_config=None):
    app = Flask(__name__)
    app.request_class = MemoryUploadRequest
    instance = Path(app.instance_path)
    instance.mkdir(exist_ok=True)
    keyfile = instance / 'secret.key'
    if not keyfile.exists():
        try:
            with keyfile.open('x') as f:
                f.write(secrets.token_hex(32))
        except FileExistsError:
            pass
    # Optional workstation configuration is ignored by Git and never sent to the browser.
    config_path = instance / 'ai_config.json'
    ai_local = json.loads(config_path.read_text(encoding='utf-8')) if config_path.exists() else {}
    voice_local = load_voice_env(ROOT / 'voice.env')
    base_url = os.environ.get('OPENAI_BASE_URL') or ai_local.get('base_url', 'https://api.openai.com/v1')
    api_key = os.environ.get('OPENAI_API_KEY') or ai_local.get('api_key', '')
    speech_enabled = os.environ.get('PAIRAGRAPH_TRANSCRIPTION_ENABLED', str(ai_local.get('transcription_enabled', True))).lower() in ('1', 'true', 'yes')
    gemini_key = os.environ.get('GEMINI_API_KEY') or os.environ.get('GOOGLE_API_KEY') or voice_local.get('GEMINI_API_KEY') or voice_local.get('GOOGLE_API_KEY', '')
    speech_provider = os.environ.get('PAIRAGRAPH_SPEECH_PROVIDER') or voice_local.get('PAIRAGRAPH_SPEECH_PROVIDER') or ('gemini' if gemini_key else 'openai')
    speech_base = 'https://generativelanguage.googleapis.com/v1beta' if speech_provider == 'gemini' else ai_local.get('transcription_base_url', base_url)
    speech_key = gemini_key if speech_provider == 'gemini' else (voice_local.get('OPENAI_API_KEY') or (api_key if speech_enabled else ''))
    app.config.update(
        SECRET_KEY=os.environ.get('PAIRAGRAPH_SECRET') or keyfile.read_text(),
        DATABASE=str(instance / 'pairagraph.sqlite3'), MAX_CONTENT_LENGTH=6 * 1024 * 1024,
        LOCAL_TEACHER_ID=1,
        OPENAI_API_KEY=api_key,
        OPENAI_BASE_URL=base_url,
        AI_TIMEOUT=int(os.environ.get('PAIRAGRAPH_AI_TIMEOUT', ai_local.get('timeout', 90))),
        STORY_API_STYLE=os.environ.get('PAIRAGRAPH_STORY_API_STYLE', ai_local.get('story_api_style', 'responses')),
        SPEECH_PROVIDER=speech_provider,
        TRANSCRIPTION_BASE_URL=os.environ.get('PAIRAGRAPH_TRANSCRIPTION_BASE_URL') or voice_local.get('PAIRAGRAPH_TRANSCRIPTION_BASE_URL') or speech_base,
        SPEECH_API_KEY=os.environ.get('PAIRAGRAPH_SPEECH_API_KEY') or voice_local.get('PAIRAGRAPH_SPEECH_API_KEY') or speech_key,
        TRANSCRIPTION_MODEL=os.environ.get('PAIRAGRAPH_TRANSCRIPTION_MODEL') or voice_local.get('PAIRAGRAPH_TRANSCRIPTION_MODEL') or ('gemini-3.8-flash' if speech_provider == 'gemini' else 'gpt-transcribe'),
        STORY_MODEL=os.environ.get('PAIRAGRAPH_STORY_MODEL', ai_local.get('story_model', 'gpt-4o-mini')),
        SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE='Lax',
        SESSION_COOKIE_SECURE=os.environ.get('PAIRAGRAPH_HTTPS') == '1',
        PERMANENT_SESSION_LIFETIME=timedelta(hours=8),
    )
    if test_config:
        app.config.update(test_config)
    provider_file = instance / 'provider.json'
    local_provider = json.loads(provider_file.read_text(encoding='utf-8-sig')) if provider_file.exists() else {}
    app.extensions['reading_provider'] = app.config.get('READING_PROVIDER') or OpenAIProvider(
        api_key=os.environ.get('PAIRAGRAPH_AI_KEY') or os.environ.get('OPENAI_API_KEY') or local_provider.get('api_key') or app.config['OPENAI_API_KEY'],
        model=os.environ.get('PAIRAGRAPH_AI_MODEL') or local_provider.get('model') or app.config['STORY_MODEL'],
        base_url=os.environ.get('PAIRAGRAPH_AI_BASE_URL') or local_provider.get('base_url') or app.config['OPENAI_BASE_URL'],
        api_mode=os.environ.get('PAIRAGRAPH_AI_MODE') or local_provider.get('api_mode') or ('chat' if app.config['STORY_API_STYLE']=='chat_completions' else 'responses'),
        transcription_url=os.environ.get('PAIRAGRAPH_STT_URL') or local_provider.get('transcription_url', ''),
        transcription_model=os.environ.get('PAIRAGRAPH_STT_MODEL') or local_provider.get('transcription_model', 'gpt-transcribe'),
        transcription_key=os.environ.get('PAIRAGRAPH_STT_KEY') or local_provider.get('transcription_key', ''),
        timeout=app.config['AI_TIMEOUT'],
    )

    @app.before_request
    def prepare():
        g.app_db = app.config['DATABASE']
        # This local workspace uses one server-selected teacher; no login is needed.
        g.teacher = db().execute('SELECT * FROM teachers WHERE id=?', (app.config['LOCAL_TEACHER_ID'],)).fetchone()
        if not g.teacher:
            abort(503, 'The local teacher workspace is not configured.')
        if 'csrf' not in session:
            session['csrf'] = secrets.token_hex(32)
        if request.method == 'POST':
            token = request.form.get('csrf', '')
            if not secrets.compare_digest(token.encode('utf-8'), session['csrf'].encode('utf-8')):
                abort(400, 'Your form expired. Refresh the page and try again.')

    @app.after_request
    def headers(response):
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'DENY'
        response.headers['Referrer-Policy'] = 'same-origin'
        response.headers['Content-Security-Policy'] = "default-src 'self'; style-src 'self'; script-src 'self'; img-src 'self' data:; media-src 'self' blob:; frame-ancestors 'none'; form-action 'self'"
        can_record = request.endpoint in ('reading', 'student_reading') or (request.endpoint == 'voice_capture' and app.config['SPEECH_API_KEY'])
        response.headers['Permissions-Policy'] = 'microphone=(self), camera=()' if can_record else 'microphone=(), camera=()'
        response.headers['Cache-Control'] = 'no-store'
        return response

    @app.teardown_appcontext
    def close_db(error):
        conn = g.pop('db', None)
        if conn is not None:
            conn.close()

    @app.context_processor
    def context():
        return dict(goals=GOALS, ratings=RATINGS, age_bands=AGE_BANDS,
                    provider_ready=app.extensions['reading_provider'].configured)

    @app.errorhandler(HTTPException)
    def error(e):
        return render_template('student/error.html' if request.path.startswith('/student') else 'error.html', error=e), e.code

    def owned(table, ident):
        # Table names are internal constants; identifiers and tenants are bound parameters.
        row = db().execute(f'SELECT * FROM {table} WHERE id=? AND institute_id=?',
                           (ident, g.teacher['institute_id'])).fetchone()
        if not row:
            abort(404)
        return row

    def text_field(name, maximum=1000, minimum=1):
        value = request.form.get(name, '').strip()
        if len(value) < minimum or len(value) > maximum:
            abort(400, f'{name.replace("_", " ").capitalize()} must contain {minimum}–{maximum} characters.')
        return value

    def choice(name, choices):
        value = request.form.get(name, '')
        if value not in choices:
            abort(400, f'Choose a valid {name.replace("_", " ")}.')
        return value

    def number(name):
        try:
            return int(request.form.get(name, ''))
        except ValueError:
            abort(400, f'Choose a valid {name.replace("_", " ")}.')

    def pair_info(ident):
        owned('pairs', ident)
        return db().execute('''SELECT p.*, m.alias mentor, b.alias buddy, m.goal mentor_goal, b.goal buddy_goal
            FROM pairs p JOIN learners m ON m.id=p.mentor_id JOIN learners b ON b.id=p.buddy_id WHERE p.id=?''', (ident,)).fetchone()

    def activity_info(ident):
        activity = dict(owned('activities', ident))
        activity['tasks'] = json.loads(activity['tasks'])
        activity['pair'] = pair_info(activity['pair_id'])
        activity['source'] = db().execute('''SELECT c.*, d.title, d.source, d.filename FROM chunks c
             JOIN documents d ON d.id=c.document_id WHERE c.id=? AND d.institute_id=?''',
             (activity['chunk_id'], g.teacher['institute_id'])).fetchone()
        return activity

    @app.get('/login')
    def login():
        # Keep old bookmarks working without showing a sign-in screen.
        return redirect(url_for('dashboard'))

    @app.get('/')
    def home():
        return app.view_functions['student_home']()

    @app.get('/workspace')
    def dashboard():
        tenant = g.teacher['institute_id']
        counts = {table: db().execute(f'SELECT count(*) FROM {table} WHERE institute_id=?', (tenant,)).fetchone()[0]
                  for table in ['learners', 'pairs', 'sessions']}
        counts['documents'] = db().execute('SELECT count(*) FROM documents WHERE institute_id=? AND approved=1', (tenant,)).fetchone()[0]
        activities = db().execute('''SELECT a.*, m.alias mentor, b.alias buddy, d.title FROM activities a
            JOIN pairs p ON p.id=a.pair_id JOIN learners m ON m.id=p.mentor_id JOIN learners b ON b.id=p.buddy_id
            JOIN chunks c ON c.id=a.chunk_id JOIN documents d ON d.id=c.document_id
            WHERE a.institute_id=? ORDER BY a.id DESC LIMIT 8''', (tenant,)).fetchall()
        return render_template('dashboard.html', counts=counts, activities=activities)

    @app.route('/learners', methods=['GET', 'POST'])
    def learners():
        if request.method == 'POST':
            alias = text_field('alias', 60)
            role = choice('role', GOALS)
            goal = choice('goal', GOALS[role])
            try:
                with db():
                    db().execute('INSERT INTO learners(institute_id,alias,role,goal) VALUES (?,?,?,?)',
                                 (g.teacher['institute_id'], alias, role, goal))
            except sqlite3.IntegrityError:
                abort(400, 'That pseudonym is already used in your institute. Choose another.')
            flash('Learner added.', 'success')
            return redirect(url_for('learners'))
        rows = db().execute('SELECT * FROM learners WHERE institute_id=? ORDER BY alias', (g.teacher['institute_id'],)).fetchall()
        return render_template('learners.html', learners=rows)

    @app.route('/learners/<int:ident>/edit', methods=['GET', 'POST'])
    def edit_learner(ident):
        learner = owned('learners', ident)
        if request.method == 'POST':
            alias = text_field('alias', 60)
            goal = choice('goal', GOALS[learner['role']])
            try:
                with db():
                    db().execute('UPDATE learners SET alias=?,goal=? WHERE id=?', (alias, goal, ident))
            except sqlite3.IntegrityError:
                abort(400, 'That pseudonym is already used in your institute.')
            flash('Learner updated. Existing activities and results keep their original goals.', 'success')
            return redirect(url_for('learners'))
        return render_template('edit_learner.html', learner=learner)

    @app.route('/pairs', methods=['GET', 'POST'])
    def pairs():
        if request.method == 'POST':
            mentor = owned('learners', number('mentor_id'))
            buddy = owned('learners', number('buddy_id'))
            if mentor['role'] != 'mentor' or buddy['role'] != 'buddy' or mentor['id'] == buddy['id']:
                abort(400, 'Select one mentor and one different buddy.')
            with db():
                db().execute('INSERT OR IGNORE INTO pairs(institute_id,mentor_id,buddy_id) VALUES (?,?,?)',
                             (g.teacher['institute_id'], mentor['id'], buddy['id']))
            flash('Pair ready for a shared reading activity.', 'success')
            return redirect(url_for('pairs'))
        rows = db().execute('''SELECT p.*, m.alias mentor, b.alias buddy, m.goal mentor_goal, b.goal buddy_goal
            FROM pairs p JOIN learners m ON m.id=p.mentor_id JOIN learners b ON b.id=p.buddy_id
            WHERE p.institute_id=? ORDER BY p.id DESC''', (g.teacher['institute_id'],)).fetchall()
        learners = db().execute('SELECT * FROM learners WHERE institute_id=? ORDER BY alias', (g.teacher['institute_id'],)).fetchall()
        return render_template('pairs.html', pairs=rows, learners=learners)

    @app.route('/library', methods=['GET', 'POST'])
    def library():
        if request.method == 'POST':
            title = text_field('title', 160)
            source = text_field('source', 500)
            upload = request.files.get('file')
            if not upload or not upload.filename:
                abort(400, 'Choose a UTF-8 TXT or text-based PDF file.')
            filename = upload.filename.replace('\\', '/').split('/')[-1][:200]
            raw = upload.read(5 * 1024 * 1024 + 1)
            if len(raw) > 5 * 1024 * 1024:
                abort(413, 'The file must be 5 MB or smaller.')
            extracted = extract_pages(raw, filename)
            with db():
                ident = db().execute('INSERT INTO documents(institute_id,title,source,filename) VALUES (?,?,?,?)',
                    (g.teacher['institute_id'], title, source, filename)).lastrowid
                db().executemany('INSERT INTO pages(document_id,page_number,text) VALUES (?,?,?)',
                                 [(ident, n, text) for n, text in extracted])
            flash('Text extracted. Review the pages before approving this material.', 'success')
            return redirect(url_for('document', ident=ident))
        documents = db().execute('SELECT * FROM documents WHERE institute_id=? ORDER BY id DESC', (g.teacher['institute_id'],)).fetchall()
        return render_template('library.html', documents=documents)

    @app.get('/library/<int:ident>')
    def document(ident):
        doc = owned('documents', ident)
        pages = [dict(page, readable=has_readable_text(page['text'])) for page in
                 db().execute('SELECT * FROM pages WHERE document_id=? ORDER BY page_number', (ident,)).fetchall()]
        return render_template('document.html', doc=doc, pages=pages)

    @app.post('/library/<int:ident>/approve')
    def approve_document(ident):
        doc = owned('documents', ident)
        if request.form.get('confirm') != 'yes':
            abort(400, 'Confirm that you reviewed this content and its source.')
        if not doc['approved']:
            with db():
                # Conditional update prevents duplicate indexing on concurrent approval.
                changed = db().execute('UPDATE documents SET approved=1,approved_by=? WHERE id=? AND approved=0',
                                       (g.teacher['id'], ident)).rowcount
                if changed:
                    pages = db().execute('SELECT * FROM pages WHERE document_id=? ORDER BY page_number', (ident,)).fetchall()
                    for page in pages:
                        if not has_readable_text(page['text']):
                            continue
                        for n, passage in enumerate(chunk_text(page['text']), 1):
                            if not has_readable_text(passage):
                                continue
                            db().execute('INSERT INTO chunks(document_id,page_number,chunk_number,text) VALUES (?,?,?,?)',
                                         (ident, page['page_number'], n, passage))
        flash('Material approved and indexed for activities.', 'success')
        return redirect(url_for('document', ident=ident))

    @app.route('/activities/new', methods=['GET', 'POST'])
    def new_activity():
        if request.method == 'POST':
            pair = pair_info(number('pair_id'))
            doc = owned('documents', number('document_id'))
            if not doc['approved']:
                abort(400, 'Only approved reading materials can be used.')
            query = text_field('query', 200, 0)
            chunks = db().execute('SELECT * FROM chunks WHERE document_id=? ORDER BY page_number,chunk_number', (doc['id'],)).fetchall()
            if not chunks:
                abort(400, 'This material has no readable passages.')
            chunk = retrieve(chunks, query)
            selected_chunk = request.form.get('chunk_id', '')
            if selected_chunk:
                chunk = next((row for row in chunks if str(row['id']) == selected_chunk), None)
                if chunk is None:
                    abort(400, 'Choose a passage from the selected approved material.')
            tasks = make_tasks(chunk['text'], pair['mentor_goal'], pair['buddy_goal'])
            tasks['origin'] = 'template'
            tasks['generation'] = 'template'
            if request.form.get('use_rag') == 'yes' or (request.form.get('use_ai') == 'yes' and not request.form.get('age_band')):
                context_rows = sorted(chunks, key=lambda row: keyword_score(row['text'], query), reverse=True)[:3]
                context = [dict(chunk_id=row['id'], document_id=doc['id'], title=doc['title'], source=doc['source'],
                                page=row['page_number'], chunk=row['chunk_number'], text=row['text']) for row in context_rows]
                observations = {}
                for role in ['mentor', 'buddy']:
                    reviewed = db().execute('''SELECT confirmed_issues FROM reading_attempts
                        WHERE institute_id=? AND learner_id=? AND reviewed=1 ORDER BY id DESC LIMIT 1''',
                        (g.teacher['institute_id'], pair[role + '_id'])).fetchone()
                    observations[role] = json.loads(reviewed['confirmed_issues']) if reviewed else []
                try:
                    tasks = generate_rag_activity(app.config['OPENAI_API_KEY'], app.config['STORY_MODEL'], context, chunk['id'],
                        pair['mentor_goal'], pair['buddy_goal'], observations, base_url=app.config['OPENAI_BASE_URL'],
                        timeout=app.config['AI_TIMEOUT'], api_style=app.config['STORY_API_STYLE'])
                except ProviderError as e:
                    tasks['generation'] = 'template-fallback'
                    flash(f'{e} This draft uses templates, not AI. Review it before use.', 'error')
            if request.form.get('use_ai') == 'yes' and request.form.get('age_band') and request.form.get('use_rag') != 'yes':
                age_band = choice('age_band', AGE_BANDS)
                try:
                    adapted = app.extensions['reading_provider'].adapt(chunk['text'], pair['mentor_goal'], pair['buddy_goal'], age_band)
                    tasks.update(adapted)
                    tasks.update(origin='ai', age_band=age_band, model=app.extensions['reading_provider'].model,
                                 generated_tasks=adapted.copy())
                except ProviderError as exc:
                    tasks['fallback_reason'] = str(exc)
                    flash(str(exc) + ' A template draft was created for teacher review.', 'error')
            tasks['query'] = query
            tasks['retrieval_note'] = ('Keyword match' if query and keyword_score(chunk['text'], query) else
                                       'First passage (no keyword match)' if query else 'First passage (no topic specified)')
            if selected_chunk:
                tasks['retrieval_note'] = 'Teacher-selected recommended passage'
            with db():
                ident = db().execute('''INSERT INTO activities(institute_id,pair_id,chunk_id,mentor_goal,buddy_goal,tasks)
                    VALUES (?,?,?,?,?,?)''', (g.teacher['institute_id'], pair['id'], chunk['id'], pair['mentor_goal'],
                                             pair['buddy_goal'], json.dumps(tasks))).lastrowid
            return redirect(url_for('activity', ident=ident))
        pairs = db().execute('''SELECT p.id, m.alias mentor, b.alias buddy FROM pairs p JOIN learners m ON m.id=p.mentor_id
            JOIN learners b ON b.id=p.buddy_id WHERE p.institute_id=?''', (g.teacher['institute_id'],)).fetchall()
        docs = db().execute('SELECT * FROM documents WHERE institute_id=? AND approved=1', (g.teacher['institute_id'],)).fetchall()
        return render_template('new_activity.html', pairs=pairs, documents=docs, selected=request.args.get('pair', type=int))

    @app.get('/activities/<int:ident>')
    def activity(ident):
        act = activity_info(ident)
        saved = db().execute('SELECT id FROM sessions WHERE activity_id=? AND institute_id=?',
                             (ident, g.teacher['institute_id'])).fetchone()
        return render_template('activity.html', activity=act, saved=saved)

    @app.post('/activities/<int:ident>/approve')
    def approve_activity(ident):
        owned('activities', ident)
        if request.form.get('confirm') != 'yes':
            abort(400, 'Review the passage and both tasks, then confirm approval.')
        with db():
            db().execute("UPDATE activities SET status='approved',approved_by=? WHERE id=? AND status='draft'", (g.teacher['id'], ident))
        return redirect(url_for('relay', ident=ident))

    @app.route('/activities/<int:ident>/relay', methods=['GET', 'POST'])
    def relay(ident):
        act = activity_info(ident)
        if act['status'] == 'draft':
            abort(400, 'The teacher must approve this activity before learners begin.')
        if act['status'] == 'completed':
            return redirect(url_for('activity', ident=ident))
        if request.method == 'POST':
            stage = number('stage')
            if stage != act['stage'] or stage >= 3:
                abort(409, 'This step has already changed. Refresh to continue.')
            with db():
                changed = db().execute('UPDATE activities SET stage=stage+1 WHERE id=? AND stage=? AND status=\'approved\'', (ident, stage)).rowcount
                if not changed:
                    abort(409, 'This step has already changed. Refresh to continue.')
            return redirect(url_for('relay', ident=ident))
        return render_template('relay.html', activity=act)

    @app.route('/activities/<int:ident>/evaluate', methods=['GET', 'POST'])
    def evaluate(ident):
        act = activity_info(ident)
        reviewed_flags = confirmed_flags(db, ident)
        if act['status'] != 'approved' or act['stage'] != 3:
            abort(409, 'Complete Read, Retell, and Teach-back before recording results. Completed sessions cannot be submitted again.')
        if request.method == 'POST':
            mentor_rating = choice('mentor_rating', RATINGS)
            buddy_rating = choice('buddy_rating', RATINGS)
            mentor_evidence = text_field('mentor_observations', 3000)
            buddy_evidence = text_field('buddy_answers', 3000)
            notes = text_field('notes', 3000, 0)
            if request.form.get('confirm') != 'yes':
                abort(400, 'Confirm that these are your teacher-reviewed observations.')
            selected_ids = set(request.form.getlist('reading_flag'))
            try:
                with db():
                    db().execute('BEGIN IMMEDIATE')
                    allowed_flags = {str(flag['id']): flag for flag in confirmed_flags(db, ident)}
                    if not selected_ids.issubset(allowed_flags):
                        abort(400, 'Only accepted, teacher-reviewed observations from this activity can be used.')
                    sid = db().execute('INSERT INTO sessions(institute_id,activity_id,teacher_id,notes) VALUES (?,?,?,?)',
                        (g.teacher['institute_id'], ident, g.teacher['id'], notes)).lastrowid
                    for role, rating, evidence in [('mentor', mentor_rating, mentor_evidence), ('buddy', buddy_rating, buddy_evidence)]:
                        role_flags = [flag for key, flag in allowed_flags.items() if key in selected_ids and flag['role'] == role]
                        for flag in role_flags:
                            evidence += '\nTeacher-confirmed reading observation: ' + flag['teacher_note']
                        rid = db().execute('INSERT INTO results(session_id,learner_id,role,goal,rating,evidence) VALUES (?,?,?,?,?,?)',
                            (sid, act['pair'][role + '_id'], role, act[role + '_goal'], rating, evidence)).lastrowid
                        db().executemany('INSERT INTO result_reading_flags(result_id,flag_id) VALUES (?,?)',
                                         [(rid, flag['id']) for flag in role_flags])
                    db().execute("UPDATE activities SET status='completed' WHERE id=?", (ident,))
            except sqlite3.IntegrityError:
                abort(409, 'This session has already been saved.')
            flash('Session confirmed. Separate results are saved for both learners.', 'success')
            if db().execute('SELECT 1 FROM reading_attempts WHERE activity_id=? AND institute_id=?', (ident, g.teacher['institute_id'])).fetchone():
                return redirect(url_for('reading_feedback', ident=ident))
            return redirect(url_for('session_summary', ident=sid))
        return render_template('evaluate.html', activity=act, reviewed_flags=reviewed_flags)

    @app.get('/progress')
    def progress():
        learners = db().execute('SELECT * FROM learners WHERE institute_id=? ORDER BY alias', (g.teacher['institute_id'],)).fetchall()
        selected = request.args.get('learner', type=int)
        learner = owned('learners', selected) if selected else (learners[0] if learners else None)
        history, totals = [], []
        if learner:
            history = db().execute('''SELECT r.*, s.id saved_session_id, s.created_at, s.notes, s.activity_id, d.title FROM results r
                JOIN sessions s ON s.id=r.session_id JOIN activities a ON a.id=s.activity_id
                JOIN chunks c ON c.id=a.chunk_id JOIN documents d ON d.id=c.document_id
                WHERE r.learner_id=? AND s.institute_id=? ORDER BY s.id DESC''', (learner['id'], g.teacher['institute_id'])).fetchall()
            totals = db().execute('''SELECT r.goal, count(*) practiced,
                sum(CASE WHEN r.rating='Demonstrated' THEN 1 ELSE 0 END) demonstrated FROM results r
                JOIN sessions s ON s.id=r.session_id WHERE r.learner_id=? AND s.institute_id=? GROUP BY r.goal''',
                (learner['id'], g.teacher['institute_id'])).fetchall()
        readings = []
        if learner:
            readings = db().execute('''SELECT r.*, d.title FROM reading_attempts r JOIN activities a ON a.id=r.activity_id
                JOIN chunks c ON c.id=a.chunk_id JOIN documents d ON d.id=c.document_id
                WHERE r.learner_id=? AND r.institute_id=? ORDER BY r.id DESC''', (learner['id'], g.teacher['institute_id'])).fetchall()
        return render_template('progress.html', learners=learners, learner=learner, history=history, totals=totals, readings=readings)

    register_p1(app, db, owned, pair_info, activity_info, text_field, make_tasks)
    register_student(app, db, owned, chunk_text)
    register_voice(app, db, owned, activity_info, chunk_text)
    with app.app_context():
        g.app_db = app.config['DATABASE']
        for migration in sorted((ROOT / 'migrations').glob('*.sql')):
            db().executescript(migration.read_text(encoding='utf-8'))
        seed(db())
        if app.config.get('STUDENT_BUILTINS', True):
            institute = db().execute('SELECT institute_id FROM teachers WHERE id=?', (app.config['LOCAL_TEACHER_ID'],)).fetchone()
            if institute:
                initialize_student_library(db(), institute['institute_id'], chunk_text)
    return app


def has_readable_text(text):
    return bool(re.search(r'[^\W\d_]', text, re.UNICODE))


def extract_pages(raw, filename):
    if filename.lower().endswith('.txt'):
        try:
            text = raw.decode('utf-8-sig')
        except UnicodeDecodeError:
            abort(400, 'TXT files must use UTF-8 encoding. Export the text as UTF-8 and try again.')
        if '\x00' in text:
            abort(400, 'This file does not appear to be plain text.')
        pages = [(1, text.strip())]
    elif filename.lower().endswith('.pdf'):
        if not raw.startswith(b'%PDF-'):
            abort(400, 'The file is not a valid PDF.')
        try:
            reader = PdfReader(io.BytesIO(raw))
            if reader.is_encrypted:
                abort(400, 'Password-protected PDFs are not supported. Upload an unlocked copy.')
            if len(reader.pages) > 100:
                abort(400, 'Use a PDF with 100 pages or fewer.')
            pages = []
            for i, page in enumerate(reader.pages):
                contents = page.get_contents()
                if contents and len(contents.get_data()) > 8 * 1024 * 1024:
                    abort(400, 'This PDF page is too complex. Export a smaller text-based copy.')
                pages.append((i + 1, (page.extract_text() or '').strip()))
        except HTTPException:
            raise
        except Exception:
            abort(400, 'This PDF could not be read. Try a text-based PDF or a UTF-8 TXT file.')
    else:
        abort(400, 'Only TXT and text-based PDF files are supported.')
    if sum(len(t) for _, t in pages) > 500_000:
        abort(400, 'Use a shorter document (up to 500,000 extracted characters).')
    if not any(has_readable_text(text) for _, text in pages):
        abort(400, 'No readable text was found. Scanned PDFs need OCR first; upload a text-based PDF or TXT instead.')
    return pages


def chunk_text(text, limit=180):
    # Non-overlapping, page-local chunks retain original words and page attribution.
    words = text.split()
    return [' '.join(words[i:i + limit]) for i in range(0, len(words), limit)]


def keyword_score(text, query):
    terms = set(re.findall(r'\w+', query.lower()))
    tokens = re.findall(r'\w+', text.lower())
    return sum(tokens.count(term) for term in terms)


def retrieve(chunks, query):
    return max(chunks, key=lambda row: keyword_score(row['text'], query))


def make_tasks(passage, mentor_goal, buddy_goal):
    words = list(dict.fromkeys(re.findall(r"[A-Za-z]+(?:'[A-Za-z]+)?", passage.lower())))
    vocabulary = sorted((w for w in words if len(w) >= 5), key=lambda w: -len(w))[:3]
    if not vocabulary:
        vocabulary = words[:3]
    focus = ', '.join(vocabulary) if vocabulary else 'two words from the passage'
    mentor = {
        'Explain word meanings': f'Explore these words from the passage: {focus}. Explain each in your own words and use one in a new sentence.',
        'Use context clues': f'Find {focus} in the passage. Point to nearby words that help explain each meaning, then share your reasoning with your buddy.',
        'Teach vocabulary clearly': f'Teach your buddy these words: {focus}. Use a simple explanation and an example, then ask your buddy to explain one back.',
    }[mentor_goal]
    buddy = {
        'Find key details': 'Name two important details from this passage. Point to the words that support each answer. Explain how the details connect.',
        'Retell in sequence': 'Retell what you read in order: first, next, and finally. Use details from this passage. If it describes rather than tells a story, explain its ideas in the order presented.',
        'Make supported inferences': 'What is one idea you can work out even though the passage does not say it directly? Point to a clue in the passage and explain your reasoning.',
    }[buddy_goal]
    return dict(mentor=mentor, buddy=buddy, vocabulary=vocabulary,
                teach_back='Buddy: teach one new word or idea back to your mentor using the passage. Mentor: listen, ask one clarifying question, and help your buddy find supporting words.')


def seed(conn):
    if conn.execute('SELECT 1 FROM teachers LIMIT 1').fetchone():
        return
    with conn:
        conn.execute("INSERT INTO institutes(id,name) VALUES (1,'Pairagraph Demo Institute')")
        conn.execute('INSERT INTO teachers(id,institute_id,email,password_hash,name) VALUES (1,1,?,?,?)',
                     ('teacher@pairagraph.local', generate_password_hash('PairagraphDemo!2026'), 'Demo Teacher'))
        conn.executemany('INSERT INTO learners(id,institute_id,alias,role,goal) VALUES (?,1,?,?,?)',
                         [(1, 'Maple', 'mentor', GOALS['mentor'][0]), (2, 'Robin', 'buddy', GOALS['buddy'][0])])
        conn.execute('INSERT INTO pairs(id,institute_id,mentor_id,buddy_id) VALUES (1,1,1,2)')
        conn.execute('''INSERT INTO documents(id,institute_id,title,source,filename) VALUES
            (1,1,'The Seed Library','Original fictional demo passage written for Pairagraph; not learner data.','demo-seed-library.txt')''')
        conn.execute('INSERT INTO pages(document_id,page_number,text) VALUES (1,1,?)', (SAMPLE,))


if __name__ == '__main__':
    app = create_app()
    app.config['TEMPLATES_AUTO_RELOAD'] = True
    app.run(host='127.0.0.1', port=int(os.environ.get('PORT', 5000)), debug=False)

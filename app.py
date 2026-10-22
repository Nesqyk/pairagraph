"""Pairagraph P0: teacher-led paired reading, backed by SQLite."""
from __future__ import annotations

import functools
import io
import json
import os
from pathlib import Path
import re
import secrets
import sqlite3
import time
from datetime import timedelta

from flask import Flask, abort, flash, g, redirect, render_template, request, session, url_for
from pypdf import PdfReader
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.exceptions import HTTPException

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


def create_app(test_config=None):
    app = Flask(__name__)
    instance = Path(app.instance_path)
    instance.mkdir(exist_ok=True)
    keyfile = instance / 'secret.key'
    if not keyfile.exists():
        try:
            with keyfile.open('x') as f:
                f.write(secrets.token_hex(32))
        except FileExistsError:
            pass
    app.config.update(
        SECRET_KEY=os.environ.get('PAIRAGRAPH_SECRET') or keyfile.read_text(),
        DATABASE=str(instance / 'pairagraph.sqlite3'), MAX_CONTENT_LENGTH=6 * 1024 * 1024,
        SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE='Lax',
        SESSION_COOKIE_SECURE=os.environ.get('PAIRAGRAPH_HTTPS') == '1',
        PERMANENT_SESSION_LIFETIME=timedelta(hours=8),
    )
    if test_config:
        app.config.update(test_config)

    @app.before_request
    def prepare():
        g.app_db = app.config['DATABASE']
        g.teacher = None
        if session.get('teacher_id'):
            g.teacher = db().execute('SELECT * FROM teachers WHERE id=?', (session['teacher_id'],)).fetchone()
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
        response.headers['Content-Security-Policy'] = "default-src 'self'; style-src 'self'; script-src 'self'; img-src 'self' data:; frame-ancestors 'none'; form-action 'self'"
        response.headers['Permissions-Policy'] = 'microphone=(), camera=()'
        response.headers['Cache-Control'] = 'no-store'
        return response

    @app.teardown_appcontext
    def close_db(error):
        conn = g.pop('db', None)
        if conn is not None:
            conn.close()

    @app.context_processor
    def context():
        return dict(goals=GOALS, ratings=RATINGS)

    @app.errorhandler(HTTPException)
    def error(e):
        return render_template('error.html', error=e), e.code

    def login_required(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            if not g.teacher:
                return redirect(url_for('login'))
            return fn(*args, **kwargs)
        return wrapper

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

    @app.route('/login', methods=['GET', 'POST'])
    def login():
        if request.method == 'POST':
            email = text_field('email', 254).lower()
            password = text_field('password', 256)
            key = email + '|' + (request.remote_addr or 'local')
            attempt = db().execute('SELECT * FROM login_attempts WHERE key=?', (key,)).fetchone()
            if attempt and time.time() - attempt['since'] < 300 and attempt['attempts'] >= 10:
                abort(429, 'Too many sign-in attempts. Try again in five minutes.')
            teacher = db().execute('SELECT * FROM teachers WHERE email=?', (email,)).fetchone()
            # Perform a hash check for unknown accounts as well.
            valid = check_password_hash(teacher['password_hash'] if teacher else app.config['DUMMY_HASH'], password)
            if not teacher or not valid:
                with db():
                    if not attempt or time.time() - attempt['since'] >= 300:
                        db().execute('INSERT OR REPLACE INTO login_attempts VALUES (?,1,?)', (key, time.time()))
                    else:
                        db().execute('UPDATE login_attempts SET attempts=attempts+1 WHERE key=?', (key,))
                flash('Email or password is incorrect.', 'error')
                return render_template('login.html'), 401
            with db():
                db().execute('DELETE FROM login_attempts WHERE key=?', (key,))
            session.clear()
            session['teacher_id'] = teacher['id']
            session['csrf'] = secrets.token_hex(32)
            session.permanent = True
            return redirect(url_for('dashboard'))
        return render_template('login.html')

    @app.post('/logout')
    @login_required
    def logout():
        session.clear()
        return redirect(url_for('login'))

    @app.get('/')
    @login_required
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
    @login_required
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
    @login_required
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
    @login_required
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
    @login_required
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
    @login_required
    def document(ident):
        doc = owned('documents', ident)
        pages = [dict(page, readable=has_readable_text(page['text'])) for page in
                 db().execute('SELECT * FROM pages WHERE document_id=? ORDER BY page_number', (ident,)).fetchall()]
        return render_template('document.html', doc=doc, pages=pages)

    @app.post('/library/<int:ident>/approve')
    @login_required
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
    @login_required
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
            tasks = make_tasks(chunk['text'], pair['mentor_goal'], pair['buddy_goal'])
            tasks['query'] = query
            tasks['retrieval_note'] = ('Keyword match' if query and keyword_score(chunk['text'], query) else
                                       'First passage (no keyword match)' if query else 'First passage (no topic specified)')
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
    @login_required
    def activity(ident):
        return render_template('activity.html', activity=activity_info(ident))

    @app.post('/activities/<int:ident>/approve')
    @login_required
    def approve_activity(ident):
        owned('activities', ident)
        if request.form.get('confirm') != 'yes':
            abort(400, 'Review the passage and both tasks, then confirm approval.')
        with db():
            db().execute("UPDATE activities SET status='approved',approved_by=? WHERE id=? AND status='draft'", (g.teacher['id'], ident))
        return redirect(url_for('relay', ident=ident))

    @app.route('/activities/<int:ident>/relay', methods=['GET', 'POST'])
    @login_required
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
    @login_required
    def evaluate(ident):
        act = activity_info(ident)
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
            try:
                with db():
                    sid = db().execute('INSERT INTO sessions(institute_id,activity_id,teacher_id,notes) VALUES (?,?,?,?)',
                        (g.teacher['institute_id'], ident, g.teacher['id'], notes)).lastrowid
                    for role, rating, evidence in [('mentor', mentor_rating, mentor_evidence), ('buddy', buddy_rating, buddy_evidence)]:
                        db().execute('INSERT INTO results(session_id,learner_id,role,goal,rating,evidence) VALUES (?,?,?,?,?,?)',
                            (sid, act['pair'][role + '_id'], role, act[role + '_goal'], rating, evidence))
                    db().execute("UPDATE activities SET status='completed' WHERE id=?", (ident,))
            except sqlite3.IntegrityError:
                abort(409, 'This session has already been saved.')
            flash('Session confirmed. Separate results are saved for both learners.', 'success')
            return redirect(url_for('progress'))
        return render_template('evaluate.html', activity=act)

    @app.get('/progress')
    @login_required
    def progress():
        learners = db().execute('SELECT * FROM learners WHERE institute_id=? ORDER BY alias', (g.teacher['institute_id'],)).fetchall()
        selected = request.args.get('learner', type=int)
        learner = owned('learners', selected) if selected else (learners[0] if learners else None)
        history, totals = [], []
        if learner:
            history = db().execute('''SELECT r.*, s.created_at, s.notes, s.activity_id, d.title FROM results r
                JOIN sessions s ON s.id=r.session_id JOIN activities a ON a.id=s.activity_id
                JOIN chunks c ON c.id=a.chunk_id JOIN documents d ON d.id=c.document_id
                WHERE r.learner_id=? AND s.institute_id=? ORDER BY s.id DESC''', (learner['id'], g.teacher['institute_id'])).fetchall()
            totals = db().execute('''SELECT r.goal, count(*) practiced,
                sum(CASE WHEN r.rating='Demonstrated' THEN 1 ELSE 0 END) demonstrated FROM results r
                JOIN sessions s ON s.id=r.session_id WHERE r.learner_id=? AND s.institute_id=? GROUP BY r.goal''',
                (learner['id'], g.teacher['institute_id'])).fetchall()
        return render_template('progress.html', learners=learners, learner=learner, history=history, totals=totals)

    app.config['DUMMY_HASH'] = generate_password_hash(secrets.token_hex(16))
    with app.app_context():
        g.app_db = app.config['DATABASE']
        db().executescript((ROOT / 'migrations' / '001_initial.sql').read_text())
        seed(db())
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
    create_app().run(host='127.0.0.1', port=int(os.environ.get('PORT', 5000)), debug=False)

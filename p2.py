"""Optional practice planning, exports, and explicit offline relay synchronization."""
import csv
import hashlib
import io
import json
from collections import Counter
from pathlib import Path
from xml.sax.saxutils import escape

from flask import Response, abort, g, jsonify, redirect, render_template, request, send_file, url_for

SLOTS = ('Weekday morning', 'Weekday afternoon', 'Weekend morning', 'Weekend afternoon')
LANGUAGES = {'en': 'English', 'fil': 'Filipino', 'ceb': 'Cebuano'}


def safe_cell(value):
    value = str(value)
    return "'" + value if value.lstrip().startswith(('=', '+', '-', '@')) or value.startswith(('\t', '\r', '\n')) else value


def activity_revision(activity, approved):
    payload = {key: activity[key] for key in ('id', 'status', 'stage', 'mentor_goal', 'buddy_goal', 'tasks')}
    payload.update(source=dict(activity['source']), pair=dict(activity['pair']), material_approved=approved)
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def register_p2(app, db, owned, activity_info):
    def scope():
        return hashlib.sha256(f"{app.config['SECRET_KEY']}:{app.config['DATABASE']}:{g.teacher['institute_id']}:{g.teacher['id']}".encode()).hexdigest()

    def history(ident):
        return db().execute('''SELECT r.*,s.created_at,s.notes,s.activity_id,d.title,d.source,
            c.page_number,c.chunk_number FROM results r JOIN sessions s ON s.id=r.session_id
            JOIN activities a ON a.id=s.activity_id JOIN chunks c ON c.id=a.chunk_id
            JOIN documents d ON d.id=c.document_id WHERE r.learner_id=? AND s.institute_id=?
            ORDER BY s.id''', (ident, g.teacher['institute_id'])).fetchall()

    @app.context_processor
    def p2_context():
        return {'reading_languages': LANGUAGES}

    @app.get('/practice')
    def practice():
        pairs = db().execute('''SELECT p.id,m.alias mentor,b.alias buddy,count(s.id) sessions
            FROM pairs p JOIN learners m ON m.id=p.mentor_id JOIN learners b ON b.id=p.buddy_id
            LEFT JOIN activities a ON a.pair_id=p.id LEFT JOIN sessions s ON s.activity_id=a.id
            AND s.institute_id=p.institute_id WHERE p.institute_id=? GROUP BY p.id ORDER BY p.id''',
            (g.teacher['institute_id'],)).fetchall()
        return render_template('practice.html', pairs=pairs, milestones=(1, 3, 5, 10))

    @app.get('/learners/<int:ident>/insights')
    def insights(ident):
        learner = owned('learners', ident)
        rows = history(ident)
        counts = Counter(row['rating'] for row in rows)
        return render_template('insights.html', learner=learner, history=rows, counts=counts)

    @app.route('/learners/<int:ident>/availability', methods=['GET', 'POST'])
    def availability(ident):
        learner = owned('learners', ident)
        if request.method == 'POST':
            selected = set(request.form.getlist('slot'))
            if not selected.issubset(SLOTS):
                abort(400, 'Choose a listed availability slot.')
            with db():
                db().execute('DELETE FROM learner_availability WHERE learner_id=?', (ident,))
                db().executemany('INSERT INTO learner_availability VALUES (?,?)', [(ident, slot) for slot in selected])
            return redirect(url_for('pair_suggestions'))
        selected = [row['slot'] for row in db().execute('SELECT slot FROM learner_availability WHERE learner_id=?', (ident,))]
        return render_template('availability.html', learner=learner, slots=SLOTS, selected=selected)

    @app.get('/pair-suggestions')
    def pair_suggestions():
        learners = db().execute('SELECT * FROM learners WHERE institute_id=? ORDER BY alias', (g.teacher['institute_id'],)).fetchall()
        slots = {row['id']: {s['slot'] for s in db().execute('SELECT slot FROM learner_availability WHERE learner_id=?', (row['id'],))} for row in learners}
        existing = {(row['mentor_id'], row['buddy_id']) for row in db().execute('SELECT * FROM pairs WHERE institute_id=?', (g.teacher['institute_id'],))}
        suggestions = []
        for mentor in learners:
            for buddy in learners:
                overlap = sorted(slots[mentor['id']] & slots[buddy['id']])
                if mentor['role'] == 'mentor' and buddy['role'] == 'buddy' and overlap and (mentor['id'], buddy['id']) not in existing:
                    suggestions.append(dict(mentor=mentor, buddy=buddy, overlap=overlap,
                        reason=f"Practice {mentor['goal'].lower()} while supporting your buddy to {buddy['goal'].lower()}."))
        # Suggestions are schedule-compatible, never a ranking of learners.
        return render_template('pair_suggestions.html', learners=learners, slots=slots, suggestions=suggestions)

    @app.route('/library/<int:ident>/language', methods=['GET', 'POST'])
    def material_language(ident):
        doc = owned('documents', ident)
        saved = db().execute('SELECT * FROM material_languages WHERE document_id=?', (ident,)).fetchone()
        if request.method == 'POST':
            language = request.form.get('language')
            notes = request.form.get('notes', '').strip()
            if language not in LANGUAGES or request.form.get('confirm') != 'yes' or not 1 <= len(notes) <= 1000:
                abort(400, 'Choose a language, record your content review, and confirm it.')
            with db():
                db().execute('''INSERT INTO material_languages(document_id,language,reviewed_by,notes) VALUES (?,?,?,?)
                    ON CONFLICT(document_id) DO UPDATE SET language=excluded.language,reviewed_by=excluded.reviewed_by,
                    notes=excluded.notes,reviewed_at=CURRENT_TIMESTAMP''', (ident, language, g.teacher['id'], notes))
            return redirect(url_for('document', ident=ident))
        return render_template('material_language.html', doc=doc, saved=saved)

    @app.get('/learners/<int:ident>/report.<format>')
    def learner_report(ident, format):
        learner = owned('learners', ident)
        rows = history(ident)
        if format == 'csv':
            stream = io.StringIO(newline='')
            writer = csv.writer(stream)
            writer.writerow(['Learner', 'Role', 'Goal practiced', 'Teacher assessment', 'Teacher observations', 'Session notes', 'Date UTC', 'Material', 'Source', 'Page', 'Chunk'])
            for row in rows:
                writer.writerow([safe_cell(value) for value in [learner['alias'], row['role'], row['goal'], row['rating'], row['evidence'], row['notes'], row['created_at'], row['title'], row['source'], row['page_number'], row['chunk_number']]])
            return Response('\ufeff' + stream.getvalue(), mimetype='text/csv', headers={'Content-Disposition': f'attachment; filename="learner-{ident}.csv"'})
        if format != 'pdf':
            abort(404)
        from reportlab import __file__ as reportlab_file
        from reportlab.lib import colors
        from reportlab.lib.styles import ParagraphStyle
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, HRFlowable
        if 'Pairagraph' not in pdfmetrics.getRegisteredFontNames():
            pdfmetrics.registerFont(TTFont('Pairagraph', str(Path(reportlab_file).parent / 'fonts' / 'Vera.ttf')))
        body = ParagraphStyle('body', fontName='Pairagraph', fontSize=10, leading=16, spaceAfter=8, textColor=colors.HexColor('#243e36'), splitLongWords=True)
        heading = ParagraphStyle('heading', parent=body, fontSize=19, leading=25, spaceAfter=14)
        subheading = ParagraphStyle('subheading', parent=body, fontSize=12, leading=18, spaceBefore=12)
        def p(text, style=body):
            return Paragraph(escape(str(text)).replace('\n', '<br/>'), style)
        content = [p('Pairagraph - Learner practice report', heading), p(f"{learner['alias']} | {learner['role']}"),
            p('Teacher-confirmed observations describe recorded practice, not proof of measured improvement.'), p(f"Current goal: {learner['goal']}")]
        if not rows:
            content.append(p('No confirmed sessions yet.'))
        for row in rows:
            content.extend([Spacer(1, 10), HRFlowable(width='100%', color=colors.HexColor('#dfe5dc')), p(f"{row['created_at']} UTC | {row['rating']}", subheading),
                p('Goal practiced: ' + row['goal']), p('Teacher observations: ' + row['evidence'])])
            if row['notes']:
                content.append(p('Shared notes: ' + row['notes']))
            content.append(p(f"Source: {row['title']} | {row['source']} | Page {row['page_number']}, chunk {row['chunk_number']}"))
        output = io.BytesIO()
        def footer(canvas, document):
            canvas.setFont('Pairagraph', 8)
            canvas.drawString(42, 24, 'Pairagraph | Private teacher report')
            canvas.drawRightString(document.pagesize[0] - 42, 24, str(document.page))
        SimpleDocTemplate(output, rightMargin=42, leftMargin=42, topMargin=42, bottomMargin=45, title='Pairagraph learner practice report').build(content, onFirstPage=footer, onLaterPages=footer)
        output.seek(0)
        return send_file(output, mimetype='application/pdf', as_attachment=True, download_name=f'learner-{ident}.pdf')

    @app.get('/offline')
    def offline():
        # Generic shell only: no learner data or CSRF token may be cached by the worker.
        return render_template('offline.html')

    @app.get('/service-worker.js')
    def service_worker():
        return send_file(Path(app.static_folder) / 'service-worker.js', mimetype='application/javascript')

    @app.get('/offline/context')
    def offline_context():
        from flask import session
        return jsonify(scope=scope(), csrf=session['csrf'])

    @app.get('/activities/<int:ident>/offline.json')
    def offline_activity(ident):
        act = activity_info(ident)
        approved = owned('documents', act['source']['document_id'])['approved']
        if act['status'] != 'approved' or not approved:
            abort(409, 'Only unfinished approved activities with approved material can be saved offline.')
        return jsonify(id=ident, scope=scope(), revision=activity_revision(act, approved), stage=act['stage'],
            mentor=act['pair']['mentor'], buddy=act['pair']['buddy'], mentor_goal=act['mentor_goal'], buddy_goal=act['buddy_goal'],
            passage=act['source']['text'], source=dict(act['source']), tasks=act['tasks'])

    @app.post('/activities/<int:ident>/offline-sync')
    def offline_sync(ident):
        # No assessment, transcript, or audio is synchronized automatically.
        with db():
            db().execute('BEGIN IMMEDIATE')
            act = activity_info(ident)
            approved = owned('documents', act['source']['document_id'])['approved']
            if request.form.get('scope') != scope():
                return jsonify(error='This offline copy belongs to a different workspace.'), 409
            if act['status'] != 'approved' or not approved or request.form.get('revision') != activity_revision(act, approved):
                return jsonify(error='The online activity changed. Keep your local copy, inspect the online activity, and download a fresh copy. No changes were applied.'), 409
            try:
                target = int(request.form.get('stage', ''))
            except ValueError:
                return jsonify(error='Choose a valid relay stage.'), 400
            if not act['stage'] <= target <= 3:
                return jsonify(error='Offline progress cannot move backward or skip teacher evaluation.'), 400
            db().execute('UPDATE activities SET stage=? WHERE id=?', (target, ident))
        return jsonify(ok=True, stage=target)

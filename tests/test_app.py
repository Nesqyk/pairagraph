import io
import re
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject
from werkzeug.security import generate_password_hash

from app import create_app, GOALS, chunk_text, make_tasks, retrieve


def pdf_bytes(text=None):
    writer = PdfWriter()
    page = writer.add_blank_page(width=612, height=792)
    if text:
        font = DictionaryObject({NameObject('/Type'): NameObject('/Font'), NameObject('/Subtype'): NameObject('/Type1'),
                                 NameObject('/BaseFont'): NameObject('/Helvetica')})
        page[NameObject('/Resources')] = DictionaryObject({NameObject('/Font'): DictionaryObject({NameObject('/F1'): writer._add_object(font)})})
        stream = DecodedStreamObject()
        stream.set_data(f'BT /F1 12 Tf 50 700 Td ({text}) Tj ET'.encode())
        page[NameObject('/Contents')] = writer._add_object(stream)
    result = io.BytesIO()
    writer.write(result)
    return result.getvalue()


class PairagraphTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.other_hash = generate_password_hash('OtherTeacher!2026')

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = str(Path(self.temp.name) / 'test.sqlite3')
        self.app = create_app({'TESTING': True, 'STUDENT_BUILTINS': False, 'DATABASE': self.path, 'SECRET_KEY': 'test-secret'})
        self.client = self.app.test_client()

    def tearDown(self):
        self.temp.cleanup()

    def sql(self, statement, params=()):
        with closing(sqlite3.connect(self.path)) as conn, conn:
            conn.row_factory = sqlite3.Row
            return conn.execute(statement, params).fetchall()

    def post(self, path, data=None, follow=True):
        self.client.get('/')  # establish a CSRF token if this is a fresh client
        with self.client.session_transaction() as session:
            token = session['csrf']
        payload = dict(data or {})
        payload['csrf'] = token
        response = self.client.post(path, data=payload, follow_redirects=follow)
        response.get_data()
        response.close()
        return response

    def open_workspace(self):
        response = self.client.get('/')
        self.assertEqual(response.status_code, 200)
        return response

    def draft(self):
        self.open_workspace()
        self.assertEqual(self.post('/library/1/approve', {'confirm': 'yes'}).status_code, 200)
        self.assertEqual(self.post('/activities/new', {'pair_id': 1, 'document_id': 1, 'query': 'seeds'}).status_code, 200)
        return self.sql('SELECT id FROM activities ORDER BY id DESC')[0]['id']

    def ready(self):
        ident = self.draft()
        self.assertEqual(self.post(f'/activities/{ident}/approve', {'confirm': 'yes'}).status_code, 200)
        for stage in range(3):
            self.assertEqual(self.post(f'/activities/{ident}/relay', {'stage': stage}).status_code, 200)
        return ident

    def evaluation(self):
        return dict(mentor_rating='Demonstrated', buddy_rating='Practicing',
                    mentor_observations='Explained resource using the shared seeds.',
                    buddy_answers='Named the cabinet and bean seeds; needed a prompt to connect them.',
                    notes='Revisit sharing next time.', confirm='yes')

    def test_full_acceptance_journey_persists_after_restart(self):
        self.open_workspace()
        for alias, role in [('Cedar', 'mentor'), ('Finch', 'buddy')]:
            response = self.post('/learners', {'alias': alias, 'role': role, 'goal': GOALS[role][1]})
            self.assertEqual(response.status_code, 200)
        ids = {r['role']: r['id'] for r in self.sql('SELECT * FROM learners WHERE id>2')}
        self.assertEqual(self.post('/pairs', {'mentor_id': ids['mentor'], 'buddy_id': ids['buddy']}).status_code, 200)
        pair_id = self.sql('SELECT max(id) id FROM pairs')[0]['id']
        text = 'The garden had a remarkable sunflower. Sam watered it carefully. Later the flower opened and bees visited.'
        response = self.post('/library', {'title': 'Garden lesson', 'source': 'Original test fixture', 'file': (io.BytesIO(text.encode()), 'garden.txt')})
        self.assertEqual(response.status_code, 200)
        doc_id = self.sql('SELECT max(id) id FROM documents')[0]['id']
        self.assertEqual(self.sql('SELECT count(*) n FROM chunks WHERE document_id=?', (doc_id,))[0]['n'], 0)
        self.assertEqual(self.post(f'/library/{doc_id}/approve', {'confirm': 'yes'}).status_code, 200)
        response = self.post('/activities/new', {'pair_id': pair_id, 'document_id': doc_id, 'query': 'sunflower'})
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Original test fixture', response.data)
        self.assertIn(b'Page 1', response.data)
        self.assertIn(b'Use context clues', response.data)
        self.assertIn(b'Retell in sequence', response.data)
        self.assertIn(text.encode(), response.data)
        ident = self.sql('SELECT max(id) id FROM activities')[0]['id']
        self.post(f'/activities/{ident}/approve', {'confirm': 'yes'})
        for stage in range(3):
            self.assertEqual(self.post(f'/activities/{ident}/relay', {'stage': stage}).status_code, 200)
        self.assertEqual(self.post(f'/activities/{ident}/evaluate', self.evaluation()).status_code, 200)
        self.assertEqual(len(self.sql('SELECT * FROM sessions')), 1)
        results = self.sql('SELECT * FROM results ORDER BY id')
        self.assertEqual(len(results), 2)
        self.assertEqual(results[0]['rating'], 'Demonstrated')
        self.assertEqual(results[1]['rating'], 'Practicing')
        self.assertEqual(results[0]['goal'], 'Use context clues')
        # Recreate the app and open the same on-disk workspace without signing in.
        self.app = create_app({'TESTING': True, 'STUDENT_BUILTINS': False, 'DATABASE': self.path, 'SECRET_KEY': 'test-secret'})
        self.client = self.app.test_client()
        self.open_workspace()
        mentor = self.client.get(f'/progress?learner={ids["mentor"]}')
        buddy = self.client.get(f'/progress?learner={ids["buddy"]}')
        self.assertIn(self.evaluation()['mentor_observations'].encode(), mentor.data)
        self.assertNotIn(self.evaluation()['buddy_answers'].encode(), mentor.data)
        self.assertIn(self.evaluation()['buddy_answers'].encode(), buddy.data)
        self.assertNotIn(self.evaluation()['mentor_observations'].encode(), buddy.data)
        self.assertIn(b'<strong>1</strong> confirmed sessions', mentor.data)
        self.assertIn(b'<strong>0</strong> marked demonstrated', buddy.data)

    def test_all_get_screens_render_without_login(self):
        self.assertEqual(self.client.get('/').status_code, 200)
        for route in ['/', '/learners', '/learners/1/edit', '/pairs', '/library', '/library/1', '/activities/new', '/progress']:
            self.assertEqual(self.client.get(route).status_code, 200, route)
        response = self.client.get('/login', follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Small steps. Shared growth.', response.data)
        self.assertNotIn(b'Sign out', response.data)
        self.assertNotIn(b'name="password"', response.data)
        self.client = self.app.test_client()
        self.assertEqual(self.client.get('/learners').status_code, 200)

    def test_csrf_and_privacy_headers(self):
        self.assertEqual(self.client.post('/learners', data={'alias': 'Bad'}).status_code, 400)
        response = self.client.get('/')
        self.assertEqual(response.headers['Permissions-Policy'], 'microphone=(), camera=()')
        self.assertIn("default-src 'self'", response.headers['Content-Security-Policy'])

    def test_unapproved_material_and_activity_are_blocked(self):
        self.open_workspace()
        self.assertEqual(self.post('/activities/new', {'pair_id': 1, 'document_id': 1}).status_code, 400)
        self.assertEqual(self.post('/library/1/approve').status_code, 400)
        ident = self.draft()
        self.assertEqual(self.client.get(f'/activities/{ident}/relay').status_code, 400)
        self.assertEqual(self.post(f'/activities/{ident}/approve').status_code, 400)
        self.assertEqual(self.client.get(f'/activities/{ident}/evaluate').status_code, 409)

    def test_non_ascii_csrf_is_rejected_without_server_error(self):
        self.open_workspace()
        response = self.client.post('/learners', data={
            'csrf': '\u2603', 'alias': 'Willow', 'role': 'mentor', 'goal': GOALS['mentor'][0],
        })
        self.assertEqual(response.status_code, 400)
        self.assertEqual(len(self.sql('SELECT * FROM learners')), 2)

    def test_relay_order_duplicate_submission_and_confirmation(self):
        ident = self.draft()
        self.post(f'/activities/{ident}/approve', {'confirm': 'yes'})
        self.assertEqual(self.post(f'/activities/{ident}/relay', {'stage': 2}).status_code, 409)
        self.assertEqual(self.post(f'/activities/{ident}/evaluate', self.evaluation()).status_code, 409)
        for stage in range(3):
            self.post(f'/activities/{ident}/relay', {'stage': stage})
        self.assertEqual(self.post(f'/activities/{ident}/relay', {'stage': 2}).status_code, 409)
        self.assertEqual(self.client.get(f'/activities/{ident}/evaluate').status_code, 200)
        payload = self.evaluation()
        payload.pop('confirm')
        self.assertEqual(self.post(f'/activities/{ident}/evaluate', payload).status_code, 400)
        self.assertEqual(len(self.sql('SELECT * FROM results')), 0)
        self.assertEqual(self.post(f'/activities/{ident}/evaluate', self.evaluation()).status_code, 200)
        self.assertEqual(self.post(f'/activities/{ident}/evaluate', self.evaluation()).status_code, 409)
        self.assertEqual(len(self.sql('SELECT * FROM results')), 2)

    def test_goal_edits_preserve_activity_and_history(self):
        ident = self.ready()
        self.assertEqual(self.post('/learners/1/edit', {'alias': 'Maple revised', 'goal': GOALS['mentor'][2]}).status_code, 200)
        self.post(f'/activities/{ident}/evaluate', self.evaluation())
        self.assertEqual(self.sql('SELECT goal FROM results WHERE learner_id=1')[0]['goal'], GOALS['mentor'][0])
        self.assertEqual(self.sql('SELECT goal FROM learners WHERE id=1')[0]['goal'], GOALS['mentor'][2])

    def test_tenant_boundaries_on_reads_and_writes(self):
        ident = self.ready()
        self.post(f'/activities/{ident}/evaluate', self.evaluation())
        with closing(sqlite3.connect(self.path)) as conn, conn:
            conn.execute("INSERT INTO institutes VALUES (2,'Other institute')")
            conn.execute("INSERT INTO teachers(institute_id,email,password_hash,name) VALUES (2,'other@local',?,'Other')", (self.other_hash,))
            conn.execute("INSERT INTO learners(institute_id,alias,role,goal) VALUES (2,'OtherBuddy','buddy',?)", (GOALS['buddy'][0],))
        # The teacher context is server-selected, never taken from a browser cookie.
        other_id = self.sql("SELECT id FROM teachers WHERE email='other@local'")[0]['id']
        with self.client.session_transaction() as browser_session:
            browser_session['teacher_id'] = other_id
        self.assertIn(b'Maple', self.client.get('/learners').data)
        self.app.config['LOCAL_TEACHER_ID'] = other_id
        for path in ['/learners/1/edit', '/library/1', '/activities/1', '/activities/1/relay', '/activities/1/evaluate', '/progress?learner=1']:
            self.assertEqual(self.client.get(path).status_code, 404, path)
        for path, data in [('/learners/1/edit', {'alias': 'Hijack', 'goal': GOALS['mentor'][0]}),
                           ('/library/1/approve', {'confirm': 'yes'}), ('/activities/1/approve', {'confirm': 'yes'}),
                           ('/activities/1/relay', {'stage': 0}), ('/activities/1/evaluate', self.evaluation()),
                           ('/activities/new', {'pair_id': 1, 'document_id': 1}), ('/pairs', {'mentor_id': 1, 'buddy_id': 3})]:
            self.assertEqual(self.post(path, data).status_code, 404, path)
        for path in ['/', '/learners', '/pairs', '/library', '/progress']:
            response = self.client.get(path)
            self.assertEqual(response.status_code, 200)
            self.assertNotIn(b'Maple', response.data)
            self.assertNotIn(b'The Seed Library', response.data)

    def test_validation_and_escaping(self):
        self.open_workspace()
        self.assertEqual(self.post('/learners', {'alias': ' ', 'role': 'mentor', 'goal': GOALS['mentor'][0]}).status_code, 400)
        self.assertEqual(self.post('/learners', {'alias': 'X', 'role': 'mentor', 'goal': GOALS['buddy'][0]}).status_code, 400)
        self.assertEqual(self.post('/learners', {'alias': 'Maple', 'role': 'mentor', 'goal': GOALS['mentor'][0]}).status_code, 400)
        self.assertEqual(self.post('/pairs', {'mentor_id': 2, 'buddy_id': 1}).status_code, 400)
        self.assertEqual(self.post('/pairs', {'mentor_id': 'bad', 'buddy_id': 2}).status_code, 400)
        response = self.post('/learners', {'alias': '<script>alert(1)</script>', 'role': 'mentor', 'goal': GOALS['mentor'][0]})
        self.assertIn(b'&lt;script&gt;', response.data)
        self.assertNotIn(b'<script>alert', response.data)

    def test_pdf_txt_extraction_errors_and_page_attribution(self):
        self.open_workspace()
        cases = [(b'\xff\xfe', 'bad.txt', 400), (b'', 'empty.txt', 400), (b'abc', 'bad.pdf', 400),
                 (b'abc', 'bad.exe', 400), (pdf_bytes(), 'scan.pdf', 400), (b'x' * (5 * 1024 * 1024 + 1), 'large.txt', 413)]
        for raw, name, status in cases:
            response = self.post('/library', {'title': 'Test', 'source': 'Test source', 'file': (io.BytesIO(raw), name)})
            self.assertEqual(response.status_code, status, name)
        writer = PdfWriter()
        from pypdf import PdfReader
        writer.add_page(PdfReader(io.BytesIO(pdf_bytes())).pages[0])
        writer.add_page(PdfReader(io.BytesIO(pdf_bytes('A remarkable sunflower grew in the garden.'))).pages[0])
        raw = io.BytesIO()
        writer.write(raw)
        response = self.post('/library', {'title': 'Two pages', 'source': 'PDF test fixture', 'file': (io.BytesIO(raw.getvalue()), 'two.pdf')})
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'No selectable text on this page', response.data)
        self.assertIn(b'A remarkable sunflower', response.data)
        doc = self.sql('SELECT max(id) id FROM documents')[0]['id']
        self.post(f'/library/{doc}/approve', {'confirm': 'yes'})
        self.post(f'/library/{doc}/approve', {'confirm': 'yes'})
        chunks = self.sql('SELECT * FROM chunks WHERE document_id=?', (doc,))
        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0]['page_number'], 2)

    def test_chunk_retrieval_and_goal_specific_generation(self):
        chunks = [{'text': 'Cats sleep.', 'page_number': 1}, {'text': 'Sunflowers grow. Bees visit sunflowers.', 'page_number': 2}]
        self.assertEqual(retrieve(chunks, 'sunflowers')['page_number'], 2)
        self.assertEqual(retrieve(chunks, 'unmatched')['page_number'], 1)
        self.assertEqual(len(chunk_text('word ' * 361)), 3)
        mentor_tasks, buddy_tasks = set(), set()
        for mentor in GOALS['mentor']:
            for buddy in GOALS['buddy']:
                tasks = make_tasks('The remarkable sunflower grew carefully beside the garden.', mentor, buddy)
                mentor_tasks.add(tasks['mentor'])
                buddy_tasks.add(tasks['buddy'])
                for word in tasks['vocabulary']:
                    self.assertIn(word, 'the remarkable sunflower grew carefully beside the garden.')
        self.assertEqual(len(mentor_tasks), 3)
        self.assertEqual(len(buddy_tasks), 3)

    def test_non_reading_pdf_pages_are_not_retrieved(self):
        self.open_workspace()
        writer = PdfWriter()
        from pypdf import PdfReader
        for text in ['12345 ---', 'A remarkable sunflower grew in the garden.']:
            writer.add_page(PdfReader(io.BytesIO(pdf_bytes(text))).pages[0])
        raw = io.BytesIO()
        writer.write(raw)
        response = self.post('/library', {
            'title': 'Numbered cover', 'source': 'Original test fixture',
            'file': (io.BytesIO(raw.getvalue()), 'numbered.pdf'),
        })
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'It will not be used in activities', response.data)
        doc = self.sql('SELECT max(id) id FROM documents')[0]['id']
        self.assertEqual(self.post(f'/library/{doc}/approve', {'confirm': 'yes'}).status_code, 200)
        chunks = self.sql('SELECT * FROM chunks WHERE document_id=?', (doc,))
        self.assertEqual([chunk['page_number'] for chunk in chunks], [2])
        response = self.post('/activities/new', {'pair_id': 1, 'document_id': doc, 'query': ''})
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Page 2', response.data)
        self.assertIn(b'A remarkable sunflower grew in the garden.', response.data)


if __name__ == '__main__':
    unittest.main()

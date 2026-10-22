import io
import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from app import create_app
from providers import ProviderError
from student import highlighted_comparison


class StudentUITest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = str(Path(self.temp.name) / 'student.sqlite3')
        self.app = create_app({'TESTING': True, 'STUDENT_BUILTINS': False, 'DATABASE': self.path, 'SECRET_KEY': 'student-test',
            'STUDENT_GEMINI_KEY': 'fake-gemini-key', 'STUDENT_STORY_KEY': 'fake-story-key'})
        self.client = self.app.test_client()
        self.text = 'The flower is red. A little bird can sing in the garden.'
        self.post('/library', {'title': 'The Little Garden', 'source': 'Original test fixture', 'file': (io.BytesIO(self.text.encode()), 'garden.txt')})
        self.post('/library/2/approve', {'confirm': 'yes'})
        self.chunk = self.sql('SELECT id FROM chunks WHERE document_id=2')[0]['id']

    def tearDown(self):
        self.temp.cleanup()

    def sql(self, statement, params=()):
        with closing(sqlite3.connect(self.path)) as conn, conn:
            conn.row_factory = sqlite3.Row
            return conn.execute(statement, params).fetchall()

    def post(self, path, data=None):
        self.client.get('/').close()
        with self.client.session_transaction() as cookie:
            token = cookie['csrf']
        response = self.client.post(path, data={**(data or {}), 'csrf': token}, follow_redirects=True)
        response.get_data()
        response.close()
        return response

    def start(self):
        response = self.post('/student/start', {'learner_id': 2, 'chunk_id': self.chunk})
        self.assertEqual(response.status_code, 200)
        return self.sql('SELECT max(id) id FROM student_readings')[0]['id']

    def submit(self, ident, text=None):
        response = self.post(f'/student/reading/{ident}/submit', {'transcript': text or self.text, 'consent': 'yes'})
        self.assertEqual(response.status_code, 201)
        return response

    def test_all_five_screens_and_manual_reading_persistence(self):
        home = self.client.get('/student')
        self.assertEqual(home.status_code, 200)
        self.assertIn(b'Start Reading', home.data)
        self.assertNotIn(b'nav-caption', home.data)
        ident = self.start()
        self.assertEqual(self.client.get(f'/student/reading/{ident}').headers['Permissions-Policy'], 'microphone=(self), camera=()')
        self.submit(ident, 'The flower is blue. A little bird can sing in the garden.')
        analysis = self.client.get(f'/student/analysis/{ident}')
        self.assertIn(b'original-mark', analysis.data)
        self.assertIn(b'heard-mark', analysis.data)
        self.assertIn(b'Manually entered', analysis.data)
        self.assertEqual(self.client.get(f'/student/next/{ident}').status_code, 200)
        progress = self.client.get('/student/progress')
        self.assertIn(b'The Little Garden', progress.data)
        self.assertIn(b'red', progress.data)
        self.assertEqual(self.post(f'/student/reading/{ident}/submit', {'transcript': self.text, 'consent': 'yes'}).status_code, 409)
        self.assertEqual(len(self.sql('SELECT * FROM student_readings')), 1)
        # A fresh application instance sees the same persisted history.
        fresh = create_app({'TESTING': True, 'STUDENT_BUILTINS': False, 'DATABASE': self.path, 'SECRET_KEY': 'student-test', 'STUDENT_GEMINI_KEY': ''})
        other = fresh.test_client()
        with other.session_transaction() as cookie:
            cookie['student_learner_id'] = 2
        self.assertIn(b'The Little Garden', other.get('/student/progress').data)

    def test_random_approved_next_story_without_differences(self):
        ident = self.start()
        self.submit(ident)
        self.post('/library/1/approve', {'confirm': 'yes'})
        self.assertIn(b'A new little adventure.', self.client.get(f'/student/next/{ident}').data)
        saved = self.sql('SELECT * FROM student_readings WHERE id=?', (ident,))[0]
        self.assertEqual(saved['next_kind'], 'random')
        self.assertNotEqual(saved['next_chunk_id'], self.chunk)
        again = self.client.get(f'/student/next/{ident}')
        self.assertEqual(again.status_code, 200)
        self.assertEqual(self.sql('SELECT next_chunk_id FROM student_readings WHERE id=?',(ident,))[0][0], saved['next_chunk_id'])

    def test_real_provider_route_is_isolated_and_errors_do_not_save(self):
        ident = self.start()
        audio = lambda: {'audio': (io.BytesIO(b'RIFF1234WAVE' + b'0'*100), 'reading.wav'), 'consent': 'yes'}
        with patch('student.transcribe_gemini', side_effect=ProviderError('Service unavailable')):
            self.assertEqual(self.post(f'/student/reading/{ident}/submit', audio()).status_code, 502)
        self.assertEqual(self.sql('SELECT status FROM student_readings')[0][0], 'reading')
        with patch('student.transcribe_gemini', return_value=self.text) as provider:
            self.assertEqual(self.post(f'/student/reading/{ident}/submit', audio()).status_code, 201)
            self.assertEqual(provider.call_args.args[0], 'fake-gemini-key')
        self.assertEqual(self.sql('SELECT origin FROM student_readings')[0][0], 'gemini')
        self.assertNotIn(b'RIFF1234WAVE', Path(self.path).read_bytes())

    def test_consent_student_selection_and_tenant_boundaries(self):
        ident = self.start()
        self.assertEqual(self.post(f'/student/reading/{ident}/submit', {'transcript': self.text}).status_code, 400)
        with self.client.session_transaction() as cookie:
            cookie['student_learner_id'] = 1
        self.assertEqual(self.client.get(f'/student/reading/{ident}').status_code, 404)
        self.sql("INSERT INTO institutes(id,name) VALUES (2,'Other')")
        self.sql("INSERT INTO learners(id,institute_id,alias,role,goal) VALUES (3,2,'Other child','buddy','Details')")
        self.assertEqual(self.post('/student/start', {'learner_id': 3, 'chunk_id': self.chunk}).status_code, 404)
        self.assertEqual(self.post('/student/start', {'learner_id': 2, 'chunk_id': 999}).status_code, 404)

    def test_generated_story_is_ready_without_teacher_review(self):
        ident = self.start()
        self.submit(ident, 'The flower is blue. A little bird can sing in the garden.')
        draft = {'title': 'A Flower for a Bird', 'story': 'The red flower grows in the garden.',
                 'rationale': 'Practice the word red.', 'targets': ['red']}
        with patch('student.generate_story', return_value=draft) as provider:
            self.assertEqual(self.post(f'/student/next/{ident}', {'consent': 'yes'}).status_code, 200)
            provider.assert_called_once()
        page = self.client.get(f'/student/next/{ident}')
        self.assertIn(b'AI practice story', page.data)
        self.assertNotIn(b'Teacher review', page.data)
        self.assertEqual(len(self.sql('SELECT * FROM documents')), 3)
        self.assertEqual(self.post(f'/student/next/{ident}', {'consent':'yes'}).status_code, 200)
        self.assertEqual(len(self.sql('SELECT * FROM documents')), 3)
        row = self.sql('SELECT * FROM student_readings WHERE id=?', (ident,))[0]
        self.assertTrue(json.loads(row['next_draft'])['ready'])
        self.assertEqual(self.post('/student/start', {'learner_id':2,'chunk_id':row['next_chunk_id']}).status_code,200)

    def test_built_in_stories_start_without_setup_or_approval(self):
        other = create_app({'TESTING':True, 'DATABASE':str(Path(self.temp.name)/'builtins.sqlite3'),
                            'STUDENT_BUILTINS':True, 'SECRET_KEY':'builtin-test'})
        client = other.test_client()
        home = client.get('/')
        self.assertEqual(home.status_code,200)
        self.assertIn(b'The Little Garden',home.data)
        self.assertNotIn(b'Teacher',home.data)
        self.assertNotIn(b'approve_sample',home.data)
        with client.session_transaction() as cookie:
            csrf = cookie['csrf']
        response=client.post('/student/start',data={'csrf':csrf,'learner_id':2},follow_redirects=True)
        self.assertEqual(response.status_code,200)
        self.assertIn(b'Start recording',response.data)
        self.assertNotIn(b'Teacher',response.data)

    def test_highlight_preserves_case_punctuation_and_incomplete_end(self):
        comparison = highlighted_comparison('Hello, friend! The flower is red.', 'Hello friend! The flower is blue.')
        self.assertEqual(''.join(part['original'] for part in comparison), 'Hello, friend! The flower is red.')
        self.assertEqual(''.join(part['heard'] for part in comparison), 'Hello friend! The flower is blue.')


if __name__ == '__main__':
    unittest.main()

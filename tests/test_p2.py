import csv
import io
import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from pypdf import PdfReader

from app import create_app, GOALS
from providers import OpenAIProvider


class P2Test(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = str(Path(self.temp.name) / 'p2.sqlite3')
        self.app = create_app({'TESTING': True, 'DATABASE': self.path, 'SECRET_KEY': 'p2-test',
                               'READING_PROVIDER': OpenAIProvider()})
        self.client = self.app.test_client()

    def tearDown(self):
        self.temp.cleanup()

    def sql(self, statement, params=()):
        with closing(sqlite3.connect(self.path)) as conn, conn:
            conn.row_factory = sqlite3.Row
            return conn.execute(statement, params).fetchall()

    def post(self, path, data=None):
        self.client.get('/')
        with self.client.session_transaction() as session:
            csrf = session['csrf']
        response = self.client.post(path, data={**(data or {}), 'csrf': csrf}, follow_redirects=True)
        response.get_data()
        response.close()
        return response

    def activity(self, approve=True):
        self.post('/library/1/approve', {'confirm': 'yes'})
        response = self.post('/activities/new', {'pair_id': 1, 'document_id': 1})
        self.assertEqual(response.status_code, 200)
        ident = self.sql('SELECT max(id) id FROM activities')[0]['id']
        if approve:
            self.post(f'/activities/{ident}/approve', {'confirm': 'yes'})
        return ident

    def complete(self, evidence='Explained how the community shares seeds.'):
        ident = self.activity()
        for stage in range(3):
            self.post(f'/activities/{ident}/relay', {'stage': stage})
        self.assertEqual(self.post(f'/activities/{ident}/evaluate', dict(mentor_rating='Demonstrated',
            buddy_rating='Practicing', mentor_observations=evidence, buddy_answers='Retold the story with help.',
            notes='Practice again.', confirm='yes')).status_code, 200)
        return ident

    def test_milestones_count_confirmed_sessions_and_charts_wait_for_three(self):
        self.activity()
        self.assertIn(b'0 confirmed shared sessions', self.client.get('/practice').data)
        self.complete()
        self.assertIn(b'1 confirmed shared sessions', self.client.get('/practice').data)
        self.assertNotIn(b'<meter', self.client.get('/learners/1/insights').data)
        self.complete()
        self.complete()
        page = self.client.get('/learners/1/insights').data
        self.assertIn(b'<meter', page)
        self.assertIn(b'not proof of measured improvement', page)
        self.assertIn(b'3 confirmed shared sessions', self.client.get('/practice').data)
        self.assertIn(b'Reached together', self.client.get('/practice').data)

    def test_pair_suggestions_need_shared_availability_and_exclude_existing_pairs(self):
        self.post('/learners', {'alias': 'Cedar', 'role': 'buddy', 'goal': GOALS['buddy'][1]})
        cedar = self.sql("SELECT id FROM learners WHERE alias='Cedar'")[0]['id']
        self.assertIn(b'No new compatible pairs', self.client.get('/pair-suggestions').data)
        self.post('/learners/1/availability', {'slot': ['Weekday morning']})
        self.post(f'/learners/{cedar}/availability', {'slot': ['Weekend afternoon']})
        self.assertIn(b'No new compatible pairs', self.client.get('/pair-suggestions').data)
        self.post(f'/learners/{cedar}/availability', {'slot': ['Weekday morning']})
        page = self.client.get('/pair-suggestions').data
        self.assertIn(b'Maple + Cedar', page)
        self.assertIn(b'Retell in sequence', page)
        self.assertIn(b'Weekday morning', page)
        self.post('/pairs', {'mentor_id': 1, 'buddy_id': cedar})
        self.assertIn(b'No new compatible pairs', self.client.get('/pair-suggestions').data)
        self.assertEqual(self.post('/learners/1/availability', {'slot': ['anything']}).status_code, 400)

    def test_reports_preserve_evidence_escape_formulas_and_paginate(self):
        self.complete('=SUM(1,2)\nOriginal teacher evidence, with a comma.')
        response = self.client.get('/learners/1/report.csv')
        self.assertEqual(response.status_code, 200)
        rows = list(csv.reader(io.StringIO(response.data.decode('utf-8-sig'))))
        self.assertEqual(rows[1][4], "'=SUM(1,2)\nOriginal teacher evidence, with a comma.")
        self.assertIn('Original fictional', rows[1][8])
        self.assertNotIn('Retold the story with help.', response.data.decode())
        self.sql('UPDATE results SET evidence=? WHERE learner_id=1', ('Long observation. ' * 180,))
        response = self.client.get('/learners/1/report.pdf')
        reader = PdfReader(io.BytesIO(response.data))
        self.assertGreater(len(reader.pages), 1)
        text = '\n'.join(page.extract_text() for page in reader.pages)
        self.assertIn('Long observation.', text)
        self.assertIn('Page 1, chunk 1', text)
        self.assertNotIn('Retold the story with help.', text)
        self.assertEqual(self.client.get('/learners/1/report.exe').status_code, 404)

    def test_offline_snapshot_gates_and_sync_conflicts(self):
        ident = self.activity(approve=False)
        self.assertEqual(self.client.get(f'/activities/{ident}/offline.json').status_code, 409)
        self.post(f'/activities/{ident}/approve', {'confirm': 'yes'})
        snapshot = self.client.get(f'/activities/{ident}/offline.json').json
        self.assertEqual(snapshot['stage'], 0)
        payload = {key: snapshot[key] for key in ('scope', 'revision')}
        self.assertEqual(self.post(f'/activities/{ident}/offline-sync', {**payload, 'stage': 4}).status_code, 400)
        self.assertEqual(self.post(f'/activities/{ident}/offline-sync', {**payload, 'scope': 'foreign', 'stage': 1}).status_code, 409)
        self.assertEqual(self.post(f'/activities/{ident}/offline-sync', {**payload, 'stage': 2}).status_code, 200)
        self.assertEqual(self.sql('SELECT stage FROM activities WHERE id=?', (ident,))[0]['stage'], 2)
        self.assertEqual(self.post(f'/activities/{ident}/offline-sync', {**payload, 'stage': 3}).status_code, 409)
        self.assertEqual(self.sql('SELECT count(*) n FROM sessions')[0]['n'], 0)
        fresh = self.client.get(f'/activities/{ident}/offline.json').json
        fresh_payload = {key: fresh[key] for key in ('scope', 'revision')}
        self.assertEqual(self.post(f'/activities/{ident}/offline-sync', {**fresh_payload, 'stage': 1}).status_code, 400)
        self.sql("UPDATE learners SET goal=? WHERE id=1", (GOALS['mentor'][1],))
        self.assertEqual(self.post(f'/activities/{ident}/offline-sync', {**fresh_payload, 'stage': 3}).status_code, 409)

    def test_offline_sync_rejects_revoked_material_completed_sessions_and_missing_csrf(self):
        ident = self.activity()
        snapshot = self.client.get(f'/activities/{ident}/offline.json').json
        payload = {key: snapshot[key] for key in ('scope', 'revision')}
        self.assertEqual(self.client.post(f'/activities/{ident}/offline-sync', data={**payload, 'stage': 3}).status_code, 400)
        self.sql('UPDATE documents SET approved=0 WHERE id=1')
        self.assertEqual(self.client.get(f'/activities/{ident}/offline.json').status_code, 409)
        self.assertEqual(self.post(f'/activities/{ident}/offline-sync', {**payload, 'stage': 3}).status_code, 409)
        self.sql('UPDATE documents SET approved=1 WHERE id=1')
        self.sql("UPDATE activities SET status='completed' WHERE id=?", (ident,))
        self.assertEqual(self.post(f'/activities/{ident}/offline-sync', {**payload, 'stage': 3}).status_code, 409)

    def test_localized_tasks_require_language_review_and_survive_rejection(self):
        self.post('/library/1/approve', {'confirm': 'yes'})
        for language, passage, expected in [('fil', 'Ang mga bata ay nagtanim ng halaman sa hardin.', 'Ipaliwanag'),
                                             ('ceb', 'Ang mga bata nagtanom og mga liso sa tanaman.', 'Ipasabot')]:
            self.assertEqual(self.post('/activities/new', {'pair_id': 1, 'document_id': 1, 'language': language}).status_code, 400)
            # Material review is teacher confirmation, not automatic language detection.
            self.sql('UPDATE chunks SET text=? WHERE document_id=1', (passage,))
            self.assertEqual(self.post('/library/1/language', {'language': language, 'notes': 'Reviewed by a fluent teacher.', 'confirm': 'yes'}).status_code, 200)
            self.assertEqual(self.post('/activities/new', {'pair_id': 1, 'document_id': 1, 'language': language, 'use_ai': 'yes'}).status_code, 200)
            act = self.sql('SELECT * FROM activities ORDER BY id DESC')[0]
            tasks = json.loads(act['tasks'])
            self.assertEqual(tasks['language'], language)
            self.assertEqual(tasks['origin'], 'template')
            self.assertIn(expected, tasks['mentor'])
            self.assertTrue(all(word in passage.casefold() for word in tasks['vocabulary']))
            import hashlib
            revision = hashlib.sha256(json.dumps(tasks).encode()).hexdigest()
            self.assertEqual(self.post(f"/activities/{act['id']}/review", {'action': 'reject', 'revision': revision}).status_code, 200)
            self.assertIn(expected, json.loads(self.sql('SELECT tasks FROM activities WHERE id=?', (act['id'],))[0]['tasks'])['mentor'])
            self.sql('DELETE FROM material_languages WHERE document_id=1')
        self.assertEqual(self.post('/library/1/language', {'language': 'unknown', 'notes': 'test', 'confirm': 'yes'}).status_code, 400)

    def test_new_routes_preserve_tenant_boundaries_and_generic_offline_shell(self):
        self.sql("INSERT INTO institutes VALUES (2,'Other')")
        self.sql("INSERT INTO learners VALUES (20,2,'Private','mentor',?)", (GOALS['mentor'][0],))
        self.sql("INSERT INTO documents(id,institute_id,title,source,filename) VALUES (20,2,'Secret','Private','x.txt')")
        self.sql("INSERT INTO pairs VALUES (20,2,20,20)")
        self.sql("INSERT INTO pages VALUES (20,20,1,'Private text')")
        self.sql("INSERT INTO chunks VALUES (20,20,1,1,'Private text')")
        self.sql("INSERT INTO activities(id,institute_id,pair_id,chunk_id,mentor_goal,buddy_goal,tasks,status) VALUES (20,2,20,20,'x','x','{}','approved')")
        for route in ['/learners/20/insights', '/learners/20/availability', '/learners/20/report.csv', '/learners/20/report.pdf', '/library/20/language', '/activities/20/offline.json']:
            self.assertEqual(self.client.get(route).status_code, 404, route)
        self.assertEqual(self.post('/activities/20/offline-sync', {'stage': 3}).status_code, 404)
        self.assertNotIn(b'Private', self.client.get('/pair-suggestions').data)
        shell = self.client.get('/offline').data
        self.assertNotIn(b'Maple', shell)
        self.assertNotIn(b'csrf', shell)
        self.assertEqual(self.client.get('/service-worker.js').status_code, 200)

    def test_migration_restart_preserves_preferences_and_sessions(self):
        self.post('/learners/1/availability', {'slot': ['Weekday morning']})
        self.complete()
        restarted = create_app({'TESTING': True, 'DATABASE': self.path, 'SECRET_KEY': 'p2-test', 'READING_PROVIDER': OpenAIProvider()})
        page = restarted.test_client().get('/practice')
        self.assertIn(b'1 confirmed shared sessions', page.data)
        self.assertEqual(self.sql('SELECT slot FROM learner_availability WHERE learner_id=1')[0]['slot'], 'Weekday morning')


if __name__ == '__main__':
    unittest.main()

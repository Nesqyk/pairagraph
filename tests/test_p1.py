import hashlib
import io
import json
import re
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import Mock

from app import create_app, GOALS
from p1 import compare_reading
from providers import OpenAIProvider, ProviderError, validate_tasks


class P1Test(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = str(Path(self.temp.name) / 'test.sqlite3')
        self.provider = OpenAIProvider(api_key='test-key', transcription_key='voice-test',
                                       transcription_url='https://voice.test/transcriptions')
        self.provider.adapt = Mock(return_value={
            'mentor': 'Explain the word community using a clue from the passage.',
            'buddy': 'Name two key details about the seed library and point to the supporting words.',
            'teach_back': 'Buddy explains one seed-library idea back to the mentor.', 'vocabulary': ['community'],
        })
        self.provider.transcribe = Mock(return_value='The seed library has seeds for neighbors.')
        self.app = create_app({'TESTING': True, 'DATABASE': self.path, 'SECRET_KEY': 'test',
                               'READING_PROVIDER': self.provider})
        self.client = self.app.test_client()

    def tearDown(self):
        self.temp.cleanup()

    def sql(self, query, args=()):
        with closing(sqlite3.connect(self.path)) as conn, conn:
            conn.row_factory = sqlite3.Row
            return conn.execute(query, args).fetchall()

    def post(self, path, data=None, follow=True):
        self.client.get('/')
        with self.client.session_transaction() as cookie:
            csrf = cookie['csrf']
        response = self.client.post(path, data={**(data or {}), 'csrf': csrf}, follow_redirects=follow)
        response.get_data()
        response.close()
        return response

    def draft(self, ai=False):
        self.post('/library/1/approve', {'confirm': 'yes'})
        response = self.post('/activities/new', dict(pair_id=1, document_id=1, query='seeds',
            use_ai='yes' if ai else '', age_band='9–11'))
        self.assertEqual(response.status_code, 200)
        return self.sql('SELECT max(id) id FROM activities')[0]['id']

    def approved(self):
        ident = self.draft()
        self.post(f'/activities/{ident}/approve', {'confirm': 'yes'})
        return ident

    def ready(self, ident):
        for stage in range(3):
            self.assertEqual(self.post(f'/activities/{ident}/relay', {'stage': stage}).status_code, 200)

    def evaluation(self):
        return dict(mentor_rating='Demonstrated', buddy_rating='Practicing', mentor_observations='Explained community.',
                    buddy_answers='Found seeds with one prompt.', notes='Practice supporting details.', confirm='yes')

    def manual(self, ident, role='buddy'):
        response = self.post(f'/activities/{ident}/reading', {
            'role': role, 'transcript': 'The seed library has seeds for neighbors.', 'confirm': 'yes'})
        self.assertEqual(response.status_code, 200)
        return self.sql('SELECT max(id) id FROM transcripts')[0]['id']

    def confirm_review(self, tid, accepted=True):
        transcript = self.sql('SELECT * FROM transcripts WHERE id=?', (tid,))[0]
        data = dict(action='confirm', confirm='yes', revision=transcript['revision'])
        flags = self.sql('SELECT * FROM reading_flags WHERE transcript_id=?', (tid,))
        for flag in flags:
            data[f'decision_{flag["id"]}'] = 'accepted' if accepted else 'rejected'
            data[f'note_{flag["id"]}'] = 'Teacher heard a different word; return to the passage.' if accepted else ''
        self.assertEqual(self.post(f'/transcripts/{tid}', data).status_code, 200)
        return flags

    def edit_payload(self, ident, action='save'):
        tasks = json.loads(self.sql('SELECT tasks FROM activities WHERE id=?', (ident,))[0]['tasks'])
        return dict(action=action, revision=hashlib.sha256(json.dumps(tasks).encode()).hexdigest(),
                    mentor='Teach the word community with one clear example from this passage.',
                    buddy='Point to two important details in this shared passage and explain them.',
                    teach_back='Buddy explains one word and asks the mentor a question.', vocabulary='community')

    def test_ai_uses_approved_source_and_persists_attributed_draft(self):
        self.assertEqual(self.post('/activities/new', dict(pair_id=1,document_id=1,use_ai='yes',age_band='9–11')).status_code, 400)
        self.provider.adapt.assert_not_called()
        ident = self.draft(ai=True)
        args = self.provider.adapt.call_args.args
        self.assertEqual(args[1:], (GOALS['mentor'][0], GOALS['buddy'][0], '9–11'))
        tasks = json.loads(self.sql('SELECT tasks FROM activities')[0]['tasks'])
        self.assertEqual(tasks['origin'], 'ai')
        page = self.client.get(f'/activities/{ident}')
        self.assertIn(b'AI-assisted adaptation', page.data)
        self.assertIn(b'Page 1', page.data)
        self.assertEqual(self.client.get(f'/activities/{ident}/relay').status_code, 400)
        self.assertEqual(self.client.get(f'/activities/{ident}/review').status_code, 200)

    def test_provider_failure_keeps_runnable_labeled_fallback(self):
        self.provider.adapt.side_effect = ProviderError('Provider is unavailable.')
        ident = self.draft(ai=True)
        page = self.client.get(f'/activities/{ident}')
        self.assertIn(b'Template fallback used', page.data)
        self.assertNotIn(b'AI-assisted adaptation', page.data)
        self.assertEqual(self.post(f'/activities/{ident}/approve', {'confirm': 'yes'}).status_code, 200)
        self.ready(ident)
        self.assertEqual(self.post(f'/activities/{ident}/evaluate', self.evaluation()).status_code, 200)

    def test_edit_reject_and_freeze_adaptations(self):
        ident = self.draft(ai=True)
        data = self.edit_payload(ident)
        self.assertEqual(self.post(f'/activities/{ident}/review', data).status_code, 200)
        self.assertEqual(self.post(f'/activities/{ident}/review', data).status_code, 409)
        stored = json.loads(self.sql('SELECT tasks FROM activities')[0]['tasks'])
        self.assertTrue(stored['teacher_edited'])
        self.assertEqual(stored['generated_tasks']['mentor'], self.provider.adapt.return_value['mentor'])
        invalid = self.edit_payload(ident)
        invalid['vocabulary'] = 'inventedword'
        self.assertEqual(self.post(f'/activities/{ident}/review', invalid).status_code, 400)
        self.assertEqual(self.post(f'/activities/{ident}/review', self.edit_payload(ident, 'reject')).status_code, 200)
        stored = json.loads(self.sql('SELECT tasks FROM activities')[0]['tasks'])
        self.assertEqual(stored['origin'], 'template')
        self.assertEqual(stored['adaptation_review'], 'rejected')
        self.post(f'/activities/{ident}/approve', {'confirm': 'yes'})
        self.assertEqual(self.post(f'/activities/{ident}/review', self.edit_payload(ident)).status_code, 409)

    def test_transcript_edit_resets_review_and_rejects_stale_forms(self):
        ident = self.approved()
        tid = self.manual(ident)
        self.confirm_review(tid)
        current = self.sql('SELECT revision FROM transcripts WHERE id=?', (tid,))[0]['revision']
        response = self.post(f'/transcripts/{tid}', dict(action='edit',revision=current,transcript='Mina planted the seeds.'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.sql('SELECT status FROM transcripts')[0]['status'], 'draft')
        self.assertTrue(all(row['decision'] == 'pending' for row in self.sql('SELECT * FROM reading_flags')))
        self.assertEqual(self.post(f'/transcripts/{tid}', dict(action='edit',revision=current,transcript='A stale edit.')).status_code, 409)

    def test_suggestions_only_become_evidence_after_review_and_explicit_selection(self):
        ident = self.approved()
        tid = self.manual(ident)
        flag = self.sql('SELECT * FROM reading_flags LIMIT 1')[0]
        self.ready(ident)
        data = self.evaluation()
        data['reading_flag'] = str(flag['id'])
        self.assertEqual(self.post(f'/activities/{ident}/evaluate', data).status_code, 400)
        self.assertFalse(self.sql('SELECT * FROM sessions'))
        flags = self.confirm_review(tid)
        data['reading_flag'] = str(flags[0]['id'])
        response = self.post(f'/activities/{ident}/evaluate', data)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Shared teach-back', response.data)
        results = {row['role']: row for row in self.sql('SELECT * FROM results')}
        self.assertIn('Teacher-confirmed reading observation:', results['buddy']['evidence'])
        self.assertNotIn('Teacher-confirmed reading observation:', results['mentor']['evidence'])
        self.assertEqual(len(self.sql('SELECT * FROM result_reading_flags')), 1)
        self.assertEqual(self.post(f'/transcripts/{tid}/delete', {'confirm':'yes'}).status_code, 409)
        self.assertEqual(self.post(f'/transcripts/{tid}', {'action':'edit','revision':2,'transcript':'changed'}).status_code, 409)

    def test_rejecting_flags_never_populates_evidence(self):
        ident = self.approved()
        tid = self.manual(ident)
        flags = self.confirm_review(tid, accepted=False)
        self.ready(ident)
        data = self.evaluation()
        data['reading_flag'] = str(flags[0]['id'])
        self.assertEqual(self.post(f'/activities/{ident}/evaluate', data).status_code, 400)
        self.assertEqual(self.post(f'/activities/{ident}/evaluate', self.evaluation()).status_code, 200)
        self.assertFalse(self.sql('SELECT * FROM result_reading_flags'))

    def test_comparison_decisions_need_teacher_notes_and_confirmation(self):
        ident = self.approved()
        tid = self.manual(ident)
        revision = self.sql('SELECT revision FROM transcripts')[0]['revision']
        flags = self.sql('SELECT * FROM reading_flags')
        data = dict(action='confirm',revision=revision,confirm='yes')
        for flag in flags:
            data[f'decision_{flag["id"]}'] = 'accepted'
        self.assertEqual(self.post(f'/transcripts/{tid}', data).status_code, 400)
        self.assertEqual(self.sql('SELECT status FROM transcripts')[0]['status'], 'draft')
        self.assertEqual(self.post(f'/transcripts/{tid}/delete', {'confirm':'yes'}).status_code, 200)
        self.assertFalse(self.sql('SELECT * FROM transcripts'))
        self.assertFalse(self.sql('SELECT * FROM reading_flags'))

    def audio(self, **extra):
        return {'role': 'buddy', 'authorize': 'yes', 'consent': 'yes',
                'audio': (io.BytesIO(b'RIFF' + bytes(4) + b'WAVE' + bytes(80)), 'reading.wav', 'audio/wav'), **extra}

    def test_transcription_is_opt_in_has_failures_and_never_saves_audio(self):
        ident = self.approved()
        response = self.post(f'/activities/{ident}/transcribe', self.audio(consent='no'))
        self.assertEqual(response.status_code, 400)
        self.provider.transcribe.assert_not_called()
        self.provider.transcribe.side_effect = ProviderError('Provider busy. Retry later.')
        self.assertEqual(self.post(f'/activities/{ident}/transcribe', self.audio()).status_code, 502)
        self.assertFalse(self.sql('SELECT * FROM transcripts'))
        self.provider.transcribe.side_effect = None
        response = self.post(f'/activities/{ident}/transcribe', self.audio(), follow=False)
        self.assertEqual(response.status_code, 201)
        transcript = self.sql('SELECT * FROM transcripts')[0]
        self.assertEqual(transcript['origin'], 'provider')
        self.assertEqual(transcript['status'], 'draft')
        self.assertNotIn('audio', transcript.keys())
        self.assertIn('redirect', response.json)
        self.assertFalse(self.sql('SELECT * FROM results'))

    def test_voice_provider_not_configured_does_not_use_rag_key(self):
        ident = self.approved()
        self.provider.api_mode = 'chat'
        self.provider.transcription_url = ''
        self.assertEqual(self.post(f'/activities/{ident}/transcribe', self.audio()).status_code, 503)
        page = self.client.get(f'/activities/{ident}/reading')
        self.assertIn(b'Transcription is not configured', page.data)
        self.assertIn(b'manual transcript', page.data)
        self.provider.transcribe.assert_not_called()

    def test_audio_upload_validation(self):
        ident = self.approved()
        bad = self.audio()
        bad['audio'] = (io.BytesIO(b'not audio' * 10), 'reading.wav', 'audio/wav')
        self.assertEqual(self.post(f'/activities/{ident}/transcribe', bad).status_code, 400)
        bad = self.audio()
        bad['audio'] = (io.BytesIO(b'RIFF' + bytes(5*1024*1024)), 'reading.wav', 'audio/wav')
        self.assertEqual(self.post(f'/activities/{ident}/transcribe', bad).status_code, 400)
        self.provider.transcribe.assert_not_called()

    def test_recording_only_allowed_on_opt_in_page_and_uploads_use_memory(self):
        ident = self.approved()
        response = self.client.get(f'/activities/{ident}/reading')
        self.assertEqual(response.headers['Permissions-Policy'], 'microphone=(self), camera=()')
        self.assertIn(b'data-record-authorize', response.data)
        self.assertNotIn(b'data-record-authorize checked', response.data)
        self.assertEqual(self.client.get('/').headers['Permissions-Policy'], 'microphone=(), camera=()')
        with self.app.test_request_context():
            from flask import request
            self.assertIsInstance(request._get_file_stream(1000000, 'audio/webm', 'reading.webm'), io.BytesIO)

    def test_recommendations_use_confirmed_history_and_approved_material_only(self):
        ident = self.approved()
        before = self.client.get('/pairs/1/recommendations')
        self.assertIn(b'Approved starting points', before.data)
        self.ready(ident)
        self.post(f'/activities/{ident}/evaluate', self.evaluation())
        self.sql("INSERT INTO documents(institute_id,title,source,filename) VALUES (1,'Unapproved Secret','Private','x.txt')")
        response = self.client.get('/pairs/1/recommendations')
        self.assertIn(b'Suggested approved passages', response.data)
        self.assertIn(b'Found seeds with one prompt.', response.data)
        self.assertNotIn(b'Unapproved Secret', response.data)
        self.assertIn(b'Page 1', response.data)
        chunk = self.sql('SELECT * FROM chunks LIMIT 1')[0]
        result = self.post('/activities/new', dict(pair_id=1, document_id=1, chunk_id=chunk['id']))
        self.assertIn(b'Teacher-selected recommended passage', result.data)
        self.assertEqual(self.post('/activities/new', dict(pair_id=1, document_id=1, chunk_id=999)).status_code, 400)

    def test_summary_combines_both_learners_and_preserves_historical_goals(self):
        ident = self.approved()
        self.ready(ident)
        self.post('/learners/1/edit', dict(alias='Maple',goal=GOALS['mentor'][2]))
        response = self.post(f'/activities/{ident}/evaluate', self.evaluation())
        for text in [b'Maple',b'Robin',b'Practiced skills',b'Explain word meanings',b'Find key details',
                     b'Explained community.',b'Found seeds with one prompt.',b'Page 1']:
            self.assertIn(text, response.data)
        self.assertNotIn(b'<h2>Teach vocabulary clearly</h2>', response.data)
        self.assertIn(b'View both learners', self.client.get('/progress?learner=2').data)
        restarted = create_app({'TESTING':True,'DATABASE':self.path,'SECRET_KEY':'test','READING_PROVIDER':self.provider})
        self.assertEqual(restarted.test_client().get('/sessions/1').status_code, 200)

    def test_new_workflows_enforce_institute_boundaries(self):
        ident = self.approved()
        tid = self.manual(ident)
        self.ready(ident)
        self.post(f'/activities/{ident}/evaluate', self.evaluation())
        self.sql("INSERT INTO institutes VALUES (2,'Other')")
        self.sql("INSERT INTO teachers(id,institute_id,email,password_hash,name) VALUES (2,2,'other','unused','Other')")
        self.app.config['LOCAL_TEACHER_ID'] = 2
        for path in [f'/activities/{ident}/review',f'/activities/{ident}/reading',f'/transcripts/{tid}',
                     '/sessions/1','/pairs/1/recommendations']:
            self.assertEqual(self.client.get(path).status_code, 404, path)
        for path in [f'/activities/{ident}/review',f'/activities/{ident}/transcribe',f'/transcripts/{tid}',f'/transcripts/{tid}/delete']:
            self.assertEqual(self.post(path).status_code, 404, path)

    def test_alignment_handles_skips_substitutions_insertions_and_punctuation(self):
        flags = compare_reading('Mina planted bean seeds in the garden.', 'Mina planted pea seeds in garden today.')
        self.assertEqual({flag['kind'] for flag in flags}, {'substitution','skip','insertion'})
        self.assertEqual(compare_reading('The SEED library!', 'the seed library'), [])
        self.assertEqual(compare_reading("Mina’s seed", "Mina's seed"), [])

    def test_task_validation_rejects_unattributed_words_and_unexpected_fields(self):
        valid = self.provider.adapt.return_value
        for invalid in [{**valid,'vocabulary':['notinthepassage']},{**valid,'score':100},{**valid,'buddy':12}]:
            with self.assertRaises(ProviderError):
                validate_tasks(invalid, 'The community shares seeds.')

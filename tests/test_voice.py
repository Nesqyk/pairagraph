import io
import json
import sqlite3
import tempfile
import unittest
import urllib.error
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from app import MemoryUploadRequest, create_app
from reading_ai import ProviderError, audio_extension, compare_reading, generate_story, guidance, transcribe


class VoiceTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = str(Path(self.temp.name) / 'voice.sqlite3')
        self.app = create_app({'TESTING': True, 'DATABASE': self.path, 'SECRET_KEY': 'voice-test', 'OPENAI_API_KEY': 'test-key-not-real',
                               'SPEECH_API_KEY': 'test-speech-key-not-real', 'SPEECH_PROVIDER': 'openai', 'TRANSCRIPTION_MODEL': 'gpt-transcribe', 'OPENAI_BASE_URL': 'https://api.openai.com/v1',
                               'TRANSCRIPTION_BASE_URL': 'https://api.openai.com/v1', 'STORY_API_STYLE': 'responses', 'STORY_MODEL': 'gpt-4o-mini'})
        self.client = self.app.test_client()
        self.post('/library/1/approve', {'confirm': 'yes'})
        self.post('/activities/new', {'pair_id': 1, 'document_id': 1})
        self.post('/activities/1/approve', {'confirm': 'yes'})

    def tearDown(self):
        self.temp.cleanup()

    def sql(self, statement, params=()):
        with closing(sqlite3.connect(self.path)) as conn, conn:
            conn.row_factory = sqlite3.Row
            return conn.execute(statement, params).fetchall()

    def post(self, path, data=None):
        self.client.get('/').close()
        with self.client.session_transaction() as session:
            token = session['csrf']
        response = self.client.post(path, data={**(data or {}), 'csrf': token}, follow_redirects=True)
        response.get_data()
        response.close()
        return response

    def audio(self, role='buddy', consent='yes'):
        return {'role': role, 'consent': consent, 'audio': (io.BytesIO(b'RIFF\x00\x00\x00\x00WAVEfake-test-audio'), 'reading.wav')}

    def attempt(self, role='buddy'):
        with patch('voice_routes.transcribe', return_value='The Seed Library. Every Saturday Mina visited the garden.') as provider:
            response = self.post('/activities/1/voice', self.audio(role))
            self.assertEqual(response.status_code, 200)
            provider.assert_called_once()
        return self.sql('SELECT max(id) id FROM reading_attempts')[0]['id']

    def confirm(self, ident):
        row = self.sql('SELECT * FROM reading_attempts WHERE id=?', (ident,))[0]
        analysis = json.loads(row['analysis'])
        chosen = str(analysis['issues'][0]['id'])
        response = self.post(f'/voice/{ident}', {'action': 'confirm', 'confirm': 'yes', 'issue': chosen,
                                                'reviewed_transcript': row['reviewed_transcript']})
        self.assertEqual(response.status_code, 200)

    def complete(self):
        for stage in range(3):
            self.post('/activities/1/relay', {'stage': stage})
        response = self.post('/activities/1/evaluate', dict(mentor_rating='Practicing', buddy_rating='Needs support',
            mentor_observations='Explained a word.', buddy_answers='Needed help to find details.', confirm='yes'))
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Individual next steps', response.data)

    def test_capture_consent_connection_and_provider_failures(self):
        with patch('voice_routes.transcribe') as provider:
            self.assertEqual(self.post('/activities/1/voice', self.audio(consent='no')).status_code, 400)
            self.assertEqual(self.post('/activities/1/voice', self.audio(role='unknown')).status_code, 400)
            provider.assert_not_called()
        self.app.config['SPEECH_API_KEY'] = ''
        page = self.client.get('/activities/1/voice')
        self.assertIn(b'Voice AI is not connected yet', page.data)
        self.assertEqual(self.post('/activities/1/voice', self.audio()).status_code, 503)
        self.app.config['SPEECH_API_KEY'] = 'test-key'
        with patch('voice_routes.transcribe', side_effect=ProviderError('Provider unavailable')):
            self.assertEqual(self.post('/activities/1/voice', self.audio()).status_code, 502)
        self.assertEqual(len(self.sql('SELECT * FROM reading_attempts')), 0)

    def test_no_raw_audio_storage_and_separate_learners(self):
        ident = self.attempt('buddy')
        other = self.attempt('mentor')
        self.assertEqual(self.sql('SELECT learner_id FROM reading_attempts WHERE id=?', (ident,))[0]['learner_id'], 2)
        self.assertEqual(self.sql('SELECT learner_id FROM reading_attempts WHERE id=?', (other,))[0]['learner_id'], 1)
        self.assertIsInstance(MemoryUploadRequest._get_file_stream(None, 100, 'audio/wav'), io.BytesIO)
        contents = Path(self.path).read_bytes()
        self.assertNotIn(b'fake-test-audio', contents)
        self.assertNotIn(b'test-key-not-real', contents)
        self.assertNotIn(b'reading.wav', contents)
        page = self.client.get('/progress?learner=2')
        self.assertIn(f'/voice/{ident}'.encode(), page.data)
        self.assertNotIn(f'/voice/{other}'.encode(), page.data)

    def test_correction_confirmation_and_immutable_feedback(self):
        ident = self.attempt()
        original = self.sql('SELECT transcript FROM reading_attempts WHERE id=?', (ident,))[0]['transcript']
        response = self.post(f'/voice/{ident}', {'action': 'correct', 'transcript': 'The Seed Library Every Saturday Mina and Leo visited the garden'})
        self.assertEqual(response.status_code, 200)
        row = self.sql('SELECT * FROM reading_attempts WHERE id=?', (ident,))[0]
        self.assertEqual(row['transcript'], original)
        self.assertNotEqual(row['reviewed_transcript'], original)
        self.assertEqual(self.post(f'/voice/{ident}', {'action': 'confirm', 'confirm': 'yes', 'reviewed_transcript': original}).status_code, 409)
        self.assertEqual(self.post(f'/voice/{ident}', {'action': 'confirm', 'confirm': 'yes', 'issue': '999',
                          'reviewed_transcript': row['reviewed_transcript']}).status_code, 400)
        self.confirm(ident)
        result = self.sql('SELECT * FROM reading_attempts WHERE id=?', (ident,))[0]
        self.assertEqual(result['reviewed'], 1)
        self.assertEqual(len(json.loads(result['confirmed_issues'])), 1)
        self.assertEqual(self.post(f'/voice/{ident}', {'action': 'correct', 'transcript': 'Changed'}).status_code, 409)

    def test_story_requires_completed_session_review_and_approval(self):
        ident = self.attempt()
        self.assertEqual(self.post(f'/voice/{ident}/story', {'confirm': 'yes'}).status_code, 409)
        self.confirm(ident)
        self.assertEqual(self.post(f'/voice/{ident}/story', {'confirm': 'yes'}).status_code, 409)
        self.complete()
        with patch('voice_routes.generate_story', return_value={'title': 'The New Garden', 'story': 'A short teacher-editable story.',
                            'rationale': 'Practice the confirmed target word.', 'targets': ['garden']}) as provider:
            self.assertEqual(self.post(f'/voice/{ident}/story').status_code, 400)
            response = self.post(f'/voice/{ident}/story', {'confirm': 'yes'})
            self.assertEqual(response.status_code, 200)
            provider.assert_called_once()
        self.assertEqual(len(self.sql('SELECT * FROM documents')), 1)
        self.assertEqual(self.post('/practice/1', {'title': 'Reviewed story', 'story': 'We shared seeds in the garden.'}).status_code, 400)
        self.assertEqual(self.post('/practice/1', {'title': 'Reviewed story', 'story': 'We shared seeds in the garden.', 'confirm': 'yes'}).status_code, 200)
        doc = self.sql('SELECT * FROM documents WHERE id=2')[0]
        self.assertEqual(doc['approved'], 1)
        self.assertIn('page 1, chunk 1', doc['source'])
        self.assertEqual(self.sql('SELECT text FROM chunks WHERE document_id=2')[0]['text'], 'We shared seeds in the garden.')
        self.assertEqual(self.post('/practice/1', {'confirm': 'yes'}).status_code, 200)
        self.assertEqual(len(self.sql('SELECT * FROM documents')), 2)
        self.assertEqual(self.post('/activities/new', {'pair_id': 1, 'document_id': 2}).status_code, 200)

    def test_voice_tenant_boundaries_and_capture_stage(self):
        ident = self.attempt()
        self.post('/activities/1/relay', {'stage': 0})
        self.assertEqual(self.post('/activities/1/voice', self.audio()).status_code, 409)
        self.sql("INSERT INTO institutes(id,name) VALUES (2,'Other')")
        self.sql("INSERT INTO teachers(id,institute_id,email,password_hash,name) VALUES (2,2,'other@local','unused','Other')")
        self.app.config['LOCAL_TEACHER_ID'] = 2
        for path in ['/activities/1/voice', f'/voice/{ident}', '/activities/1/feedback']:
            self.assertEqual(self.client.get(path).status_code, 404)
        self.assertEqual(self.post(f'/voice/{ident}/story', {'confirm': 'yes'}).status_code, 404)

    def test_alignment_suggestions_are_not_pronunciation_scores(self):
        self.assertEqual(compare_reading('Hello, friend!', 'hello friend')['issues'], [])
        self.assertEqual(compare_reading('The red seed grew', 'The seed grew')['issues'][0]['kind'], 'Possible omission')
        self.assertEqual(compare_reading('The seed grew', 'The seed seed grew')['issues'][0]['kind'], 'Possible addition / repetition')
        self.assertEqual(compare_reading('The seed grew', 'The tree grew')['issues'][0]['kind'], 'Possible substitution')
        self.assertEqual(compare_reading('The seed grew', 'The seed')['issues'][0]['kind'], 'Unheard ending / incomplete reading')
        self.assertNotIn('score', compare_reading('The seed grew', 'The seed'))
        self.assertIn('No specific reading difficulty', guidance([])[0])
        with self.assertRaises(ValueError):
            compare_reading('Read this', '')
        with self.assertRaises(ValueError):
            audio_extension(b'pretend audio', 'test.wav')

    def test_provider_contracts_and_safe_errors(self):
        with patch('reading_ai._call', return_value={'text': 'The seed grew.'}) as call:
            self.assertEqual(transcribe('test-key', 'gpt-transcribe', b'audio', 'webm'), 'The seed grew.')
            self.assertEqual(call.call_args.args[1], 'audio/transcriptions')
            self.assertNotIn(b'name="prompt"', call.call_args.args[2])
            self.assertIn(b'gpt-transcribe', call.call_args.args[2])
        story = {'title': 'Seed Day', 'story': ('We plant a seed. The seed can grow. ' * 9).strip(), 'rationale': 'Practice seed in short sentences.'}
        response = {'status': 'completed', 'output': [{'type': 'message', 'content': [{'type': 'output_text', 'text': json.dumps(story)}]}]}
        with patch('reading_ai._call', return_value=response) as call:
            result = generate_story('test-key', 'gpt-4o-mini', 'An approved seed story.', [{'expected': 'seed', 'heard': 'tree', 'kind': 'Possible substitution'}])
            self.assertEqual(result['targets'], ['seed'])
            payload = json.loads(call.call_args.args[2])
            self.assertFalse(payload['store'])
            self.assertTrue(payload['text']['format']['strict'])
        response['status'] = 'incomplete'
        with patch('reading_ai._call', return_value=response), self.assertRaises(ProviderError):
            generate_story('test-key', 'model', 'source', [])
        with patch('reading_ai.urllib.request.urlopen', side_effect=urllib.error.HTTPError('url', 401, 'sensitive provider message', {}, None)):
            with self.assertRaises(ProviderError) as error:
                transcribe('secret', 'model', b'audio', 'webm')
            self.assertNotIn('secret', str(error.exception))
            self.assertNotIn('sensitive', str(error.exception))

    def test_gateway_chat_completions_and_local_validation(self):
        story = {'title': 'Seed Day', 'story': ('We plant a seed. The seed can grow. ' * 9).strip(), 'rationale': 'Practice seed in short sentences.'}
        result = {'choices': [{'finish_reason': 'stop', 'message': {'content': '```json\n' + json.dumps(story) + '\n```'}}]}
        with patch('reading_ai._call', return_value=result) as call:
            draft = generate_story('gateway-test-key', 'claude-haiku-5-5', 'A seed story.',
                [{'kind': 'Possible substitution', 'expected': 'seed', 'heard': 'tree'}],
                base_url='http://gateway.invalid/api', api_style='chat_completions', timeout=300)
            self.assertEqual(draft['title'], 'Seed Day')
            self.assertEqual(call.call_args.args[1], 'chat/completions')
            self.assertEqual(call.call_args.kwargs['base_url'], 'http://gateway.invalid/api')
            self.assertEqual(call.call_args.kwargs['timeout'], 300)
            payload = json.loads(call.call_args.args[2])
            self.assertEqual(payload['model'], 'claude-haiku-5-5')
            self.assertEqual(payload['messages'][0]['role'], 'system')
            self.assertNotIn('response_format', payload)
            self.assertNotIn('input', payload)
        result['choices'][0]['finish_reason'] = 'length'
        with patch('reading_ai._call', return_value=result), self.assertRaises(ProviderError):
            generate_story('test-key', 'model', 'source', [], api_style='chat_completions')

    def test_chat_only_gateway_does_not_enable_microphone(self):
        self.app.config['SPEECH_API_KEY'] = ''
        response = self.client.get('/activities/1/voice')
        self.assertEqual(response.headers['Permissions-Policy'], 'microphone=(), camera=()')
        self.assertIn(b'Story-generation access alone cannot transcribe audio', response.data)
        with patch('voice_routes.transcribe') as provider:
            self.assertEqual(self.post('/activities/1/voice', self.audio()).status_code, 503)
            provider.assert_not_called()

    def test_gemini_voice_route_uses_separate_provider_and_saves_transcript(self):
        self.app.config.update(SPEECH_PROVIDER='gemini', SPEECH_API_KEY='gemini-test-key',
            TRANSCRIPTION_MODEL='gemini-3.8-flash', TRANSCRIPTION_BASE_URL='https://generativelanguage.googleapis.com/v1beta')
        with patch('voice_routes.transcribe_gemini', return_value='The Seed Library. Every Saturday Mina visited the garden.') as google, patch('voice_routes.transcribe') as other:
            response = self.post('/activities/1/voice', self.audio())
            self.assertEqual(response.status_code, 200)
            google.assert_called_once()
            other.assert_not_called()
            self.assertEqual(google.call_args.args[0], 'gemini-test-key')
            self.assertEqual(google.call_args.kwargs['base_url'], 'https://generativelanguage.googleapis.com/v1beta')
        saved = self.sql('SELECT * FROM reading_attempts')[0]
        self.assertEqual(saved['model'], 'gemini-3.8-flash')
        self.assertEqual(saved['learner_id'], 2)
        self.assertEqual(self.app.config['STORY_MODEL'], 'gpt-4o-mini')


if __name__ == '__main__':
    unittest.main()

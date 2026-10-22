import io
import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from app import create_app
from rag import generate_rag_activity
from reading_ai import ProviderError


class RagTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = str(Path(self.temp.name) / 'rag.sqlite3')
        self.app = create_app({'TESTING': True, 'DATABASE': self.path, 'SECRET_KEY': 'rag-test',
            'OPENAI_API_KEY': 'fake-rag-key', 'SPEECH_API_KEY': '', 'STORY_MODEL': 'claude-haiku-5-5',
            'STORY_API_STYLE': 'chat_completions', 'OPENAI_BASE_URL': 'http://gateway.invalid/api', 'AI_TIMEOUT': 300})
        self.client = self.app.test_client()

    def tearDown(self):
        self.temp.cleanup()

    def sql(self, statement, params=()):
        with closing(sqlite3.connect(self.path)) as conn, conn:
            conn.row_factory = sqlite3.Row
            return conn.execute(statement, params).fetchall()

    def post(self, path, data):
        self.client.get('/').close()
        with self.client.session_transaction() as session:
            token = session['csrf']
        response = self.client.post(path, data={**data, 'csrf': token}, follow_redirects=True)
        response.get_data()
        response.close()
        return response

    def task(self):
        return dict(mentor='Explain the meaning of garden using words from the passage.',
            buddy='Find two details that show how the children cared for their plants.',
            teach_back='Explain one new word to your partner and point to the passage.', vocabulary=['garden'],
            citations=[{'chunk_id': 1, 'quote': 'The Seed Library'}])

    def reply(self, task):
        return {'choices': [{'finish_reason': 'stop', 'message': {'content': json.dumps(task)}}]}

    def test_rag_uses_approved_context_and_preserves_attribution(self):
        self.post('/library/1/approve', {'confirm': 'yes'})
        self.post('/library', {'title': 'Unapproved secret', 'source': 'Do not retrieve',
                               'file': (io.BytesIO(b'Never include this unapproved text.'), 'secret.txt')})
        with patch('rag._call', return_value=self.reply(self.task())) as call:
            response = self.post('/activities/new', {'pair_id': 1, 'document_id': 1, 'query': 'garden', 'use_ai': 'yes'})
            self.assertEqual(response.status_code, 200)
            self.assertIn(b'RAG', response.data)
            self.assertIn(b'claude-haiku-5-5', response.data)
            payload = json.loads(call.call_args.args[2])
            context = json.loads(payload['messages'][1]['content'])
            self.assertLessEqual(len(context['retrieved_context']), 3)
            self.assertEqual(context['mentor_goal'], 'Explain word meanings')
            self.assertEqual(context['buddy_goal'], 'Find key details')
            sent = payload['messages'][1]['content']
            self.assertNotIn('Maple', sent)
            self.assertNotIn('Robin', sent)
            self.assertNotIn('Unapproved secret', sent)
            self.assertEqual(call.call_args.kwargs['timeout'], 300)
        row = self.sql('SELECT * FROM activities')[0]
        tasks = json.loads(row['tasks'])
        self.assertEqual(tasks['generation'], 'rag')
        self.assertEqual(row['status'], 'draft')
        self.assertEqual(tasks['citations'][0]['document_id'], 1)
        self.assertEqual(tasks['citations'][0]['page'], 1)
        self.assertEqual(self.client.get('/activities/1/relay').status_code, 400)

    def test_unapproved_material_never_reaches_model(self):
        with patch('rag._call') as call:
            self.assertEqual(self.post('/activities/new', {'pair_id': 1, 'document_id': 1, 'use_ai': 'yes'}).status_code, 400)
            call.assert_not_called()

    def test_invalid_quotes_and_provider_errors_use_labeled_fallback(self):
        self.post('/library/1/approve', {'confirm': 'yes'})
        task = self.task()
        task['citations'][0]['quote'] = 'An invented unsupported source quotation'
        with patch('rag._call', return_value=self.reply(task)):
            response = self.post('/activities/new', {'pair_id': 1, 'document_id': 1, 'use_ai': 'yes'})
            self.assertIn(b'Template fallback', response.data)
            self.assertNotIn(b'An invented unsupported source quotation', response.data)
        with patch('rag._call', side_effect=ProviderError('Gateway unavailable')):
            response = self.post('/activities/new', {'pair_id': 1, 'document_id': 1, 'use_ai': 'yes'})
            self.assertIn(b'This draft uses templates, not AI', response.data)
        with patch('rag._call') as call:
            self.post('/activities/new', {'pair_id': 1, 'document_id': 1})
            call.assert_not_called()

    def test_unretrieved_citations_and_invented_vocabulary_are_rejected(self):
        context = [dict(chunk_id=1, document_id=1, title='Garden', source='Original fixture', page=1, chunk=1,
                        text='The Seed Library has a community garden.')]
        for field in ['citations', 'vocabulary']:
            task = self.task()
            if field == 'citations':
                task['citations'][0]['chunk_id'] = 999
            else:
                task['vocabulary'] = ['unretrievedword']
            with patch('rag._call', return_value=self.reply(task)), self.assertRaises(ProviderError):
                generate_rag_activity('fake', 'model', context, 1, 'Vocabulary', 'Details', {},
                                      base_url='http://gateway.invalid/api', timeout=300, api_style='chat_completions')


if __name__ == '__main__':
    unittest.main()

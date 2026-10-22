import io
import json
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError

from providers import OpenAIProvider, ProviderError


class ProviderTest(unittest.TestCase):
    def setUp(self):
        self.tasks = dict(mentor='Explain the word community to your buddy.',
                          buddy='Find one important detail in this passage.',
                          teach_back='Teach one new idea back to the mentor.', vocabulary=['community'])
        self.passage = 'The community shares seeds.'

    def response(self, value):
        return io.BytesIO(json.dumps(value).encode())

    def test_responses_protocol_and_strict_schema(self):
        provider = OpenAIProvider(api_key='test-rag-key')
        with patch('providers.urlopen', return_value=self.response({
            'status':'completed', 'output':[{'type':'message','content':[{'type':'output_text','text':json.dumps(self.tasks)}]}],
        })) as transport:
            tasks = provider.adapt(self.passage, 'word meanings', 'details', '9–11')
        self.assertEqual(tasks, self.tasks)
        request = transport.call_args.args[0]
        payload = json.loads(request.data)
        self.assertFalse(payload['store'])
        self.assertTrue(payload['text']['format']['strict'])
        self.assertEqual(json.loads(payload['input'])['passage'], self.passage)
        self.assertNotIn('alias', json.loads(payload['input']))

    def test_chat_protocol_validates_json_with_source_words(self):
        provider = OpenAIProvider(api_key='test',api_mode='chat',base_url='http://example.test/api',model='rag-model')
        with patch('providers.urlopen', return_value=self.response({'choices':[{
            'finish_reason':'stop','message':{'content':'```json\n' + json.dumps(self.tasks) + '\n```'},
        }]})) as transport:
            self.assertEqual(provider.adapt(self.passage,'words','details','9–11'), self.tasks)
        request = transport.call_args.args[0]
        self.assertEqual(request.full_url, 'http://example.test/api/chat/completions')
        self.assertEqual(json.loads(request.data)['response_format']['type'], 'json_schema')

    def test_malformed_refused_and_truncated_outputs_fail_closed(self):
        provider = OpenAIProvider(api_key='test')
        cases = [{'status':'incomplete','output':[]}, {'status':'completed','output':[]},
                 {'status':'completed','output':[{'type':'message','content':[{'type':'refusal','refusal':'No'}]}]},
                 {'status':'completed','output':[{'type':'message','content':[{'type':'output_text','text':'{"mentor":12}'}]}]}]
        for data in cases:
            with patch('providers.urlopen', return_value=self.response(data)):
                with self.assertRaises(ProviderError):
                    provider.adapt(self.passage,'words','details','9–11')

    def test_network_and_auth_errors_hide_provider_payloads(self):
        provider = OpenAIProvider(api_key='test')
        for error in [URLError('private information'), TimeoutError('private information'),
                      HTTPError('https://example.test',403,'private information',{},io.BytesIO(b'private data'))]:
            with patch('providers.urlopen', side_effect=error):
                with self.assertRaises(ProviderError) as result:
                    provider.adapt(self.passage,'words','details','9–11')
                self.assertNotIn('private', str(result.exception))

    def test_separate_voice_endpoint_and_key_are_used_only_explicitly(self):
        provider = OpenAIProvider(api_key='rag-test',api_mode='chat',transcription_key='voice-test',
                                 transcription_url='https://voice.example.test/transcriptions',transcription_model='voice-model')
        with patch('providers.urlopen', return_value=self.response({'text':'The community shares seeds.'})) as transport:
            self.assertEqual(provider.transcribe(b'RIFF-test-fixture', 'audio/wav'), self.passage)
        request = transport.call_args.args[0]
        self.assertEqual(request.full_url, 'https://voice.example.test/transcriptions')
        self.assertEqual(request.get_header('Authorization'), 'Bearer voice-test')
        self.assertIn(b'voice-model', request.data)
        self.assertIn(b'RIFF-test-fixture', request.data)
        provider.transcription_url = ''
        with patch('providers.urlopen') as transport:
            with self.assertRaises(ProviderError):
                provider.transcribe(b'RIFF-test-fixture','audio/wav')
            transport.assert_not_called()

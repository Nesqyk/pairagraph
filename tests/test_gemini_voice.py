import base64
import io
import json
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

from gemini_voice import transcribe_gemini
from reading_ai import ProviderError
from voice_config import load_voice_env


class GeminiVoiceTest(unittest.TestCase):
    def response(self, transcript='The seed seed grew.'):
        data = {'candidates': [{'finishReason': 'STOP', 'content': {'parts': [{'text': json.dumps({'transcript': transcript})}]}}]}
        return io.BytesIO(json.dumps(data).encode())

    def test_inline_audio_request_and_verbatim_transcript(self):
        with patch('gemini_voice.urllib.request.urlopen', return_value=self.response()) as call:
            text = transcribe_gemini('test-gemini-key', 'gemini-3.8-flash', b'synthetic-wave', 'wav', timeout=300)
            self.assertEqual(text, 'The seed seed grew.')
            req = call.call_args.args[0]
            self.assertEqual(req.full_url, 'https://generativelanguage.googleapis.com/v1beta/models/gemini-3.8-flash:generateContent')
            self.assertNotIn('test-gemini-key', req.full_url)
            self.assertEqual(req.get_header('X-goog-api-key'), 'test-gemini-key')
            payload = json.loads(req.data)
            audio = payload['contents'][0]['parts'][1]['inlineData']
            self.assertEqual(audio['mimeType'], 'audio/wav')
            self.assertEqual(base64.b64decode(audio['data']), b'synthetic-wave')
            self.assertIn('Preserve repetitions', payload['systemInstruction']['parts'][0]['text'])
            self.assertNotIn('reference', payload)
            self.assertEqual(call.call_args.kwargs['timeout'], 300)

    def test_empty_truncated_and_malformed_transcripts_are_rejected(self):
        variants = [self.response(''), io.BytesIO(b'{}'), io.BytesIO(b'not-json'),
                    io.BytesIO(json.dumps({'candidates': [{'finishReason': 'MAX_TOKENS'}]}).encode())]
        for response in variants:
            with patch('gemini_voice.urllib.request.urlopen', return_value=response), self.assertRaises(ProviderError):
                transcribe_gemini('test-key', 'model', b'synthetic', 'wav')

    def test_provider_errors_and_credential_destination(self):
        for code in [400, 401, 403, 404, 429, 500]:
            error = urllib.error.HTTPError('url', code, 'secret-key-and-provider-detail', {}, None)
            with patch('gemini_voice.urllib.request.urlopen', side_effect=error), self.assertRaises(ProviderError) as caught:
                transcribe_gemini('test-key', 'model', b'audio', 'webm')
            self.assertNotIn('secret-key-and-provider-detail', str(caught.exception))
        for url in ['http://generativelanguage.googleapis.com/v1beta', 'https://untrusted.invalid/v1beta',
                    'https://generativelanguage.googleapis.com/v1beta?key=leak']:
            with patch('gemini_voice.urllib.request.urlopen') as call, self.assertRaises(ProviderError):
                transcribe_gemini('test-key', 'model', b'audio', 'wav', base_url=url)
            call.assert_not_called()

    def test_voice_env_is_read_without_modifying_story_configuration(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'voice.env'
            path.write_text('# private config\nexport GEMINI_API_KEY="gemini-test"\nOPENAI_API_KEY=voice-test # comment\nUNRELATED=discard\n', encoding='utf-8')
            result = load_voice_env(path)
            self.assertEqual(result, {'GEMINI_API_KEY': 'gemini-test', 'OPENAI_API_KEY': 'voice-test'})
            self.assertEqual(load_voice_env(Path(temp) / 'missing.env'), {})


if __name__ == '__main__':
    unittest.main()

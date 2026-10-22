"""Read a small, voice-only dotenv file without executing or exporting its contents."""
import re

ALLOWED = {'GEMINI_API_KEY', 'GOOGLE_API_KEY', 'OPENAI_API_KEY', 'PAIRAGRAPH_SPEECH_API_KEY',
           'PAIRAGRAPH_SPEECH_PROVIDER', 'PAIRAGRAPH_TRANSCRIPTION_MODEL', 'PAIRAGRAPH_TRANSCRIPTION_BASE_URL'}


def load_voice_env(path):
    if not path.exists():
        return {}
    values = {}
    for raw in path.read_text(encoding='utf-8-sig').splitlines():
        raw = raw.strip()
        if raw.startswith('export '):
            raw = raw[7:].strip()
        if not raw or raw.startswith('#') or '=' not in raw:
            continue
        name, value = raw.split('=', 1)
        name, value = name.strip(), value.strip()
        if name not in ALLOWED:
            continue
        if len(value) >= 2 and value[0] in ('"', "'") and value[-1] == value[0]:
            value = value[1:-1]
        else:
            value = re.split(r'\s+#', value, maxsplit=1)[0].strip()
        values[name] = value
    return values

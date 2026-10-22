import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path.cwd()))
from app import create_app
import student

def demo_transcription(*args, **kwargs):
    time.sleep(4)
    return ('Lina found a small patch of soil beside her house. She planted three seeds '
            'and gave them a little water each morning. At first, the garden looked empty. '
            'Lina waited. One day, a green shoot pushed through the soil. Soon, a blue '
            'flower opened beside it. A little bird landed on the fence and began to sing. '
            'Lina smiled. She did not need a big garden to make a happy place. She only '
            'needed a little care, a little patience, and room for things to grow.')

student.transcribe_gemini = demo_transcription
app = create_app({'DATABASE': str(Path.cwd() / 'output/pairagraph-demo/video-demo.sqlite3'),
                  'SECRET_KEY': 'isolated-video-demo', 'STUDENT_GEMINI_KEY': 'demo-only',
                  'STUDENT_STORY_KEY': ''})
app.run(host='127.0.0.1', port=5002, debug=False)

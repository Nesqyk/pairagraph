// Progressive enhancement only; all persistence and authorization live on the server.
document.querySelectorAll('[data-learner-form]').forEach((form) => {
  const role = form.querySelector('[data-role]');
  const goal = form.querySelector('[data-goal]');
  const options = Array.from(goal.options).map((option) => ({value: option.value, role: option.dataset.role}));
  function updateGoals() {
    goal.replaceChildren(...options.filter((option) => option.role === role.value).map((option) => new Option(option.value, option.value)));
  }
  role.addEventListener('change', updateGoals);
  updateGoals();
});

document.querySelectorAll('[data-recording-form]').forEach((form) => {
  const start = form.querySelector('[data-record-start]');
  const stop = form.querySelector('[data-record-stop]');
  const discard = form.querySelector('[data-record-discard]');
  const consent = form.querySelector('[data-audio-consent]');
  const role = form.querySelector('[name="role"]');
  const file = form.querySelector('[data-audio-file]');
  const playback = form.querySelector('[data-record-playback]');
  const status = form.querySelector('[data-record-status]');
  const submit = form.querySelector('[data-analyze]');
  const connected = !start.disabled;
  let recorder, stream, blob, objectUrl, timer, chunks = [], busy = false, cancelRecording = false, captureVersion = 0;

  function releaseMic() {
    clearTimeout(timer);
    if (stream) stream.getTracks().forEach((track) => track.stop());
    stream = null;
  }
  function clearAudio() {
    blob = null;
    if (objectUrl) URL.revokeObjectURL(objectUrl);
    objectUrl = null;
    playback.removeAttribute('src');
    playback.hidden = true;
    discard.disabled = true;
  }
  function reset() {
    captureVersion += 1;
    cancelRecording = true;
    if (recorder && recorder.state !== 'inactive') recorder.stop();
    releaseMic();
    clearAudio();
    file.value = '';
    file.disabled = !connected;
    stop.disabled = true;
    start.disabled = !connected;
    submit.disabled = !connected;
    role.disabled = false;
    status.textContent = 'Recording discarded. Microphone is off.';
  }
  function stopRecording() {
    if (recorder && recorder.state !== 'inactive') recorder.stop();
    releaseMic();
    stop.disabled = true;
  }
  start.addEventListener('click', async () => {
    if (!consent.checked) {
      status.textContent = 'Confirm teacher authorization before enabling the microphone.';
      consent.focus();
      return;
    }
    if (!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder) {
      status.textContent = 'This browser cannot record here. Use localhost or HTTPS in a supported browser, or upload an audio file.';
      return;
    }
    start.disabled = true;
    submit.disabled = true;
    role.disabled = true;
    file.disabled = true;
    const version = ++captureVersion;
    try {
      const acquiredStream = await navigator.mediaDevices.getUserMedia({audio: true});
      if (version !== captureVersion || !consent.checked) {
        acquiredStream.getTracks().forEach((track) => track.stop());
        return;
      }
      stream = acquiredStream;
      clearAudio();
      file.value = '';
      chunks = [];
      cancelRecording = false;
      const mimeType = ['audio/webm;codecs=opus', 'audio/webm', 'audio/mp4'].find((type) => MediaRecorder.isTypeSupported(type));
      if (!mimeType) throw new Error('Recording format is unsupported. Upload a WebM, WAV, MP3, M4A or MP4 file instead.');
      recorder = new MediaRecorder(stream, {mimeType, audioBitsPerSecond: 64000});
      recorder.addEventListener('dataavailable', (event) => { if (event.data.size) chunks.push(event.data); });
      recorder.addEventListener('stop', () => {
        releaseMic();
        start.disabled = !connected;
        submit.disabled = !connected;
        role.disabled = false;
        file.disabled = !connected;
        stop.disabled = true;
        if (cancelRecording) { chunks = []; return; }
        blob = new Blob(chunks, {type: recorder.mimeType});
        chunks = [];
        if (!blob.size || blob.size > 5 * 1024 * 1024) {
          clearAudio();
          status.textContent = 'The recording was empty or too large. Try a shorter reading.';
          return;
        }
        objectUrl = URL.createObjectURL(blob);
        playback.src = objectUrl;
        playback.hidden = false;
        discard.disabled = false;
        status.textContent = 'Microphone is off. Listen back, then send the recording for analysis.';
      });
      recorder.addEventListener('error', () => {
        reset();
        status.textContent = 'Recording failed. Microphone is off. Try again or upload an audio file.';
      });
      recorder.start();
      stop.disabled = false;
      discard.disabled = false;
      status.textContent = 'Recording this learner… Stop when they finish the passage.';
      timer = setTimeout(stopRecording, 180000);
    } catch (error) {
      if (version !== captureVersion) return;
      releaseMic();
      start.disabled = !connected;
      submit.disabled = !connected;
      role.disabled = false;
      file.disabled = !connected;
      status.textContent = error.name === 'NotAllowedError' ? 'Microphone permission was denied. Allow it in your browser or upload an audio file.' : error.message;
    }
  });
  stop.addEventListener('click', stopRecording);
  discard.addEventListener('click', reset);
  consent.addEventListener('change', () => { if (!consent.checked && !busy) reset(); });
  role.addEventListener('change', () => { if (blob || file.files.length) reset(); });
  file.addEventListener('change', () => {
    clearAudio();
    if (file.files[0]) {
      objectUrl = URL.createObjectURL(file.files[0]);
      playback.src = objectUrl;
      playback.hidden = false;
      discard.disabled = false;
      status.textContent = 'Audio selected. Listen back before sending.';
    }
  });
  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    if (busy || !form.reportValidity()) return;
    if (!blob && !file.files[0]) { status.textContent = 'Record or choose an audio file first.'; return; }
    const audio = blob || file.files[0];
    if (audio.size > 5 * 1024 * 1024) { status.textContent = 'Audio must be 5 MB or smaller.'; return; }
    const data = new FormData(form);
    if (blob) data.set('audio', blob, blob.type.includes('mp4') ? 'reading.mp4' : 'reading.webm');
    busy = true;
    submit.disabled = true;
    start.disabled = true;
    role.disabled = true;
    consent.disabled = true;
    file.disabled = true;
    discard.disabled = true;
    status.textContent = `Sending audio for transcription and comparison… This can take up to ${form.dataset.aiTimeout || 90} seconds.`;
    try {
      const response = await fetch(form.action, {method: 'POST', body: data});
      if (response.ok && response.redirected) {
        clearAudio();
        window.location.assign(response.url);
        return;
      }
      const page = new DOMParser().parseFromString(await response.text(), 'text/html');
      status.textContent = page.querySelector('main .card > p:not(.eyebrow)')?.textContent || 'Analysis failed. Your audio has not been saved. Try again.';
    } catch {
      status.textContent = 'Connection interrupted. Check the reading-attempt list before retrying; processing may have completed.';
    }
    busy = false;
    submit.disabled = !connected;
    start.disabled = !connected;
    role.disabled = false;
    consent.disabled = false;
    file.disabled = !connected;
    discard.disabled = false;
  });
  window.addEventListener('pagehide', () => { captureVersion += 1; cancelRecording = true; stopRecording(); clearAudio(); });
});

document.querySelectorAll('[data-ai-submit]').forEach((form) => {
  form.addEventListener('submit', () => {
    form.querySelector('button[type="submit"], button:not([type])').disabled = true;
    form.querySelector('[data-ai-status]').textContent = 'Preparing your draft… Shared AI capacity can take several minutes.';
  });
});

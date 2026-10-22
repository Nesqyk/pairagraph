// Progressive enhancement only; all persistence and authorization live on the server.
document.querySelectorAll('[data-generation-form]').forEach((form) => {
  const button = form.querySelector('button[type=submit]');
  const status = form.querySelector('[data-generation-status]');
  form.addEventListener('submit', (event) => {
    if (form.dataset.submitting) {
      event.preventDefault();
      return;
    }
    form.dataset.submitting = 'yes';
    form.setAttribute('aria-busy', 'true');
    button.disabled = true;
    status.textContent = 'Preparing the draft. AI requests may take up to 30 seconds; unavailable AI falls back to template tasks.';
  });
});
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

document.querySelectorAll('[data-recorder]').forEach((panel) => {
  const start = panel.querySelector('[data-record-start]');
  const stop = panel.querySelector('[data-record-stop]');
  const remove = panel.querySelector('[data-record-delete]');
  const authorize = panel.querySelector('[data-record-authorize]');
  const consent = panel.querySelector('[data-transcribe-consent]');
  const send = panel.querySelector('[data-transcribe]');
  const role = panel.querySelector('[data-reading-role]');
  const player = panel.querySelector('[data-record-playback]');
  const status = panel.querySelector('[data-record-status]');
  let recorder, stream, blob, playbackUrl, timer, controller;
  let chunks = [], bytes = 0, discard = false, generation = 0, busy = false;
  const maxBytes = 5 * 1024 * 1024;
  const available = Boolean(window.isSecureContext && navigator.mediaDevices?.getUserMedia && window.MediaRecorder);

  function stopTracks() {
    stream?.getTracks().forEach((track) => track.stop());
    stream = null;
    clearTimeout(timer);
  }
  function controls() {
    const recording = recorder?.state === 'recording';
    start.disabled = !available || !authorize.checked || busy || recording || Boolean(blob);
    stop.disabled = !recording;
    remove.disabled = !recording && !blob && !busy;
    role.disabled = Boolean(recording || blob || busy);
    if (send) send.disabled = !blob || blob.size > maxBytes || !authorize.checked || !consent.checked || busy;
  }
  function clearRecording() {
    generation += 1;
    discard = true;
    controller?.abort();
    if (recorder?.state === 'recording') recorder.stop();
    stopTracks();
    player.pause();
    player.removeAttribute('src');
    player.load();
    player.hidden = true;
    if (playbackUrl) URL.revokeObjectURL(playbackUrl);
    playbackUrl = null;
    blob = null;
    chunks = [];
    bytes = 0;
    busy = false;
    if (consent) consent.checked = false;
    controls();
  }
  start.addEventListener('click', async () => {
    if (!authorize.checked || !available) return;
    const currentGeneration = ++generation;
    busy = true;
    controls();
    status.textContent = 'Waiting for microphone permission…';
    try {
      const openedStream = await navigator.mediaDevices.getUserMedia({ audio: true });
      if (currentGeneration !== generation || !authorize.checked) {
        openedStream.getTracks().forEach((track) => track.stop());
        return;
      }
      stream = openedStream;
      const mime = ['audio/webm', 'audio/ogg', 'audio/mp4'].find((type) => MediaRecorder.isTypeSupported(type));
      recorder = mime ? new MediaRecorder(stream, { mimeType: mime }) : new MediaRecorder(stream);
      const currentRecorder = recorder;
      const currentStream = stream;
      discard = false;
      chunks = [];
      bytes = 0;
      currentRecorder.addEventListener('dataavailable', (event) => {
        if (!discard && currentGeneration === generation && event.data.size) {
          chunks.push(event.data);
          bytes += event.data.size;
          if (bytes > maxBytes && currentRecorder.state === 'recording') currentRecorder.stop();
        }
      });
      currentRecorder.addEventListener('stop', () => {
        if (currentGeneration !== generation) {
          currentStream.getTracks().forEach((track) => track.stop());
          return;
        }
        stopTracks();
        if (!discard && currentGeneration === generation) {
          blob = new Blob(chunks, { type: currentRecorder.mimeType || mime || 'audio/webm' });
          playbackUrl = URL.createObjectURL(blob);
          player.src = playbackUrl;
          player.hidden = false;
          status.textContent = blob.size > maxBytes ? 'Recording exceeds 5 MB. Delete it and record a shorter reading.' : 'Recording stopped. Play it back, delete it, or explicitly send it for transcription.';
        }
        busy = false;
        controls();
      });
      currentRecorder.addEventListener('error', () => {
        if (currentGeneration !== generation) return;
        clearRecording();
        status.textContent = 'Recording failed. Retry or enter a manual transcript.';
      });
      currentRecorder.start(500);
      timer = setTimeout(() => { if (currentRecorder.state === 'recording') currentRecorder.stop(); }, 60000);
      status.textContent = 'Recording now. Maximum 60 seconds. Nothing has been uploaded.';
      busy = false;
      controls();
    } catch {
      clearRecording();
      status.textContent = 'Microphone unavailable or permission denied. You can enter a manual transcript.';
    }
  });
  stop.addEventListener('click', () => {
    if (recorder?.state === 'recording') recorder.stop();
  });
  remove.addEventListener('click', () => {
    clearRecording();
    status.textContent = 'Recording deleted from this browser. Review any transcript already sent separately.';
  });
  authorize.addEventListener('change', () => {
    if (!authorize.checked) {
      clearRecording();
      status.textContent = 'Authorization cleared. Microphone off and local recording deleted.';
    }
    controls();
  });
  consent?.addEventListener('change', controls);
  send?.addEventListener('click', async () => {
    if (!blob || !authorize.checked || !consent.checked || busy) return;
    busy = true;
    controller = new AbortController();
    const data = new FormData();
    const mime = blob.type.split(';')[0];
    const extension = { 'audio/webm': 'webm', 'audio/ogg': 'ogg', 'audio/mp4': 'mp4' }[mime] || 'webm';
    data.append('audio', blob, `reading.${extension}`);
    data.append('csrf', panel.querySelector('[name=csrf]').value);
    data.append('role', role.value);
    data.append('authorize', 'yes');
    data.append('consent', 'yes');
    status.textContent = 'Transcribing… The result will be an unconfirmed, editable draft.';
    controls();
    try {
      const response = await fetch(panel.dataset.url, { method: 'POST', body: data, signal: controller.signal });
      const result = await response.json();
      if (!response.ok) throw new Error(result.error || 'Transcription failed. Try again or enter a manual transcript.');
      clearRecording();
      window.location.assign(result.redirect);
    } catch (error) {
      if (error.name !== 'AbortError') status.textContent = error.message.startsWith('Unexpected') ? 'The server could not process this recording. Try a shorter reading or enter a manual transcript.' : error.message;
    } finally {
      busy = false;
      controls();
    }
  });
  window.addEventListener('pagehide', clearRecording);
  if (!available) status.textContent = 'Recording needs a supported browser and localhost or HTTPS. Manual transcripts remain available.';
  controls();
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

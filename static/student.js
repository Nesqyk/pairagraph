const dialog = document.querySelector('#start-dialog');
document.querySelectorAll('[data-open-start]').forEach((button) => button.addEventListener('click', () => dialog?.showModal()));
document.querySelector('[data-close-start]')?.addEventListener('click', () => dialog.close());
dialog?.addEventListener('click', (event) => { if (event.target === dialog) dialog.close(); });
document.querySelector('[data-text-size]')?.addEventListener('click', (event) => {
  const large = document.querySelector('[data-story-prose]').classList.toggle('larger');
  event.currentTarget.setAttribute('aria-pressed', String(large));
});

const panel = document.querySelector('[data-student-recorder]');
if (panel) {
  const flow = document.querySelector('[data-reading-flow]');
  function showStory() {
    flow.classList.add('story-visible');
    const story = document.querySelector('[data-reading-story]');
    story.hidden = false;
    story.focus({preventScroll: true});
    window.scrollTo(0, 0);
  }
  const start = panel.querySelector('[data-start]');
  const stop = panel.querySelector('[data-stop]');
  const discard = panel.querySelector('[data-discard]');
  const submit = panel.querySelector('[data-submit]');
  const consent = panel.querySelector('[data-consent]');
  const playback = panel.querySelector('[data-playback]');
  const status = panel.querySelector('[data-record-status]');
  const label = panel.querySelector('[data-recorder-label]');
  const timer = panel.querySelector('[data-timer]');
  const overlay = document.querySelector('[data-processing]');
  const ready = panel.dataset.ready === 'yes';
  let recorder, stream, blob, objectUrl, interval, recordingStarted, chunks = [], canceled = false, busy = false, version = 0;
  function release() {
    clearInterval(interval);
    stream?.getTracks().forEach((track) => track.stop());
    stream = null;
    panel.classList.remove('is-recording');
  }
  function clearPlayback() {
    blob = null;
    playback.pause();
    if (objectUrl) URL.revokeObjectURL(objectUrl);
    objectUrl = null;
    playback.removeAttribute('src');
    playback.hidden = true;
  }
  function reset() {
    version += 1;
    canceled = true;
    if (recorder && recorder.state !== 'inactive') recorder.stop();
    release();
    clearPlayback();
    chunks = [];
    start.hidden = false;
    start.disabled = !ready;
    stop.hidden = true;
    discard.hidden = true;
    submit.disabled = true;
    submit.hidden = true;
    timer.innerHTML = '00:00 <span>/ 03:00</span>';
    label.textContent = 'YOUR MICROPHONE IS OFF';
    status.textContent = 'Ready to try again?';
  }
  function stopRecording() {
    if (recorder && recorder.state !== 'inactive') recorder.stop();
    release();
    stop.hidden = true;
    label.textContent = 'YOUR MICROPHONE IS OFF';
  }
  start.addEventListener('click', async () => {
    if (!consent.checked) { status.textContent = 'Tick the box before you record.'; consent.focus(); return; }
    if (!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder) { status.textContent = 'Recording is not available in this browser. Ask a grown-up to help.'; return; }
    start.disabled = true;
    const currentVersion = ++version;
    try {
      const acquired = await navigator.mediaDevices.getUserMedia({audio: true});
      if (currentVersion !== version || !consent.checked) { acquired.getTracks().forEach((track) => track.stop()); return; }
      stream = acquired;
      const type = ['audio/webm;codecs=opus', 'audio/webm', 'audio/mp4'].find((mime) => MediaRecorder.isTypeSupported(mime));
      if (!type) throw new Error('This browser cannot record your voice. Ask a grown-up to help.');
      clearPlayback();
      chunks = [];
      canceled = false;
      recorder = new MediaRecorder(stream, {mimeType: type, audioBitsPerSecond: 64000});
      recorder.addEventListener('dataavailable', (event) => { if (event.data.size) chunks.push(event.data); });
      recorder.addEventListener('stop', () => {
        release();
        if (canceled) return;
        blob = new Blob(chunks, {type: recorder.mimeType});
        chunks = [];
        if (!blob.size || blob.size > 5 * 1024 * 1024) { reset(); status.textContent = 'That recording was empty or too large. Try a shorter reading.'; return; }
        objectUrl = URL.createObjectURL(blob);
        playback.src = objectUrl;
        playback.hidden = false;
        discard.hidden = false;
        start.hidden = false;
        start.disabled = false;
        start.textContent = 'Record again';
        submit.disabled = false;
        submit.hidden = false;
        discard.hidden = true;
        label.textContent = 'YOUR READING IS READY';
        status.textContent = 'Nice work! Press See how I did.';
      });
      recorder.addEventListener('error', () => { reset(); status.textContent = 'Recording was interrupted. Your microphone is off. You can try again.'; });
      recorder.start();
      showStory();
      recordingStarted = Date.now();
      interval = setInterval(() => {
        const elapsed = Math.min(180, Math.floor((Date.now() - recordingStarted) / 1000));
        timer.innerHTML = `${String(Math.floor(elapsed / 60)).padStart(2, '0')}:${String(elapsed % 60).padStart(2, '0')} <span>/ 03:00</span>`;
        if (elapsed >= 180) stopRecording();
      }, 250);
      panel.classList.add('is-recording');
      start.hidden = true;
      stop.hidden = false;
      discard.hidden = false;
      submit.disabled = true;
      submit.hidden = true;
      label.textContent = 'LISTENING TO YOUR READING';
      status.textContent = 'Read out loud. Press Stop when you’re done.';
    } catch (error) {
      if (currentVersion !== version) return;
      release();
      start.disabled = !ready;
      status.textContent = error.name === 'NotAllowedError' ? 'Your microphone is blocked. Ask a grown-up to help turn it on.' : error.message;
    }
  });
  stop.addEventListener('click', stopRecording);
  discard.addEventListener('click', reset);
  consent.addEventListener('change', () => { if (!consent.checked && !busy) reset(); });
  async function send() {
    if (busy) return;
    if (recorder?.state === 'recording') { status.textContent = 'Press Stop on your recording first.'; return; }
    if (!consent.checked) { status.textContent = 'Tick the box so we can save your words.'; consent.focus(); return; }
    if (!blob) { status.textContent = 'Record a reading first.'; return; }
    const data = new FormData();
    data.set('csrf', panel.querySelector('[name="csrf"]').value);
    data.set('consent', 'yes');
    data.set('audio', blob, blob.type.includes('mp4') ? 'reading.mp4' : 'reading.webm');
    busy = true;
    release();
    [start, stop, discard, submit, consent].forEach((control) => control.disabled = true);
    overlay.hidden = false;
    panel.setAttribute('aria-busy', 'true');
    try {
      const response = await fetch(panel.dataset.submit, {method: 'POST', body: data});
      const result = await response.json();
      if (response.ok && result.redirect) { clearPlayback(); location.assign(result.redirect); return; }
      status.textContent = result.error || 'We couldn’t finish this reading. Please try again in a moment.';
    } catch {
      status.textContent = 'The connection was interrupted. Check My progress before trying again; your reading may already be saved.';
    }
    overlay.hidden = true;
    panel.removeAttribute('aria-busy');
    busy = false;
    [discard, consent].forEach((control) => control.disabled = false);
    start.disabled = !ready;
    submit.disabled = !blob;
  }
  submit.addEventListener('click', send);
  window.addEventListener('pagehide', () => { version += 1; canceled = true; stopRecording(); clearPlayback(); });
}
document.querySelector('[data-generate-form]')?.addEventListener('submit', (event) => {
  event.currentTarget.querySelector('button').disabled = true;
  event.currentTarget.querySelector('[data-generation-status]').textContent = 'Making your next story… This may take a few minutes.';
});

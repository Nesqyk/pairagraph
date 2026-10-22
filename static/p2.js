// Reading preferences are device-local. No microphone or provider is started here.
if (document.querySelector('.passage')) {
  const tools = document.createElement('section');
  tools.className = 'reader-tools';
  tools.setAttribute('aria-label', 'Reading display settings');
  const label = document.createElement('label');
  label.textContent = 'Reading text size';
  const size = document.createElement('select');
  for (const [value, text] of [['normal', 'Standard'], ['large', 'Large'], ['largest', 'Extra large']]) {
    size.add(new Option(text, value));
  }
  label.append(size);
  const focus = document.createElement('button');
  focus.type = 'button';
  focus.className = 'secondary';
  focus.textContent = 'Focus reading';
  focus.setAttribute('aria-pressed', 'false');
  focus.addEventListener('click', () => {
    const active = document.body.classList.toggle('reading-focus');
    focus.setAttribute('aria-pressed', String(active));
    focus.textContent = active ? 'Exit focus reading' : 'Focus reading';
  });
  function setSize(value) {
    document.body.classList.toggle('large-reading', value === 'large');
    document.body.classList.toggle('largest-reading', value === 'largest');
  }
  try { size.value = localStorage.getItem('pairagraph-reading-size') || 'normal'; } catch {}
  setSize(size.value);
  size.addEventListener('change', () => {
    setSize(size.value);
    try { localStorage.setItem('pairagraph-reading-size', size.value); } catch {}
  });
  tools.append(label, focus);
  document.querySelector('main').prepend(tools);
}

document.querySelector('[data-offline-save]')?.addEventListener('click', async (event) => {
  const status = document.querySelector('[data-offline-status]');
  const consent = document.querySelector('[data-offline-consent]');
  const button = event.currentTarget;
  if (!consent.checked) {
    status.textContent = 'Authorize storage on this device before saving an offline copy.';
    return;
  }
  button.disabled = true;
  try {
    if (!('serviceWorker' in navigator) || !window.isSecureContext) throw new Error('Offline reading requires localhost or HTTPS and service worker support.');
    status.textContent = 'Preparing the offline reader…';
    await navigator.serviceWorker.register('/service-worker.js');
    // Wait for the generic shell and its assets to finish caching before claiming success.
    await navigator.serviceWorker.ready;
    const response = await fetch(`/activities/${button.dataset.offlineSave}/offline.json`, {cache: 'no-store'});
    if (!response.ok) throw new Error('This activity could not be saved. Refresh and confirm that it is still approved and unfinished.');
    const activity = await response.json();
    const key = `pairagraph-offline:${activity.scope}:${activity.id}`;
    const existing = localStorage.getItem(key);
    if (existing) {
      const old = JSON.parse(existing);
      if (old.localStage > old.stage && !window.confirm('Replace your saved copy and discard its unsynchronized relay progress?')) {
        status.textContent = 'Your existing offline progress was kept.';
        return;
      }
    }
    localStorage.setItem(key, JSON.stringify({...activity, localStage: activity.stage, savedAt: new Date().toISOString()}));
    status.textContent = 'Saved on this device. Open Offline reading now, then test it with the connection turned off.';
  } catch (error) {
    status.textContent = `${error.message} If device storage is unavailable or full, use the online relay.`;
  } finally {
    button.disabled = false;
  }
});

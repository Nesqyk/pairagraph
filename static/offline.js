// This shell has no embedded workspace identity, credentials, or learner data.
const list = document.getElementById('offline-list');
const status = document.getElementById('offline-status');
const PREFIX = 'pairagraph-offline:';
const stages = ['Read', 'Retell', 'Teach-back', 'Ready for online teacher evaluation'];
function element(tag, text, className) {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  if (className) node.className = className;
  return node;
}
function copies() {
  return Object.keys(localStorage).filter((key) => key.startsWith(PREFIX));
}
function render() {
  list.replaceChildren();
  try {
    const keys = copies();
    status.textContent = keys.length ? `${keys.length} saved activities. Synchronization is always explicit.` : 'No offline activities yet. Open an approved Story Relay online and choose Save for offline reading.';
    for (const key of keys) {
      let copy;
      try { copy = JSON.parse(localStorage.getItem(key)); } catch { continue; }
      const card = element('article', undefined, 'card');
      card.append(element('h2', copy.source.title), element('p', `${copy.mentor} + ${copy.buddy}`),
        element('p', `Saved ${copy.savedAt} · Current offline step: ${stages[copy.localStage]}`));
      const passage = element('p', copy.passage, 'passage');
      card.append(passage, element('p', `Source: ${copy.source.source} · Page ${copy.source.page_number} · Chunk ${copy.source.chunk_number}`),
        element('h3', `${copy.mentor} · ${copy.mentor_goal}`), element('p', copy.tasks.mentor),
        element('h3', `${copy.buddy} · ${copy.buddy_goal}`), element('p', copy.tasks.buddy),
        element('h3', 'Teach-back'), element('p', copy.tasks.teach_back));
      const message = element('p', undefined);
      message.setAttribute('role', 'status');
      if (copy.localStage < 3) {
        const next = element('button', `Complete ${stages[copy.localStage]}`);
        next.addEventListener('click', () => {
          try {
            const latest = JSON.parse(localStorage.getItem(key));
            if (!latest || latest.revision !== copy.revision || latest.localStage !== copy.localStage) {
              render();
              return;
            }
            localStorage.setItem(key, JSON.stringify({...copy, localStage: copy.localStage + 1}));
            render();
          } catch { message.textContent = 'Local storage failed. Progress was not saved; keep this page open and reconnect.'; }
        });
        card.append(next);
      }
      const sync = element('button', 'Synchronize relay progress');
      sync.className = 'secondary';
      sync.addEventListener('click', async () => {
        sync.disabled = true;
        message.textContent = 'Checking the online workspace…';
        try {
          const latest = JSON.parse(localStorage.getItem(key));
          if (!latest || latest.revision !== copy.revision || latest.localStage !== copy.localStage) throw new Error('This local copy changed in another tab. Reload the offline reader.');
          const contextResponse = await fetch('/offline/context', {cache: 'no-store'});
          if (!contextResponse.ok) throw new Error('Reconnect to the online workspace before synchronizing.');
          const context = await contextResponse.json();
          if (context.scope !== copy.scope) throw new Error('This copy belongs to a different workspace. It was not sent.');
          const response = await fetch(`/activities/${copy.id}/offline-sync`, {method: 'POST',
            body: new URLSearchParams({csrf: context.csrf, scope: copy.scope, revision: copy.revision, stage: String(copy.localStage)})});
          const result = await response.json();
          if (!response.ok) throw new Error(result.error || 'Synchronization failed. Your local copy was kept.');
          // Fetch a new base revision only when the online update is confirmed.
          const freshResponse = await fetch(`/activities/${copy.id}/offline.json`, {cache: 'no-store'});
          if (!freshResponse.ok) throw new Error('Progress was synchronized. Reopen the online activity before syncing again.');
          const fresh = await freshResponse.json();
          const after = JSON.parse(localStorage.getItem(key));
          if (after && after.revision === copy.revision && after.localStage === copy.localStage) {
            localStorage.setItem(key, JSON.stringify({...fresh, localStage: fresh.stage, savedAt: new Date().toISOString()}));
          }
          render();
          status.textContent = 'Relay progress synchronized. Complete teacher evaluation in the online workspace.';
        } catch (error) { message.textContent = error.message || 'Could not connect. Your local progress was kept.'; }
        finally { sync.disabled = false; }
      });
      const remove = element('button', 'Delete this offline copy');
      remove.className = 'secondary';
      remove.addEventListener('click', () => {
        if (!window.confirm('Delete this saved activity and any unsynchronized progress from this device?')) return;
        try { localStorage.removeItem(key); render(); } catch { message.textContent = 'Could not delete device storage. Clear site data in browser settings.'; }
      });
      const online = element('a', 'Open online activity');
      online.href = `/activities/${Number(copy.id)}/relay`;
      card.append(sync, remove, online, message);
      list.append(card);
    }
  } catch { status.textContent = 'Device storage is unavailable. Use the online workspace.'; }
}
document.getElementById('offline-clear').addEventListener('click', async () => {
  if (!window.confirm('Delete all offline activities and unsynchronized progress on this device?')) return;
  try {
    copies().forEach((key) => localStorage.removeItem(key));
    for (const key of await caches.keys()) if (key.startsWith('pairagraph-offline-')) await caches.delete(key);
    const registrations = await navigator.serviceWorker?.getRegistrations() || [];
    for (const registration of registrations) if (registration.active?.scriptURL === `${location.origin}/service-worker.js`) await registration.unregister();
    render();
  } catch { status.textContent = 'Could not clear all data. Clear site data in browser settings.'; }
});
window.addEventListener('storage', render);
render();

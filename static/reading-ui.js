// Presentation only: the existing recorder and server own consent and persistence.
const flow = document.querySelector('[data-reading-flow]');
if (flow) {
  const panel = flow.querySelector('[data-recorder]');
  const loading = flow.querySelector('[data-analyzing]');
  const analysis = flow.querySelector('[data-analysis-content]');
  const analysisStatus = flow.querySelector('[data-analysis-status]');
  const jump = (id) => {
    const target = document.getElementById(id);
    target.scrollIntoView({block: 'start', behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'instant' : 'smooth'});
    target.querySelector('h2')?.focus({preventScroll: true});
  };
  const screen = (name) => {
    if (loading) loading.hidden = name !== 'analyzing';
    analysis.setAttribute('aria-busy', String(name === 'analyzing'));
    if (name === 'analyzing') {analysisStatus.replaceChildren(); jump('analysis');}
  };
  flow.querySelector('[data-begin]')?.addEventListener('click', (event) => {event.preventDefault(); jump('reading');});
  const links = [...flow.querySelectorAll('.reader-section-nav a')];
  links.forEach(link => link.addEventListener('click', event => {event.preventDefault(); jump(link.hash.slice(1));}));
  const sections = [...flow.querySelectorAll('.reader-section')];
  const updateCurrent = () => {
    const current = sections.filter(section => section.getBoundingClientRect().top < 180).at(-1) || sections[0];
    links.forEach(link => {
      if (link.hash === '#' + current.id) link.setAttribute('aria-current', 'location');
      else link.removeAttribute('aria-current');
    });
  };
  window.addEventListener('scroll', updateCurrent, {passive: true});
  updateCurrent();
  let resultController;
  const loadResults = async (url) => {
    resultController?.abort();
    const controller = new AbortController();
    resultController = controller;
    flow.dataset.resultsBusy = 'true';
    screen('analyzing');
    analysisStatus.replaceChildren();
    try {
      const response = await fetch(url, {signal: controller.signal});
      if (!response.ok) throw new Error('comparison');
      const doc = new DOMParser().parseFromString(await response.text(), 'text/html');
      const content = doc.querySelector('[data-result-content]');
      if (!content) throw new Error('comparison');
      analysis.replaceChildren(content);
      highlightReading(analysis);
      const actions = [...analysis.querySelectorAll('.reader-bottom a')];
      actions[0].href = '#reading';
      actions[0].addEventListener('click', event => {event.preventDefault(); jump('reading');});
      actions[1].href = '#progress';
      actions[1].setAttribute('aria-label', 'Save');
      actions[1].addEventListener('click', event => {
        event.preventDefault(); analysisStatus.textContent = 'Draft saved.'; jump('progress');
      });
      actions[2].href = '#next-story';
      actions[2].addEventListener('click', event => {event.preventDefault(); jump('next-story');});
      const history = flow.querySelector('[data-reading-history]');
      if (![...history.querySelectorAll('a')].some(link => link.href === new URL(url, location.href).href)) {
        history.querySelector('[data-empty-history]')?.remove();
        const link = document.createElement('a');
        link.href = url;
        link.dataset.viewTranscript = '';
        link.textContent = content.querySelector('.reader-result-heading .reader-chip').textContent + ' - Saved draft';
        history.prepend(link);
      }
      analysisStatus.textContent = 'Reading saved. Comparison ready.';
    } catch (error) {
      if (error.name === 'AbortError') return;
      analysisStatus.textContent = 'Could not load this saved reading. ';
      const retry = document.createElement('button');
      retry.type = 'button'; retry.className = 'secondary'; retry.textContent = 'Retry';
      retry.addEventListener('click', () => loadResults(url));
      const link = document.createElement('a'); link.href = url; link.textContent = 'Open reading';
      analysisStatus.append(retry, document.createTextNode(' '), link);
    } finally {
      if (resultController === controller) {delete flow.dataset.resultsBusy; screen('ready');}
    }
  };
  flow.addEventListener('reading-saved', event => loadResults(event.detail.url));
  flow.querySelector('[data-reading-history]').addEventListener('click', event => {
    const link = event.target.closest('[data-view-transcript]');
    if (!link || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
    event.preventDefault(); loadResults(link.href);
  });
  const next = flow.querySelector('[data-next-url]');
  const loadNext = async () => {
    const retry = next.querySelector('[data-next-retry]');
    retry.hidden = true;
    try {
      const response = await fetch(next.dataset.nextUrl);
      if (!response.ok) throw new Error('stories');
      const doc = new DOMParser().parseFromString(await response.text(), 'text/html');
      const stories = doc.querySelector('.reader-next-list');
      if (!stories) throw new Error('stories');
      next.querySelector('[data-next-content]').replaceChildren(stories);
    } catch {
      next.querySelector('[data-next-content]').textContent = 'Stories could not load. Try again.';
      retry.hidden = false;
    }
  };
  next.querySelector('[data-next-retry]').addEventListener('click', loadNext);
  loadNext();
  if (panel) {
    const role = panel.querySelector('[data-reading-role]');
    const manualRole = flow.querySelector('[name=role]');
    const requestedRole = new URLSearchParams(location.search).get('reader');
    if (['mentor', 'buddy'].includes(requestedRole)) role.value = requestedRole;
    const syncRole = () => {
      flow.querySelector('[data-role-chip]').textContent = role.value === 'mentor' ? 'Mentor' : 'Buddy';
      manualRole.value = role.value;
    };
    role.addEventListener('change', syncRole);
    syncRole();
    const stop = panel.querySelector('[data-record-stop]');
    const player = panel.querySelector('[data-record-playback]');
    const timer = panel.querySelector('[data-record-timer]');
    const status = panel.querySelector('[data-record-status]');
    const friendlyStatus = document.createElement('p');
    friendlyStatus.className = 'reader-muted';
    friendlyStatus.setAttribute('role', 'status');
    friendlyStatus.setAttribute('aria-live', 'polite');
    status.hidden = true;
    status.setAttribute('aria-live', 'off');
    status.after(friendlyStatus);
    let started = null, interval, previousMessage = '';
    const refresh = () => {
      const recording = !stop.disabled;
      panel.dataset.recording = String(recording);
      panel.dataset.recorded = String(!player.hidden && Boolean(player.getAttribute('src')));
      if (recording && started === null) {
        if (document.activeElement === panel.querySelector('[data-record-start]')) stop.focus({preventScroll: true});
        started = Date.now();
        const tick = () => {
          const elapsed = Math.min(60, Math.floor((Date.now() - started) / 1000));
          timer.textContent = `${Math.floor(elapsed / 60)}:${String(elapsed % 60).padStart(2, '0')} / 1:00`;
        };
        tick();
        interval = setInterval(tick, 250);
      } else if (!recording && started !== null) {
        clearInterval(interval);
        started = null;
        if (document.activeElement === stop && !player.hidden) player.focus({preventScroll: true});
      }
      if (!recording && player.hidden && timer.textContent !== '0:00 / 1:00') timer.textContent = '0:00 / 1:00';
      const message = status.textContent;
      let short = message;
      if (message.startsWith('Recording now')) short = 'Reading…';
      else if (message.startsWith('Recording stopped')) short = 'Ready to play back.';
      else if (message.startsWith('Recording deleted') || message.startsWith('Authorization cleared')) short = 'Recording deleted. Microphone off.';
      else if (message.startsWith('Microphone unavailable') || message.startsWith('Recording needs')) short = 'Microphone unavailable. Try again or type instead.';
      else if (message.startsWith('Recording exceeds')) short = 'Recording too long. Delete it and try again.';
      else if (message.startsWith('Transcribing')) short = 'Finding practice ideas…';
      else if (message.length > 100) short = 'Something went wrong. Try again or type instead.';
      if (friendlyStatus.textContent !== short) friendlyStatus.textContent = short;
      if (message.startsWith('Transcribing') && message !== previousMessage) screen('analyzing');
      else if (!message.startsWith('Transcribing') && previousMessage.startsWith('Transcribing') && !flow.dataset.manualBusy && !flow.dataset.resultsBusy) screen('reading');
      previousMessage = message;
    };
    new MutationObserver(refresh).observe(panel, {subtree: true, attributes: true, attributeFilter: ['disabled', 'src', 'hidden'], childList: true, characterData: true});
    refresh();
    panel.querySelector('[data-record-delete]').addEventListener('click', () => panel.querySelector('[data-record-start]').focus({preventScroll: true}));
    window.addEventListener('pagehide', () => clearInterval(interval));
    const form = flow.querySelector('[data-manual-form]');
    form.addEventListener('submit', async (event) => {
      event.preventDefault();
      if (flow.dataset.manualBusy) return;
      flow.dataset.manualBusy = 'true';
      const data = new FormData(form);
      const button = form.querySelector('button');
      button.disabled = true;
      // Entering a transcript is also leaving the recording step; discard local audio.
      panel.querySelector('[data-record-delete]').click();
      screen('analyzing');
      try {
        const response = await fetch(form.action, {method: 'POST', body: data});
        if (!response.ok || !response.redirected) throw new Error('save');
        const destination = new URL(response.url);
        destination.searchParams.set('view', 'student');
        await loadResults(destination.href);
        button.disabled = false;
      } catch {
        screen('reading');
        form.querySelector('[data-manual-status]').textContent = 'Could not save. Please try again.';
        button.textContent = 'Retry';
        button.disabled = false;
        button.focus();
      } finally { delete flow.dataset.manualBusy; }
    });
  }
}

// Use real server comparison positions; text nodes preserve punctuation and escaping.
function highlightReading(root) {
const reference = root.querySelector('[data-reference]');
if (!reference) return;
  const text = reference.textContent;
  const words = [...text.matchAll(/[\p{L}\p{N}_]+(?:['’][\p{L}\p{N}_]+)*/gu)];
  const flags = [...root.querySelectorAll('[data-flag]')];
  const fragment = document.createDocumentFragment();
  const extra = (flag) => {
    const mark = document.createElement('mark');
    mark.className = 'reader-insertion reader-extra';
    mark.textContent = ' + ';
    mark.setAttribute('aria-label', 'Possible extra words; check the comparison below');
    fragment.append(mark);
  };
  let offset = 0;
  words.forEach((word, index) => {
    fragment.append(document.createTextNode(text.slice(offset, word.index)));
    flags.filter(flag => flag.dataset.kind === 'insertion' && Number(flag.dataset.start) === index + 1).forEach(extra);
    const flag = flags.find(flag => flag.dataset.kind !== 'insertion' && Number(flag.dataset.start) <= index + 1 && Number(flag.dataset.end) >= index + 1);
    if (flag) {
      const mark = document.createElement('mark');
      mark.className = `reader-${flag.dataset.kind}`;
      mark.textContent = word[0];
      mark.setAttribute('aria-label', `Check ${word[0]}: possible ${flag.dataset.kind === 'skip' ? 'skip' : 'swap'}`);
      fragment.append(mark);
    } else fragment.append(document.createTextNode(word[0]));
    offset = word.index + word[0].length;
  });
  fragment.append(document.createTextNode(text.slice(offset)));
  flags.filter(flag => flag.dataset.kind === 'insertion' && Number(flag.dataset.start) > words.length).forEach(extra);
  reference.replaceChildren(fragment);
}

highlightReading(document);

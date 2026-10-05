import { initializeApp } from 'https://www.gstatic.com/firebasejs/12.19.0/firebase-app.js';
import {
  getAuth, isSignInWithEmailLink, onAuthStateChanged, sendSignInLinkToEmail,
  signInWithEmailLink, signOut,
} from 'https://www.gstatic.com/firebasejs/12.19.0/firebase-auth.js';
import { getFunctions, httpsCallable } from 'https://www.gstatic.com/firebasejs/12.19.0/firebase-functions.js';

const firebaseConfig = {
  apiKey: 'AIzaSyD-G145nHdP-4rCi4-3BrQNvMqjovpQpbA',
  authDomain: 'padua-workshop-groups-2026.firebaseapp.com',
  projectId: 'padua-workshop-groups-2026',
  storageBucket: 'padua-workshop-groups-2026.firebasestorage.app',
  messagingSenderId: '50920565432',
  appId: '1:50920565432:web:7b81b6ad2ad91ebe63e24d',
};
const app = initializeApp(firebaseConfig);
const auth = getAuth(app);
const functions = getFunctions(app, 'europe-west1');
const workshopApi = httpsCallable(functions, 'workshop_api', { timeout: 30000 });
const generateGroups = httpsCallable(functions, 'generate_groups', { timeout: 300000 });
const appEl = document.querySelector('#app');
const accountEl = document.querySelector('#account');
const noticeEl = document.querySelector('#notice');
let state = null;
let busy = false;
let wishes = new Set();
let vetoes = new Set();

const esc = (value) => String(value ?? '').replace(/[&<>"']/g, (c) => ({
  '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
}[c]));
const qs = (selector) => document.querySelector(selector);
function notice(message, error = false) {
  noticeEl.innerHTML = message ? `<div class="notice ${error ? 'error' : ''}">${esc(message)}</div>` : '';
  if (message) noticeEl.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
}
function errorMessage(error) {
  const text = String(error?.message || error || 'Something went wrong');
  return text.replace(/^.*?\)\s*/, '').replace(/^Firebase:\s*/, '');
}
function phaseLabel(phase) {
  return ({ setup: 'Getting ready', enrollment: 'Registration open', preferences: 'Preferences open', matching: 'Matching in progress', published: 'Groups published' })[phase] || phase;
}
function steps(phase) {
  const labels = [['enrollment', '1 Register'], ['preferences', '2 Choose groupmates'], ['matching', '3 Form groups'], ['published', '4 See your group']];
  return `<div class="steps" aria-label="Workshop progress">${labels.map(([key, label]) => `<span class="${key === phase ? 'current' : ''}">${label}</span>`).join('')}</div>`;
}
function selectOptions(values, current) {
  return values.map(([value, label]) => `<option value="${esc(value)}" ${value === current ? 'selected' : ''}>${esc(label)}</option>`).join('');
}
const careers = [
  ['student_under_3', 'Student · under 3 years of work after BA'],
  ['student_3_plus', 'Student · 3 or more years of work after BA'],
  ['junior_faculty', 'Junior faculty'], ['senior_faculty', 'Senior faculty'], ['other', 'Other'],
];
const familiarity = [
  ['low', 'Low · occasional chat use'], ['medium', 'Medium · weekly research use, mostly chat'],
  ['high', 'High · weekly agentic research use'], ['very_high', 'Very high · expert workflows'],
];
const subscriptions = [['none', 'None'], ['20', '$20/month plan or better'], ['100', '$100/month plan or better, or equivalent API credits']];
const genders = [['woman', 'Woman'], ['man', 'Man'], ['nonbinary', 'Nonbinary'], ['other', 'Another description'], ['prefer_not_to_say', 'Prefer not to say']];

function renderAuth(completeLink = false) {
  accountEl.innerHTML = '';
  appEl.innerHTML = `<section class="card" style="max-width:660px">
    <h2>${completeLink ? 'Complete sign-in' : 'Sign in by email'}</h2>
    <p class="muted">${completeLink ? 'Enter the same email address to which this sign-in link was sent.' : 'We will email you a one-time sign-in link. Any email address you can access will work.'}</p>
    <form id="email-form" class="stack">
      <div class="field"><label for="email">Email address</label><input id="email" name="email" type="email" autocomplete="email" required /></div>
      <div class="actions"><button class="button" type="submit">${completeLink ? 'Complete sign-in' : 'Send sign-in link'}</button></div>
    </form>
  </section>`;
  qs('#email-form').addEventListener('submit', async (event) => {
    event.preventDefault();
    const email = qs('#email').value.trim().toLowerCase();
    await working(async () => {
      if (completeLink) {
        await signInWithEmailLink(auth, email, location.href);
        localStorage.removeItem('paduaEmailForSignIn');
        history.replaceState(null, '', location.pathname);
        await refresh();
        notice('Signed in.');
      } else {
        await sendSignInLinkToEmail(auth, email, { url: `${location.origin}${location.pathname}`, handleCodeInApp: true });
        localStorage.setItem('paduaEmailForSignIn', email);
        notice(`Sign-in link sent to ${email}. Check your inbox and spam folder.`);
      }
    });
  });
}

async function working(task) {
  if (busy) return;
  busy = true;
  const buttonStates = [...document.querySelectorAll('button')].map((button) => [button, button.disabled]);
  buttonStates.forEach(([button]) => { button.disabled = true; });
  try { await task(); }
  catch (error) { console.error(error); notice(errorMessage(error), true); }
  finally { busy = false; buttonStates.forEach(([button, disabled]) => { if (button.isConnected) button.disabled = disabled; }); }
}
async function call(action, extra = {}) {
  const response = await workshopApi({ action, ...extra });
  return response.data;
}
async function refresh() {
  if (!auth.currentUser) return renderAuth();
  state = await call('state');
  wishes = new Set(state.preferences?.wishes || []);
  vetoes = new Set(state.preferences?.vetoes || []);
  render();
}

function render() {
  const email = state.email || auth.currentUser?.email || '';
  accountEl.innerHTML = `<small>${esc(email)}</small><button id="sign-out" type="button">Sign out</button>`;
  qs('#sign-out').addEventListener('click', () => working(async () => { await signOut(auth); state = null; renderAuth(); notice('Signed out.'); }));
  const phase = state.config.phase;
  appEl.innerHTML = `${steps(phase)}<div class="card"><span class="pill ${phase === 'matching' ? 'warn' : ''}">${esc(phaseLabel(phase))}</span>
    <p class="muted small">${phase === 'setup' ? 'The organizer is preparing registration.' : phase === 'enrollment' ? 'Please complete your registration now.' : phase === 'preferences' ? 'Choose people you would be happy to work with and list any people you cannot be grouped with.' : phase === 'matching' ? 'Responses are closed while groups are formed.' : 'Your group is ready below.'}</p></div>
    ${renderParticipant()}${state.isAdmin ? renderAdmin() : ''}`;
  bindParticipant();
  if (state.isAdmin) bindAdmin();
}

function renderParticipant() {
  const phase = state.config.phase;
  if (phase === 'enrollment') return renderProfile();
  if (!state.profile) return `<section class="card"><h2>Registration is closed</h2><p>Please contact the organizer if you need to join.</p></section>`;
  if (!state.profile.approved) return `<section class="card"><h2>Registration received</h2><p>The organizer is reviewing the roster. Your name is not yet shown to other participants.</p></section>`;
  if (phase === 'preferences') return renderPreferences();
  if (phase === 'published') return renderAssignment();
  return `<section class="card"><h2>You are registered</h2><p>Thank you, ${esc(state.profile.name)}. ${phase === 'setup' ? 'The workshop is not open yet.' : 'The organizer is forming groups.'}</p></section>`;
}
function renderProfile() {
  const p = state.profile || {};
  return `<section class="card"><h2>${p.name ? 'Update your registration' : 'Register for the workshop'}</h2>
    <p class="muted">Your survey answers and email address are available to the organizer. Other participants see only your name and institution after the roster is approved. Your free-text response is read in anonymous form and is not used in automated matching.</p>
    <form id="profile-form" class="stack">
      <div class="grid2"><div class="field"><label for="name">Name *</label><input id="name" name="name" maxlength="100" value="${esc(p.name)}" required /></div>
      <div class="field"><label for="institution">Institution</label><input id="institution" name="institution" maxlength="120" value="${esc(p.institution)}" /></div></div>
      <div class="field"><label for="career">Career stage *</label><select id="career" name="career" required><option value="">Choose one</option>${selectOptions(careers, p.career)}</select></div>
      <div class="field"><label for="familiarity">Familiarity with AI tools *</label><select id="familiarity" name="familiarity" required><option value="">Choose the highest level that applies</option>${selectOptions(familiarity, p.familiarity)}</select><small>Do not choose above medium unless you have run an agent on your computer that modifies files or runs code. High means at least an hour a week of agentic research or similar work. Very high means expert workflows and regular engagement with current developments.</small></div>
      <div class="grid2"><div class="field"><label for="subscription">Coding agent access *</label><select id="subscription" name="subscription" required><option value="">Choose one</option>${selectOptions(subscriptions, p.subscription)}</select></div>
      <div class="field"><label for="gender">Gender *</label><select id="gender" name="gender" required><option value="">Choose one</option>${selectOptions(genders, p.gender)}</select></div></div>
      <div class="field"><label for="reflection">What are you thinking about after the presentation?</label><textarea id="reflection" name="reflection" maxlength="2000" placeholder="How you feel, or what you would like to get from the exercise">${esc(p.reflection)}</textarea><small>Ben will mostly read responses anonymously. They are excluded from automated matching.</small></div>
      <div class="actions"><button class="button" type="submit">Save registration</button>${p.name ? '<span class="pill">Saved previously</span>' : ''}</div>
    </form></section>`;
}
function renderPreferences() {
  const roster = (state.roster || []).filter((p) => p.id !== auth.currentUser.uid).sort((a, b) => a.name.localeCompare(b.name));
  return `<section class="card"><h2>Choose your groupmates</h2>
    <p class="muted">Select at least ten people you would like to, or would be very open to, working with. Random names are fine if you do not know ten people. You may also veto anyone you cannot be grouped with. Vetoes are private.</p>
    <div class="field"><label for="roster-search">Find a participant</label><input class="search" id="roster-search" type="search" placeholder="Search by name or institution" /></div>
    <p id="preference-count" class="small"></p><div class="roster" id="roster" aria-label="Participant roster"></div>
    <div class="actions"><button class="button" id="save-preferences" type="button">Save choices</button>${state.preferences ? '<span class="pill">Saved previously</span>' : ''}</div>
    <p class="small muted">You can revise your choices until the organizer closes this phase.</p>
  </section>`;
}
function drawRoster(filter = '') {
  const roster = (state.roster || []).filter((p) => p.id !== auth.currentUser.uid).sort((a, b) => a.name.localeCompare(b.name));
  const term = filter.trim().toLowerCase();
  const visible = roster.filter((p) => `${p.name} ${p.institution}`.toLowerCase().includes(term));
  qs('#preference-count').textContent = `${wishes.size} preferred selected (at least ${Math.min(10, roster.length)} required) · ${vetoes.size} vetoes selected`;
  qs('#roster').innerHTML = visible.length ? visible.map((p) => `<div class="roster-row" data-id="${esc(p.id)}">
    <span><strong>${esc(p.name)}</strong><small>${esc(p.institution)}</small></span>
    <label><input type="checkbox" data-kind="wish" ${wishes.has(p.id) ? 'checked' : ''} /> Prefer</label>
    <label><input type="checkbox" data-kind="veto" ${vetoes.has(p.id) ? 'checked' : ''} /> Veto</label>
  </div>`).join('') : '<p class="muted" style="padding:1rem">No matching names.</p>';
}
function renderAssignment() {
  const a = state.assignment;
  if (!a) return '<section class="card"><h2>Assignments are being published</h2><p>Please refresh shortly.</p></section>';
  return `<section class="card"><span class="pill">Group ${esc(a.group)}</span><h2>Your working group</h2>
    <ul>${(a.teammates || []).map((p) => `<li>${esc(p.name)}${p.id === auth.currentUser.uid ? ' (you)' : ''}</li>`).join('')}</ul>
    <p class="muted">Please meet your group at the location announced by the organizer.</p></section>`;
}
function bindParticipant() {
  const profile = qs('#profile-form');
  if (profile) profile.addEventListener('submit', (event) => {
    event.preventDefault();
    working(async () => {
      const data = Object.fromEntries(new FormData(profile));
      state = await call('saveProfile', { profile: data });
      render(); notice('Registration saved.');
    });
  });
  if (qs('#roster')) {
    drawRoster();
    qs('#roster-search').addEventListener('input', (event) => drawRoster(event.target.value));
    qs('#roster').addEventListener('change', (event) => {
      const input = event.target;
      const id = input.closest('[data-id]')?.dataset.id;
      if (!id) return;
      const set = input.dataset.kind === 'wish' ? wishes : vetoes;
      const other = input.dataset.kind === 'wish' ? vetoes : wishes;
      if (input.checked) { set.add(id); other.delete(id); } else set.delete(id);
      drawRoster(qs('#roster-search').value);
    });
    qs('#save-preferences').addEventListener('click', () => working(async () => {
      state = await call('savePreferences', { wishes: [...wishes], vetoes: [...vetoes] });
      render(); notice('Groupmate choices saved.');
    }));
  }
}

function renderAdmin() {
  const admin = state.admin || { profiles: [], preferences: {}, runs: [] };
  const profiles = admin.profiles || [];
  const approved = profiles.filter((p) => p.approved);
  const pending = profiles.filter((p) => !p.approved);
  const completed = approved.filter((p) => admin.preferences[p.id]?.wishes?.length >= 10);
  const phase = state.config.phase;
  return `<section class="card" id="organizer"><span class="pill neutral">Organizer</span><h2>Workshop control</h2>
    <div class="summary"><div class="metric"><strong>${profiles.length}</strong><span>registered</span></div><div class="metric"><strong>${approved.length}</strong><span>approved</span></div><div class="metric"><strong>${completed.length}</strong><span>choices complete</span></div><div class="metric"><strong>${admin.runs.length}</strong><span>recent runs</span></div></div>
    <h3>Phase</h3><p class="muted small">Changing phase closes or opens participant forms. Published assignments appear only while the phase is “Groups published.”</p>
    <div class="actions">${[['enrollment', 'Open registration'], ['preferences', 'Freeze roster · open choices'], ['matching', 'Close choices · match']].map(([value, label]) => `<button class="button ${phase === value ? '' : 'secondary'}" data-phase="${value}" type="button">${label}</button>`).join('')}</div>
  </section>
  <section class="card"><h2>Roster review</h2><p class="muted">Only approved participants appear on the groupmate selection list. Check unexpected or duplicate names before opening choices.</p>
    <div class="actions"><button class="button secondary" id="approve-all" type="button" ${pending.length ? '' : 'disabled'}>Approve all ${pending.length} pending</button><button class="button secondary" id="export" type="button">Download organizer JSON</button><button class="button secondary" id="export-csv" type="button">Download roster CSV</button></div>
    <div class="table-wrap"><table class="admin-table"><thead><tr><th>Name</th><th>Email</th><th>Institution</th><th>Choices</th><th>Status</th></tr></thead><tbody>${profiles.sort((a,b) => a.name.localeCompare(b.name)).map((p) => `<tr><td>${esc(p.name)}</td><td>${esc(p.email)}</td><td>${esc(p.institution)}</td><td>${admin.preferences[p.id]?.wishes?.length || 0}</td><td><button class="button secondary" data-approve="${esc(p.id)}" data-next="${p.approved ? 'false' : 'true'}" type="button">${p.approved ? 'Approved' : 'Approve'}</button></td></tr>`).join('')}</tbody></table></div>
    <details><summary>Anonymous reflections (${profiles.filter((p) => p.reflection).length})</summary><ol>${profiles.filter((p) => p.reflection).map((p) => `<li>${esc(p.reflection)}</li>`).join('')}</ol></details>
  </section>
  <section class="card"><h2>Form groups</h2><p class="muted">The optimizer favors groups near four. It first tries to satisfy all hard rules. If that cannot be proven within its time limit, it suggests a grouping with every violation flagged. Review before publishing.</p>
    <div class="actions"><button class="button" id="run-match" type="button" ${phase === 'matching' ? '' : 'disabled'}>Run matching</button></div>
    ${admin.runs.length ? renderRuns(admin.runs, approved) : '<p class="muted">No match run yet.</p>'}
  </section>`;
}
function renderRuns(runs, profiles) {
  const byId = Object.fromEntries(profiles.map((p) => [p.id, p]));
  const run = runs[0];
  if (!run.groups) return `<div class="danger">Last run found no grouping. Hard solve: ${esc(run.hardStatus)}; suggested solve: ${esc(run.solveStatus)}. Try again or resolve participant conflicts.</div>`;
  const check = run.check || {};
  const violations = check.violations || [];
  const flags = (check.groups || []).filter((g) => g.needsAccessKey).length;
  return `<div class="${violations.length ? 'danger' : 'success'}">
    <strong>${violations.length ? `${violations.length} hard-rule violation${violations.length === 1 ? '' : 's'} require review` : 'All hard rules pass'}</strong><br />
    ${run.groups.length} groups · ${run.participantCount} people · ${flags} groups need an access key · hard solve ${esc(run.hardStatus)}
  </div>
  ${run.missingPreferences?.length ? `<p class="danger">${run.missingPreferences.length} approved people have no saved groupmate choices.</p>` : ''}
  ${violations.length ? `<ul>${violations.map((v) => `<li>Group ${esc(v.group)}: ${esc(v.rule)} — ${v.members.map((id) => esc(byId[id]?.name || id)).join(', ')}</li>`).join('')}</ul>` : ''}
  <div class="group-grid">${(check.groups || []).map((g) => `<article class="group-card"><h3>Group ${g.group} <span class="pill neutral">${g.size} people</span></h3>
    <ul>${g.members.map((id) => `<li>${esc(byId[id]?.name || id)}</li>`).join('')}</ul>
    <p class="small muted">${g.wishesMet} preferred pairings met · ${g.needsAccessKey ? '<strong>Access key needed</strong>' : '$100-tier member present'}</p></article>`).join('')}</div>
  ${state.config.phase === 'matching' ? `<div class="actions">${violations.length ? '<label class="inline-check"><input id="ack-violations" type="checkbox" /> I have reviewed every hard-rule violation and accept this grouping.</label>' : ''}<button class="button" id="publish" data-run="${esc(run.id)}" type="button">Publish these groups</button></div>` : `<p class="success">Published run: ${esc(state.config.activeRun || '')}</p>`}`;
}
function download(name, text, mime) {
  const blob = new Blob([text], { type: mime });
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a'); link.href = url; link.download = name; link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
function csv(rows) {
  const escapeCell = (value) => `"${String(value ?? '').replaceAll('"', '""')}"`;
  return rows.map((row) => row.map(escapeCell).join(',')).join('\n');
}
function bindAdmin() {
  document.querySelectorAll('[data-phase]').forEach((button) => button.addEventListener('click', () => working(async () => {
    state = await call('setPhase', { phase: button.dataset.phase }); render(); notice(`Phase changed to ${phaseLabel(button.dataset.phase)}.`);
  })));
  document.querySelectorAll('[data-approve]').forEach((button) => button.addEventListener('click', () => working(async () => {
    state = await call('approve', { ids: [button.dataset.approve], approved: button.dataset.next === 'true' }); render(); notice('Roster approval updated.');
  })));
  qs('#approve-all')?.addEventListener('click', () => working(async () => {
    const ids = state.admin.profiles.filter((p) => !p.approved).map((p) => p.id);
    state = await call('approve', { ids, approved: true }); render(); notice(`${ids.length} registrations approved.`);
  }));
  qs('#run-match')?.addEventListener('click', () => working(async () => {
    notice('Matching is running. This can take a few minutes; keep this tab open.');
    await generateGroups({}); await refresh(); notice('Match ready for review.');
  }));
  qs('#publish')?.addEventListener('click', () => working(async () => {
    const violations = state.admin.runs[0]?.check?.violations || [];
    const acknowledged = qs('#ack-violations')?.checked === true;
    if (violations.length && !acknowledged) throw new Error('Review and acknowledge the flagged violations before publishing.');
    state = await call('publish', { runId: qs('#publish').dataset.run, acknowledgeViolations: acknowledged });
    render(); notice('Groups published. Participants can now see their own group.');
  }));
  qs('#export')?.addEventListener('click', () => download('padua-workshop-organizer.json', JSON.stringify(state.admin, null, 2), 'application/json'));
  qs('#export-csv')?.addEventListener('click', () => {
    const rows = [['Name', 'Email', 'Institution', 'Career', 'Familiarity', 'Subscription', 'Gender', 'Approved', 'Preferences complete']];
    for (const p of state.admin.profiles) rows.push([p.name, p.email, p.institution, p.career, p.familiarity, p.subscription, p.gender, p.approved, (state.admin.preferences[p.id]?.wishes?.length || 0) >= 10]);
    download('padua-workshop-roster.csv', csv(rows), 'text/csv');
  });
}

async function boot() {
  if (isSignInWithEmailLink(auth, location.href)) {
    const email = localStorage.getItem('paduaEmailForSignIn');
    if (!email) return renderAuth(true);
    try {
      await signInWithEmailLink(auth, email, location.href);
      localStorage.removeItem('paduaEmailForSignIn');
      history.replaceState(null, '', location.pathname);
    } catch (error) { renderAuth(true); notice(errorMessage(error), true); return; }
  }
  onAuthStateChanged(auth, async (user) => {
    if (!user) return renderAuth();
    try { await refresh(); } catch (error) { console.error(error); notice(errorMessage(error), true); appEl.innerHTML = '<section class="card">The workshop service is temporarily unavailable. Please refresh shortly.</section>'; }
  });
}
boot();

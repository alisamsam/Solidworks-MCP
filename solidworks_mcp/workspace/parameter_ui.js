/* Local workspace queues immutable requests; CAD runs on the MCP COM thread. */
const token = new URLSearchParams(location.search).get('token');
const el = id => document.getElementById(id);
let projects = [], snapshot = null, projectId = null, ownerId = null;
const localEdits = new ParameterEditBuffer();
const requestNotes = new Map();
let writing = false, loadSequence = 0;
const hasDraft = p => p.has_draft ?? p.draft_value != null;
const requestKey = () => JSON.stringify([projectId, ownerId]);
const ownerKinds = {assembly:'Sestav',part:'Part',occurrence:'Pojavitev',weldment_body:'Telo varjenca',drawing:'Risba',requirement:'Zahteva'};

function node(tag, text = '', className = '') {
  const element = document.createElement(tag);
  element.textContent = text == null ? '' : String(text);
  if (className) element.className = className;
  return element;
}
function toast(text) {
  const target = el('toast'); target.textContent = text; target.classList.add('show');
  setTimeout(() => target.classList.remove('show'), 3800);
}
async function api(path, method = 'GET', data) {
  const response = await fetch('/api' + path, {
    method, headers: {'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'},
    body: data ? JSON.stringify(data) : undefined, cache: 'no-store'
  });
  const result = await response.json();
  if (!response.ok) { const error = new Error(result.error || 'Zahteva ni uspela.'); error.code = result.code; throw error; }
  return result;
}
async function action(path, data, afterSave = () => {}) {
  if (snapshot?.project.id !== projectId || !path.startsWith('/projects/' + projectId + '/')) {
    toast('Počakajte, da se izbrani projekt naloži.'); return false;
  }
  if (writing) { toast('Počakajte, da se trenutna sprememba shrani.'); return false; }
  writing = true;
  try {
    await api(path, 'POST', {...data, expected_revision: snapshot?.revision});
    afterSave();
    try { await refresh(); toast('Shranjeno v projektni register.'); }
    catch (_) { toast('Shranjeno; osvežitev ni uspela. Poskusite Osveži.'); }
    return true;
  } catch (error) {
    toast(error.message);
    if (error.code === 'REVISION_CONFLICT') { try { await refresh(); } catch (_) {} }
    return false;
  } finally { writing = false; }
}
function ownerPath(id) {
  const names = []; const seen = new Set();
  while (id && !seen.has(id)) {
    seen.add(id); const owner = snapshot.owners.find(o => o.id === id);
    if (!owner) break; names.unshift(owner.name); id = owner.parent_id;
  }
  return names.join(' → ');
}
function valueText(value, unit) { return value == null ? '—' : (typeof value === 'boolean' ? (value ? 'Da' : 'Ne') : String(value)) + (unit ? ' ' + unit : ''); }
function status(param) {
  if (localEdits.conflicts(projectId, param)) return ['Konflikt vnosa', 'error'];
  if (localEdits.get(projectId, param.id)) return ['Neshranjen vnos', 'draft'];
  if (param.completeness === 'invalid_input') return ['Napaka izračuna', 'error'];
  if (hasDraft(param)) return [param.draft_value == null ? 'Prazen osnutek' : 'Osnutek', 'draft'];
  if (param.role === 'derived') return param.completeness === 'calculated' ? ['Izračun', 'derived'] : ['Manjkajo vhodi', 'missing'];
  if (param.completeness === 'missing') return ['Potreben podatek', 'missing'];
  if (param.role !== 'input' && param.role !== 'metadata') return ['Samo branje', ''];
  return ['Evidentirano', ''];
}
function renderOwners() {
  const target = el('owners'); target.replaceChildren();
  const all = node('button', 'Vsi elementi');
  if (!ownerId) all.classList.add('active');
  all.onclick = () => { ownerId = null; render(); }; target.append(all);
  const seen = new Set();
  const add = (parent, depth) => {
    for (const owner of snapshot.owners.filter(o => o.parent_id === parent)) {
      if (seen.has(owner.id)) continue; seen.add(owner.id);
      const button = node('button', ''); button.style.paddingLeft = (12 + depth * 15) + 'px';
      button.append(node('span', owner.name), node('span', ownerKinds[owner.kind] || owner.kind, 'kind'));
      if (ownerId === owner.id) button.classList.add('active');
      button.onclick = () => { ownerId = owner.id; render(); };
      target.append(button); add(owner.id, depth + 1);
    }
  };
  add(null, 0);
  for (const orphan of snapshot.owners.filter(o => !seen.has(o.id))) {
    const button = node('button', orphan.name + ' · ' + (ownerKinds[orphan.kind] || orphan.kind));
    button.onclick = () => { ownerId = orphan.id; render(); }; target.append(button);
  }
}
function makeEditor(p) {
  const targetProject = projectId;
  const label = node('label', 'Predlagana vrednost'); let input;
  if (p.value_type === 'boolean' || p.value_type === 'enum') {
    input = node('select');
    const options = p.value_type === 'boolean' ? [['', '—'], ['true', 'Da'], ['false', 'Ne']]
      : [['', '—'], ...(p.choices || []).map(v => [v, v])];
    for (const [value, name] of options) {
      const option = node('option', name); option.value = value; input.append(option);
    }
    input.value = localEdits.value(targetProject, p);
  } else {
    input = node('input'); input.type = p.value_type === 'text' ? 'text' : 'text';
    input.inputMode = p.value_type === 'number' || p.value_type === 'integer' ? 'decimal' : 'text';
    input.value = localEdits.value(targetProject, p);
  }
  input.setAttribute('aria-label', p.label + ' predlog');
  const note = node('small', '', 'edit-note');
  const updateNote = () => {
    note.textContent = localEdits.conflicts(targetProject, p)
      ? 'Vrednost v registru se je spremenila. Vaš vnos je ohranjen; primerjajte ga ali zavrzite.'
      : localEdits.get(targetProject, p.id) ? 'Vnos še ni shranjen.' : '';
  };
  const remember = () => { localEdits.stage(targetProject, p, input.value); updateNote(); };
  input.oninput = remember; input.onchange = remember;
  const save = node('button', 'Shrani osnutek', 'light');
  save.setAttribute('aria-label', 'Shrani osnutek: ' + p.label);
  save.onclick = async () => {
    const pending = localEdits.get(targetProject, p.id) || localEdits.stage(targetProject, p, input.value);
    const latest = snapshot?.parameters.find(item => item.id === p.id);
    if (snapshot?.project.id !== targetProject || !latest || localEdits.conflicts(targetProject, latest)) {
      toast('Vrednost v registru se je spremenila. Vnos je ohranjen; najprej primerjajte podatke.'); return;
    }
    let value = input.value;
    if (p.value_type === 'boolean' && value) value = value === 'true';
    await action('/projects/' + targetProject + '/drafts', {parameter_id: p.id, value},
      () => localEdits.clearIf(targetProject, p.id, pending));
  };
  const discard = node('button', 'Zavrzi vnos / osnutek', 'light');
  discard.setAttribute('aria-label', 'Zavrzi: ' + p.label);
  discard.onclick = async () => {
    if (localEdits.get(targetProject, p.id)) { localEdits.discard(targetProject, p.id); render(); }
    else if (hasDraft(p)) await action('/projects/' + targetProject + '/discard-draft', {parameter_id:p.id});
  };
  if (localEdits.conflicts(targetProject, p)) {
    note.textContent = 'V registru je zdaj ' + valueText(p.effective_value ?? (hasDraft(p) ? p.draft_value : p.observed_value), p.unit) + '. Vaš vnos je ohranjen.';
  } else updateNote();
  label.append(input, note, save, discard); return label;
}
function renderParameters() {
  const target = el('parameters'); target.replaceChildren();
  const query = el('search').value.trim().toLowerCase(); const filter = el('filter').value;
  const visible = snapshot.parameters.filter(p => {
    if (ownerId && p.owner_id !== ownerId) return false;
    if (query && !(p.label + ' ' + ownerPath(p.owner_id) + ' ' + p.key).toLowerCase().includes(query)) return false;
    if (filter === 'missing' && !['missing', 'missing_input'].includes(p.completeness)) return false;
    if (filter === 'draft' && !hasDraft(p) && !localEdits.get(projectId,p.id)) return false;
    if (filter === 'invalid' && p.completeness !== 'invalid_input' && !localEdits.conflicts(projectId,p)) return false;
    if (filter === 'derived' && p.role !== 'derived') return false;
    if (filter === 'readonly' && p.availability !== 'read_only') return false;
    return true;
  });
  el('empty').hidden = visible.length !== 0;
  for (const p of visible) {
    const card = node('article', '', 'parameter'); const top = node('div', '', 'parameter-top');
    const title = node('div'); title.append(node('div', ownerPath(p.owner_id) + ' · ' + p.group, 'owner-path'), node('h3', p.label));
    const [state, style] = status(p); top.append(title, node('span', state, 'badge ' + style)); card.append(top);
    if (p.description) card.append(node('p', p.description, 'description'));
    if (p.calculation_error) card.append(node('p', p.calculation_error, 'error-text'));
    if (p.formula) {
      const symbols = {add:'+',subtract:'−',multiply:'×',divide:'÷'};
      const labels = p.formula.inputs.map(id => snapshot.parameters.find(x => x.id === id)?.label || 'Neznan vhod');
      card.append(node('p', 'Izračun: ' + labels.join(' ' + symbols[p.formula.op] + ' '), 'description'));
    }
    const body = node('div', '', 'parameter-body');
    if (p.availability === 'draft_only') body.append(makeEditor(p));
    else {
      const label = node('div', p.role === 'derived' ? 'Izračunano' : 'Prebrano', 'observed');
      label.append(node('strong', valueText(p.role === 'derived' ? p.computed_value : p.observed_value, p.unit)));
      body.append(label);
    }
    if (p.availability === 'draft_only') {
      const label = node('div', 'Trenutno', 'observed');
      label.append(node('strong', valueText(p.observed_value, p.unit))); body.append(label);
    }
    card.append(body);
    const own = snapshot.owners.find(o => o.id === p.owner_id);
    if (own?.kind === 'occurrence' && own.document_id && snapshot.owners.filter(o =>
      o.kind === 'occurrence' && o.document_id === own.document_id && o.configuration === own.configuration).length > 1) {
      card.append(node('p', 'Ta part je v sestavu uporabljen večkrat. Sprememba skupne geometrije lahko vpliva tudi na druge pojavitve.', 'description'));
    }
    const details = node('details'); const summary = node('summary', 'Pojasnilo in tehnična vezava'); details.append(summary);
    const rows = [
      ['Vrsta', p.role], ['Izvor', p.source || 'Projektni register'], ['Merska referenca', p.reference || 'Ni določena'],
      ['Element', ownerPath(p.owner_id)], ['Enota', p.unit || '—'], ['Dokument', snapshot.owners.find(o => o.id === p.owner_id)?.document_id || 'Ni vezan'],
      ['Konfiguracija', snapshot.owners.find(o => o.id === p.owner_id)?.configuration || 'Ni določena'],
      ['Pojavitev', snapshot.owners.find(o => o.id === p.owner_id)?.instance_path || '—'],
      ['CAD vezava', p.binding ? 'Ne preverjena v CAD · ' + JSON.stringify(p.binding) : 'Ni vezana'],
      ['Formula', p.formula ? JSON.stringify(p.formula) : '—'],
      ['CAD sprememba', p.binding?.kind === 'dimension' ? 'Osnutek lahko oddate v CAD čakalno vrsto' : 'Ni podprte CAD vezave']
    ];
    const dl = node('dl'); for (const [key, value] of rows) dl.append(node('dt', key), node('dd', value));
    details.append(dl); card.append(details); target.append(card);
  }
}
function renderSide() {
  const drafts = el('drafts'); drafts.replaceChildren();
  el('request-text').value = requestNotes.get(requestKey()) || '';
  for (const p of snapshot.parameters.filter(hasDraft)) {
    const row = node('div', '', 'entry'); row.append(node('strong', p.label), node('small', valueText(p.draft_value, p.unit) + ' · ' + ownerPath(p.owner_id))); drafts.append(row);
  }
  if (!drafts.children.length) drafts.append(node('p', 'Brez osnutkov.'));
  el('queue-cad').disabled = !snapshot.parameters.some(hasDraft) || (snapshot.cad_jobs || []).some(j => ['queued','running'].includes(j.status));
  const jobs = el('cad-jobs'); jobs.replaceChildren();
  const jobNames = {queued:'Čaka na MCP agenta',running:'MCP izvaja spremembe',completed:'Spremembe potrjene',failed:'Izvedba ni uspela — preverite delne spremembe',cancelled:'Preklicano'};
  for (const j of (snapshot.cad_jobs || []).slice(0,5)) {
    const row = node('div', jobNames[j.status] || j.status, 'entry');
    row.append(node('small', j.id));
    if (j.result?.message) row.append(node('small',j.result.message));
    if (j.status === 'queued') { const cancel=node('button','Prekliči'); cancel.onclick=()=>action('/projects/'+projectId+'/cancel-cad-job',{job_id:j.id}); row.append(cancel); }
    jobs.append(row);
  }
  const requests = el('requests'); requests.replaceChildren();
  for (const r of snapshot.requests.slice(0, 6)) {
    const statusNames = {waiting:'Čaka na agenta',in_progress:'V obravnavi',needs_info:'Potreben podatek',proposed:'Predlog pripravljen',completed:'Obravnavano',rejected:'Zavrnjeno',cancelled:'Preklicano'};
    const row = node('div', r.text, 'entry'); row.append(node('small', (statusNames[r.status] || r.status) + ' · ' + (r.owner_id ? ownerPath(r.owner_id) : 'Ves projekt'))); requests.append(row);
  }
  const history = el('history'); history.replaceChildren();
  const names = {owner_added:'Dodan element', parameter_added:'Dodan parameter', draft_changed:'Spremenjen osnutek', draft_discarded:'Zavržen osnutek', request_added:'Oddana zahteva',request_status_changed:'Obravnava zahteve',cad_queued:'CAD spremembe oddane',cad_running:'CAD spremembe v izvajanju',cad_completed:'CAD spremembe potrjene',cad_failed:'CAD izvedba ni uspela',cad_cancelled:'CAD spremembe preklicane'};
  for (const event of snapshot.history.slice(0, 10)) {
    const row = node('div', names[event.action] || event.action, 'entry');
    if (event.detail.label) row.append(node('div', event.detail.label + (Object.hasOwn(event.detail,'before') ? ': ' + valueText(event.detail.before) + ' → ' + valueText(event.detail.value) : '')));
    row.append(node('small', event.created_at + ' UTC · revizija ' + event.revision)); history.append(row);
  }
}
function render() {
  if (!snapshot) return;
  const selected = snapshot.owners.find(o => o.id === ownerId);
  el('path').textContent = selected ? ownerPath(ownerId).toUpperCase() : snapshot.project.name.toUpperCase();
  el('heading').textContent = selected ? selected.name : 'Vsi parametri';
  el('coverage').textContent = snapshot.coverage;
  el('connection').textContent = snapshot.cad.connected ? 'CAD povezan' : 'CAD spremembe izvaja MCP agent';
  renderOwners(); renderParameters(); renderSide();
  const stats = el('stats'); stats.replaceChildren();
  const numbers = [['Parametri', snapshot.parameters.length],
    ['Potrebni podatki', snapshot.parameters.filter(p => ['missing','missing_input'].includes(p.completeness)).length],
    ['Osnutki', snapshot.parameters.filter(hasDraft).length]];
  for (const [name, count] of numbers) { const box = node('div', name, 'stat'); box.prepend(node('strong', count)); stats.append(box); }
}
async function refresh() {
  const sequence = ++loadSequence;
  const listed = await api('/projects');
  if (sequence !== loadSequence) return;
  projects = listed; const select = el('projects'); select.replaceChildren();
  for (const p of projects) { const option = node('option', p.name); option.value = p.id; select.append(option); }
  if (!projects.length) { snapshot = null; el('heading').textContent = 'Ustvarite prvi projekt'; el('parameters').replaceChildren(); return; }
  if (!projectId || !projects.some(p => p.id === projectId)) projectId = projects[0].id;
  const targetProject = projectId;
  select.value = projectId;
  const fresh = await api('/projects/' + targetProject);
  if (sequence !== loadSequence || targetProject !== projectId) return;
  snapshot = fresh;
  if (ownerId && !snapshot.owners.some(o => o.id === ownerId)) ownerId = null;
  render();
}
function showForm(title, fields, onSubmit) {
  el('dialog-title').textContent = title; const area = el('form-fields'); area.replaceChildren(); const controls = {};
  for (const field of fields) {
    const label = node('label', field.label, 'field'); let input;
    if (field.options) { input = node('select'); for (const [value, name] of field.options) { const option = node('option', name); option.value = value; input.append(option); } }
    else { input = node('input'); input.type = field.type || 'text'; input.placeholder = field.placeholder || ''; }
    input.name = field.key; input.required = !!field.required; if (field.value != null) input.value = field.value;
    label.append(input); area.append(label); controls[field.key] = input;
  }
  const form = el('form'); form.onsubmit = async event => { event.preventDefault(); const data = {};
    for (const [key, input] of Object.entries(controls)) data[key] = input.value;
    if (await onSubmit(data)) el('dialog').close();
  };
  el('dialog').showModal();
}
el('cancel').onclick = () => el('dialog').close();
el('projects').onchange = event => { projectId = event.target.value; ownerId = null; refresh().catch(e => toast(e.message)); };
el('refresh').onclick = () => refresh().catch(e => toast(e.message));
el('export').onclick = async () => {
  if (!projectId) return toast('Najprej ustvarite projekt.');
  try {
    const data = await api('/projects/' + projectId + '/export');
    const blob = new Blob([JSON.stringify({schema_version:1, ...data}, null, 2)], {type:'application/json'});
    const link = document.createElement('a'); link.href = URL.createObjectURL(blob);
    link.download = 'parametri-' + projectId + '.json'; link.click();
    setTimeout(() => URL.revokeObjectURL(link.href), 1000);
  } catch (error) { toast(error.message); }
};
el('search').oninput = renderParameters; el('filter').onchange = renderParameters;
el('new-project').onclick = () => showForm('Nov projekt', [
  {key:'name', label:'Ime projekta', required:true},
  {key:'template', label:'Začetna struktura', options:[['','Prazen projekt'],['stairs_railing','Stopnice in ograja']]}
], async data => {
  try { const project = await api('/projects', 'POST', data); projectId = project.id; ownerId = null; await refresh(); toast('Projekt ustvarjen.'); return true; }
  catch (error) { toast(error.message); return false; }
});
el('new-owner').onclick = () => {
  if (!projectId) return toast('Najprej ustvarite projekt.');
  showForm('Dodaj element', [
    {key:'name', label:'Naziv', required:true},
    {key:'kind', label:'Vrsta', options:[['assembly','Sestav'],['part','Part'],['occurrence','Pojavitev parta'],['weldment_body','Telo varjenca'],['drawing','Risba'],['requirement','Konstrukcijska zahteva']]},
    {key:'document_id', label:'ID dokumenta (po želji)'},
    {key:'configuration', label:'Konfiguracija (po želji)'},
    {key:'instance_path', label:'Pot pojavitve v sestavu (po želji)'}
  ], data => action('/projects/' + projectId + '/owners', {...data, parent_id:ownerId}));
};
el('new-parameter').onclick = () => {
  if (!projectId || !snapshot?.owners.length) return toast('Najprej dodajte element.');
  const ownerChoices = snapshot.owners.map(o => [o.id, ownerPath(o.id)]);
  const inputChoices = [['', 'Izberite vhod'], ...snapshot.parameters.filter(p => p.role === 'input' || p.role === 'derived').map(p => [p.id, p.label + ' · ' + ownerPath(p.owner_id)])];
  showForm('Dodaj parameter', [
    {key:'owner_id', label:'Del ali sestav', options:ownerChoices, value:ownerId || ownerChoices[0][0]},
    {key:'key', label:'Stabilni ključ', required:true, placeholder:'npr. skupna_visina'},
    {key:'label', label:'Naziv za uporabnika', required:true},
    {key:'value_type', label:'Vrsta podatka', options:[['number','Število'],['integer','Celo število'],['text','Besedilo'],['boolean','Da / ne'],['enum','Izbira']]},
    {key:'role', label:'Vloga', options:[['input','Vhodni parameter'],['measurement','Izmerjena vrednost'],['constraint','Omejitev'],['metadata','Podatek'],['derived','Izračun']]},
    {key:'unit', label:'Enota (po želji)', placeholder:'mm'},
    {key:'group', label:'Skupina', placeholder:'Geometrija'},
    {key:'source', label:'Izvor (po želji)'},
    {key:'reference', label:'Merska referenca (po želji)'},
    {key:'choices_text', label:'Možnosti za izbiro, ločene z vejico'},
    {key:'formula_a', label:'Prvi vhod izračuna', options:inputChoices},
    {key:'formula_b', label:'Drugi vhod izračuna', options:inputChoices},
    {key:'formula_op', label:'Računska operacija', options:[['divide','Deljenje'],['add','Seštevanje'],['subtract','Odštevanje'],['multiply','Množenje']]}
  ], data => {
    const payload = {...data}; delete payload.choices_text; delete payload.formula_a; delete payload.formula_b; delete payload.formula_op;
    if (data.choices_text) payload.choices = data.choices_text.split(',').map(s => s.trim()).filter(Boolean);
    if (data.role === 'derived') payload.formula = {op:data.formula_op, inputs:[data.formula_a,data.formula_b]};
    if (!payload.group) payload.group = 'Splošno';
    return action('/projects/' + projectId + '/parameters', payload);
  });
};
el('send-request').onclick = () => {
  if (!projectId) return toast('Najprej ustvarite projekt.');
  const rawText = el('request-text').value;
  const text = rawText.trim(); if (!text) return toast('Vnesite zahtevo.');
  const context = requestKey();
  action('/projects/' + projectId + '/requests', {text, owner_id:ownerId}, () => {
    if (requestNotes.get(context) === rawText) requestNotes.delete(context);
  });
};
el('request-text').oninput = () => requestNotes.set(requestKey(), el('request-text').value);
el('queue-cad').onclick = () => {
  if (localEdits.size) return toast('Najprej shranite vnose v osnutke.');
  return action('/projects/'+projectId+'/cad-jobs', {});
};
window.addEventListener('beforeunload', event => {
  if (localEdits.size || [...requestNotes.values()].some(value => value.trim())) { event.preventDefault(); event.returnValue = ''; }
});
refresh().catch(error => toast(error.message));
setInterval(() => {
  if (document.hidden || el('dialog').open || document.activeElement?.matches('input,select,textarea')) return;
  refresh().catch(() => {});
}, 15000);

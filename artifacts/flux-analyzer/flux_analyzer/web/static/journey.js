/* Flux Analyzer — Simple-mode guided journey. Mixed into the Alpine component from app.js.
   No financial math happens here: every amount shown comes from the server. */
(function () {
  const STAGES = ['upload', 'path', 'data', 'compare', 'include', 'group', 'important', 'explain', 'review', 'results', 'save'];
  const STEP_IDS = ['data', 'compare', 'include', 'group', 'important', 'explain'];
  const STAGE_TO_STEP = { upload: 'sources', path: 'sources', data: 'columns', compare: 'comparison', include: 'scope', group: 'classification', important: 'rules', explain: 'rules', review: 'review', results: 'results', save: 'review' };
  const STEP_TO_STAGE = { sources: 'upload', flux: 'path', columns: 'data', comparison: 'compare', scope: 'include', classification: 'group', rules: 'important', review: 'review', results: 'results' };
  const TOUR = [
    { title: 'Describe it in your own words', text: 'Tell us what you are comparing — for example “Q2 vs Q1 by country, threshold 100k”. We set up as much as we can.' },
    { title: 'Every AI change can be undone', text: 'When the assistant changes your setup you see a short summary with Change and Undo. Nothing is hidden.' },
    { title: 'Steps marked “Needs input”', text: 'If the assistant was unsure, the step is marked. Open it, check the choice and continue.' },
    { title: 'You confirm the explanations', text: 'AI drafts are marked for review. Only a person can confirm an explanation, and the Excel pack shows what still needs work.' },
  ];
  const META = window.__JOURNEY__ || {};
  const clone = (o) => JSON.parse(JSON.stringify(o ?? null));
  const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

  function journey() {
    return {
      mode: 'simple', stage: 'upload', stages: STAGES, stepIds: STEP_IDS, meta: META, tour: TOUR,
      jBusy: false, jLabel: '', jSince: 0, jElapsed: 0, jTimer: null, jStopped: false,
      lastAI: null, askText: '', describeText: '',
      fData: {}, fCompare: {}, fInclude: [], fGroup: [], fImportant: {}, fExplain: {}, formSnap: {},
      values: {}, valueSearch: {}, exampleText: '',
      exp: [], expCounts: {}, expDrafts: {}, expBases: {}, expOpen: { ai: false, rest: false }, reviewer: '', answer: null, askResult: '',
      setups: [], setupsOpenJ: false, setupForm: { name: '', description: '', note: '' }, setupBusy: false, setupDetail: null, deleteName: '',
      helpOpenJ: false, tourStep: -1, mobileSteps: false,

      jInit() {
        this.mode = localStorage.getItem('flux-mode') === 'advanced' ? 'advanced' : 'simple';
        this.$watch('mode', (m) => document.documentElement.classList.toggle('simple-mode', m === 'simple'));
        document.documentElement.classList.toggle('simple-mode', this.mode === 'simple');
        this.reviewer = localStorage.getItem('flux-reviewer') || '';
        const initial = window.__STAGE__ && STAGES.includes(window.__STAGE__) ? window.__STAGE__ : (STEP_TO_STAGE[this.step] || 'upload');
        this.stage = this.hasData || ['upload'].includes(initial) ? initial : 'upload';
        if (this.stage === 'results' && !this.s.result) this.stage = this.hasData ? 'review' : 'upload';
        this.loadForms();
        if (this.mode === 'simple') this.enterStage(this.stage, false);
        window.addEventListener('popstate', () => {
          const m = location.pathname.match(/flow\/(\w+)/);
          if (m && STAGES.includes(m[1])) { this.stage = m[1]; this.enterStage(m[1], false); }
        });
        if (this.mode === 'simple' && !localStorage.getItem('flux-tour-done')) this.tourStep = 0;
      },

      /* ---------- mode and navigation ---------- */
      get hasData() { return !!(this.s.journey && this.s.journey.has_data); },
      get jSteps() { return (this.s.journey && this.s.journey.steps) || []; },
      jStep(id) { return this.jSteps.find((x) => x.id === id) || { id, status: 'needs_input', summary: [], questions: [] }; },
      stepMeta(id) { return (META.steps || []).find((x) => x.id === id) || {}; },
      setMode(mode) {
        if (mode === this.mode) return;
        if (mode === 'advanced') {
          this.mode = 'advanced'; localStorage.setItem('flux-mode', 'advanced');
          const step = STAGE_TO_STEP[this.stage] || 'sources';
          this.step = step; history.pushState({}, '', '/step/' + step);
        } else {
          if (this.anyDirty && !confirm('You have unsaved changes in Advanced mode. Switch anyway? Unsaved edits are lost.')) return;
          this.mode = 'simple'; localStorage.setItem('flux-mode', 'simple');
          this.refresh().then(() => { this.loadForms(); this.goStage(STEP_TO_STAGE[this.step] || 'upload'); });
        }
      },
      stageIndex(stage) { return STAGES.indexOf(stage || this.stage); },
      progressStages() { return [['upload', 'Upload'], ['path', 'Describe'], ['steps', 'Set up'], ['review', 'Review'], ['results', 'Results'], ['save', 'Save']]; },
      progressState(key) {
        const here = STEP_IDS.includes(this.stage) ? 'steps' : this.stage;
        const order = ['upload', 'path', 'steps', 'review', 'results', 'save'];
        const a = order.indexOf(key), b = order.indexOf(here);
        return a === b ? 'current' : a < b ? 'done' : 'todo';
      },
      canOpen(stage) {
        if (stage === 'upload') return true;
        if (!this.hasData) return false;
        if (stage === 'results' || stage === 'save') return !!this.s.result;
        return true;
      },
      goStage(stage, push = true) {
        if (!STAGES.includes(stage)) stage = 'upload';
        if (!this.canOpen(stage)) { this.toast(this.hasData ? 'Run the report first.' : 'Upload your data first.', 'error'); return; }
        this.stage = stage;
        this.step = STAGE_TO_STEP[stage] || this.step;
        if (push) history.pushState({}, '', '/flow/' + stage);
        this.api('POST', '/journey/stage', { stage }).catch(() => {});
        this.enterStage(stage, true);
        window.scrollTo({ top: 0, behavior: 'smooth' });
      },
      enterStage(stage) {
        this.mobileSteps = false;
        if (STEP_IDS.includes(stage)) this.loadForm(stage);
        if (stage === 'include') this.fInclude.forEach((f) => this.loadValues(f.col));
        if (stage === 'review' && this.hasData) this.jChecks();
        if (stage === 'results' && this.s.result) this.loadExplanations();
        if (stage === 'save') { this.loadSetups(); if (!this.setupForm.name) this.setupForm.name = (this.s.loaded_setup || {}).name || ''; }
      },
      nextStage() {
        if (STEP_IDS.includes(this.stage)) {
          const next = STEP_IDS[STEP_IDS.indexOf(this.stage) + 1];
          return next || 'review';
        }
        return STAGES[this.stageIndex() + 1] || 'save';
      },
      prevStage() { return STAGES[Math.max(0, this.stageIndex() - 1)]; },

      /* ---------- upload ---------- */
      async jUpload(files) {
        if (!files || !files.length) return;
        const bad = [...files].filter((f) => !/\.(csv|xlsx|xlsm|xls)$/i.test(f.name));
        if (bad.length) { this.toast('Only CSV or Excel files can be added: ' + bad.map((f) => f.name).join(', '), 'error'); return; }
        const fd = new FormData();
        [...files].forEach((f) => fd.append('files', f));
        await this.run('Reading ' + files.length + ' file' + (files.length > 1 ? 's' : ''), async () => {
          await this.api('POST', '/sources/upload', fd, true);
          await this.autoDefine();
        });
      },
      async jDemo() {
        await this.run('Loading the sample ledger', async () => { await this.api('POST', '/sources/demo', {}); await this.autoDefine(); });
      },
      async autoDefine() {
        const st = await this.api('POST', '/sources/auto-define', {});
        this.hydrate(st, true); this.loadForms();
        if ((st.define_errors || []).length) { this.toast('Some files need setting up by hand: ' + st.define_errors.join(' '), 'error'); return; }
        this.toast('File read. ' + ((st.profile || {}).n_rows || 0).toLocaleString() + ' rows found.');
      },
      async setRole(src, role) {
        await this.run('Updating file type', async () => { this.hydrate(await this.api('POST', `/sources/${src.id}/role`, { role }), true); this.loadForms(); });
      },
      async jRemoveSource(src) {
        if (!confirm(`Remove "${src.name}" from this analysis?`)) return;
        await this.run('Removing file', async () => { this.hydrate(await this.api('DELETE', '/sources/' + src.id)); this.loadForms(); });
      },
      roleLabel(role) { return { primary: 'Main data', lookup: 'Lookup', forecast: 'Forecast' }[role] || 'Main data'; },

      /* ---------- assistant jobs ---------- */
      async assist(url, body, label) {
        if (this.jBusy) { this.toast('The assistant is still working on your last request.', 'error'); return null; }
        this.jBusy = true; this.jLabel = label; this.jStopped = false; this.jSince = Date.now(); this.jElapsed = 0;
        this.jTimer = setInterval(() => (this.jElapsed = Math.round((Date.now() - this.jSince) / 1000)), 1000);
        try {
          const { job_id } = await this.api('POST', url, body);
          const job = await this.poll(job_id, (m) => { if (!this.jStopped) this.jLabel = m; });
          if (this.jStopped) return null;
          return job.result;
        } catch (e) {
          if (!this.jStopped) this.toast(e.message + ' You can continue with the controls on this page.', 'error');
          return null;
        } finally { clearInterval(this.jTimer); this.jBusy = false; this.jLabel = ''; }
      },
      async stopAssistant() {
        this.jStopped = true; this.jBusy = false; clearInterval(this.jTimer);
        try { await this.api('POST', '/journey/stop-assistant', {}); } catch (e) { /* the answer will still be checked against the setup */ }
        this.toast('Stopped. Any late answer will be ignored. Continue with the controls on this page.');
      },
      async afterAI(result) {
        if (!result) return;
        await this.refresh(); this.loadForms();
        this.lastAI = { summary: result.summary || '', changes: this.friendlyChanges(result.changes || []), warnings: result.warnings || [], questions: result.questions || [], applied: !!result.applied, obsolete: !!result.obsolete, status: result.status, at: this.stage };
        if (result.obsolete) this.toast('Your setup changed while the assistant was working, so its answer was not used.', 'error');
        else if (result.status === 'cannot_do' || result.status === 'invalid') this.toast('The assistant could not do that. Nothing changed.', 'error');
      },
      friendlyChanges(changes) {
        const names = [['/roles/value', 'Amount column'], ['/roles/period', 'Month column'], ['/roles/driver_text', 'Description column'], ['/roles/dimensions', 'Grouping fields'], ['/roles/scenario', 'Version column'],
          ['/comparison', 'Periods compared'], ['/scope', "What's included"], ['/drivers/materiality', 'Importance threshold'], ['/drivers/top_n', 'Number of movements shown'],
          ['/drivers/others_label', 'Label for everything else'], ['/commentary/style_profile', 'Explanation style'], ['/flux_name', 'Analysis name']];
        const out = []; let hidden = 0;
        changes.forEach((c) => {
          const hit = names.find(([p]) => c.setting === p || String(c.setting).startsWith(p + '/'));
          const nice = (v) => (/^-?\d+(\.\d+)?$/.test(String(v || '')) ? Number(v).toLocaleString() : v);
          if (hit && !out.some((o) => o.setting === hit[1])) out.push({ setting: hit[1], from: nice(c.from), to: nice(c.to) });
          else if (!hit) hidden++;
        });
        if (hidden) out.push({ setting: hidden + ' supporting setting' + (hidden > 1 ? 's' : ''), from: '', to: 'set automatically (see Advanced mode)' });
        return out;
      },
      async planFromDescription() {
        const text = this.describeText.trim();
        if (!text) { this.toast('Describe what you want to compare first.', 'error'); return; }
        const result = await this.assist('/journey/plan', { description: text, mode: 'simple' }, 'Reading your description and matching it to your columns and months…');
        if (!result) return;
        await this.afterAI(result);
        if (result.applied || result.status === 'needs_input') {
          const j = this.s.journey || {};
          this.goStage(j.first_open || 'review');
          if (this.lastAI) this.lastAI.at = this.stage;
        }
      },
      async askStep() {
        const text = this.askText.trim();
        if (!text) return;
        const result = await this.assist('/instruction', { instruction: text, target_step: STEP_IDS.includes(this.stage) ? this.stage : null, ui_step: this.stage, mode: 'simple' }, 'Reading your request and checking it against your data…');
        if (result) { this.askText = ''; await this.afterAI(result); }
      },
      async answerQuestion(question, option) {
        this.askText = option; await this.askStep();
      },
      async suggestStep() {
        const result = await this.assist('/journey/suggest/' + this.stage, { ui_step: this.stage, mode: 'simple' }, 'Looking at your columns and months…');
        await this.afterAI(result);
      },
      async undoAI() {
        await this.run('Undoing', async () => { this.hydrate(await this.api('POST', '/spec/undo', {}), true); this.loadForms(); this.lastAI = null; this.toast('Change undone.'); });
      },
      async markStepOk(step) {
        await this.run('Saving', async () => { this.hydrate(await this.api('POST', `/journey/step/${step}/ok`, {}), true); });
      },

      /* ---------- step forms ---------- */
      get columnNames() { return ((this.s.profile || {}).columns || []).map((c) => c.name); },
      column(name) { return ((this.s.profile || {}).columns || []).find((c) => c.name === name) || null; },
      columnsOfType(...types) { return ((this.s.profile || {}).columns || []).filter((c) => types.includes(c.dtype_guess)).map((c) => c.name); },
      get groupingChoices() {
        const roles = (this.s.spec || {}).roles || {};
        const skip = new Set([roles.value, roles.period, ...(roles.driver_text || [])]);
        return ((this.s.profile || {}).columns || []).filter((c) => !skip.has(c.name) && c.dtype_guess !== 'number' && c.n_unique > 1).map((c) => c.name);
      },
      loadForms() { STEP_IDS.forEach((id) => this.loadForm(id)); },
      loadForm(id) {
        const sp = this.s.spec || {}; const r = sp.roles || {};
        if (id === 'data') this.fData = { amount: r.value || '', month: r.period || '', description: (r.driver_text || [])[0] || '', grouping: [...(r.dimensions || [])] };
        if (id === 'compare') { const c = sp.comparison || {}; this.fCompare = { base: [...((c.base || {}).months || [])], current: [...((c.current || {}).months || [])], base_scenario: (c.base || {}).scenario || '', current_scenario: (c.current || {}).scenario || '' }; }
        if (id === 'include') this.fInclude = (sp.scope || []).filter((x) => ['eq', 'in'].includes(x.op)).map((x) => ({ col: x.col, values: Array.isArray(x.val) ? x.val.map(String) : [String(x.val)] }));
        if (id === 'group') { const v = (sp.views || []).find((x) => x.name === (sp.drivers || {}).view); this.fGroup = [...((v || {}).keys || [])]; }
        if (id === 'important') { const d = sp.drivers || {}; const m = d.materiality || { mode: 'abs', abs: 0 }; this.fImportant = { threshold: m.mode === 'abs' ? m.abs : '', top_n: d.top_n ?? 15, others_label: d.others_label || 'Other items', pctRule: (m.mode || 'abs') !== 'abs', replace_rule: false }; }
        if (id === 'explain') {
          const p = (sp.commentary || {}).style_profile || {};
          this.fExplain = { audience: p.audience || 'controller', length: p.length || 'medium', tone: p.tone || 'neutral', structure_type: (p.structure || {}).type || 'overall', split_by: (p.structure || {}).split_by || '', instructions: p.instructions || '', objective: p.objective || '', business_context: p.business_context || '', include: [...(p.include || ['to_verify'])], example: (p.example_style || {}).summary_of_style || '', phrases: [...((p.example_style || {}).sample_phrases || [])] };
        }
        this.formSnap[id] = JSON.stringify(this.formPayload(id));
      },
      formPayload(id) {
        if (id === 'data') return { amount: this.fData.amount, month: this.fData.month, description: this.fData.description || null, grouping: this.fData.grouping };
        if (id === 'compare') return { base_months: this.fCompare.base, current_months: this.fCompare.current, base_scenario: this.fCompare.base_scenario || null, current_scenario: this.fCompare.current_scenario || null };
        if (id === 'include') { const sp = this.s.spec || {}; const had = (sp.scope || []).filter((x) => ['eq', 'in'].includes(x.op)).map((x) => x.col); return { filters: this.fInclude.filter((f) => f.col && f.values.length), clear: had }; }
        if (id === 'group') return { keys: this.fGroup };
        if (id === 'important') { const p = { top_n: Number(this.fImportant.top_n), others_label: this.fImportant.others_label }; if (!this.fImportant.pctRule || this.fImportant.replace_rule) { p.threshold = this.parseAmount(this.fImportant.threshold); p.replace_rule = this.fImportant.replace_rule; } return p; }
        if (id === 'explain') return { audience: this.fExplain.audience, length: this.fExplain.length, tone: this.fExplain.tone, structure_type: this.fExplain.structure_type, split_by: this.fExplain.split_by || null, instructions: this.fExplain.instructions, objective: this.fExplain.objective, business_context: this.fExplain.business_context, include: this.fExplain.include };
        return {};
      },
      formDirty(id) { return this.formSnap[id] !== JSON.stringify(this.formPayload(id)); },
      parseAmount(v) {
        if (typeof v === 'number') return v;
        const t = String(v || '').trim().toLowerCase().replace(/,/g, '');
        const m = t.match(/^(-?\d+(?:\.\d+)?)\s*(k|m|bn|b)?$/);
        if (!m) return NaN;
        return Number(m[1]) * ({ k: 1e3, m: 1e6, b: 1e9, bn: 1e9 }[m[2]] || 1);
      },
      async saveStep(id) {
        if (id === 'important' && isNaN(this.formPayload('important').threshold ?? 0)) { this.toast('Write the threshold as a number, e.g. 250000 or 250k.', 'error'); return false; }
        const ok = await this.run('Saving', async () => {
          this.hydrate(await this.api('POST', '/journey/simple/' + id, this.formPayload(id)), true);
          this.loadForm(id); return true;
        });
        return !!ok;
      },
      async continueStep() {
        const id = this.stage;
        if (STEP_IDS.includes(id) && this.formDirty(id) && !(await this.saveStep(id))) return;
        const step = this.jStep(id);
        if (STEP_IDS.includes(id) && step.status !== 'ready' && !(step.questions || []).length) { this.toast(step.reason || 'This step still needs input.', 'error'); return; }
        if (STEP_IDS.includes(id) && (step.questions || []).length) await this.markStepOk(id);
        this.goStage(this.nextStage());
      },
      toggle(list, value, max) {
        const i = list.indexOf(value);
        if (i >= 0) list.splice(i, 1);
        else if (!max || list.length < max) list.push(value);
        else this.toast(`Choose up to ${max}.`, 'error');
      },
      /* compare helpers */
      get months() { return [...(this.s.periods || [])].sort(); },
      monthLabel(m) { const [y, mo] = String(m).split('-'); return MONTHS[Number(mo) - 1] ? `${MONTHS[Number(mo) - 1]} ${y}` : m; },
      monthRows(m) { return (this.s.monthly_row_counts || {})[m]; },
      isPartial(m) { return (this.s.partial_periods_detected || []).includes(m); },
      quickCompare(kind) {
        const ms = this.months; if (!ms.length) return;
        const last = ms[ms.length - 1];
        const shift = (m, n) => { const [y, mo] = m.split('-').map(Number); const d = new Date(Date.UTC(y, mo - 1 + n, 1)); return `${d.getUTCFullYear()}-${String(d.getUTCMonth() + 1).padStart(2, '0')}`; };
        if (kind === 'month') { this.fCompare.current = [last]; this.fCompare.base = ms.includes(shift(last, -1)) ? [shift(last, -1)] : []; }
        if (kind === 'quarter') {
          const q = (m) => { const [y, mo] = m.split('-').map(Number); return `${y}-Q${Math.ceil(mo / 3)}`; };
          const quarters = [...new Set(ms.map(q))].filter((k) => ms.filter((m) => q(m) === k).length === 3);
          if (quarters.length < 2) { this.toast('Your data does not have two full quarters.', 'error'); return; }
          const [cq, bq] = [quarters[quarters.length - 1], quarters[quarters.length - 2]];
          this.fCompare.current = ms.filter((m) => q(m) === cq); this.fCompare.base = ms.filter((m) => q(m) === bq);
        }
        if (kind === 'year') { const b = shift(last, -12); if (!ms.includes(b)) { this.toast('The same month last year is not in your data.', 'error'); return; } this.fCompare.current = [last]; this.fCompare.base = [b]; }
      },
      toggleMonth(side, m) { const list = this.fCompare[side]; const i = list.indexOf(m); if (i >= 0) list.splice(i, 1); else { list.push(m); list.sort(); } },
      /* include helpers */
      async loadValues(col) {
        if (!col || this.values[col]) return;
        try { this.values = { ...this.values, [col]: await this.api('GET', '/journey/values?col=' + encodeURIComponent(col)) }; } catch (e) { this.toast(e.message, 'error'); }
      },
      addFilter() { this.fInclude.push({ col: '', values: [] }); },
      filteredValues(f) { const q = (this.valueSearch[f.col] || '').toLowerCase(); return ((this.values[f.col] || {}).values || []).filter((v) => !q || v.value.toLowerCase().includes(q)).slice(0, 60); },
      get complexScope() { return ((this.s.spec || {}).scope || []).filter((x) => !['eq', 'in'].includes(x.op)).length; },
      /* explain helpers */
      async learnStyle() {
        if (!this.exampleText.trim()) { this.toast('Paste an example first.', 'error'); return; }
        const result = await this.assist('/style/extract', { example_text: this.exampleText, ui_step: 'explain', mode: 'simple' }, 'Reading the style of your example (not its numbers or names)…');
        if (result) { this.exampleText = ''; await this.afterAI(result); }
      },
      async clearStyle() { await this.run('Clearing', async () => { this.hydrate(await this.api('POST', '/journey/simple/explain', { clear_example: true }), true); this.loadForm('explain'); }); },

      /* ---------- review and run ---------- */
      async jChecks() {
        try { const r = await this.api('POST', '/review/controls', {}); this.controls = r.controls || []; this.controlsRan = true; }
        catch (e) { this.toast(e.message, 'error'); }
      },
      checkLabel(id) { return (META.controls || {})[id] || String(id).replace(/_/g, ' '); },
      async jRun() {
        await this.jChecks();
        if (this.stops) { this.toast('Fix the stopped data checks before running the report.', 'error'); return; }
        this.busy = true; this.busyLabel = 'Running checks and calculating movements…';
        try {
          const { job_id } = await this.api('POST', '/run', {});
          const job = await this.poll(job_id, (m) => (this.busyLabel = m));
          await this.refresh();
          this.setResult(await this.api('GET', `/results/${job.result.run_id}?format=json`));
          this.goStage('results');
        } catch (e) { this.toast(e.message, 'error'); } finally { this.busy = false; this.busyLabel = ''; }
      },

      /* ---------- results and explanations ---------- */
      async loadExplanations() {
        const id = (this.result || this.s.result || {}).id; if (!id) return;
        try {
          const r = await this.api('GET', `/results/${id}?format=json`);
          this.setResult(r); this.setExplanations(r);
        } catch (e) { this.toast(e.message, 'error'); }
      },
      setExplanations(r) {
        this.exp = r.explanations || []; this.expCounts = r.explanation_counts || {};
        // Keep what the reviewer typed unless the stored explanation itself changed underneath it.
        const drafts = {}, bases = {};
        this.exp.forEach((x) => {
          const fresh = x.status === 'needs_explanation' && /\[TO VERIFY\]/.test(x.text || '') ? '' : (x.text || '');
          bases[x.driver_id] = x.text || '';
          drafts[x.driver_id] = this.expBases[x.driver_id] === bases[x.driver_id] && x.driver_id in this.expDrafts ? this.expDrafts[x.driver_id] : fresh;
        });
        this.expDrafts = drafts; this.expBases = bases;
        if (r.commentary && this.result) this.result.commentary = r.commentary;
      },
      expBy(status) { return this.exp.filter((x) => x.status === status); },
      rememberReviewer() { localStorage.setItem('flux-reviewer', this.reviewer.trim()); },
      async explain(item, action) {
        if (action !== 'use_ai_draft' && !this.reviewer.trim()) { this.toast('Enter your name first so the confirmation is recorded.', 'error'); this.$nextTick(() => document.getElementById('reviewer')?.focus()); return; }
        this.rememberReviewer();
        const body = { action, confirmed_by: this.reviewer.trim() };
        if (action === 'save') body.text = this.expDrafts[item.driver_id] || '';
        await this.run(action === 'confirm' ? 'Confirming' : 'Saving', async () => {
          const r = await this.api('POST', `/results/${this.result.id}/explanations/${item.driver_id}`, body);
          delete this.expDrafts[item.driver_id]; this.setExplanations(r);
          const now = this.exp.find((x) => x.driver_id === item.driver_id);
          this.toast(now && now.status === 'confirmed' ? 'Explanation confirmed.' : 'Saved. It still needs work before it can be confirmed.');
        });
      },
      async confirmAll() {
        if (!this.reviewer.trim()) { this.toast('Enter your name first so the confirmation is recorded.', 'error'); return; }
        const n = this.expBy('ai_review').length;
        if (!confirm(`Confirm all ${n} AI explanations as checked by ${this.reviewer.trim()}?`)) return;
        this.rememberReviewer();
        await this.run('Confirming', async () => { const r = await this.api('POST', `/results/${this.result.id}/explanations/confirm-all`, { confirmed_by: this.reviewer.trim() }); this.setExplanations(r); this.toast(`${r.confirmed} explanations confirmed.`); });
      },
      async draftExplanations() {
        const result = await this.assist(`/results/${this.result.id}/narrative`, {}, 'Drafting explanations from the checked evidence…');
        if (!result) return;
        if (!result.applied) this.toast('The draft did not pass the checks, so nothing changed. You can write the explanations yourself.', 'error');
        else this.toast('Draft explanations added. Review them before confirming.');
        await this.loadExplanations();
      },
      async jAsk() {
        const q = this.askResult.trim(); if (!q) return;
        const r = await this.assist('/questions', { question: q, run_id: this.result.id }, 'Answering from the checked results…');
        if (r) this.answer = { q, a: (r.proposal || {}).answer || 'No answer was returned.' };
      },
      statusLabel(s) { return (META.status_labels || {})[s] || s; },
      signed(v) { return (v > 0 ? '+' : '') + this.money(v); },

      /* ---------- saved setups ---------- */
      async loadSetups() { try { this.setups = await this.api('GET', '/setups'); } catch (e) { this.toast(e.message, 'error'); } },
      openSetups() { this.setupsOpenJ = true; this.setupDetail = null; this.loadSetups(); },
      async suggestName() {
        const r = await this.assist('/setup/describe', { name: this.setupForm.name, description: this.setupForm.description }, 'Writing a name and description…');
        if (r && r.suggested_name) { this.setupForm.name = r.suggested_name; this.setupForm.description = r.description; this.toast('Suggestion added. Edit it before saving.'); }
      },
      async saveSetup(asVersion) {
        if (!this.setupForm.name.trim() && !asVersion) { this.toast('Give the setup a name.', 'error'); return; }
        this.rememberReviewer();
        await this.run('Saving setup', async () => {
          const loaded = this.s.loaded_setup;
          const r = asVersion && loaded
            ? await this.api('POST', `/setups/${loaded.id}/versions`, { expected_version: this.currentVersionOf(loaded.id), note: this.setupForm.note, description: this.setupForm.description, saved_by: this.reviewer })
            : await this.api('POST', '/setups', { name: this.setupForm.name.trim(), description: this.setupForm.description, saved_by: this.reviewer });
          this.setups = r.setups; this.hydrate(r.state, true);
          this.toast(`Saved “${r.setup.name}” as version ${r.setup.current_version}.`);
          this.setupForm.note = '';
        });
      },
      currentVersionOf(id) { const x = this.setups.find((s) => s.id === id); return x ? x.current_version : (this.s.loaded_setup || {}).version; },
      async viewSetup(item) { await this.run('Opening', async () => { this.setupDetail = await this.api('GET', '/setups/' + item.id); this.deleteName = ''; }); },
      async loadSetupVersion(item, version) {
        if (!confirm(`Load “${item.name}” version ${version}? Your current setup can be restored with Undo.`)) return;
        await this.run('Loading setup', async () => {
          const r = await this.api('POST', `/setups/${item.id}/load`, { version });
          this.hydrate(r, true); this.loadForms(); this.setupsOpenJ = false;
          if ((r.missing_columns || []).length) { this.toast('Some columns from this setup are not in your file: ' + r.missing_columns.join(', ') + '.', 'error'); this.goStage('data'); }
          else { this.toast('Setup loaded.'); this.goStage(this.hasData ? 'review' : 'upload'); }
        });
      },
      async renameSetup(item) {
        const name = prompt('New name for this setup', item.name); if (!name || name === item.name) return;
        await this.run('Renaming', async () => { const r = await this.api('POST', `/setups/${item.id}/rename`, { name }); this.setups = r.setups; this.setupDetail = { ...this.setupDetail, ...r.setup }; });
      },
      async duplicateSetup(item) { await this.run('Copying', async () => { const r = await this.api('POST', `/setups/${item.id}/duplicate`, { saved_by: this.reviewer }); this.setups = r.setups; this.toast(`Created “${r.setup.name}”.`); }); },
      async deleteSetup(item) {
        await this.run('Deleting', async () => { const r = await this.api('DELETE', `/setups/${item.id}`, { confirm_name: this.deleteName }); this.setups = r.setups; this.setupDetail = null; this.toast('Setup deleted.'); });
      },
      importSetupFile(file) {
        if (!file) return;
        const reader = new FileReader();
        reader.onload = async () => {
          let setup; try { setup = JSON.parse(reader.result); } catch (e) { this.toast('That file is not a valid setup.', 'error'); return; }
          await this.run('Importing', async () => { const r = await this.api('POST', '/setups/import', { setup, saved_by: this.reviewer }); this.setups = r.setups; this.toast(`Imported “${r.setup.name}”.`); });
        };
        reader.readAsText(file);
      },

      /* ---------- help and tour ---------- */
      get helpStep() { return STEP_IDS.includes(this.stage) ? this.stepMeta(this.stage) : null; },
      tourNext() { if (this.tourStep < TOUR.length - 1) this.tourStep++; else this.tourDone(); },
      tourDone() { this.tourStep = -1; localStorage.setItem('flux-tour-done', '1'); },
      restartTour() { this.helpOpenJ = false; this.tourStep = 0; },
      async jNewProject() {
        if (!confirm('Start a new analysis? Your current files and reports stay in the project history.')) return;
        await this.run('Starting fresh', async () => { this.hydrate(await this.api('POST', '/project/new', {})); this.result = null; this.exp = []; this.lastAI = null; this.loadForms(); this.goStage('upload'); });
      },
    };
  }

  // Merge into the main component, keeping getters intact (spread would evaluate them).
  const base = window.fluxApp;
  window.fluxApp = function () {
    const merged = {};
    Object.defineProperties(merged, Object.getOwnPropertyDescriptors(base()));
    Object.defineProperties(merged, Object.getOwnPropertyDescriptors(journey()));
    return merged;
  };
})();

/* Flux Analyzer — client controller (Alpine component). No financial math happens here. */
(function () {
  const STEPS = [
    { slug: 'sources', label: 'Sources & preset', hint: 'Upload, define, choose preset' },
    { slug: 'columns', label: 'Columns', hint: 'Map roles' },
    { slug: 'comparison', label: 'Comparison', hint: 'Base vs current' },
    { slug: 'scope', label: 'Scope', hint: 'Filters, joins, derived' },
    { slug: 'classification', label: 'Classification', hint: 'Keyword categories' },
    { slug: 'rules', label: 'Rules', hint: 'Measures, flags, drivers' },
    { slug: 'review', label: 'Review', hint: 'Controls before run' },
    { slug: 'results', label: 'Results', hint: 'Pack and commentary' },
  ];
  const LEGACY = { flux: 'sources' };
  const AGENT_FOR = { sources: 'detect_flux', columns: 'map_columns', comparison: 'define_comparison', scope: 'derive_columns', classification: 'classify_terms', rules: 'define_rules' };
  const RULE_BLOCKS = ['measures', 'views', 'flags', 'gates', 'sections', 'decompose', 'drivers', 'drill', 'commentary', 'controls'];
  const SCOPE_BLOCKS = ['scope', 'value_rules', 'joins', 'derive'];
  const BLOCK_LABEL = { measures: 'Measures', views: 'Views', flags: 'Flags', gates: 'Gates', sections: 'Sections', decompose: 'Volume and rate split', drivers: 'Drivers and materiality', drill: 'Drill-down', commentary: 'Commentary', controls: 'Controls', scope: 'Scope filters', value_rules: 'Value rules', joins: 'Joins', derive: 'Derived columns', classification: 'Classification', comparison: 'Comparison', roles: 'Column roles', preset: 'Preset' };
  const ADD_PROMPT = { flags: 'What should be flagged? e.g. Flag anything above 10% as Material', gates: 'When should a line be gated? e.g. Exclude movements under 5k', measures: 'What should be measured? e.g. Count of invoices', views: 'How should results be grouped? e.g. Add a view by Region and Site', controls: 'What should be checked? e.g. Warn if classification coverage is below 95%', sections: 'Describe the sections you need', decompose: 'Describe the volume and rate split', drivers: 'e.g. Set materiality to 250k', drill: 'e.g. Drill by vendor, top 8', commentary: 'e.g. Split commentary by region' };
  const HELP_DOCS = [['getting_started', 'Getting started'], ['glossary', 'Glossary'], ['presets', 'Presets'], ['controls', 'Controls'], ['ai_and_data', 'AI and your data'], ['known_gaps', 'Known gaps']];
  const clone = (o) => JSON.parse(JSON.stringify(o ?? null));
  const isObj = (v) => v && typeof v === 'object' && !Array.isArray(v);

  window.fluxApp = function () {
    return {
      s: window.__INITIAL__ || {},
      steps: STEPS,
      step: LEGACY[window.__STEP__] || window.__STEP__ || 'sources',
      dark: false, busy: false, busyLabel: '', toasts: [], dragging: false,
      presetDetail: null, presetEditorOpen: false,
      presetEditor: { id: '', name: '', owner: '', description: '', guidance: '' },
      // source modal
      modal: null, def: {}, preview: null, previewLoading: false,
      // side panel
      panel: 'assist', helpDocId: '', helpDoc: null, helpLoading: false, helpError: '',
      // agent and change box
      agentStatus: 'idle', agentMsg: '', agentError: '', lastChange: null, instruction: '', target: null, targetLabel: '', context: '',
      pendingSuggestion: null, changeDialog: false,
      // manual edits
      roles: {}, comp: {}, dirty: false,
      scopeEd: [], flipEd: [], valueEd: {source:'column',null_as_zero:true}, joinsEd: [], deriveEd: [], scopeDirty: { scope: false, value_rules: false, joins: false, derive: false }, sectionPreview: {},
      cls: { rules: [] }, clsDirty: false, clsFilter: 'all', clsQuery: '', clsSelected: [], clsPreview: null,
      thr: {}, thrDirty: false,
      adv: {}, advText: {}, advErr: {},
      editCard: null,
      logOpen: false,
      // review/results
      controls: [], controlsRan: false, result: null, tab: 'variance', drill: null, drillRows: null, chart: null,
      commentary: '', commentarySaved: true, lines: [], headline: '', othersSummary: '', lineVal: {}, validation: null, regenBusy: '',
      qText: '', qThread: [], qBusy: false, qErr: '',
      // specs
      specsOpen: false, specName: '', importText: '', missing: [],

      init() {
        this.dark = localStorage.getItem('flux-theme') === 'dark' ||
          (!localStorage.getItem('flux-theme') && window.matchMedia('(prefers-color-scheme: dark)').matches);
        this.applyTheme();
        this.hydrate(this.s);
        if (this.s.result) this.setResult(this.s.result);
        if (!STEPS.find((x) => x.slug === this.step)) this.step = 'sources';
        this.panel = localStorage.getItem('flux-panel') === 'help' ? 'help' : 'assist';
        window.addEventListener('popstate', () => {
          const m = location.pathname.match(/step\/(\w+)/);
          const slug = m ? (LEGACY[m[1]] || m[1]) : 'sources';
          this.step = STEPS.find((x) => x.slug === slug) ? slug : 'sources';
        });
        window.addEventListener('beforeunload', (e) => { if (this.anyDirty) { e.preventDefault(); e.returnValue = ''; } });
        this.$watch('step', () => { this.$nextTick(() => this.drawChart()); if (this.panel === 'help') this.loadHelp('steps/' + this.step); });
        if (this.panel === 'help') this.loadHelp('steps/' + this.step);
        if (this.jInit) this.jInit();
      },

      /* ---------- plumbing ---------- */
      applyTheme() {
        document.documentElement.classList.toggle('dark', this.dark);
        localStorage.setItem('flux-theme', this.dark ? 'dark' : 'light');
        this.$nextTick(() => this.drawChart());
      },
      toast(msg, kind = 'info') {
        const id = Date.now() + Math.random();
        this.toasts.push({ id, msg, kind });
        setTimeout(() => (this.toasts = this.toasts.filter((t) => t.id !== id)), kind === 'error' ? 7000 : 3800);
      },
      async api(method, url, body, isForm) {
        const headers = { Accept: 'application/json' };
        if (method !== 'GET') headers['X-CSRF-Token'] = this.s.csrf_token || '';
        if (body && !isForm) headers['Content-Type'] = 'application/json';
        const res = await fetch(url, { method, headers, credentials: 'include', body: isForm ? body : body ? JSON.stringify(body) : undefined });
        let data = null;
        try { data = await res.json(); } catch (e) { /* non-json */ }
        if (!res.ok) throw new Error((data && data.error) || `Request failed (${res.status})`);
        return data;
      },
      async run(label, fn) {
        this.busy = true; this.busyLabel = label;
        try { return await fn(); } catch (e) { this.toast(e.message, 'error'); return null; } finally { this.busy = false; this.busyLabel = ''; }
      },
      hydrate(state, keepControls) {
        if (!state) return;
        const token = this.s.csrf_token;
        this.s = state;
        if (!this.s.csrf_token) this.s.csrf_token = token;
        const sp = state.spec || {};
        const r = sp.roles || {};
        this.roles = { value: r.value || '', period: r.period || '', scenario: r.scenario || '', debit: r.debit || '', credit: r.credit || '',
          keys: [...(r.keys || [])], dimensions: [...(r.dimensions || [])], driver_text: [...(r.driver_text || [])] };
        const c = sp.comparison || {};
        this.comp = { type: c.type || 'QoQ', base: { months: [...((c.base || {}).months || [])], scenario: (c.base || {}).scenario || '' },
          current: { months: [...((c.current || {}).months || [])], scenario: (c.current || {}).scenario || '' } };
        this.scopeEd = clone(sp.scope || []);
        this.flipEd = clone((sp.value_rules || {}).flip_sign_when || []);
        this.valueEd = {source:'column',null_as_zero:true,...clone(sp.value_rules || {})};
        this.joinsEd = clone(sp.joins || []).map((j) => ({ how: 'left', columns: [], prefix: '', key_normalise: [], dedupe_right: 'first', ...j, on: j.on && j.on.length ? j.on : [{ left: '', right: '' }] }));
        this.deriveEd = clone(sp.derive || []);
        this.scopeDirty = { scope: false, value_rules: false, joins: false, derive: false };
        const cl = sp.classification || {};
        this.cls = { target_col: cl.target_col || 'Category', source_cols: [...(cl.source_cols || [])], rules: clone(cl.rules || []), fallback: cl.fallback ?? 'Unclassified', case_sensitive: !!cl.case_sensitive };
        this.clsDirty = false; this.clsSelected = [];
        const d = sp.drivers || {}; const m = d.materiality || { mode: 'abs', abs: d.materiality_abs || 0 }; const cm = sp.commentary || {};
        this.thr = { mode: m.mode || 'abs', abs: m.abs ?? '', pct: m.pct ?? '', basis: m.basis || 'abs_total_movement', top_n: d.top_n ?? 15, others_label: d.others_label || '',
          units: cm.units || 'K', decimals: cm.decimals ?? 1, verify_tag: cm.verify_tag || '[TO VERIFY]' };
        this.thrDirty = false;
        this.adv = {}; this.advText = {}; this.advErr = {};
        this.closeEdit();
        this.dirty = false;
        if (!keepControls) { this.controls = []; this.controlsRan = false; }
      },
      async refresh() { const st = await this.api('GET', '/state'); this.hydrate(st, true); },
      get anyDirty() { return !!this.pendingSuggestion || this.dirty || this.clsDirty || this.thrDirty || Object.values(this.scopeDirty).some(Boolean) || !!this.editCard?.path; },

      /* ---------- navigation ---------- */
      stepIndex(slug) { return STEPS.findIndex((x) => x.slug === (slug || this.step)); },
      stepDone(slug) {
        const sp = this.s.spec || {};
        switch (slug) {
          case 'sources': return (this.s.sources || []).some((x) => x.defined);
          case 'columns': return !!(sp.roles && sp.roles.value && sp.roles.period);
          case 'comparison': return !!(sp.comparison && (sp.comparison.current || {}).months && sp.comparison.current.months.length);
          case 'scope': return this.stepDone('comparison') && Array.isArray(sp.scope);
          case 'classification': return !!(sp.classification && (sp.classification.rules || []).length);
          case 'rules': return Object.keys(sp.measures || {}).length > 0;
          case 'review': return this.controlsRan && !this.controls.some((c) => c.status === 'stop');
          case 'results': return !!this.result;
        }
        return false;
      },
      go(slug) {
        slug = LEGACY[slug] || slug;
        if (slug === this.step) return;
        if (this.pendingSuggestion) { this.toast('Accept or discard the AI draft before leaving this step.', 'error'); return; }
        if (this.anyDirty && !confirm('You have unsaved edits on this screen. Leave without saving them?')) return;
        if (this.anyDirty) this.hydrate(this.s, true);
        this.step = slug;
        this.agentStatus = 'idle'; this.agentError = '';
        this.clearTarget();
        history.pushState({}, '', '/step/' + slug);
        window.scrollTo({ top: 0, behavior: 'smooth' });
      },
      next() { const i = this.stepIndex(); if (i < STEPS.length - 1) this.go(STEPS[i + 1].slug); },
      get current() { return STEPS[this.stepIndex()] || STEPS[0]; },
      get columnNames() { return ((this.s.profile || {}).columns || []).map((c) => c.name); },
      get definedSources() { return (this.s.sources || []).filter((x) => x.defined); },
      get lookupSources() { return (this.s.sources || []).filter((x) => x.defined && ((x.definition || {}).role || x.role) === 'lookup'); },
      sourceColumns(name) { const src = (this.s.sources || []).find((x) => (x.definition || {}).name === name); return (src && src.columns) || []; },
      blockLabel(b) { return BLOCK_LABEL[b] || b; },
      settingLabel(path) {
        const parts = String(path || '').split('/').filter(Boolean).map((part) => part.replace(/~1/g, '/').replace(/~0/g, '~'));
        const names = { value:'Amount column', period:'Period column', scenario:'Scenario', dimensions:'Group by', keys:'Matching keys', driver_text:'Driver descriptions', abs:'Absolute threshold', pct:'Percentage threshold', flux_name:'Analysis name' };
        return parts.map((part, index) => index === 0 ? this.blockLabel(part).replace(/_/g,' ') : names[part] || part.replace(/_/g,' ')).join(' › ');
      },

      /* ---------- side panel and help ---------- */
      setPanel(p) { this.panel = p; localStorage.setItem('flux-panel', p); if (p === 'help' && !this.helpDoc) this.loadHelp('steps/' + this.step); },
      helpDocs: HELP_DOCS,
      async loadHelp(id) {
        this.helpDocId = id; this.helpLoading = true; this.helpError = '';
        try { this.helpDoc = await this.api('GET', '/help/' + id); }
        catch (e) { this.helpDoc = null; this.helpError = e.message; }
        finally { this.helpLoading = false; }
      },
      openHelp(id) { this.setPanel('help'); this.loadHelp(id || ('steps/' + this.step)); },
      md(src) {
        const inline = (t) => this.esc(t).replace(/`([^`]+)`/g, '<code>$1</code>').replace(/\*\*([^*]+)\*\*/g, '<b>$1</b>').replace(/\*([^*]+)\*/g, '<i>$1</i>')
          .replace(/\[([^\]]+)\]\((https?:\/\/[^)\s]+|\/[^)\s]*)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>');
        const out = []; let list = null; let code = null; let para = [];
        const flush = () => { if (para.length) { out.push('<p>' + inline(para.join(' ')) + '</p>'); para = []; } if (list) { out.push('</' + list + '>'); list = null; } };
        String(src || '').split('\n').forEach((line) => {
          if (code !== null) { if (/^```/.test(line)) { out.push('<pre>' + this.esc(code.join('\n')) + '</pre>'); code = null; } else code.push(line); return; }
          if (/^```/.test(line)) { flush(); code = []; return; }
          let m;
          if ((m = line.match(/^(#{1,4})\s+(.*)/))) { flush(); const n = Math.min(m[1].length + 1, 5); out.push(`<h${n}>${inline(m[2])}</h${n}>`); return; }
          if ((m = line.match(/^\s*[-*]\s+(.*)/)) || (m = line.match(/^\s*\d+[.)]\s+(.*)/))) {
            const t = /^\s*\d/.test(line) ? 'ol' : 'ul';
            if (para.length) { out.push('<p>' + inline(para.join(' ')) + '</p>'); para = []; }
            if (list !== t) { if (list) out.push('</' + list + '>'); out.push('<' + t + '>'); list = t; }
            out.push('<li>' + inline(m[1]) + '</li>'); return;
          }
          if (!line.trim()) { flush(); return; }
          if (list) { out.push('</' + list + '>'); list = null; }
          para.push(line.trim());
        });
        if (code !== null) out.push('<pre>' + this.esc(code.join('\n')) + '</pre>');
        flush();
        return out.join('');
      },

      /* ---------- sources ---------- */
      async upload(files) {
        if (!files || !files.length) return;
        const bad = [...files].filter((f) => !/\.(csv|xlsx|xlsm|xls)$/i.test(f.name));
        if (bad.length) { this.toast('Only CSV or Excel files can be added: ' + bad.map((f) => f.name).join(', '), 'error'); return; }
        const fd = new FormData();
        [...files].forEach((f) => fd.append('files', f));
        await this.run('Reading ' + files.length + ' file' + (files.length > 1 ? 's' : ''), async () => {
          this.hydrate(await this.api('POST', '/sources/upload', fd, true));
          this.toast('Files added. Define each source to continue.');
        });
      },
      onDrop(e) { this.dragging = false; this.upload(e.dataTransfer.files); },
      async demo() {
        await this.run('Loading sample ledger', async () => {
          this.hydrate(await this.api('POST', '/sources/demo', {}));
          this.toast('Sample R&M ledger and Open PO file loaded. These are synthetic, labeled data.');
        });
      },
      async removeSource(src) {
        if (!confirm(`Remove "${src.name}" from this analysis?`)) return;
        await this.run('Removing', async () => this.hydrate(await this.api('DELETE', '/sources/' + src.id)));
      },
      openDefine(src) {
        const d = src.definition || {};
        this.modal = src;
        this.def = { sheet: d.sheet || (src.sheets || [])[0] || null, header_row: d.header_row || 1, start_col: d.start_col || 'A', end_col: d.end_col || '',
          role: d.role || src.role || 'primary', name: d.name || src.name.replace(/\.[^.]+$/, '').replace(/[^A-Za-z0-9]+/g, '_').toLowerCase().slice(0, 32),
          combine_sheets: [...(d.combine_sheets || [])], tag_column: d.tag_column || '' };
        this.preview = null;
        this.loadPreview(!src.defined);
        this.$nextTick(() => { const el = document.getElementById('def-name'); el && el.focus(); });
      },
      closeModal() { this.modal = null; this.preview = null; },
      async loadPreview(useSuggested) {
        if (!this.modal) return;
        this.previewLoading = true;
        const q = new URLSearchParams({ header_row: this.def.header_row, start_col: this.def.start_col || 'A', end_col: this.def.end_col || '' });
        if (this.def.sheet) q.set('sheet', this.def.sheet);
        try {
          const p = await this.api('GET', `/sources/${this.modal.id}/preview?${q}`);
          this.preview = p;
          if (useSuggested && p.suggested_header && p.suggested_header !== this.def.header_row) {
            this.def.header_row = p.suggested_header; await this.loadPreview(false); return;
          }
        } catch (e) { this.toast(e.message, 'error'); } finally { this.previewLoading = false; }
      },
      pickRow(i) { this.def.header_row = i + 1; this.loadPreview(false); },
      pickCol(letter, ev) {
        if (ev && ev.shiftKey) this.def.end_col = letter; else { this.def.start_col = letter; if (this.def.end_col && this.colIdx(this.def.end_col) < this.colIdx(letter)) this.def.end_col = ''; }
        this.loadPreview(false);
      },
      colIdx(l) { return (this.preview && this.preview.letters || []).indexOf(l); },
      colInRange(l) {
        const i = this.colIdx(l), a = this.colIdx(this.def.start_col || 'A'), b = this.def.end_col ? this.colIdx(this.def.end_col) : 1e9;
        return i >= a && i <= b;
      },
      toggleCombine(sh) { const a = this.def.combine_sheets; const i = a.indexOf(sh); i >= 0 ? a.splice(i, 1) : a.push(sh); },
      async saveDefine() {
        if (!this.def.name || !/^[A-Za-z0-9_]+$/.test(this.def.name)) { this.toast('Short name must use letters, digits and underscores only.', 'error'); return; }
        const body = { ...this.def, header_row: Number(this.def.header_row) || 1, end_col: this.def.end_col || null, tag_column: this.def.tag_column || null };
        await this.run('Saving definition', async () => {
          this.hydrate(await this.api('POST', `/sources/${this.modal.id}/define`, body));
          this.closeModal();
          this.toast('Source defined.');
        });
      },

      /* ---------- agent: suggestions, instructions, questions ---------- */
      poll(jobId, onMsg) {
        if (window.htmx) return this.htmxPoll(jobId, onMsg);
        return new Promise((resolve, reject) => {
          const tick = async () => {
            try {
              const j = await this.api('GET', '/jobs/' + jobId);
              if (j.message && onMsg) onMsg(j.message);
              if (j.status === 'done') return resolve(j);
              if (j.status === 'error') return reject(new Error(j.error || 'The job failed.'));
              setTimeout(tick, 1500);
            } catch (e) { reject(e); }
          };
          tick();
        });
      },
      htmxPoll(jobId, onMsg) {
        return new Promise((resolve, reject) => {
          const el = document.createElement('div');
          el.setAttribute('hx-get', '/jobs/' + encodeURIComponent(jobId));
          el.setAttribute('hx-trigger', 'load, every 1500ms');
          el.setAttribute('hx-swap', 'none');
          el.setAttribute('hx-headers', JSON.stringify({ Accept: 'application/json' }));
          let finished = false;
          const end = (fn, v) => { if (finished) return; finished = true; el.remove(); fn(v); };
          el.addEventListener('htmx:afterRequest', (e) => {
            let j = {};
            try { j = JSON.parse(e.detail.xhr.responseText || '{}'); } catch (_) { return end(reject, new Error('Could not read job status.')); }
            if (!e.detail.successful) return end(reject, new Error(j.error || 'Job status request failed.'));
            if (j.message && onMsg) onMsg(j.message);
            if (j.status === 'done') end(resolve, j);
            else if (j.status === 'error') end(reject, new Error(j.error || 'The job failed.'));
          });
          (document.getElementById('job-pollers') || document.body).appendChild(el);
          window.htmx.process(el);
        });
      },
      get agentAvailable() { return !!AGENT_FOR[this.step]; },
      agentLabel(k) { return { detect_flux: 'Detect flux type', map_columns: 'Map columns', define_comparison: 'Define comparison', derive_columns: 'Suggest scope and derived columns', classify_terms: 'Classify description terms', define_rules: 'Propose rules' }[k] || k; },
      async runAgentJob(start, label, suggestionStep) {
        this.agentStatus = 'pending'; this.agentError = ''; this.agentMsg = label;
        try {
          const { job_id } = await start();
          const job = await this.poll(job_id, (m) => (this.agentMsg = m));
          const r = job.result || {};
          this.lastChange = { ...r, at: new Date().toISOString() };
          this.agentStatus = 'done';
          if (suggestionStep && r.suggested && r.draft_spec) {
            const before = clone(this.s.spec);
            this.pendingSuggestion = { step: suggestionStep, baseSpec: before, proposedSpec: clone(r.draft_spec), draftSpec: clone(r.draft_spec),
              confidence: r.confidence, rationale: r.rationale || '', summary: r.summary || '', changes: r.changes || [], warnings: r.warnings || [], edited: false };
            try { await this.previewDraft(this.pendingSuggestion.draftSpec); }
            catch (e) { this.pendingSuggestion = null; throw e; }
            this.toast('Suggestion ready for review. Your saved settings have not changed.');
          } else if (r.status === 'cannot_do' || r.status === 'invalid') this.toast('The assistant could not suggest a valid change. Your settings are unchanged.', 'error');
          return r;
        } catch (e) { this.agentStatus = 'error'; this.agentError = e.message; return null; }
      },
      async resolvePendingBeforeAnotherSuggestion() {
        if (!this.pendingSuggestion) return true;
        const keep = confirm('An AI suggestion is still a draft. Choose OK to keep and save it before asking again, or Cancel to discard it and start over.');
        if (keep) return !!(await this.acceptSuggestion({continueAfter:false}));
        return !!(await this.discardSuggestion());
      },
      async previewDraft(spec) {
        const state = await this.api('POST', '/config/draft/preview', { spec });
        if (this.pendingSuggestion) this.pendingSuggestion.draftSpec = clone(state.spec);
        this.hydrate(state, false);
        this.controlsRan = false; this.controls = [];
      },
      async acceptSuggestion({continueAfter=true} = {}) {
        if (this.pendingSuggestion && this.editCard) { this.toast('Save or cancel the open rule form first.', 'error'); return false; }
        if (this.pendingSuggestion && this.step === 'columns' && this.dirty) {
          if (!this.roles.value || !this.roles.period) { this.toast('Choose the amount and period columns first.', 'error'); return false; }
          if (!(await this.saveRoles())) return false;
        }
        if (this.pendingSuggestion && this.step === 'comparison' && this.dirty && !(await this.saveComparison())) return false;
        if (this.pendingSuggestion && this.step === 'classification' && this.clsDirty && !(await this.saveCls())) return false;
        if (this.pendingSuggestion && this.step === 'rules' && this.thrDirty && !(await this.saveThresholds())) return false;
        if (this.pendingSuggestion && this.step === 'scope' && Object.values(this.scopeDirty).some(Boolean)) {
          this.toast('Save the edited scope sections into the draft before accepting.', 'error'); return false;
        }
        const pending = this.pendingSuggestion;
        if (!pending) return false;
        return this.run('Saving reviewed settings', async () => {
          const state = await this.api('POST', '/config/draft/accept', { base_spec: pending.baseSpec, spec: pending.draftSpec,
            reason: `Accepted reviewed ${pending.step} suggestion${pending.edited ? ' with edits' : ''}` });
          this.pendingSuggestion = null;
          this.hydrate(state, false);
          this.agentStatus = 'idle'; this.lastChange = null;
          this.toast('Configuration saved and validated.');
          if (continueAfter) this.next();
          return true;
        });
      },
      async discardSuggestion() {
        if (!this.pendingSuggestion) return false;
        return this.run('Discarding AI suggestion', async () => {
          const state = await this.api('GET', '/state');
          this.pendingSuggestion = null;
          this.hydrate(state, false);
          this.agentStatus = 'idle'; this.lastChange = null;
          this.toast('AI suggestion and edits made to its draft were discarded. Saved settings were restored.');
          return true;
        });
      },
      confidenceLabel(confidence) {
        const value = String(confidence ?? '').toLowerCase();
        const level = ['high','medium','low'].includes(value) ? value : typeof confidence === 'number' ? (confidence >= .75 ? 'high' : confidence >= .45 ? 'medium' : 'low') : 'medium';
        return `${level[0].toUpperCase()}${level.slice(1)}`;
      },
      getAtPath(root, path) {
        return String(path || '').split('/').slice(1).map((x) => x.replace(/~1/g, '/').replace(/~0/g, '~')).reduce((v, k) => v == null ? undefined : v[k], root);
      },
      suggestionFor(path) {
        const p = this.pendingSuggestion;
        if (!p || !(p.changes || []).some((c) => c.setting === path)) return null;
        return JSON.stringify(this.getAtPath(p.draftSpec, path)) === JSON.stringify(this.getAtPath(p.proposedSpec, path)) ? p : null;
      },
      async restoreSuggestion(path) {
        const p = this.pendingSuggestion;
        if (!p) return false;
        const previous = this.getAtPath(p.baseSpec, path), current = this.getAtPath(p.draftSpec, path);
        const op = previous === undefined ? 'remove' : current === undefined ? 'add' : 'replace';
        const ok = await this.patch([{ op, path, ...(op === 'remove' ? {} : {value:previous}) }], 'Restored the previous value', 'Restoring value');
        if (ok) p.edited = true;
        return ok;
      },
      suggest(stepKey) {
        stepKey = stepKey || AGENT_FOR[this.step];
        if (!stepKey) return;
        if (this.agentStatus === 'pending') return;
        return this.resolvePendingBeforeAnotherSuggestion().then((ready) => ready && this.runAgentJob(() => this.api('POST', `/config/${stepKey}/suggest`, { user_message: this.context || '' }), 'Asking the assistant', stepKey));
      },
      setTarget(path, label) { this.target = path; this.targetLabel = label || path; this.$nextTick(() => { const el = document.getElementById('change-box'); el && el.focus(); }); },
      clearTarget() { this.target = null; this.targetLabel = ''; },
      async sendInstruction(text) {
        const instruction = (text ?? this.instruction).trim();
        if (!instruction) { this.toast('Describe the change first.', 'error'); return; }
        const body = { instruction }; if (this.target) body.target = this.target;
        if (this.agentStatus === 'pending') return;
        const ready = await this.resolvePendingBeforeAnotherSuggestion();
        if (!ready) return;
        const r = await this.runAgentJob(() => this.api('POST', '/instruction', body), 'Interpreting your change', 'apply_instruction');
        if (r && r.suggested) { this.instruction = ''; this.changeDialog = false; this.clearTarget(); }
      },
      questionText(q) { return typeof q === 'string' ? q : (q.question || q.text || q.prompt || ''); },
      questionOptions(q) { return typeof q === 'string' ? [] : (q.options || q.choices || []).map((o) => (typeof o === 'string' ? o : o.label || o.text || o.value)); },
      useQuestion(q) { this.instruction = this.questionText(q) + ' '; this.$nextTick(() => { const el = document.getElementById('change-box'); el && el.focus(); }); },
      changeTone(r) { if (!r) return ''; if (r.status === 'cannot_do' || r.status === 'invalid' || r.applied === false) return 'stop'; if (r.confidence === 'low' || (typeof r.confidence === 'number' && r.confidence < 0.55)) return 'warn'; if (r.status === 'needs_input') return 'warn'; return 'ok'; },
      changeHeading(r) {
        if (!r) return '';
        if (r.applied === false || r.status === 'cannot_do' || r.status === 'invalid') return 'Not applied';
        if (r.status === 'needs_input') return 'Partly applied, input needed';
        if (this.changeTone(r) === 'warn') return 'Applied, please check';
        return 'Applied';
      },
      fmtVal(v) {
        if (v === undefined) return 'not set';
        if (v === null) return 'empty';
        if (typeof v === 'string') return v || 'empty';
        if (Array.isArray(v) && v.every((x) => typeof x !== 'object')) return v.join(', ') || 'none';
        const t = JSON.stringify(v); return t.length > 90 ? t.slice(0, 88) + '...' : t;
      },
      get lastAnswer() {
        const la = this.s.last_answer; if (!la) return null;
        const a = la.answer || (la.proposal || {}).answer || ((la.result || {}).proposal || {}).answer || la.summary;
        return a ? { q: la.question || '', a, at: la.timestamp || la.at || la.created || '', run_id: la.run_id } : null;
      },
      async ask() {
        const question = this.qText.trim(); if (!question) return;
        this.qErr = '';
        const item = { q: question, a: '', status: 'pending', error: '' };
        this.qThread.push(item); this.qText = ''; this.qBusy = true;
        const idx = this.qThread.length - 1;
        try {
          const body = { question }; if (this.result) body.run_id = this.result.id;
          const { job_id } = await this.api('POST', '/questions', body);
          const job = await this.poll(job_id);
          const r = job.result || {};
          this.qThread[idx] = { ...item, status: 'done', a: ((r.proposal || {}).answer) || r.summary || r.rationale || 'No answer returned.', warnings: r.warnings || [] };
          if (r.state) this.s.last_answer = r.state.last_answer || this.s.last_answer;
        } catch (e) { this.qErr = e.message; this.qThread[idx] = { ...item, status: 'error', error: e.message }; }
        finally { this.qBusy = false; }
      },

      /* ---------- spec patches ---------- */
      async patch(ops, reason, label) {
        if (this.pendingSuggestion) {
          const pending = this.pendingSuggestion;
          return this.run(label || 'Updating draft', async () => {
            const state = await this.api('POST', '/config/draft/patch', {
              base_spec: pending.baseSpec, draft_spec: pending.draftSpec, patch: ops, reason: reason || 'Edited the suggested draft',
            });
            pending.draftSpec = clone(state.spec); pending.edited = true;
            pending.changes = pending.changes.map((change) => ({ ...change, to: this.getAtPath(state.spec, change.setting) }));
            this.pendingSuggestion = pending;
            this.hydrate(state, false);
            return true;
          });
        }
        return this.run(label || 'Saving', async () => {
          this.hydrate(await this.api('POST', '/spec/patch', { patch: ops, reason: reason || 'Manual edit' }), false);
          this.toast('Saved. Logged as a user change.');
          return true;
        });
      },
      async continueStep() {
        if (this.pendingSuggestion) return this.acceptSuggestion();
        if (this.step === 'columns' && this.dirty) {
          if (!this.roles.value || !this.roles.period) { this.toast('Choose the amount and period columns before continuing.', 'error'); return false; }
          if (!(await this.saveRoles())) return false;
        } else if (this.step === 'comparison' && this.dirty) {
          if (!this.stepDone('comparison')) { this.toast('Select periods or a scenario on both sides before continuing.', 'error'); return false; }
          if (!(await this.saveComparison())) return false;
        } else if (this.step === 'classification' && this.clsDirty) {
          if (!(await this.saveCls())) return false;
        } else if (this.step === 'rules') {
          if (this.editCard?.path) { this.toast('Save or cancel the open rule form first.', 'error'); return false; }
          if (this.thrDirty && !(await this.saveThresholds())) return false;
        }
        this.next();
        return true;
      },
      async setPreset(id) {
        return this.run('Applying preset', async () => {
          this.hydrate(await this.api('POST', '/presets/apply', { id }));
          this.presetDetail = null;
          this.toast('Preset applied. Review the defaults before analysis.');
          return true;
        });
      },
      async viewPreset(id) {
        try { this.presetDetail = await this.api('GET', `/presets/${encodeURIComponent(id)}`); }
        catch (e) { this.toast(e.message, 'error'); }
      },
      async editPreset(id) {
        try {
          const preset = await this.api('GET', `/presets/${encodeURIComponent(id)}`);
          this.presetDetail = preset;
          this.presetEditor = { id: preset.id, name: preset.name, owner: preset.owner || '', description: preset.description || '', guidance: preset.guidance || '' };
          this.presetEditorOpen = true;
        } catch (e) { this.toast(e.message, 'error'); }
      },
      duplicatePreset() {
        const original = this.presetEditor.id.trim();
        this.presetEditor.id = `${original}_copy`.slice(0, 48);
        this.presetEditor.name = `${this.presetEditor.name} copy`.slice(0, 120);
      },
      async savePreset() {
        return this.run('Saving preset', async () => {
          const response = await this.api('POST', '/presets/save', this.presetEditor);
          this.hydrate(response.state);
          this.presetDetail = response.preset;
          this.presetEditorOpen = false;
          this.toast(`Saved ${response.preset.name} ${response.preset.version}.`);
          return true;
        });
      },
      async importPresetFile(file) {
        if (!file) return;
        try {
          const manifest = JSON.parse(await file.text());
          const response = await this.api('POST', '/presets/import', manifest);
          await this.refresh();
          this.presetDetail = response.preset;
          this.toast(`Imported ${response.preset.name} ${response.preset.version}.`);
        } catch (e) { this.toast(`Preset import failed: ${e.message}`, 'error'); }
        finally { document.getElementById('preset-import').value = ''; }
      },
      async undoSpec(direction) {
        return this.run(direction === 'undo' ? 'Undoing change' : 'Redoing change', async () => {
          this.hydrate(await this.api('POST', `/spec/${direction}`, {}), true);
          this.lastChange = null;
          this.agentStatus = 'idle';
          this.toast(direction === 'undo' ? 'Change undone.' : 'Change redone.');
          return true;
        });
      },
      get changeLog() { return [...(this.s.change_log || [])].reverse(); },
      saveFluxName(v) { if (!v.trim()) return; this.patch([{ op: 'add', path: '/flux_name', value: v.trim() }], 'Renamed analysis', 'Renaming'); },
      toggleIn(arr, v) { const i = arr.indexOf(v); i >= 0 ? arr.splice(i, 1) : arr.push(v); this.dirty = true; },

      /* ---------- columns ---------- */
      SCALARS: ['value', 'period', 'scenario', 'debit', 'credit'],
      setScalarRole(k, col) {
        this.SCALARS.forEach((o) => { if (o !== k && col && this.roles[o] === col) this.roles[o] = ''; });
        this.roles[k] = col; this.dirty = true;
      },
      roleOf(col) {
        const r = this.roles;
        for (const k of this.SCALARS) if (r[k] === col) return k;
        for (const k of ['keys', 'dimensions', 'driver_text']) if (r[k].includes(col)) return k;
        return '';
      },
      saveRoles() {
        const r = this.roles;
        const roles = { value: r.value || null, period: r.period || null, scenario: r.scenario || null, debit: r.debit || null, credit: r.credit || null,
          keys: r.keys, dimensions: r.dimensions, driver_text: r.driver_text };
        return this.patch([{ op: 'add', path: '/roles', value: roles }], 'Column roles mapped', 'Saving column roles');
      },

      /* ---------- comparison ---------- */
      get months() { return this.s.available_months || this.s.periods || []; },
      monthCount(m) { const c = this.s.monthly_row_counts || {}; return Array.isArray(c) ? ((c.find((x) => x.month === m) || {}).rows ?? (c.find((x) => x.month === m) || {}).count) : c[m]; },
      isPartial(m) { const p = this.s.partial_periods_detected || []; return p.some((x) => (typeof x === 'string' ? x : x.month) === m); },
      partialReason(m) { const x = (this.s.partial_periods_detected || []).find((y) => (typeof y === 'string' ? y : y.month) === m); return x && typeof x === 'object' ? (x.reason || '') : 'Row count is low compared with other months.'; },
      monthLabel(m) { const [y, mo] = String(m).split('-'); const n = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'][Number(mo) - 1]; return n ? `${n} ${y}` : m; },
      saveComparison() {
        if ((!this.comp.current.months.length && !this.comp.current.scenario) || (!this.comp.base.months.length && !this.comp.base.scenario)) { this.toast('Pick months or a scenario for each slice.', 'error'); return; }
        const slice = (x) => ({ months: [...x.months].sort(), ...(x.scenario ? { scenario: x.scenario } : {}) });
        const value = { type: this.comp.type, base: slice(this.comp.base), current: slice(this.comp.current) };
        return this.patch([{ op: 'add', path: '/comparison', value }], `Comparison set to ${this.sliceLabel(value.current)} vs ${this.sliceLabel(value.base)}`, 'Saving comparison');
      },

      /* ---------- rule cards ---------- */
      cardsFor(blocks) { return (this.s.rule_cards || []).filter((c) => blocks.includes(c.block)); },
      cardsByBlock(blocks) {
        const out = {}; blocks.forEach((b) => (out[b] = []));
        (this.s.rule_cards || []).forEach((c) => { if (out[c.block]) out[c.block].push(c); });
        return blocks.map((b) => ({ block: b, cards: out[b] }));
      },
      actorLabel(a) { return ({ agent: 'Added by agent', user: 'Added by user', preset: 'From preset' })[a] || (a ? 'Added by ' + a : 'Default'); },
      sentenceHtml(t) { return this.esc(t).replace(/\*\*([^*]+)\*\*/g, '<b>$1</b>'); },
      fieldKind(k, v) {
        if (typeof v === 'boolean') return 'bool';
        if (typeof v === 'number') return 'num';
        if (typeof v === 'string') return /(^col$|_col$|^column$|^left$)/.test(k) ? 'col' : 'text';
        if (Array.isArray(v) && v.every((x) => typeof x === 'string')) return /keys|cols|columns|group_by|dimensions/.test(k) ? 'cols' : 'list';
        return 'json';
      },
      /* ---------- structured rule forms ---------- */
      AGGS: ['sum', 'count', 'mean', 'min', 'max', 'nunique'],
      OPS: [['eq', 'equals'], ['ne', 'is not'], ['in', 'is one of'], ['not_in', 'is not one of'], ['gt', '>'], ['gte', '>='], ['lt', '<'], ['lte', '<='], ['startswith', 'starts with'], ['contains', 'contains'], ['regex', 'matches pattern'], ['isnull', 'is empty'], ['notnull', 'is not empty']],
      CONTROL_IDS: ['required_columns', 'periods_present', 'no_duplicate_periods_across_files', 'sections_reconcile', 'flags_sum_to_rows', 'drivers_reconcile', 'debit_minus_credit_equals_value', 'new_or_removed_members', 'join_unmatched_keys', 'join_fanout', 'classification_coverage', 'partial_period_used'],
      FORM_BLOCKS: ['measures', 'views', 'flags', 'gates', 'sections', 'decompose', 'controls', 'commentary', 'drivers', 'drill'],
      get measureNames() { return Object.keys((this.s.spec || {}).measures || {}); },
      get viewNames() { return ((this.s.spec || {}).views || []).map((v) => v.name).filter(Boolean); },
      formKind(block, path) {
        if (!this.FORM_BLOCKS.includes(block)) return '';
        const seg = String(path || '').split('/').filter(Boolean);
        if (['measures', 'views', 'flags', 'gates', 'controls'].includes(block)) return seg.length === 2 || !path ? block : '';
        return seg.length === 1 || !path ? block : '';
      },
      fromFilter(f) { const v = f.val; return { col: f.col || '', op: f.op || 'eq', val: Array.isArray(v) ? v.join(', ') : v == null ? '' : String(v) }; },
      toFilter(f) {
        if (!f.col) throw new Error('Every filter needs a column.');
        const o = { col: f.col, op: f.op };
        if (['isnull', 'notnull'].includes(f.op)) return o;
        if (['in', 'not_in'].includes(f.op)) { o.val = String(f.val).split(',').map((x) => x.trim()).filter(Boolean); return o; }
        if (['gt', 'gte', 'lt', 'lte'].includes(f.op)) { if (f.val === '' || isNaN(f.val)) throw new Error(`Filter on ${f.col} needs a number.`); o.val = Number(f.val); return o; }
        o.val = f.val; return o;
      },
      toForm(kind, v, path) {
        v = isObj(v) ? clone(v) : {};
        const c0 = this.columnNames[0] || '';
        const m0 = this.measureNames[0] || 'amount';
        switch (kind) {
          case 'measures': { const nm = path ? (path.split('/')[2] || '').replace(/~1/g, '/').replace(/~0/g, '~') : ''; return { name: nm, origName: nm, agg: v.agg || 'sum', col: v.col || (this.s.spec?.roles?.value) || c0, slice: v.slice || '', filter: (v.filter || []).map((f) => this.fromFilter(f)) }; }
          case 'views': return { name: v.name || '', keys: [...(v.keys || [])], measures: [...(v.measures || [m0])], compare: v.compare !== false, _extra: v.joins ? { joins: v.joins } : {} };
          case 'flags': return { view: v.view || this.viewNames[0] || '', name: v.name || '', ordered: clone(v.ordered || [{ if: '', label: '' }]), default: v.default ?? 'Unclassified' };
          case 'gates': return { view: v.view || this.viewNames[0] || '', name: v.name || '', if: v.if || '' };
          case 'sections': return { split_by: v.split_by || c0, must_reconcile_to: v.must_reconcile_to || m0, order: (v.order || []).join(', '), _extra: Object.fromEntries(Object.entries(v).filter(([k]) => !['split_by', 'must_reconcile_to', 'order'].includes(k))) };
          case 'decompose': return { method: v.method || 'volume_at_base_rate', measure: v.measure || m0, volume: v.volume || '', rate: v.rate || '' };
          case 'controls': { const p = clone(v.params || {}); const mp = p.minimum_percentage; delete p.minimum_percentage; return { id: v.id || 'classification_coverage', severity: v.severity || 'warn', tolerance: v.tolerance ?? '', minimum_percentage: mp ?? '', _params: p }; }
          case 'drivers': { const o = { view: v.view || '', measure: v.measure || '', top_n: v.top_n ?? 15, others_label: v.others_label || '' }; o._extra = Object.fromEntries(Object.entries(v).filter(([k]) => !(k in o))); return o; }
          case 'drill': return { group_by: Array.isArray(v.group_by) ? [...v.group_by] : v.group_by ? [v.group_by] : [], top_n: v.top_n ?? 5 };
          case 'commentary': {
            const dls = []; Object.entries(v.dimension_label_style || {}).forEach(([col, mp]) => { if (isObj(mp)) Object.entries(mp).forEach(([val, label]) => dls.push({ col, val, label: String(label) })); });
            return { units: v.units || 'M', decimals: v.decimals ?? 1, currency_symbol: v.currency_symbol ?? '$', sign_style: v.sign_style || 'plus_minus', favorable_when: v.favorable_when || 'positive', max_line_words: v.max_line_words ?? 35, verify_tag: v.verify_tag ?? '[TO VERIFY]', style: v.style || '', headline_template: v.headline_template || '', forbidden_terms: (v.forbidden_terms || []).join(', '), dls };
          }
        }
        return {};
      },
      fromForm(kind, f) {
        const req = (x, what) => { if (x === '' || x == null || (Array.isArray(x) && !x.length)) throw new Error(`${what} is required.`); return x; };
        const int = (x, what, lo, hi) => { const n = Number(x); if (x === '' || !Number.isInteger(n) || n < lo || n > hi) throw new Error(`${what} must be a whole number from ${lo} to ${hi}.`); return n; };
        switch (kind) {
          case 'measures': {
            if (!/^[A-Za-z_][A-Za-z0-9_]*$/.test(f.name || '')) throw new Error('Measure name must start with a letter or underscore and use only letters, digits and underscores.');
            if (f.name !== f.origName && this.measureNames.includes(f.name)) throw new Error(`A measure called ${f.name} already exists.`);
            const o = { agg: f.agg, col: req(f.col, 'Column') }; if (f.slice) o.slice = f.slice;
            if (f.filter.length) o.filter = f.filter.map((x) => this.toFilter(x)); return o;
          }
          case 'views': return { name: req(String(f.name).trim(), 'View name'), keys: f.keys, measures: req(f.measures, 'At least one measure'), compare: !!f.compare, ...f._extra };
          case 'flags': {
            const ordered = f.ordered.filter((r) => r.if || r.label);
            ordered.forEach((r, i) => { if (!r.if || !r.label) throw new Error(`Condition ${i + 1} needs both a test and a label.`); });
            req(ordered, 'At least one condition');
            const o = { view: req(f.view, 'View'), name: req(String(f.name).trim(), 'Flag column name'), ordered }; if (f.default !== '') o.default = f.default; return o;
          }
          case 'gates': return { view: req(f.view, 'View'), name: req(String(f.name).trim(), 'Gate name'), if: req(String(f.if).trim(), 'Expression') };
          case 'sections': { const o = { ...f._extra, split_by: req(f.split_by, 'Split column'), must_reconcile_to: req(f.must_reconcile_to, 'Measure') }; const order = String(f.order).split(',').map((x) => x.trim()).filter(Boolean); if (order.length) o.order = order; return o; }
          case 'decompose': return { method: 'volume_at_base_rate', measure: req(f.measure, 'Amount measure'), volume: req(f.volume, 'Volume measure'), rate: req(f.rate, 'Rate measure') };
          case 'controls': {
            const o = { id: f.id, severity: f.severity };
            if (f.tolerance !== '' && f.tolerance != null) { if (isNaN(f.tolerance) || Number(f.tolerance) < 0) throw new Error('Tolerance must be zero or more.'); o.tolerance = Number(f.tolerance); }
            const p = { ...f._params };
            if (f.id === 'classification_coverage' && f.minimum_percentage !== '' && f.minimum_percentage != null) { const n = Number(f.minimum_percentage); if (isNaN(n) || n < 0 || n > 100) throw new Error('Minimum % must be between 0 and 100.'); p.minimum_percentage = n; }
            if (Object.keys(p).length) o.params = p; return o;
          }
          case 'drivers': { const o = { ...f._extra, top_n: int(f.top_n, 'Top N', 1, 100) }; if (f.view) o.view = f.view; if (f.measure) o.measure = f.measure; if (f.others_label) o.others_label = f.others_label; return o; }
          case 'drill': { const o = { top_n: int(f.top_n, 'Top N', 1, 100) }; if (f.group_by.length) o.group_by = f.group_by.length === 1 ? f.group_by[0] : f.group_by; return o; }
          case 'commentary': {
            const o = { units: f.units, decimals: int(f.decimals, 'Decimals', 0, 6), currency_symbol: f.currency_symbol, sign_style: f.sign_style, favorable_when: f.favorable_when, max_line_words: int(f.max_line_words, 'Max words per line', 1, 200), verify_tag: f.verify_tag };
            if (f.style) o.style = f.style; if (f.headline_template) o.headline_template = f.headline_template;
            const ft = String(f.forbidden_terms).split(',').map((x) => x.trim()).filter(Boolean); if (ft.length) o.forbidden_terms = ft;
            const d = {}; f.dls.forEach((r) => { if (!r.col || r.val === '') return; (d[r.col] = d[r.col] || {})[r.val] = r.label; }); if (Object.keys(d).length) o.dimension_label_style = d;
            return o;
          }
        }
        return {};
      },
      fieldInit(k, v) { const kind = this.fieldKind(k, v); return { k, kind, val: kind === 'json' ? JSON.stringify(v, null, 2) : kind === 'list' ? v.join(', ') : clone(v), err: '', open: false }; },
      startEdit(card, isNew) {
        const v = clone(card.value);
        const kind = this.formKind(card.block, isNew ? '' : card.path);
        const fields = kind ? [] : isObj(v) ? Object.keys(v).map((k) => this.fieldInit(k, v[k])) : [this.fieldInit('', v)];
        this.editCard = { path: card.path, block: card.block, sentence: card.sentence || '', isNew: !!isNew, kind, form: {filter:[],keys:[],measures:[],ordered:[],group_by:[],dls:[],...(kind ? this.toForm(kind, v, isNew ? '' : card.path) : {})}, isObj: isObj(v), fields, showJson: false, json: JSON.stringify(v, null, 2), jsonErr: '', reason: '' };
      },
      closeEdit() {
        // Retain the form through Alpine's asynchronous removal of nested options.
        if (this.editCard) this.editCard = {...this.editCard, path:null, isNew:false};
      },
      newDraft(block) {
        const existing = (this.s.rule_cards || []).find((c) => c.block === block && c.path === '/' + block);
        if (['sections', 'decompose', 'commentary', 'drivers', 'drill'].includes(block) && existing) { this.clearTarget(); this.startEdit(existing); this.toast('This block holds one setting; editing it in a form.'); return; }
        if (this.editCard?.path && !confirm('Discard the edit in progress?')) return;
        this.clearTarget();
        this.startEdit({ path: '/' + block, block, value: {} }, true);
        if (block === 'measures') this.editCard.form.name = 'measure_' + (this.measureNames.length + 1);
        if (block === 'flags' || block === 'gates' || block === 'views') this.editCard.form.name = '';
        this.$nextTick(() => { const el = document.querySelector('.editor.draft input, .editor.draft select'); el && el.focus(); });
      },
      editValue() {
        const e = this.editCard; if (!e) return undefined;
        if (e.showJson) return JSON.parse(e.json);
        if (e.kind) return this.fromForm(e.kind, e.form);
        const conv = (f) => {
          if (f.kind === 'num') { if (f.val === '' || isNaN(f.val)) throw new Error(`${f.k || 'Value'} must be a number.`); return Number(f.val); }
          if (f.kind === 'list') return String(f.val).split(',').map((x) => x.trim()).filter(Boolean);
          if (f.kind === 'json') { try { return JSON.parse(f.val); } catch (err) { throw new Error(`${f.k || 'Value'}: ${err.message}`); } }
          return f.val;
        };
        if (!e.isObj) return conv(e.fields[0]);
        const o = {}; e.fields.forEach((f) => (o[f.k] = conv(f))); return o;
      },
      toggleEditJson() {
        const e = this.editCard;
        try {
          if (!e.showJson) { e.json = JSON.stringify(this.editValue(), null, 2); e.showJson = true; e.jsonErr = ''; }
          else {
            const v = JSON.parse(e.json); const name = e.kind === 'measures' ? e.form.name : null; const orig = e.kind === 'measures' ? e.form.origName : null;
            const keep = { isNew: e.isNew, reason: e.reason };
            this.startEdit({ path: e.path, block: e.block, sentence: e.sentence, value: v }, e.isNew);
            Object.assign(this.editCard, keep); if (name != null) { this.editCard.form.name = name; this.editCard.form.origName = orig; }
          }
        } catch (err) { e.jsonErr = err.message; }
      },
      esc_ptr(x) { return String(x).replace(/~/g, '~0').replace(/\//g, '~1'); },
      async saveEdit() {
        let value;
        const e = this.editCard;
        try { value = this.editValue(); } catch (err) { e.jsonErr = err.message; return; }
        let ops;
        const label = this.blockLabel(e.block).toLowerCase();
        if (e.kind === 'measures' || (e.block === 'measures' && e.isNew)) {
          const name = e.form ? e.form.name : null;
          if (!name) { e.jsonErr = 'Measure name is required.'; return; }
          const path = '/measures/' + this.esc_ptr(name);
          if (e.isNew) ops = [{ op: 'add', path, value }];
          else if (name !== e.form.origName) {
            const used = ((this.s.spec || {}).views || []).filter((v) => (v.measures || []).includes(e.form.origName)).map((v) => v.name);
            if (used.length && !confirm(`Views ${used.join(', ')} use ${e.form.origName}. Rename anyway? You will need to update those views.`)) return;
            ops = [{ op: 'remove', path: e.path }, { op: 'add', path, value }];
          } else ops = [{ op: 'replace', path: e.path, value }];
        } else if (e.isNew) {
          ops = [{ op: 'add', path: ['sections', 'decompose'].includes(e.block) ? '/' + e.block : '/' + e.block + '/-', value }];
        } else ops = [{ op: 'replace', path: e.path, value }];
        const ok = await this.patch(ops, e.reason || `${e.isNew ? 'Added' : 'Edited'} ${label}`, e.isNew ? 'Adding rule' : 'Saving rule');
        if (ok) this.closeEdit();
      },
      async removeCard(card) {
        if (!this.canRemove(card)) { this.toast('This setting is required. Edit it instead.', 'error'); return; }
        if (!confirm(`Remove this rule?\n\n${card.sentence.replace(/\*\*/g, '')}`)) return;
        await this.patch([{ op: 'remove', path: card.path }], `Removed: ${card.sentence.replace(/\*\*/g, '')}`.slice(0, 200), 'Removing rule');
      },
      REQUIRED_PARENTS: ['roles', 'comparison', 'drivers', 'commentary', 'drill', 'value_rules', 'classification', 'preset', 'periods'],
      REQUIRED_TOP: ['roles', 'comparison', 'measures', 'drivers', 'commentary', 'flux_name', 'spec_version', 'sources'],
      canRemove(card) {
        if (card.removable === false) return false;
        if (card.removable === true) return true;
        const seg = String(card.path || '').split('/').filter(Boolean);
        if (!seg.length) return false;
        if (/^\d+$/.test(seg[seg.length - 1])) return true;
        if (seg.length === 1) return !this.REQUIRED_TOP.includes(seg[0]);
        if (seg[0] === 'measures' && seg.length === 2) return Object.keys((this.s.spec || {}).measures || {}).length > 1;
        return !this.REQUIRED_PARENTS.includes(seg[0]);
      },
      describeCard(card) { this.setTarget(card.path, card.sentence.replace(/\*\*/g, '')); this.instruction = ''; this.changeDialog = true; },
      addRule(block) { this.setTarget('/' + block, this.blockLabel(block)); this.addPrompt = ADD_PROMPT[block] || 'Describe what to add'; },
      addPrompt: '',
      get changePlaceholder() { return this.target ? (this.addPrompt && this.targetLabel === this.blockLabel(this.target.slice(1)) ? this.addPrompt : 'Describe how this rule should change') : 'Only EMEA · Compare May vs April · Set materiality to 250k · Flag anything above 10% as Material'; },

      /* ---------- advanced JSON per block ---------- */
      toggleAdv(b) {
        if (this.adv[b]) { this.adv = { ...this.adv, [b]: false }; return; }
        const v = (this.s.spec || {})[b];
        this.advText = { ...this.advText, [b]: JSON.stringify(v === undefined ? null : v, null, 2) };
        this.advErr = { ...this.advErr, [b]: '' };
        this.adv = { ...this.adv, [b]: true };
      },
      checkAdv(b) { try { JSON.parse(this.advText[b]); this.advErr = { ...this.advErr, [b]: '' }; } catch (e) { this.advErr = { ...this.advErr, [b]: 'Not valid JSON: ' + e.message }; } },
      async saveAdv(b) {
        let v; try { v = JSON.parse(this.advText[b]); } catch (e) { this.advErr = { ...this.advErr, [b]: 'Not valid JSON: ' + e.message }; return; }
        const ok = await this.patch([{ op: 'add', path: '/' + b, value: v }], `Edited ${this.blockLabel(b).toLowerCase()} in Advanced JSON`, 'Validating and saving');
        if (ok) this.adv = { ...this.adv, [b]: false };
      },

      /* ---------- scope, value rules, joins, derive ---------- */
      OPS: [['eq', 'equals'], ['ne', 'does not equal'], ['in', 'is one of'], ['not_in', 'is not one of'], ['contains', 'contains'], ['startswith', 'starts with'], ['regex', 'matches pattern'], ['gt', 'greater than'], ['gte', 'at least'], ['lt', 'less than'], ['lte', 'at most'], ['isnull', 'is empty'], ['notnull', 'is not empty']],
      noVal(op) { return op === 'isnull' || op === 'notnull'; },
      valText(f) { if (!f || f.val == null) return ''; return Array.isArray(f.val) ? f.val.join(', ') : String(f.val); },
      coerceVal(op, raw) {
        if (this.noVal(op)) return undefined;
        if (op === 'in' || op === 'not_in') return String(raw).split(',').map((x) => x.trim()).filter(Boolean);
        if (['gt', 'gte', 'lt', 'lte'].includes(op) && String(raw).trim() !== '' && !isNaN(raw)) return Number(raw);
        return raw;
      },
      setFilter(f, field, v) {
        if (field === 'op') { f.op = v; const val = this.coerceVal(v, this.valText(f)); if (val === undefined) delete f.val; else f.val = val; }
        else if (field === 'val') f.val = this.coerceVal(f.op, v);
        else f[field] = v;
      },
      filterList(kind) { return kind === 'flip' ? this.flipEd : this.scopeEd; },
      markFilter(kind) { this.scopeDirty[kind === 'flip' ? 'value_rules' : 'scope'] = true; },
      addFilter(kind) { this.filterList(kind).push({ col: this.columnNames[0] || '', op: 'eq', val: '' }); this.markFilter(kind); },
      updFilter(kind, i, field, v) { this.setFilter(this.filterList(kind)[i], field, v); this.markFilter(kind); },
      delFilter(kind, i) { this.filterList(kind).splice(i, 1); this.markFilter(kind); },
      saveScope() { this.patch([{ op: 'add', path: '/scope', value: this.scopeEd }], this.scopeEd.length ? `Scope set to ${this.scopeEd.length} filter(s)` : 'Scope cleared', 'Saving scope'); },
      saveFlip() {
        const vr = { ...this.valueEd, flip_sign_when: this.flipEd };
        this.patch([{ op: 'add', path: '/value_rules', value: vr }], 'Sign flip conditions updated', 'Saving value rules');
      },
      addJoin() { const src = this.lookupSources[0]; this.joinsEd.push({ source: src ? src.definition.name : '', on: [{ left: '', right: '' }], how: 'left', columns: [], prefix: '', key_normalise: [], dedupe_right: 'first' }); this.scopeDirty.joins = true; },
      delJoin(i) { if (!confirm('Remove this join?')) return; this.joinsEd.splice(i, 1); this.scopeDirty.joins = true; },
      toggleJoinArr(j, k, v) { const a = j[k]; const i = a.indexOf(v); i >= 0 ? a.splice(i, 1) : a.push(v); this.scopeDirty.joins = true; },
      saveJoins() {
        for (const j of this.joinsEd) {
          if (!j.source) { this.toast('Each join needs a lookup source.', 'error'); return; }
          if (j.on.some((p) => !p.left || !p.right)) { this.toast('Fill both key columns for every join pair.', 'error'); return; }
        }
        const value = this.joinsEd.map((j) => {
          const o = { source: j.source, on: j.on.map((p) => ({ left: p.left, right: p.right })), how: 'left', columns: j.columns, prefix: j.prefix || '', key_normalise: j.key_normalise, dedupe_right: j.dedupe_right };
          if (j.unmatched) o.unmatched = j.unmatched;
          if (j.optional !== undefined) o.optional = j.optional;
          return o;
        });
        this.patch([{ op: 'add', path: '/joins', value }], `Joins updated (${value.length})`, 'Saving joins');
      },
      whenOf(r) { return Array.isArray(r.when) ? r.when[0] || {} : r.when || {}; },
      DERIVE_TYPES: [['rules', 'Rules (first match wins)'], ['regex_extract', 'Extract with a pattern'], ['map', 'Map values'], ['ratio', 'Ratio of two columns'], ['concat', 'Join columns as text'], ['bucket_numeric', 'Numeric buckets']],
      newDerive: 'rules',
      deriveTemplate(type, name) {
        const c0 = this.columnNames[0] || '';
        const t = { rules: { rules: [], default: 'Other' }, regex_extract: { source: c0, pattern: '', default: 'UNMATCHED' }, map: { source: c0, mapping: {}, default: 'UNMATCHED' },
          ratio: { numerator: c0, denominator: c0 }, concat: { source: [], separator: ' ' }, bucket_numeric: { source: c0, bins: [] } }[type] || {};
        return { name, type, ...t };
      },
      addDerive() { this.deriveEd.push(this.deriveTemplate(this.newDerive, 'New_column_' + (this.deriveEd.length + 1))); this.scopeDirty.derive = true; },
      changeDeriveType(i, type) {
        const d = this.deriveEd[i]; if (d.type === type) return;
        if (!confirm('Changing the type resets this column\'s settings. Continue?')) { this.deriveEd = [...this.deriveEd]; return; }
        this.deriveEd[i] = this.deriveTemplate(type, d.name); this.scopeDirty.derive = true;
      },
      srcList(d) { return Array.isArray(d.source) ? d.source : d.source ? [d.source] : []; },
      toggleDeriveSrc(i, col) {
        const d = this.deriveEd[i]; const a = [...this.srcList(d)]; const k = a.indexOf(col); k >= 0 ? a.splice(k, 1) : a.push(col);
        d.source = d.type === 'regex_extract' && a.length === 1 ? a[0] : a; this.scopeDirty.derive = true;
      },
      mapEntries(d) { return Object.entries(d.mapping || d.map || {}); },
      setMapRows(i, rows) { const d = this.deriveEd[i]; const o = {}; rows.forEach(([k, v]) => { o[k] = v; }); delete d.map; d.mapping = o; this.scopeDirty.derive = true; },
      updMap(i, idx, part, v) {
        const rows = this.mapEntries(this.deriveEd[i]);
        if (part === 0 && rows.some((r, j) => j !== idx && r[0] === v)) { this.toast('That source value is already mapped.', 'error'); this.deriveEd = [...this.deriveEd]; return; }
        rows[idx][part] = v; this.setMapRows(i, rows);
      },
      addMapRow(i) { const rows = this.mapEntries(this.deriveEd[i]); let k = 'value'; let n = 1; while (rows.some((r) => r[0] === k)) k = 'value_' + (++n); rows.push([k, '']); this.setMapRows(i, rows); },
      delMapRow(i, idx) { const rows = this.mapEntries(this.deriveEd[i]); rows.splice(idx, 1); this.setMapRows(i, rows); },
      numList(raw) { return String(raw).split(',').map((x) => x.trim()).filter((x) => x !== '').map(Number); },
      setBins(i, raw) {
        const b = this.numList(raw); const d = this.deriveEd[i];
        if (b.some(isNaN)) { this.toast('Bin edges must be numbers separated by commas.', 'error'); return; }
        if (b.some((x, k) => k && x <= b[k - 1])) { this.toast('Bin edges must increase from left to right.', 'error'); return; }
        d.bins = b; this.scopeDirty.derive = true;
      },
      setLabels(i, raw) { const d = this.deriveEd[i]; const l = String(raw).split(',').map((x) => x.trim()).filter(Boolean); if (l.length) d.labels = l; else delete d.labels; this.scopeDirty.derive = true; },
      deriveProblem(d) {
        if (!d.name || !String(d.name).trim()) return 'needs a column name';
        switch (d.type) {
          case 'regex_extract': if (!this.srcList(d).length) return 'needs a source column'; if (!d.pattern) return 'needs a pattern'; try { new RegExp(d.pattern); } catch (e) { return 'pattern is not valid'; } if (d.pattern.length > 500) return 'pattern is too long'; return '';
          case 'map': if (!d.source) return 'needs a source column'; if (!this.mapEntries(d).length) return 'needs at least one mapping'; return '';
          case 'ratio': if (!d.numerator || !d.denominator) return 'needs numerator and denominator'; return '';
          case 'concat': if (!this.srcList(d).length) return 'needs at least one column'; return '';
          case 'bucket_numeric': if (!d.source) return 'needs a source column'; if ((d.bins || []).length < 2) return 'needs at least two bin edges'; if (d.labels && d.labels.length !== d.bins.length - 1) return 'needs one label per bucket (edges minus one)'; return '';
          case 'rules': if ((d.rules || []).some((r) => r.then == null || r.then === '')) return 'every rule needs a label'; return '';
        }
        return '';
      },
      delDerive(i) { if (confirm('Remove this derived column?')) { this.deriveEd.splice(i, 1); this.scopeDirty.derive = true; } },
      updDerive(i, field, v) { this.deriveEd[i][field] = v; this.scopeDirty.derive = true; },
      addWhen(i) { (this.deriveEd[i].rules = this.deriveEd[i].rules || []).push({ when: { col: this.columnNames[0] || '', op: 'contains', val: '' }, then: '' }); this.scopeDirty.derive = true; },
      delWhen(i, j) { this.deriveEd[i].rules.splice(j, 1); this.scopeDirty.derive = true; },
      updWhen(i, j, field, v) {
        const r = this.deriveEd[i].rules[j];
        if (field === 'then') r.then = v;
        else if (Array.isArray(r.when)) { r.when[0] = r.when[0] || {}; this.setFilter(r.when[0], field, v); }
        else { r.when = r.when || {}; this.setFilter(r.when, field, v); }
        this.scopeDirty.derive = true;
      },
      moveWhen(i, from, to) { const rs = this.deriveEd[i].rules; if (to < 0 || to >= rs.length) return; const [x] = rs.splice(from, 1); rs.splice(to, 0, x); this.scopeDirty.derive = true; },
      dragRule: null,
      saveDerive() {
        const bad = this.deriveEd.map((d, i) => [i, this.deriveProblem(d)]).find((x) => x[1]);
        if (bad) { this.toast(`Derived column ${bad[0] + 1} ${bad[1]}.`, 'error'); return; }
        this.patch([{ op: 'add', path: '/derive', value: this.deriveEd }], `Derived columns updated (${this.deriveEd.length})`, 'Saving derived columns'); },
      async previewSection(sec) {
        if (this.scopeDirty[sec]) { this.toast('Save your edits first, then preview.', 'error'); return; }
        await this.run('Previewing ' + sec, async () => { this.sectionPreview = { ...this.sectionPreview, [sec]: await this.api('POST', '/config/preview/' + sec, {}) }; });
      },

      /* ---------- classification ---------- */
      specificity(r) { const w = { eq: 3, regex: 2, startswith: 1, contains: 0 }[r.match] ?? 0; return w * 1000 + String(r.keyword || '').length; },
      get clsRows() {
        const q = this.clsQuery.trim().toLowerCase();
        return this.cls.rules.map((r, i) => ({ r, i })).filter(({ r }) =>
          (this.clsFilter === 'all' || (this.clsFilter === 'reviewed' ? r.reviewed : !r.reviewed)) &&
          (!q || String(r.keyword).toLowerCase().includes(q) || String(r.category).toLowerCase().includes(q)));
      },
      get clsCategories() { return [...new Set(this.cls.rules.map((r) => r.category).filter(Boolean))].sort(); },
      get clsUnreviewed() { return this.cls.rules.filter((r) => !r.reviewed).length; },
      clsTouch() { this.clsDirty = true; this.clsPreview = null; },
      clsAdd() { this.cls.rules.push({ keyword: '', category: '', match: 'contains', reviewed: true }); this.clsTouch(); this.clsFilter = 'all'; this.$nextTick(() => { const el = document.getElementById('cls-kw-' + (this.cls.rules.length - 1)); el && el.focus(); }); },
      clsDel(i) { this.cls.rules.splice(i, 1); this.clsSelected = []; this.clsTouch(); },
      clsMove(i, to) { const a = this.cls.rules; if (to < 0 || to >= a.length) return; const [x] = a.splice(i, 1); a.splice(to, 0, x); this.clsSelected = []; this.clsTouch(); },
      clsSortSpecific() { this.cls.rules.sort((a, b) => this.specificity(b) - this.specificity(a)); this.clsSelected = []; this.clsTouch(); this.toast('Most specific keywords now match first. Save to keep this order.'); },
      clsToggleSel(i) { const k = this.clsSelected.indexOf(i); k >= 0 ? this.clsSelected.splice(k, 1) : this.clsSelected.push(i); },
      clsSelectVisible(on) { this.clsSelected = on ? this.clsRows.map((x) => x.i) : []; },
      clsAccept(selectedOnly) {
        const idx = selectedOnly ? this.clsSelected : this.clsRows.map((x) => x.i);
        let n = 0; idx.forEach((i) => { if (!this.cls.rules[i].reviewed) { this.cls.rules[i].reviewed = true; n++; } });
        this.clsSelected = []; if (n) this.clsTouch();
        this.toast(n ? `${n} rule${n > 1 ? 's' : ''} marked reviewed. Save to keep.` : 'Nothing to accept.');
      },
      clsDeleteSel() { if (!this.clsSelected.length || !confirm(`Delete ${this.clsSelected.length} selected rule(s)?`)) return; this.cls.rules = this.cls.rules.filter((_, i) => !this.clsSelected.includes(i)); this.clsSelected = []; this.clsTouch(); },
      clsToggleSource(c) { const a = this.cls.source_cols; const i = a.indexOf(c); i >= 0 ? a.splice(i, 1) : a.push(c); this.clsTouch(); },
      saveCls() {
        if (this.cls.rules.some((r) => !String(r.keyword).trim() || !String(r.category).trim())) { this.toast('Every rule needs a keyword and a category.', 'error'); return; }
        if (!this.cls.source_cols.length) { this.toast('Choose at least one text column to search.', 'error'); return; }
        const value = { target_col: this.cls.target_col || 'Category', source_cols: this.cls.source_cols, rules: this.cls.rules.map((r) => ({ keyword: r.keyword.trim(), category: r.category.trim(), match: r.match || 'contains', reviewed: !!r.reviewed })), fallback: this.cls.fallback, case_sensitive: !!this.cls.case_sensitive };
        return this.patch([{ op: 'add', path: '/classification', value }], `Classification saved (${value.rules.length} rules)`, 'Saving classification');
      },
      async previewCls() {
        if (this.clsDirty) { this.toast('Save the classification first, then preview.', 'error'); return; }
        await this.run('Previewing classification', async () => { this.clsPreview = await this.api('POST', '/classification/preview', {}); });
      },

      /* ---------- thresholds ---------- */
      saveThresholds() {
        const t = this.thr;
        const mat = { mode: t.mode, basis: t.basis };
        if (t.mode !== 'pct_of_total') { if (t.abs === '' || isNaN(t.abs) || Number(t.abs) < 0) { this.toast('Absolute materiality must be a number of zero or more.', 'error'); return; } mat.abs = Number(t.abs); }
        if (t.mode !== 'abs') { const p = Number(t.pct); if (t.pct === '' || isNaN(p) || p < 0 || p > 1) { this.toast('Percentage must be a fraction between 0 and 1, e.g. 0.05 for 5%.', 'error'); return; } mat.pct = p; }
        if (t.mode === 'abs') delete mat.basis;
        const ops = [
          { op: 'add', path: '/drivers/materiality', value: mat },
          { op: 'add', path: '/drivers/top_n', value: Math.max(1, Math.min(100, Number(t.top_n) || 15)) },
          { op: 'add', path: '/drivers/others_label', value: t.others_label || 'Other items' },
          { op: 'add', path: '/commentary/units', value: t.units },
          { op: 'add', path: '/commentary/decimals', value: Math.max(0, Math.min(4, Number(t.decimals) || 0)) },
          { op: 'add', path: '/commentary/verify_tag', value: t.verify_tag || '[TO VERIFY]' },
        ];
        if (!(this.s.spec || {}).drivers) ops.unshift({ op: 'add', path: '/drivers', value: {} });
        if (!(this.s.spec || {}).commentary) ops.unshift({ op: 'add', path: '/commentary', value: {} });
        return this.patch(ops, 'Materiality and output settings updated', 'Saving thresholds');
      },
      matSentence() {
        const t = this.thr; const pct = t.pct === '' ? '?' : (Number(t.pct) * 100).toFixed(2).replace(/\.?0+$/, '') + '%';
        const abs = t.abs === '' ? '?' : this.full(Number(t.abs));
        const basis = String(t.basis || '').replace(/_/g, ' ');
        return { abs: `A driver is material when its movement is at least ${abs}.`, pct_of_total: `A driver is material when its movement is at least ${pct} of ${basis}.`,
          max_of: `A driver is material when its movement clears the larger of ${abs} and ${pct} of ${basis}.`, min_of: `A driver is material when its movement clears the smaller of ${abs} and ${pct} of ${basis}.` }[t.mode] || '';
      },

      /* ---------- review & run ---------- */
      sliceLabel(slice) { if (!slice) return 'not selected'; return [((slice.months || []).map((m) => this.monthLabel(m)).join(', ') || slice.period || ''), slice.scenario || ''].filter(Boolean).join(' · ') || 'not selected'; },
      async runControls() {
        await this.run('Running controls', async () => { const r = await this.api('POST', '/review/controls', {}); this.controls = r.controls || []; this.controlsRan = true; });
      },
      get stops() { return this.controls.filter((c) => c.status === 'stop').length; },
      get warns() { return this.controls.filter((c) => c.status === 'warn').length; },
      async calculate() {
        if (!this.controlsRan || this.stops) { this.toast('Run controls and clear every stop before calculating.', 'error'); return; }
        this.busy = true; this.busyLabel = 'Calculating';
        try {
          const { job_id } = await this.api('POST', '/run', {});
          const job = await this.poll(job_id, (m) => (this.busyLabel = m));
          const res = await this.api('GET', `/results/${job.result.run_id}?format=json`);
          this.setResult(res);
          await this.refresh();
          this.go('results');
        } catch (e) { this.toast(e.message, 'error'); } finally { this.busy = false; this.busyLabel = ''; }
      },
      async openRun(id) {
        await this.run('Opening run', async () => { this.setResult(await this.api('GET', `/results/${id}?format=json`)); this.step = 'results'; history.pushState({}, '', '/step/results'); });
      },
      async reuseRun(r) {
        if (!confirm(`Reuse the settings from "${r.name}" with the sources currently uploaded? Your current spec can be restored with Undo.`)) return;
        await this.run('Reusing run settings', async () => {
          const st = await this.api('POST', `/runs/${r.id}/reuse`, {});
          this.hydrate(st); this.missing = st.missing_columns || [];
          this.toast('Historical settings applied. Run controls before calculating.');
          this.go(this.missing.length ? 'columns' : 'review');
        });
      },

      /* ---------- results ---------- */
      setResult(r) {
        this.result = r; const c = r.commentary || {};
        this.commentary = c.text || ''; this.commentarySaved = true; this.drill = null;
        this.lines = clone(c.lines || []); this.headline = c.headline || ''; this.othersSummary = c.others_summary || '';
        this.validation = c.validation || r.validation || null; this.lineVal = this.indexLineResults(this.validation);
        this.qThread = [];
        this.$nextTick(() => this.drawChart());
      },
      get clsStats() { const c = (this.result || {}).classification; return c && typeof c === 'object' && ('total' in c || 'row_coverage' in c) ? c : null; },
      get resultStats() { return this.clsStats || (this.result || {}).materiality_threshold != null; },
      covPct(v) { if (v == null || isNaN(v)) return '—'; const x = v <= 1 ? v * 100 : v; return x.toFixed(1) + '%'; },
      get joinAudit() { return ((this.result || {}).join_audit || (this.result || {}).unmatched_joins || []); },
      get unmatchedJoins() { return this.joinAudit.filter((j) => j.unmatched_rows || (j.unmatched_keys || []).length || j.fanout); },
      statLabel(k) { return String(k).replace(/_/g, ' '); },
      statVal(v) { if (typeof v === 'number') return Number.isInteger(v) ? v.toLocaleString() : (v <= 1 && v >= 0 ? (v * 100).toFixed(1) + '%' : this.full(v)); return this.fmtVal(v); },
      money(v) {
        if (v == null || isNaN(v)) return '—';
        const a = Math.abs(v); const sign = v < 0 ? '-' : '';
        if (a >= 1e9) return sign + (a / 1e9).toFixed(2) + 'B';
        if (a >= 1e6) return sign + (a / 1e6).toFixed(2) + 'M';
        if (a >= 1e3) return sign + (a / 1e3).toFixed(1) + 'K';
        return sign + a.toFixed(2);
      },
      full(v) { return v == null || isNaN(v) ? '—' : Number(v).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 }); },
      pct(v) { return v == null || isNaN(v) ? '—' : (v > 0 ? '+' : '') + Number(v).toFixed(1) + '%'; },
      viewCols(rows) { return rows && rows.length ? Object.keys(rows[0]) : []; },
      cell(v) { return typeof v === 'number' ? this.full(v) : v ?? ''; },
      drawChart() {
        const el = document.getElementById('waterfall');
        if (!el || !this.result || !window.Chart) return;
        if (this.chart) { this.chart.destroy(); this.chart = null; }
        const r = this.result; const ds = (r.drivers || []).slice(0, 12);
        const labels = ['Base', ...ds.map((d) => d.label), 'Current'];
        const bars = []; let run = r.base;
        bars.push([0, r.base]);
        ds.forEach((d) => { bars.push([run, run + d.delta]); run += d.delta; });
        bars.push([0, r.current]);
        const css = getComputedStyle(document.documentElement);
        const ink = css.getPropertyValue('--ink-3').trim(), grid = css.getPropertyValue('--line').trim();
        const red = css.getPropertyValue('--red').trim(), up = css.getPropertyValue('--ink-2').trim(), tot = css.getPropertyValue('--ink').trim();
        const colors = labels.map((_, i) => i === 0 || i === labels.length - 1 ? tot : ds[i - 1].delta >= 0 ? up : red);
        this.chart = new Chart(el, {
          type: 'bar',
          data: { labels, datasets: [{ data: bars, backgroundColor: colors, borderRadius: 3, borderSkipped: false, maxBarThickness: 46 }] },
          options: {
            responsive: true, maintainAspectRatio: false, animation: { duration: 500 },
            plugins: { legend: { display: false }, tooltip: { callbacks: { label: (c) => {
              const i = c.dataIndex; if (i === 0) return 'Base ' + this.full(r.base); if (i === labels.length - 1) return 'Current ' + this.full(r.current);
              return 'Movement ' + ds[i - 1].delta_fmt; } } } },
            scales: { x: { ticks: { color: ink, font: { size: 11 }, maxRotation: 40, autoSkip: false, callback: function (v) { const l = this.getLabelForValue(v); return l.length > 16 ? l.slice(0, 15) + '…' : l; } }, grid: { display: false } },
              y: { ticks: { color: ink, callback: (v) => this.money(v) }, grid: { color: grid } } },
            onClick: (_, els) => { if (els.length) { const i = els[0].index; if (i > 0 && i <= ds.length) this.openDrill(ds[i - 1]); } },
          },
        });
      },
      async openDrill(d) {
        this.drill = d; this.drillRows = null;
        try { this.drillRows = await this.api('GET', `/results/${this.result.id}/drill/${encodeURIComponent(d.driver_id)}`); }
        catch (e) { this.drillRows = []; this.toast(e.message, 'error'); }
        this.$nextTick(() => { const el = document.getElementById('drill-close'); el && el.focus(); });
      },
      esc(t) { return String(t ?? '').replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' })[c]); },
      esc(t) { return String(t ?? '').replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' })[c]); },
      get verifyTag() { return ((this.result && this.result.spec && this.result.spec.commentary) || (this.s.spec || {}).commentary || {}).verify_tag || '[TO VERIFY]'; },
      hl(text) { const tag = this.esc(this.verifyTag); return this.esc(text).split(tag).join('<mark class="verify">' + tag + '</mark>').replace(/\n/g, '<br>'); },
      commentaryHtml() { return this.hl(this.commentary); },
      get verifyCount() { return this.commentary.split(this.verifyTag).length - 1; },
      get commentaryEdited() { return !!this.result && this.commentary !== ((this.result.commentary || {}).text || ''); },
      indexLineResults(v) {
        const out = {}; ((v && v.line_results) || []).forEach((lr, i) => { out[lr.driver_id != null ? 'd:' + lr.driver_id : 'i:' + (lr.index ?? i)] = lr; });
        return out;
      },
      lineResult(l, i) { return this.lineVal['d:' + l.driver_id] || this.lineVal['i:' + i] || null; },
      lineOk(lr) { return lr && (lr.ok ?? lr.valid ?? !(lr.issues || []).length); },
      driverLabel(id) { const d = ((this.result || {}).drivers || []).find((x) => String(x.driver_id) === String(id)); return d ? d.label : id; },
      composeLines() { this.commentary = [this.headline, ...this.lines.map((l) => l.text), this.othersSummary].filter((x) => x && String(x).trim()).join('\n\n'); this.commentarySaved = false; },
      editLine(i, v) { this.lines[i].text = v; this.lines[i].edited = true; this.composeLines(); },
      async saveCommentary() {
        await this.run('Saving commentary', async () => {
          const body = { text: this.commentary }; if (this.lines.length) body.lines = this.lines.map((l) => ({ driver_id: l.driver_id, text: l.text }));
          const r = await this.api('POST', `/results/${this.result.id}/commentary`, body);
          if (r && r.commentary) this.result.commentary = r.commentary; else this.result.commentary = { ...(this.result.commentary || {}), text: this.commentary };
          const val = (r && (r.validation || (r.commentary || {}).validation)) || null;
          if (r && r.commentary && r.commentary.lines) this.lines = clone(r.commentary.lines);
          if (val) { r.validation = val; }
          if (r && r.validation) { this.validation = r.validation; this.lineVal = this.indexLineResults(r.validation); }
          this.commentarySaved = true; this.toast('Commentary saved and logged.');
        });
      },
      async regenerate(driverId) {
        this.regenBusy = driverId == null ? 'all' : String(driverId);
        try {
          const body = driverId == null ? {} : { driver_id: driverId };
          const { job_id } = await this.api('POST', `/results/${this.result.id}/narrative`, body);
          const job = await this.poll(job_id);
          const r = job.result || {}; const p = r.proposal || {}; const v = r.validation || null;
          if (driverId == null) {
            this.headline = p.headline || ''; this.othersSummary = p.others_summary || '';
            this.lines = (p.lines || []).map((l) => ({ driver_id: l.driver_id, text: l.text }));
            this.validation = v; this.lineVal = this.indexLineResults(v);
          } else {
            const nl = (p.lines || []).find((l) => String(l.driver_id) === String(driverId)) || (p.lines || [])[0];
            if (nl) { const i = this.lines.findIndex((l) => String(l.driver_id) === String(driverId)); if (i >= 0) this.lines[i] = { driver_id: driverId, text: nl.text }; else this.lines.push({ driver_id: driverId, text: nl.text }); }
            ((v && v.line_results) || []).forEach((lr) => { if (lr.driver_id != null) this.lineVal['d:' + lr.driver_id] = lr; });
            this.lineVal = { ...this.lineVal };
          }
          this.composeLines();
          this.toast(driverId == null ? 'New draft loaded into the editor. Review, then save.' : 'Line regenerated. Review, then save.');
        } catch (e) { this.toast(e.message, 'error'); }
        finally { this.regenBusy = ''; }
      },

      /* ---------- specs & project ---------- */
      async saveSpec() {
        if (!this.specName.trim()) { this.toast('Give the spec a name.', 'error'); return; }
        await this.run('Saving spec', async () => { this.hydrate(await this.api('POST', '/specs/save', { name: this.specName.trim() }), true); this.toast('Spec saved.'); this.specName = ''; });
      },
      async loadSpec(file) {
        await this.run('Loading spec', async () => {
          const st = await this.api('POST', '/specs/load', { file });
          this.hydrate(st); this.missing = st.missing_columns || []; this.specsOpen = false;
          if (this.missing.length) { this.toast('Some columns from this spec are missing. Remap them.', 'error'); this.go('columns'); }
          else { this.toast('Spec loaded. Review controls.'); this.go('review'); }
        });
      },
      async importSpec() {
        let spec; try { spec = JSON.parse(this.importText); } catch (e) { this.toast('Import is not valid JSON.', 'error'); return; }
        await this.run('Importing spec', async () => { this.hydrate(await this.api('POST', '/specs/import', { spec })); this.importText = ''; this.specsOpen = false; this.toast('Spec imported.'); });
      },
      readImportFile(f) { if (!f) return; const r = new FileReader(); r.onload = () => (this.importText = r.result); r.readAsText(f); },
      async newProject() {
        if (!confirm('Start a new project? This browser will switch to a blank project. Files from the current project stay on disk.')) return;
        await this.run('Starting fresh', async () => { this.hydrate(await this.api('POST', '/project/new', {})); this.pendingSuggestion = null; this.changeDialog = false; this.result = null; this.controls = []; this.controlsRan = false; this.lastChange = null; this.go('sources'); });
      },
      fmtSize(b) { if (!b) return '0 B'; const u = ['B', 'KB', 'MB', 'GB']; let i = 0; while (b >= 1024 && i < 3) { b /= 1024; i++; } return b.toFixed(i ? 1 : 0) + ' ' + u[i]; },
      fmtDate(d) { if (!d) return ''; const x = new Date(d); return isNaN(x) ? d : x.toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' }); },
    };
  };
})();

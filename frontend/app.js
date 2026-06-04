function app() {
  return {
    // ── Core state ─────────────────────────────────────────────────────────
    vehicle: {},
    scheduleStatus: [],
    loading: true,
    activeTab: 'dashboard',
    tabs: [
      { id: 'dashboard', label: 'Dashboard' },
      { id: 'catalog', label: 'Parts Catalog' },
      { id: 'plans', label: 'Service Plans' },
      { id: 'estimates', label: 'Estimates' },
    ],
    expandedItemId: null,

    // ── AI chat state ──────────────────────────────────────────────────────
    aiOk: null, // null=checking, true=ok, false=unavailable
    chatOpen: false,
    chatMessages: [], // [{role, content, thinking, tool_calls}]
    chatInput: '',
    chatLoading: false,
    chatShowThinking: false, // global toggle for all thinking blocks

    // ── Catalog state ──────────────────────────────────────────────────────
    catalogId: null,
    catalogGroups: [],
    catalogSelectedHg: null,
    catalogSubgroups: [],
    catalogSelectedSub: null,
    catalogParts: [],
    catalogDiagramUrl: null,
    catalogLoading: false,
    catalogError: null,
    catalogTargetPlanId: null, // which plan the "+ Plan" button adds to
    raDropdown: { open: false, list: [], oemPn: '', style: {} },

    // ── Toast ──────────────────────────────────────────────────────────────
    toast: { show: false, message: '', _timer: null },

    // ── Plans state ────────────────────────────────────────────────────────
    plansList: [],
    activePlan: null,
    plansLoading: false,
    newPlanName: '',
    emailModal: { open: false, text: '', planId: null },
    partModal: {
      open: false,
      part: null,
      diagramUrl: null,
      diagramLoading: false,
    },

    // ── History modal state ────────────────────────────────────────────────
    historyModal: {
      open: false,
      item_id: '',
      item_name: '',
      date: new Date().toISOString().slice(0, 10),
      odometer_km: null,
      performed_by: '',
      parts: [],
      notes: '',
    },

    // ── Init ───────────────────────────────────────────────────────────────
    async init() {
      try {
        await Promise.all([this.loadConfig(), this.loadScheduleStatus()]);
      } catch (e) {
        console.error('Init failed:', e);
      }
      this.loading = false;
      this.checkAiStatus();
    },

    async loadConfig() {
      const res = await fetch('/api/config');
      const data = await res.json();
      this.vehicle = data.vehicle;
    },

    async loadScheduleStatus() {
      const res = await fetch('/api/schedule/status');
      this.scheduleStatus = await res.json();
    },

    async onTabChange(tabId) {
      this.activeTab = tabId;
      if (tabId === 'catalog') {
        if (this.catalogGroups.length === 0) this.loadCatalogGroups();
        if (this.plansList.length === 0) this.loadPlans();
      }
      if (tabId === 'plans') this.loadPlans();
    },

    openRaDropdown(event, list, oemPn) {
      const rect = event.currentTarget.getBoundingClientRect();
      this.raDropdown = {
        open: true, list, oemPn,
        style: {
          position: 'fixed',
          top: (rect.bottom + 4) + 'px',
          right: (window.innerWidth - rect.right) + 'px',
        },
      };
      const close = (e) => {
        const dropdown = document.querySelector('[x-ref="raDropdownEl"]') || document.getElementById('ra-dropdown-overlay');
        if (dropdown && dropdown.contains(e.target)) return;
        this.raDropdown.open = false;
        window.removeEventListener('scroll', close, { capture: true });
      };
      window.addEventListener('scroll', close, { capture: true });
    },

    showToast(message) {
      if (this.toast._timer) clearTimeout(this.toast._timer);
      this.toast.message = message;
      this.toast.show = true;
      this.toast._timer = setTimeout(() => {
        this.toast.show = false;
      }, 2500);
    },

    // ── Odometer ───────────────────────────────────────────────────────────
    async saveOdometer(km) {
      if (!km || km < 0) return;
      const res = await fetch(`/api/vehicle/odometer?odometer_km=${km}`, {
        method: 'PATCH',
      });
      if (res.ok) {
        await this.loadConfig();
        await this.loadScheduleStatus();
      } else {
        console.error('Odometer save failed:', res.status, await res.text());
      }
    },

    // ── AI Status ──────────────────────────────────────────────────────────
    async checkAiStatus() {
      try {
        const res = await fetch('/api/ai/status');
        const data = await res.json();
        this.aiOk = data.ok;
      } catch {
        this.aiOk = false;
      }
    },

    // ── AI Chat ────────────────────────────────────────────────────────────
    async sendChat() {
      const msg = this.chatInput.trim();
      if (!msg || this.chatLoading) return;
      this.chatInput = '';
      this.chatMessages.push({ role: 'user', content: msg, ts: new Date().toLocaleTimeString([], {hour:'2-digit', minute:'2-digit'}) });
      this.chatLoading = true;

      // Build history for the API (exclude tool_calls field)
      const history = this.chatMessages.slice(0, -1).map((m) => ({
        role: m.role,
        content: m.content,
      }));

      try {
        const res = await fetch('/api/ai/chat', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ message: msg, history }),
        });
        const data = await res.json();
        this.chatMessages.push({
          role: 'assistant',
          content: data.reply,
          thinking: data.thinking || '',
          tool_calls: data.tool_calls || [],
          toolsOpen: {},
          ts: new Date().toLocaleTimeString([], {hour:'2-digit', minute:'2-digit'}),
        });
      } catch (e) {
        this.chatMessages.push({
          role: 'assistant',
          content: 'Error: could not reach the AI. Is Ollama running?',
          tool_calls: [],
        });
      }
      this.chatLoading = false;
      this.$nextTick(() => {
        const el = document.getElementById('chat-messages');
        if (el) el.scrollTop = el.scrollHeight;
      });
    },

    toggleToolCall(idx) {
      this.chatExpandedTools = {
        ...this.chatExpandedTools,
        [idx]: !this.chatExpandedTools[idx],
      };
    },

    clearChat() {
      this.chatMessages = [];
      this.chatExpandedTools = {};
    },

    // ── Catalog ────────────────────────────────────────────────────────────
    async loadCatalogGroups() {
      this.catalogLoading = true;
      this.catalogError = null;
      try {
        const res = await fetch('/api/catalog/groups');
        if (!res.ok) {
          const body = await res.json().catch(() => ({}));
          throw new Error(body.detail || `HTTP ${res.status}`);
        }
        const data = await res.json();
        this.catalogId = data.catalog_id;
        this.catalogGroups = data.groups;
      } catch (e) {
        this.catalogError = `Catalog error: ${e.message}`;
      }
      this.catalogLoading = false;
    },

    async selectGroup(mg) {
      if (this.catalogSelectedHg === mg) {
        this.catalogSelectedHg = null;
        this.catalogSubgroups = [];
        this.catalogSelectedSub = null;
        this.catalogParts = [];
        return;
      }
      this.catalogSelectedHg = mg;
      this.catalogSelectedSub = null;
      this.catalogParts = [];
      this.catalogLoading = true;
      try {
        const res = await fetch(
          `/api/catalog/subgroups?mg=${mg}&catalog_id=${this.catalogId}`,
        );
        const data = await res.json();
        this.catalogSubgroups = data.subgroups;
      } catch (e) {
        this.catalogError = `Could not load sub-groups: ${e.message}`;
      }
      this.catalogLoading = false;
    },

    async selectSubgroup(sub) {
      this.catalogSelectedSub = sub;
      this.catalogParts = [];
      this.catalogDiagramUrl = null;
      this.catalogLoading = true;
      try {
        const params = new URLSearchParams({
          diag_id: sub.diag_id,
          catalog_id: this.catalogId,
        });
        const res = await fetch(`/api/catalog/parts?${params}`);
        if (!res.ok) {
          const b = await res.json().catch(() => ({}));
          throw new Error(b.detail || `HTTP ${res.status}`);
        }
        const data = await res.json();
        this.catalogParts = data.parts;
        this.catalogDiagramUrl = data.diagram_url || null;
      } catch (e) {
        this.catalogError = `Could not load parts: ${e.message}`;
      }
      this.catalogLoading = false;
    },

    async addPartToPlan(part) {
      const planId = this.catalogTargetPlanId;
      if (!planId) {
        this.showToast('Select a plan from the dropdown first.');
        return;
      }
      const res = await fetch(`/api/plans/${planId}/parts`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          oem_pn: part.oem_pn,
          description: part.description,
          qty: part.qty_required,
          catalog_path: part.catalog_path || [],
          diagram_url: part.diagram_url || null,
          diagram_ref: part.diagram_ref || null,
        }),
      });
      if (res.ok) {
        const plan = this.plansList.find((p) => p.id === planId);
        this.showToast(
          `Added "${part.description}" to ${plan?.name ?? 'plan'}`,
        );
        // Keep activePlan in sync if it's the same plan
        if (this.activePlan?.id === planId) {
          this.activePlan = await res.json();
        }
      }
    },

    // ── Plans ──────────────────────────────────────────────────────────────
    async loadPlans() {
      this.plansLoading = true;
      try {
        const res = await fetch('/api/plans');
        this.plansList = await res.json();
        // Refresh active plan if one is selected
        if (this.activePlan) {
          const fresh = this.plansList.find((p) => p.id === this.activePlan.id);
          this.activePlan = fresh || null;
        }
      } catch (e) {
        console.error('Could not load plans:', e);
      }
      this.plansLoading = false;
    },

    async createPlan() {
      const name = this.newPlanName.trim();
      if (!name) return;
      const res = await fetch('/api/plans', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name }),
      });
      const plan = await res.json();
      this.newPlanName = '';
      this.plansList.unshift(plan);
      this.activePlan = plan;
      this.catalogTargetPlanId = plan.id;
    },

    async renamePlan(planId, name) {
      name = name.trim();
      if (!name) return;
      const res = await fetch(`/api/plans/${planId}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name }),
      });
      if (res.ok) {
        const updated = await res.json();
        const idx = this.plansList.findIndex((p) => p.id === planId);
        if (idx >= 0) this.plansList[idx] = updated;
        if (this.activePlan?.id === planId) this.activePlan = updated;
      }
    },

    async deletePlan(planId) {
      if (!confirm('Delete this plan?')) return;
      await fetch(`/api/plans/${planId}`, { method: 'DELETE' });
      this.plansList = this.plansList.filter((p) => p.id !== planId);
      if (this.activePlan?.id === planId) this.activePlan = null;
    },

    async updatePartQty(planId, oem_pn, qty) {
      qty = parseInt(qty);
      if (!qty || qty < 1) return;
      const res = await fetch(
        `/api/plans/${planId}/parts/${oem_pn}?qty=${qty}`,
        { method: 'PATCH' },
      );
      if (res.ok) {
        this.activePlan = await res.json();
      }
    },

    async openPartDetail(sp) {
      const part = sp.catalog_part;
      this.partModal = {
        open: true,
        part,
        diagramUrl: part.diagram_url || null,
        diagramLoading: false,
      };

      if (!this.partModal.diagramUrl) {
        this.partModal.diagramLoading = true;
        const diagId = part.catalog_path?.[0];
        try {
          const applyDiagData = (data) => {
            this.partModal.diagramUrl = data.diagram_url || null;
            // Find this part in the returned list to get its diagram_ref
            const match = (data.parts || []).find(
              (p) => p.oem_pn === part.oem_pn,
            );
            if (match?.diagram_ref)
              this.partModal.part = {
                ...this.partModal.part,
                diagram_ref: match.diagram_ref,
              };
          };

          if (diagId) {
            const params = new URLSearchParams({
              diag_id: diagId,
              catalog_id: this.catalogId || '',
            });
            const res = await fetch(`/api/catalog/parts?${params}`);
            if (res.ok) applyDiagData(await res.json());
          } else {
            // Fall back: hint search by description
            const res = await fetch(
              `/api/catalog/hint?hint=${encodeURIComponent(part.description)}`,
            );
            if (res.ok) {
              const data = await res.json();
              const match = data.matches?.[0];
              if (match?.diag_id) {
                const params = new URLSearchParams({
                  diag_id: match.diag_id,
                  catalog_id: data.catalog_id || '',
                });
                const res2 = await fetch(`/api/catalog/parts?${params}`);
                if (res2.ok) applyDiagData(await res2.json());
              }
            }
          }
        } catch {
          /* silent */
        }
        this.partModal.diagramLoading = false;
      }
    },

    viewPartInCatalog(part) {
      const diagId = part.catalog_path?.[0];
      if (!diagId) return;
      const mg = diagId.split('_')[0];
      this.partModal.open = false;
      this.onTabChange('catalog');
      // After catalog groups load, navigate to the right group/diagram
      const tryNav = async () => {
        if (this.catalogGroups.length === 0) {
          await new Promise((r) => setTimeout(r, 500));
        }
        await this.selectGroup(mg);
        const sub = this.catalogSubgroups.find((s) => s.diag_id === diagId);
        if (sub) await this.selectSubgroup(sub);
      };
      tryNav();
    },

    async deleteJob(planId, jobId) {
      const res = await fetch(`/api/plans/${planId}/jobs/${jobId}`, { method: 'DELETE' });
      if (res.ok) this.activePlan = await res.json();
    },

    async renameJob(planId, jobId, name) {
      if (!name.trim()) return;
      const res = await fetch(`/api/plans/${planId}/jobs/${jobId}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: name.trim() }),
      });
      if (res.ok) this.activePlan = await res.json();
    },

    async addJob(planId, name) {
      const res = await fetch(`/api/plans/${planId}/jobs`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name }),
      });
      if (res.ok) this.activePlan = await res.json();
    },

    async unassignPartFromJob(planId, jobId, oem_pn) {
      const res = await fetch(`/api/plans/${planId}/jobs/${jobId}/parts/${oem_pn}`, { method: 'DELETE' });
      if (res.ok) this.activePlan = await res.json();
    },

    async assignPartToJob(planId, oem_pn, jobId) {
      if (!jobId) return;
      const res = await fetch(`/api/plans/${planId}/assign`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ oem_pn, job_id: jobId }),
      });
      if (res.ok) this.activePlan = await res.json();
    },

    async removePartFromPlan(planId, oem_pn) {
      const res = await fetch(`/api/plans/${planId}/parts/${oem_pn}`, {
        method: 'DELETE',
      });
      this.activePlan = await res.json();
    },

    async generateEmail(planId, jobIds = null) {
      const res = await fetch('/api/email/generate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ plan_id: planId, job_ids: jobIds }),
      });
      const data = await res.json();
      this.emailModal = { open: true, text: data.email, planId };
    },

    copyEmail() {
      navigator.clipboard.writeText(this.emailModal.text).then(() => {
        alert('Email copied to clipboard.');
      });
    },

    // ── History modal ──────────────────────────────────────────────────────
    openHistoryForm(item) {
      this.historyModal = {
        open: true,
        item_id: item.id,
        item_name: item.name,
        date: new Date().toISOString().slice(0, 10),
        odometer_km: this.vehicle.odometer_km ?? null,
        performed_by: '',
        parts: [],
        notes: '',
      };
    },

    async submitHistory() {
      const m = this.historyModal;
      if (!m.odometer_km) return;
      const res = await fetch('/api/history', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          item_id: m.item_id,
          date: m.date,
          odometer_km: m.odometer_km,
          performed_by: m.performed_by || null,
          parts: m.parts.filter((p) => p.trim()),
          notes: m.notes || null,
        }),
      });
      if (res.ok) {
        this.historyModal.open = false;
        await this.loadScheduleStatus();
      } else {
        alert('Failed to save record. Check the console.');
        console.error(await res.text());
      }
    },

    // ── Dashboard helpers ──────────────────────────────────────────────────
    toggleExpand(id) {
      this.expandedItemId = this.expandedItemId === id ? null : id;
    },

    countStatus(status) {
      return this.scheduleStatus.filter((s) => s.status === status).length;
    },

    rowBg(s) {
      return {
        'bg-red-950/25': s.status === 'overdue',
        'bg-yellow-950/20': s.status === 'due_soon',
        'bg-gray-900/40': s.status === 'ok',
        'bg-gray-900/20': s.status === 'unknown',
      };
    },

    badgeCls(s) {
      return {
        'bg-red-500/20 text-red-400 ring-1 ring-red-500/30':
          s.status === 'overdue',
        'bg-yellow-500/20 text-yellow-400 ring-1 ring-yellow-500/30':
          s.status === 'due_soon',
        'bg-green-500/20 text-green-400 ring-1 ring-green-500/30':
          s.status === 'ok',
        'bg-gray-700 text-gray-400': s.status === 'unknown',
      };
    },

    statusLabel(s) {
      return (
        {
          overdue: 'Overdue',
          due_soon: 'Due Soon',
          ok: 'OK',
          unknown: 'Unknown',
        }[s.status] ?? s.status
      );
    },

    intervalDesc(s) {
      const it = s.item;
      const parts = [];
      if (it.interval_inspect_km && it.interval_replace_km) {
        parts.push(
          `Inspect every ${it.interval_inspect_km.toLocaleString()} km / Replace every ${it.interval_replace_km.toLocaleString()} km`,
        );
      } else if (it.interval_replace_km) {
        parts.push(
          `Replace every ${it.interval_replace_km.toLocaleString()} km`,
        );
      } else if (it.interval_inspect_km) {
        parts.push(
          `Inspect every ${it.interval_inspect_km.toLocaleString()} km`,
        );
      }
      if (it.interval_replace_months)
        parts.push(`or ${it.interval_replace_months} months`);
      else if (it.interval_inspect_months)
        parts.push(`or ${it.interval_inspect_months} months`);
      const recs = [];
      if (it.bmw_recommendation_km)
        recs.push(`${it.bmw_recommendation_km.toLocaleString()} km`);
      if (it.bmw_recommendation_months)
        recs.push(`${it.bmw_recommendation_months} months`);
      if (recs.length) parts.push(`(BMW: ${recs.join(' / ')})`);
      return parts.join(' ');
    },
  };
}

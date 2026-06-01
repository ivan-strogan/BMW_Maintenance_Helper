function app() {
  return {
    vehicle: {},
    scheduleStatus: [],
    loading: true,
    activeTab: 'dashboard',
    tabs: [
      { id: 'dashboard', label: 'Dashboard'  },
      { id: 'catalog',   label: 'Catalog'    },
      { id: 'plans',     label: 'Plans'      },
      { id: 'estimates', label: 'Estimates'  },
    ],

    expandedItemId: null,

    toggleExpand(id) {
      this.expandedItemId = this.expandedItemId === id ? null : id;
    },

    // Record-service modal state
    historyModal: {
      open:         false,
      item_id:      '',
      item_name:    '',
      date:         new Date().toISOString().slice(0, 10),
      odometer_km:  null,
      performed_by: '',
      parts:        [],
      notes:        '',
    },

    async init() {
      try {
        await Promise.all([this.loadConfig(), this.loadScheduleStatus()]);
      } catch (e) {
        console.error('Init failed:', e);
      }
      this.loading = false;
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

    // ── Odometer update ────────────────────────────────────────────────────
    async saveOdometer(km) {
      if (!km || km < 0) return;
      const res = await fetch(`/api/vehicle/odometer?odometer_km=${km}`, { method: 'PATCH' });
      if (res.ok) {
        await this.loadConfig();          // re-read from server to confirm write
        await this.loadScheduleStatus();  // recompute status with new odometer
      } else {
        console.error('Odometer save failed:', res.status, await res.text());
      }
    },

    // ── History modal ──────────────────────────────────────────────────────
    openHistoryForm(item) {
      this.historyModal = {
        open:         true,
        item_id:      item.id,
        item_name:    item.name,
        date:         new Date().toISOString().slice(0, 10),
        odometer_km:  this.vehicle.odometer_km ?? null,
        performed_by: '',
        parts:        [],
        notes:        '',
      };
    },

    async submitHistory() {
      const m = this.historyModal;
      if (!m.odometer_km) return;

      const payload = {
        item_id:      m.item_id,
        date:         m.date,
        odometer_km:  m.odometer_km,
        performed_by: m.performed_by || null,
        parts:        m.parts.filter(p => p.trim()),
        notes:        m.notes || null,
      };

      const res = await fetch('/api/history', {
        method:  'POST',
        headers: { 'Content-Type': 'application/json' },
        body:    JSON.stringify(payload),
      });

      if (res.ok) {
        this.historyModal.open = false;
        await this.loadScheduleStatus();
      } else {
        alert('Failed to save record. Check the console.');
        console.error(await res.text());
      }
    },

    // ── Table helpers ──────────────────────────────────────────────────────
    countStatus(status) {
      return this.scheduleStatus.filter(s => s.status === status).length;
    },

    rowBg(s) {
      return {
        'bg-red-950/25':    s.status === 'overdue',
        'bg-yellow-950/20': s.status === 'due_soon',
        'bg-gray-900/40':   s.status === 'ok',
        'bg-gray-900/20':   s.status === 'unknown',
      };
    },

    badgeCls(s) {
      return {
        'bg-red-500/20 text-red-400 ring-1 ring-red-500/30':         s.status === 'overdue',
        'bg-yellow-500/20 text-yellow-400 ring-1 ring-yellow-500/30': s.status === 'due_soon',
        'bg-green-500/20 text-green-400 ring-1 ring-green-500/30':    s.status === 'ok',
        'bg-gray-700 text-gray-400':                                   s.status === 'unknown',
      };
    },

    statusLabel(s) {
      return { overdue: 'Overdue', due_soon: 'Due Soon', ok: 'OK', unknown: 'Unknown' }[s.status] ?? s.status;
    },

    intervalDesc(s) {
      const it = s.item;
      const parts = [];

      // km intervals
      if (it.interval_inspect_km && it.interval_replace_km) {
        parts.push(`Inspect every ${it.interval_inspect_km.toLocaleString()} km / Replace every ${it.interval_replace_km.toLocaleString()} km`);
      } else if (it.interval_replace_km) {
        parts.push(`Replace every ${it.interval_replace_km.toLocaleString()} km`);
      } else if (it.interval_inspect_km) {
        parts.push(`Inspect every ${it.interval_inspect_km.toLocaleString()} km`);
      }

      // time intervals
      if (it.interval_replace_months) {
        parts.push(`or ${it.interval_replace_months} months`);
      } else if (it.interval_inspect_months) {
        parts.push(`or ${it.interval_inspect_months} months`);
      }

      // BMW recommendation
      const recs = [];
      if (it.bmw_recommendation_km) recs.push(`${it.bmw_recommendation_km.toLocaleString()} km`);
      if (it.bmw_recommendation_months) recs.push(`${it.bmw_recommendation_months} months`);
      if (recs.length) parts.push(`(BMW: ${recs.join(' / ')})`);

      return parts.join(' ');
    },
  };
}

function app() {
  return {
    vehicle: {},
    scheduleStatus: [],
    loading: true,
    activeTab: 'dashboard',
    tabs: [
      { id: 'dashboard', label: 'Dashboard' },
      { id: 'catalog',   label: 'Catalog'   },
      { id: 'plans',     label: 'Plans'     },
      { id: 'estimates', label: 'Estimates' },
    ],

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
        'bg-red-500/20 text-red-400 ring-1 ring-red-500/30':       s.status === 'overdue',
        'bg-yellow-500/20 text-yellow-400 ring-1 ring-yellow-500/30': s.status === 'due_soon',
        'bg-green-500/20 text-green-400 ring-1 ring-green-500/30':  s.status === 'ok',
        'bg-gray-700 text-gray-400':                                 s.status === 'unknown',
      };
    },

    statusLabel(s) {
      return { overdue: 'Overdue', due_soon: 'Due Soon', ok: 'OK', unknown: 'Unknown' }[s.status] ?? s.status;
    },

    addToPlan(s) {
      // Phase 5: open plan builder with this item pre-selected
      alert(`"${s.item.name}" will be added to a service plan in Phase 5.`);
    },
  };
}

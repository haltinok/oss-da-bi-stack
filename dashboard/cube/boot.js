// Runs before app.js. app.js asks window.dashboardData for /api/* the moment it loads,
// but sign-in and the Cube client are asynchronous (cube-source.mjs), so answer lazily.
window.dashboardData = {
  noProfit: false,
  ready: new Promise((resolve) => { window.__dashboardDataReady = resolve; }),
  async get(url, signal, onPartial) {
    return (await this.ready).get(url, signal, onPartial);
  },
};

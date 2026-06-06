const { defineConfig } = require('@playwright/test');

module.exports = defineConfig({
  use: {
    baseURL: 'http://localhost:8000',
    headless: true,
    viewport: { width: 1400, height: 900 },
  },
  timeout: 60000,
});

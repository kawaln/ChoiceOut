// @ts-check
const { defineConfig } = require("@playwright/test");

module.exports = defineConfig({
  testDir: "./tests",
  timeout: 15_000,
  fullyParallel: true,
  reporter: [["html", { open: "never" }], ["list"]],

  use: {
    baseURL: "http://127.0.0.1:8000",
    screenshot: "only-on-failure",
  },

  // Starts your actual Python server before the tests run, and stops it
  // afterward. If you already have `python3 pop.py` running yourself,
  // Playwright just reuses it instead of double-starting.
  webServer: {
    command: "python3 pop.py",
    url: "http://127.0.0.1:8000",
    reuseExistingServer: true,
    timeout: 10_000,
  },
});

import { defineConfig } from "@playwright/test";
const baseURL = process.env.BIO_WEB_BASE_URL || "http://127.0.0.1:5173";
if (!["127.0.0.1", "localhost"].includes(new URL(baseURL).hostname))
  throw new Error("Browser fixtures run locally only");
export default defineConfig({
  testDir: "./tests",
  outputDir: "./test-results",
  workers: 1,
  timeout: 30000,
  use: {
    baseURL,
    headless: true,
    launchOptions: process.env.BIO_BROWSER_PATH
      ? { executablePath: process.env.BIO_BROWSER_PATH }
      : {},
  },
  reporter: "list",
});

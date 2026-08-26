import { defineConfig } from "@playwright/test";

/**
 * E2E smoke against a production build without Supabase configured.
 * Full authenticated E2E requires a Supabase project (see supabase/README.md)
 * and E2E_SUPABASE_* env vars — those specs are skipped when absent.
 */
export default defineConfig({
  testDir: "./e2e",
  timeout: 30_000,
  retries: 1,
  use: {
    baseURL: "http://localhost:3179",
  },
  webServer: {
    command: "npm run build && npx next start -p 3179",
    url: "http://localhost:3179/login",
    reuseExistingServer: false,
    timeout: 180_000,
  },
});

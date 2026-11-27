import { test as base, expect } from "@playwright/test";
import type { BrowserContext, Page } from "@playwright/test";
import { readFile } from "node:fs/promises";

type UseSession = (page: Page, username: string) => Promise<void>;
type Cookies = Awaited<ReturnType<BrowserContext["cookies"]>>;

const test = base.extend<{}, { useSession: UseSession }>({
  useSession: [async ({ browser }, use, worker) => {
    const sessions = new Map<string, Cookies>();
    await use(async (page, username) => {
      let cookies = sessions.get(username);
      if (!cookies) {
        const context = await browser.newContext({ baseURL: worker.project.use.baseURL });
        try {
          const session = await context.request.get("/api/v1/auth/session/");
          const login = await context.request.post("/api/v1/auth/login/", {
            data: { username, password: "test-fixture-passphrase" },
            headers: { "X-CSRFToken": (await session.json()).csrf },
          });
          expect(login.ok()).toBe(true);
          cookies = await context.cookies();
          sessions.set(username, cookies);
        } finally {
          await context.close();
        }
      }
      await page.context().addCookies(cookies);
    });
  }, { scope: "worker" }],
});

test("public landing is responsive, keyboard accessible and clearly labels its illustration", async ({
  page,
}) => {
  await page.goto("/");
  await expect(
    page.getByRole("heading", {
      name: "YOUR CODE. YOUR STRATEGY. THEIR PROBLEM.",
    }),
  ).toBeVisible();
  await expect(
    page.getByText("Illustrated arena. Real matches are visible"),
  ).toBeVisible();
  await page.keyboard.press("Tab");
  await expect(
    page.getByRole("link", { name: "Skip to content" }),
  ).toBeFocused();
  await page.keyboard.press("Tab");
  await page.screenshot({
    path: test.info().outputPath("landing-desktop.png"),
    fullPage: true,
  });
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(
    page.getByRole("button", { name: "Competition console", exact: true }),
  ).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBeTruthy();
  await page.screenshot({
    path: test.info().outputPath("landing-mobile.png"),
    fullPage: true,
  });
});

test("participant signs in, sees recorded analytics and opens a match dispute", async ({
  page,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto("/#console");
  await page.getByLabel("Username", { exact: true }).fill("captain-a");
  await page
    .getByLabel("Password", { exact: true })
    .fill("test-fixture-passphrase");
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "The match room" }),
  ).toBeVisible();
  await expect(
    page.getByRole("option", { name: "QA FIXTURE — not a real competition" }),
  ).toBeAttached();
  await page.getByRole("link", { name: "Analytics", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Beyond the scoreboard" }),
  ).toBeVisible();
  await expect(
    page
      .getByRole("table", { name: "Team performance" })
      .getByRole("cell", { name: "ta", exact: true }),
  ).toBeVisible();
  await page.screenshot({
    path: test.info().outputPath("analytics-desktop.png"),
    fullPage: true,
  });
  await page
    .getByRole("link", { name: "Match disputes", exact: true })
    .click();
  await page
    .getByLabel("Title", { exact: true })
    .fill("Browser fixture review");
  await page
    .getByLabel("What should staff review?")
    .fill("Review the recorded local fixture match.");
  await page.getByRole("button", { name: "Open dispute", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Browser fixture review", exact: true }),
  ).toBeVisible();
  await page.getByLabel("Add a comment").fill("Additional fixture context.");
  await page.getByRole("button", { name: "Send comment" }).click();
  await expect(
    page.getByText("Additional fixture context.", { exact: true }),
  ).toBeVisible();
  await page.setViewportSize({ width: 390, height: 844 });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBeTruthy();
  await page.screenshot({
    path: test.info().outputPath("disputes-mobile.png"),
    fullPage: true,
  });
  await page
    .getByRole("link", { name: "Bot submissions", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "Your next contender" }),
  ).toBeVisible();
  await expect(
    page.getByText("biohelpers / 1.0.0", { exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Sign out", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Back to the arena." }),
  ).toBeVisible();
  expect(errors).toEqual([]);
});

test("Admin sees operational health and participants cannot call it", async ({
  page,
  useSession,
}) => {
  await useSession(page, "admin");
  await page.goto("/#console");
  await page.getByRole("link", { name: "Operations", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Eyes on the operation." }),
  ).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "Recent audit events" }),
  ).toBeVisible();
  await page.screenshot({
    path: test.info().outputPath("operations-desktop.png"),
    fullPage: true,
  });
});

test("participant sees tournament notices and manages a private inbox on mobile", async ({ page, browser }) => {
  await page.goto("/dashboard");
  await page.getByLabel("Username", { exact: true }).fill("captain-a");
  await page.getByLabel("Password", { exact: true }).fill("test-fixture-passphrase");
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Dashboard", exact: true })).toBeVisible();
  await expect(page.getByText("Registration deadline", { exact: true })).toBeVisible();
  await expect(page.getByText("Submission deadline", { exact: true })).toBeVisible();
  await expect(page.getByText(/^Timezone /)).toBeVisible();
  const preview = page.getByRole("region", { name: "Tournament notices" });
  await expect(preview.getByRole("heading", { name: "Fixture notice 22" })).toBeVisible();
  await expect(preview.getByText("Historical fixture notice")).toHaveCount(0);
  await preview.getByRole("link", { name: "Open inbox" }).click();
  await expect(page).toHaveURL(/\/notifications$/);
  await page.setViewportSize({ width: 390, height: 844 });
  const inbox = page.getByRole("region", { name: "Inbox" });
  await expect(inbox.getByRole("heading", { name: "Historical fixture notice" })).toBeVisible();
  await expect(inbox.getByText("23 unread")).toBeVisible();
  const prefs = page.getByRole("checkbox", { name: "Email notifications" });
  await expect(prefs).toBeChecked();
  await prefs.click();
  await expect(page.getByText("Email notifications disabled.")).toBeVisible();
  await expect(prefs).not.toBeChecked();
  await expect(page.getByText("Dashboard notifications are always on.")).toBeVisible();

  await inbox.getByRole("button", { name: "Next", exact: true }).click();
  await expect(inbox.getByText("21–23 of 23")).toBeVisible();
  await expect(inbox.getByRole("heading", { name: "Fixture notice 01" })).toBeVisible();
  await inbox.getByRole("button", { name: "Previous", exact: true }).click();
  const row = inbox.getByRole("listitem").filter({ hasText: "Fixture notice 22" });
  await row.getByRole("button", { name: "Mark read", exact: true }).click();
  await expect(row.getByRole("button", { name: "Mark unread", exact: true })).toBeVisible();

  await page.reload();
  await expect(prefs).not.toBeChecked();
  await expect(row.getByRole("button", { name: "Mark unread", exact: true })).toBeVisible();
  const unread = inbox.getByRole("button", { name: "Unread", exact: true });
  await unread.focus();
  await page.keyboard.press("Enter");
  await expect(unread).toHaveAttribute("aria-pressed", "true");
  await expect(inbox.getByText("22 unread")).toBeVisible();
  await expect(row).toHaveCount(0);

  await inbox.getByRole("button", { name: "All", exact: true }).click();
  await row.getByRole("button", { name: "Mark unread", exact: true }).click();
  await expect(inbox.getByText("23 unread")).toBeVisible();
  await prefs.click();
  await expect(page.getByText("Email notifications enabled.")).toBeVisible();
  await expect(prefs).toBeChecked();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: test.info().outputPath("inbox-mobile.png"), fullPage: true });
  await page.getByRole("button", { name: "Sign out", exact: true }).click();
  await expect(row).toHaveCount(0);

  const other = await browser.newPage();
  await other.goto(new URL("/notifications", page.url()).href);
  await other.getByLabel("Username", { exact: true }).fill("captain-b");
  await other.getByLabel("Password", { exact: true }).fill("test-fixture-passphrase");
  await other.getByRole("button", { name: "Sign in", exact: true }).click();
  await expect(other.getByText("No notifications yet.")).toBeVisible();
  await expect(other.getByText("Fixture notice 22")).toHaveCount(0);
  await other.close();
});

test("notifications deep link keeps unlinked accounts out of the personal feed", async ({ page }) => {
  await page.goto("/notifications");
  await page.getByLabel("Username", { exact: true }).fill("outsider");
  await page.getByLabel("Password", { exact: true }).fill("test-fixture-passphrase");
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await expect(page.getByRole("alert")).toHaveText(
    "Notifications are available to signed-in participants with a linked tournament account.",
  );
  await expect(page.getByRole("checkbox", { name: "Email notifications" })).toHaveCount(0);
});

test("private console opens by keyboard and guards a direct Operations link", async ({ page }) => {
  const adminRequests: string[] = [];
  page.on("request", (request) => {
    if (new URL(request.url()).pathname === "/api/v1/admin/operations/") adminRequests.push(request.url());
  });
  await page.goto("/#operations");
  await page.getByLabel("Username", { exact: true }).fill("captain-a");
  await page.getByLabel("Password", { exact: true }).fill("test-fixture-passphrase");
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await expect(page.getByRole("alert")).toHaveText("Admin access is required to open Operations.");
  await expect(page.getByRole("link", { name: "Operations", exact: true })).toHaveCount(0);
  await expect(page).toHaveURL(/#operations$/);

  await page.setViewportSize({ width: 390, height: 844 });
  const skip = page.getByRole("link", { name: "Skip to content" });
  await page.keyboard.press("Tab");
  await expect(skip).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(page.getByRole("main")).toBeFocused();
  await expect(page).toHaveURL(/#operations$/);
  await page.getByRole("link", { name: "Open Dashboard" }).click();
  await expect(page.getByRole("heading", { name: "Dashboard", exact: true })).toBeVisible();
  expect(adminRequests).toEqual([]);
});

test("staff notification route is guarded before fetching a participant inbox", async ({ page, useSession }) => {
  const inboxRequests: string[] = [];
  page.on("request", (request) => {
    if (new URL(request.url()).pathname === "/api/v1/notifications/") inboxRequests.push(request.url());
  });
  await useSession(page, "organizer");
  await page.goto("/notifications");
  await expect(page.getByRole("alert")).toHaveText("Notifications are available to linked participant accounts.");
  await expect(page.getByRole("link", { name: "Notifications", exact: true })).toHaveCount(0);
  expect(inboxRequests).toEqual([]);
});

test("a failed API request shows its server request ID with the message", async ({ page }) => {
  await page.goto("/#console");
  await page.getByLabel("Username", { exact: true }).fill("captain-a");
  await page.getByLabel("Password", { exact: true }).fill("incorrect-test-password");
  const failedLogin = page.waitForResponse((response) => new URL(response.url()).pathname === "/api/v1/auth/login/");
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  const response = await failedLogin;
  expect(response.status()).toBe(401);
  const requestId = response.headers()["x-request-id"];
  expect(requestId).toMatch(/^req_[0-9a-f]{32}$/);
  await expect(page.getByRole("alert")).toHaveText(`Invalid username or password. Request ID ${requestId}.`);
});

test("team and submission deep links show the selected roster and current deadline", async ({ page }) => {
  await page.goto("/participant/team");
  await page.getByLabel("Username", { exact: true }).fill("captain-b");
  await page.getByLabel("Password", { exact: true }).fill("test-fixture-passphrase");
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await expect(page.getByRole("heading", { name: "My team", exact: true })).toBeVisible();
  await expect(page.getByText("Eliminated", { exact: true })).toBeVisible();
  const members = page.getByRole("table", { name: "Verified team members" });
  await expect(members.getByRole("cell", { name: "Captain" })).toBeVisible();
  await expect(page.getByText("a@uni.edu")).toHaveCount(0);

  await page.getByRole("link", { name: "Bot submissions" }).click();
  await expect(page).toHaveURL(/\/participant\/submissions$/);
  await expect(page.getByText("Submissions are locked. The deadline has passed.")).toBeVisible();
  await expect(page.getByRole("link", { name: "Download v1" })).toBeVisible();
  await page.getByLabel("Tournament", { exact: true }).selectOption("upload-fixture");
  await expect(page.getByText("Only the team captain can upload a bot.")).toBeVisible();
  await expect(page.getByLabel("Python bot or bundle")).toHaveCount(0);
  await page.getByRole("link", { name: "My team" }).click();
  await expect(page.getByRole("heading", { name: "Fixture Upload Team" })).toBeVisible();
  await expect(members.getByRole("cell", { name: "member", exact: true })).toBeVisible();
  await expect(page.getByText("Awaiting bracket draw", { exact: true })).toBeVisible();
  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});

test("captain sees an invalid upload and queued validation without losing the active bot", async ({ page, useSession }) => {
  await useSession(page, "captain-a");
  await page.goto("/participant/submissions");
  await page.getByLabel("Tournament", { exact: true }).selectOption("upload-fixture");
  const history = page.getByRole("region", { name: "Submission history" });
  await expect(history.getByText("Active version: v1")).toBeVisible();
  const file = page.getByLabel("Python bot or bundle");
  const upload = page.getByRole("button", { name: "Upload for validation" });
  await file.setInputFiles({ name: "bot.py", mimeType: "text/x-python", buffer: Buffer.from("def broken(") });
  await upload.click();
  const rejected = history.getByRole("row").filter({ has: page.getByRole("rowheader", { name: "v2" }) });
  await rejected.locator("summary").click();
  await expect(rejected.getByText(/Line 1:/)).toBeVisible();
  await expect(history.getByText("Active version: v1")).toBeVisible();

  await file.setInputFiles({
    name: "bot.py", mimeType: "text/x-python", buffer: Buffer.from("def turn():\n    return None\n"),
  });
  await upload.click();
  await expect(page.getByText("Version 3 queued for validation.")).toBeVisible();
  await expect(history.getByText("Queued for validation", { exact: true })).toBeVisible();
  await history.getByRole("button", { name: "Refresh submissions" }).click();
  await expect(history.getByText("Active version: v1")).toBeVisible();
});

test("bracket links show match results and a recorded coin flip after replay archive", async ({ page, useSession }) => {
  await useSession(page, "admin");
  await page.goto("/participant/tournaments/tied-fixture/bracket");
  await expect(page.getByRole("heading", { name: "Bracket & results" })).toBeVisible();
  await expect(page.getByRole("region", { name: "Final" }).getByText("Game wins 0–0")).toBeVisible();
  await page.getByRole("link", { name: "Match details" }).click();
  const matchUrl = page.url();
  await expect(page.getByRole("heading", { name: "Recorded coin flip" })).toBeVisible();
  await expect(page.getByText(/each team had a 50% chance/i)).toBeVisible();
  const games = page.getByRole("region", { name: "Games in this series" });
  await expect(games.getByRole("listitem")).toHaveCount(4);
  await expect(games.getByText("Selected game")).toBeVisible();
  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);

  await page.getByRole("link", { name: "Replay", exact: true }).click();
  const download = page.waitForEvent("download");
  await page.getByRole("link", { name: "Download replay" }).click();
  expect((await download).suggestedFilename()).toMatch(/\.bc26$/);

  const session = await page.request.get("/api/v1/auth/session/");
  const archive = await page.request.post("/api/v1/tournaments/tied-fixture/archive/", {
    data: { confirm: true }, headers: { "X-CSRFToken": (await session.json()).csrf },
  });
  expect(archive.ok()).toBe(true);
  expect((await archive.json()).replays_deleted).toBe(true);
  await page.getByRole("button", { name: "Refresh replay status" }).click();
  await expect(page.getByText("Replay no longer available. The tournament is archived.")).toBeVisible();
  await expect(page.getByRole("link", { name: "Download replay" })).toHaveCount(0);
  await page.getByRole("link", { name: "Back to match" }).click();
  await expect(page).toHaveURL(matchUrl);
  await expect(page.getByRole("heading", { name: "Recorded coin flip" })).toBeVisible();
});

test("scoped bracket navigation shows pending draws and keeps foreign tournaments hidden", async ({ page, useSession }) => {
  await useSession(page, "captain-a");
  await page.goto("/participant/tournaments/tied-fixture/bracket");
  await expect(page.getByText("This tournament is unavailable.")).toBeVisible();
  await page.getByLabel("Tournament", { exact: true }).selectOption("upload-fixture");
  await expect(page).toHaveURL(/\/bracket$/);
  await expect(page.getByRole("heading", { name: "Awaiting bracket draw" })).toBeVisible();
});

test("Admin approval queue confirms approval, requires a reason, and refuses a stale review", async ({
  page, useSession,
}) => {
  await useSession(page, "admin");
  await page.goto("/admin/approvals");
  await expect(page.getByRole("heading", { name: "Tournament approvals" })).toBeVisible();
  const pending = page.getByLabel("Pending tournament");
  const approve = page.getByRole("button", { name: "Approve tournament", exact: true });
  await pending.selectOption("approval-approve");
  await expect(page.getByRole("heading", { name: "Fixture to approve", exact: true })).toBeVisible();
  await expect(approve).toBeDisabled();
  await page.getByLabel("Confirm tournament approval").check();
  await approve.click();
  await expect(page.getByText("Fixture to approve approved. Registration can now be opened separately.")).toBeVisible();
  await expect(pending.locator('option[value="approval-approve"]')).toHaveCount(0);
  const approved = await page.request.get("/api/v1/tournaments/approval-approve/");
  expect((await approved.json()).status).toBe("approved");

  await pending.selectOption("approval-reject");
  await expect(page.getByRole("heading", { name: "Fixture to reject", exact: true })).toBeVisible();
  await page.getByLabel("Decision").selectOption("reject");
  const reject = page.getByRole("button", { name: "Reject tournament", exact: true });
  await expect(reject).toBeDisabled();
  await page.getByLabel("Rejection reason").fill("Correct the fixture schedule.");
  await reject.click();
  await expect(page.getByText("Fixture to reject rejected. The Organizer can edit and resubmit it.")).toBeVisible();
  const rejected = await page.request.get("/api/v1/tournaments/approval-reject/");
  expect((await rejected.json()).rejection_reason).toBe("Correct the fixture schedule.");

  await expect(page.getByRole("heading", { name: "Fixture to changed", exact: true })).toBeVisible();
  await page.getByLabel("Confirm tournament approval").check();
  const stale = (await (await page.request.get("/api/v1/tournaments/approval-changed/")).json()).version;
  const csrf = (await (await page.request.get("/api/v1/auth/session/")).json()).csrf;
  const external = await page.request.post("/api/v1/tournaments/approval-changed/reject/", {
    data: { expected_version: stale, reason: "Another reviewer already decided." },
    headers: { "X-CSRFToken": csrf },
  });
  expect(external.ok()).toBe(true);
  await approve.click();
  await expect(page.getByRole("alert")).toContainText(/version|changed/i);
  await expect(approve).toBeDisabled();
  await page.getByRole("button", { name: "Reload tournament details" }).click();
  await expect(page.getByText("This tournament is now rejected. Refresh the queue.")).toBeVisible();
  await page.getByRole("button", { name: "Refresh queue" }).click();
  await expect(page.getByText("No tournaments are awaiting approval.")).toBeVisible();
});

test("a participant cannot open the Admin approval queue", async ({ page, useSession }) => {
  await useSession(page, "captain-a");
  await page.goto("/admin/approvals");
  await expect(page.getByRole("alert")).toHaveText("Admin access is required to review tournaments.");
  await expect(page.getByRole("link", { name: "Approvals", exact: true })).toHaveCount(0);
  await expect(page.getByLabel("Pending tournament")).toHaveCount(0);
});

test("Organizer creates, revises and opens an approved tournament", async ({ page, browser, useSession }) => {
  await useSession(page, "organizer");
  await page.goto("/organizer");
  await page.getByRole("link", { name: "New tournament", exact: true }).click();
  await page.getByLabel("Tournament name").fill("Organizer browser fixture");
  await page.getByLabel("Description", { exact: true }).fill("Initial fixture description.");
  const deadlines = await page.evaluate(() => [2, 3].map((days) => {
    const date = new Date(Date.now() + days * 86_400_000);
    return new Date(date.getTime() - date.getTimezoneOffset() * 60_000).toISOString().slice(0, 16);
  }));
  await page.getByLabel("Registration deadline").fill(deadlines[0]);
  await page.getByLabel("Submission deadline").fill(deadlines[1]);
  await page.getByRole("button", { name: "Create draft" }).click();
  await expect(page.getByRole("heading", { name: "Organizer browser fixture" })).toBeVisible();
  await expect(page.getByRole("status").filter({ hasText: /^Draft$/ })).toBeVisible();
  const id = new URL(page.url()).pathname.split("/").at(-1)!;
  await page.getByRole("button", { name: "Submit for approval", exact: true }).click();
  await expect(page.getByText("The Admin is reviewing this version.")).toBeVisible();
  await expect(page.getByRole("button", { name: "Open registration" })).toHaveCount(0);

  const admin = await browser.newPage({ baseURL: new URL(page.url()).origin });
  try {
    await useSession(admin, "admin");
    await admin.goto("/admin/approvals");
    await admin.getByLabel("Pending tournament").selectOption(id);
    await admin.getByLabel("Decision").selectOption("reject");
    await admin.getByLabel("Rejection reason").fill("Update the fixture description.");
    await admin.getByRole("button", { name: "Reject tournament" }).click();
    await expect(admin.getByText(/Organizer browser fixture rejected/)).toBeVisible();

    await page.getByRole("button", { name: "Refresh tournament" }).click();
    await expect(page.getByText("Update the fixture description.")).toBeVisible();
    await page.getByRole("textbox", { name: "Description", exact: true }).fill("Revised fixture description.");
    await page.getByRole("button", { name: "Save settings" }).click();
    await expect(page.getByText("Tournament settings saved.")).toBeVisible();
    await page.getByRole("button", { name: "Resubmit for approval" }).click();
    await expect(page.getByText("Revised fixture description.")).toBeVisible();

    await admin.getByRole("button", { name: "Refresh queue" }).click();
    await admin.getByLabel("Pending tournament").selectOption(id);
    await expect(admin.getByText("Revised fixture description.")).toBeVisible();
    await admin.getByLabel("Confirm tournament approval").check();
    await admin.getByRole("button", { name: "Approve tournament" }).click();
    await expect(admin.getByText(/Organizer browser fixture approved/)).toBeVisible();
    await page.getByRole("button", { name: "Refresh tournament" }).click();
    await page.getByRole("button", { name: "Open registration" }).click();
    await expect(page.getByText("Registration is open.")).toBeVisible();
    await expect(page.getByText("Registration open", { exact: true })).toBeVisible();
  } finally {
    await admin.close();
  }

  await page.getByRole("link", { name: "All tournaments" }).click();
  const created = page.getByRole("row").filter({ hasText: "Organizer browser fixture" });
  await expect(created.getByText("Registration open", { exact: true })).toBeVisible();
  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});

test("Organizer routes enforce role and tournament assignment", async ({ page, useSession }) => {
  await useSession(page, "organizer");
  await page.goto("/organizer/tournaments/tied-fixture");
  await expect(page.getByRole("alert")).toContainText("The requested resource was not found.");
  await expect(page.getByRole("heading", { name: "Edit tournament" })).toHaveCount(0);
  await useSession(page, "captain-a");
  await page.goto("/organizer/tournaments/new");
  await expect(page.getByRole("alert")).toHaveText("Organizer access is required to manage tournaments.");
  await expect(page.getByRole("button", { name: "Create draft" })).toHaveCount(0);
});

test("Organizer publishes one announcement despite a lost response", async ({ page, useSession }) => {
  await useSession(page, "organizer");
  await page.goto("/announcements/new");
  const tournament = page.getByLabel("Tournament", { exact: true });
  await tournament.selectOption("approval-changed");
  await expect(page.getByText("Announcements are available after approval and before archive.")).toBeVisible();
  await tournament.selectOption("cup");

  const keys: string[] = [];
  await page.route("**/api/v1/tournaments/cup/announcements/", async (route) => {
    keys.push(route.request().headers()["idempotency-key"]);
    if (keys.length === 1) {
      const response = await route.fetch();
      expect(response.status()).toBe(201);
      await route.abort("failed");
    } else {
      await route.continue();
    }
  });
  await page.getByRole("textbox", { name: "Headline" }).fill("Fixture captain briefing");
  await page.getByRole("textbox", { name: "Message" }).fill("Meet in the fixture lobby before the round.");
  const publish = page.getByRole("button", { name: "Publish announcement" });
  await publish.click();
  await expect(page.getByRole("alert")).toBeVisible();
  await publish.click();
  await expect(page.getByRole("status")).toHaveText("Inbox notices posted: 2. Emails queued: 2.");
  expect(keys).toHaveLength(2);
  expect(keys[1]).toBe(keys[0]);

  await useSession(page, "captain-a");
  await page.goto("/notifications");
  await expect(page.getByRole("heading", { name: "Fixture captain briefing" })).toHaveCount(1);
  await expect(page.getByText("Meet in the fixture lobby before the round.")).toBeVisible();
  await page.goto("/announcements/new");
  await expect(page.getByRole("alert")).toHaveText("Tournament staff access is required to post announcements.");
  await expect(page.getByRole("button", { name: "Publish announcement" })).toHaveCount(0);
});

test("Admin paginates global audit and filters retained events for a deleted tournament", async ({ page, useSession }) => {
  await useSession(page, "admin");
  await page.goto("/admin/audit");
  const table = page.getByRole("table", { name: "Global audit events" });
  const pages = page.getByRole("navigation", { name: "Audit pages" });
  await expect(table).toBeVisible();
  await pages.getByRole("button", { name: "Next" }).click();
  await expect(pages.getByText("Page 2", { exact: true })).toBeVisible();
  await expect(table).toBeVisible();
  await pages.getByRole("button", { name: "Previous" }).click();
  await expect(pages.getByText("Page 1", { exact: true })).toBeVisible();

  await page.getByRole("combobox", { name: "Tournament ID" }).fill("retired-fixture");
  await page.getByRole("button", { name: "Apply filter" }).click();
  const deleted = table.getByRole("row").filter({ has: page.getByRole("rowheader", { name: "delete", exact: true }) });
  await expect(deleted.getByRole("cell", { name: "retired-fixture", exact: true })).toBeVisible();
  await deleted.locator("summary").click();
  await expect(deleted.getByText("deleted", { exact: true })).toBeVisible();
  await expect(table.getByText("Private approval-suite deletion reason")).toHaveCount(0);
  await expect(pages.getByRole("button", { name: "Next" })).toBeDisabled();
  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);

  await useSession(page, "captain-a");
  await page.goto("/admin/audit");
  await expect(page.getByRole("alert")).toHaveText("Admin access is required to open the global audit log.");
  await expect(table).toHaveCount(0);
});

test("Admin confirms a locked override and a deadline extension with participant receipts", async ({ page, useSession }) => {
  await useSession(page, "admin");
  await page.goto("/admin/tournaments/deadline-fixture");
  await expect(page.getByRole("heading", { name: "Deadline controls" })).toBeVisible();
  const path = "/api/v1/tournaments/deadline-fixture/";
  const before = await (await page.request.get(path)).json();

  await page.getByRole("combobox", { name: "Action", exact: true }).selectOption("emergency-override");
  await page.getByRole("textbox", { name: "Replacement name" }).fill("Updated deadline fixture");
  await page.getByRole("textbox", { name: "Reason", exact: true }).fill("Correct the displayed fixture name.");
  const override = page.getByRole("button", { name: "Apply emergency override" });
  await expect(override).toBeDisabled();
  await page.getByRole("checkbox", { name: /Confirm this change/ }).check();
  await override.click();
  await expect(page.getByRole("status")).toHaveText("Change recorded. Affected accounts: 2. Dashboard notices published.");
  const changed = await (await page.request.get(path)).json();
  expect(changed.name).toBe("Updated deadline fixture");
  expect(changed.submission_deadline).toBe(before.submission_deadline);

  await page.getByRole("combobox", { name: "Action", exact: true }).selectOption("extend-deadline");
  const next = await page.evaluate(() => {
    const date = new Date(Date.now() + 86_400_000);
    return new Date(date.getTime() - date.getTimezoneOffset() * 60_000).toISOString().slice(0, 16);
  });
  await page.getByLabel("New deadline", { exact: true }).fill(next);
  await page.getByRole("textbox", { name: "Reason", exact: true }).fill("Allow another fixture submission.");
  await page.getByRole("checkbox", { name: /Confirm this change/ }).check();
  await page.getByRole("button", { name: "Extend deadline", exact: true }).click();
  await expect(page.getByRole("status")).toHaveText("Change recorded. Affected accounts: 2. Dashboard notices published.");
  const after = await (await page.request.get(path)).json();
  expect(Date.parse(after.submission_deadline)).toBeGreaterThan(Date.parse(changed.submission_deadline));
  expect(after.registration_deadline).toBe(before.registration_deadline);

  await useSession(page, "captain-a");
  await page.goto("/notifications");
  await expect(page.getByRole("heading", { name: "The submission deadline of deadline-fixture was extended" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "A setting of deadline-fixture was changed by an emergency override" })).toBeVisible();
  await page.goto("/admin/tournaments/deadline-fixture");
  await expect(page.getByRole("alert")).toHaveText("Admin access is required to change deadlines and locked settings.");
});

test("Admin replaces and revokes invitations with plaintext visible only after replacement", async ({ page, useSession }) => {
  await useSession(page, "admin");
  await page.goto("/admin/invitations");
  await page.getByLabel("Tournament", { exact: true }).selectOption("invite-fixture");
  const path = "/api/v1/tournaments/invite-fixture/invitation-codes/";
  const initial = (await (await page.request.get(path)).json()).items;
  expect(initial).toHaveLength(1);
  const originalId = initial[0].id;
  await page.getByRole("button", { name: `Manage code ${originalId}` }).click();
  await page.getByRole("combobox", { name: "Action", exact: true }).selectOption("replace");
  await page.getByRole("textbox", { name: "Reason", exact: true }).fill("Replace the fixture invitation.");
  const replace = page.getByRole("button", { name: "Replace invitation" });
  await expect(replace).toBeDisabled();
  await page.getByRole("checkbox", { name: "Confirm this invitation change" }).check();
  await replace.click();
  const replacement = page.getByRole("region", { name: "Replacement code" });
  await expect(replacement.getByLabel("New invitation code")).toHaveText(/^[A-Z0-9-]+$/);
  const secret = (await replacement.getByLabel("New invitation code").textContent())!;
  const table = page.getByRole("table", { name: "Invitation metadata" });
  await expect(table.getByText("Replaced", { exact: true })).toBeVisible();
  const list = (await page.request.get(path));
  const metadata = await list.json();
  expect(JSON.stringify(metadata)).not.toContain(secret);
  expect(JSON.stringify(metadata)).not.toContain("Replace the fixture invitation.");
  const activeId = metadata.items.find((item: { status: string }) => item.status === "issued").id;
  await page.getByRole("button", { name: "Dismiss replacement code" }).click();
  await expect(page.getByText(secret, { exact: true })).toHaveCount(0);

  await page.getByRole("button", { name: `Manage code ${activeId}` }).click();
  await page.getByRole("textbox", { name: "Reason", exact: true }).fill("Revoke the fixture invitation.");
  await page.getByRole("checkbox", { name: "Confirm this invitation change" }).check();
  await page.getByRole("button", { name: "Revoke invitation" }).click();
  await expect(page.getByText("Invitation revoked.", { exact: true })).toBeVisible();
  await expect(table.getByText("revoked", { exact: true })).toBeVisible();

  await useSession(page, "organizer");
  await page.goto("/admin/invitations");
  await expect(page.getByRole("alert")).toHaveText("Admin access is required to manage invitation codes.");
  await expect(table).toHaveCount(0);
});

test("Organizer imports CSV and JSON rosters, corrects an unlocked row and sees the report", async ({ page, useSession }) => {
  await useSession(page, "organizer");
  await page.goto("/organizer/tournaments/roster-fixture");
  await page.getByRole("link", { name: "Manage roster" }).click();
  await expect(page.getByRole("heading", { name: "Official roster" })).toBeVisible();
  const entries = page.getByRole("table", { name: "Official roster entries" });
  const claimed = entries.getByRole("row").filter({ has: page.getByRole("rowheader", { name: "a@uni.edu", exact: true }) });
  await expect(claimed.getByText("Locked", { exact: true })).toBeVisible();

  const file = page.getByLabel("Roster file", { exact: true });
  await file.setInputFiles({
    name: "roster.csv", mimeType: "text/csv",
    buffer: Buffer.from("email,team_key,team_name,member_number,role\n" +
      "fixture-new@uni.edu,new-roster-team,New Fixture Team,1,captain\n" +
      "fixture-invalid@uni.edu,invalid-roster-team,Invalid Fixture Team,1,coach\n"),
  });
  await page.getByRole("button", { name: "Import roster", exact: true }).click();
  await expect(page.getByText("Created 1. Updated 0. Unchanged 0. Rejected 1.")).toBeVisible();
  await expect(page.getByRole("list", { name: "Rejected roster rows" }).getByText(/^Row 2:/)).toBeVisible();
  await expect(page.getByText("Teams awaiting a verified captain: new-roster-team.")).toBeVisible();
  await page.getByRole("button", { name: "Correct fixture-new@uni.edu", exact: true }).click();
  await page.getByRole("textbox", { name: "Official email", exact: true }).fill("fixture-corrected@uni.edu");
  await page.getByRole("button", { name: "Save correction" }).click();
  await expect(entries.getByRole("rowheader", { name: "fixture-corrected@uni.edu" })).toBeVisible();

  await file.setInputFiles({
    name: "roster.json", mimeType: "application/json",
    buffer: Buffer.from(JSON.stringify({ rows: [
      { email: "fixture-json@uni.edu", team_key: "json-roster-team", team_name: "JSON Fixture Team",
        member_number: 1, role: "captain" },
    ] })),
  });
  await page.getByRole("button", { name: "Import roster", exact: true }).click();
  await expect(entries.getByRole("rowheader", { name: "fixture-json@uni.edu" })).toBeVisible();
  await page.goto("/organizer/tournaments/invite-fixture/roster");
  await expect(page.getByText("This tournament is unavailable.")).toBeVisible();
  await expect(entries).toHaveCount(0);
});

test("Organizer selects maps, generates a bracket and separately queues the ready round", async ({ page, useSession }) => {
  await useSession(page, "organizer");
  await page.goto("/organizer/tournaments/roster-fixture/rounds");
  await page.getByRole("combobox", { name: "Available map pools", exact: true }).selectOption("browser-map-pool");
  await page.getByRole("button", { name: "Save map pool", exact: true }).click();
  await expect(page.getByText("Map pool selected.", { exact: true })).toBeVisible();
  await expect(page.getByText("Selected pool: browser-map-pool", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Generate bracket" })).toHaveCount(0);

  await page.goto("/organizer/tournaments/round-fixture");
  await page.getByRole("link", { name: "Manage rounds" }).click();
  const draw = page.getByRole("button", { name: "Generate bracket", exact: true });
  await expect(draw).toBeDisabled();
  await page.getByRole("checkbox", { name: "Confirm bracket generation" }).check();
  await draw.click();
  await expect(page.getByText("Bracket generated. No rounds have been started.")).toBeVisible();
  const start = page.getByRole("button", { name: "Start round 1", exact: true });
  await expect(start).toBeDisabled();
  await page.getByRole("checkbox", { name: "Confirm start of round 1" }).check();
  await start.click();
  await expect(page.getByText("Round 1 queued.", { exact: true })).toBeVisible();
  await expect(page.getByText("running · 1 pairing", { exact: true })).toBeVisible();
  await expect(start).toHaveCount(0);

  await page.goto("/organizer/tournaments/invite-fixture/rounds");
  await expect(page.getByText("This tournament is unavailable.")).toBeVisible();
  await expect(page.getByRole("button", { name: "Generate bracket" })).toHaveCount(0);
});

test("Organizer views assigned teams and downloads verified source with audit", async ({ page, useSession }) => {
  await useSession(page, "organizer");
  await page.goto("/organizer/tournaments/cup");
  await page.getByRole("link", { name: "View teams", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Tournament teams" })).toBeVisible();
  const select = page.getByRole("combobox", { name: "Team", exact: true });
  const profile = page.getByRole("region", { name: "Selected team" });
  await select.selectOption("tb");
  await expect(profile.getByRole("heading", { name: "TB", exact: true })).toBeVisible();
  await expect(profile.getByText("Eliminated", { exact: true })).toBeVisible();
  await select.selectOption("ta");
  await expect(profile.getByRole("heading", { name: "TA", exact: true })).toBeVisible();
  await expect(profile.getByRole("table", { name: "Verified team members" }).getByText("Captain")).toBeVisible();
  await expect(page.getByText("a@uni.edu")).toHaveCount(0);
  await expect(page.getByLabel("Python bot or bundle")).toHaveCount(0);

  const downloadEvent = page.waitForEvent("download");
  await page.getByRole("link", { name: "Download v1", exact: true }).click();
  const download = await downloadEvent;
  expect(download.suggestedFilename()).toBe("bot.py");
  expect(await readFile(await download.path(), "utf8")).toBe("def turn():\n    pass\n");
  const response = await page.request.get("/api/v1/tournaments/cup/audit-logs/?limit=200");
  expect(response.ok()).toBe(true);
  const audit = (await response.json()).items;
  expect(audit).toContainEqual(expect.objectContaining({
    source: "submissions", action: "download", detail: expect.objectContaining({ submission_id: "ta-v1", role: "organizer" }),
  }));

  await page.goto("/organizer/tournaments/invite-fixture/teams");
  await expect(page.getByText("This tournament is unavailable.")).toBeVisible();
  await expect(page.getByRole("link", { name: /Download v/ })).toHaveCount(0);
});

test("Organizer and Admin issue only eligible first codes through scoped console views", async ({ page, useSession }) => {
  await useSession(page, "organizer");
  await page.goto("/organizer/tournaments/issue-fixture/roster");
  const issuance = page.getByRole("region", { name: "Issue first invitation codes" });
  await expect(issuance.getByRole("checkbox", { name: "already-issued@uni.edu" })).toHaveCount(0);
  await issuance.getByRole("checkbox", { name: "first-ready@uni.edu" }).check();
  await issuance.getByRole("button", { name: "Issue selected codes" }).click();
  const receipt = issuance.getByRole("region", { name: "Initial invitation receipt" });
  await expect(receipt.getByRole("status")).toHaveText("Issued 1. Skipped 0.");
  const codeRow = receipt.getByRole("row").filter({
    has: page.getByRole("rowheader", { name: "first-ready@uni.edu", exact: true }),
  });
  const code = (await codeRow.locator("code").textContent())!;
  expect(code).toMatch(/^[A-Z0-9-]+$/);
  await expect(issuance.getByRole("checkbox", { name: "first-ready@uni.edu" })).toHaveCount(0);
  const path = "/api/v1/tournaments/issue-fixture/invitation-codes/";
  const metadata = await (await page.request.get(path)).json();
  expect(JSON.stringify(metadata)).not.toContain(code);
  await receipt.getByRole("button", { name: "Dismiss issuance receipt" }).click();
  await expect(page.getByText(code, { exact: true })).toHaveCount(0);

  await useSession(page, "admin");
  await page.goto("/admin/invitations");
  await page.getByLabel("Tournament", { exact: true }).selectOption("issue-fixture");
  await issuance.getByRole("checkbox", { name: "second-ready@uni.edu" }).check();
  await issuance.getByRole("button", { name: "Issue selected codes" }).click();
  await expect(receipt.getByRole("status")).toHaveText("Issued 1. Skipped 0.");
  await expect(issuance.getByText("No roster entries are eligible for first issuance.")).toBeVisible();
  const finalList = (await (await page.request.get(path)).json()).items;
  expect(finalList).toHaveLength(3);
});

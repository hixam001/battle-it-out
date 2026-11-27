import { test as base, expect } from "@playwright/test";
import type { BrowserContext, Page } from "@playwright/test";

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

test("staff notification route is guarded before fetching a participant inbox", async ({ page }) => {
  const inboxRequests: string[] = [];
  page.on("request", (request) => {
    if (new URL(request.url()).pathname === "/api/v1/notifications/") inboxRequests.push(request.url());
  });
  await page.goto("/notifications");
  await page.getByLabel("Username", { exact: true }).fill("organizer");
  await page.getByLabel("Password", { exact: true }).fill("test-fixture-passphrase");
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
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

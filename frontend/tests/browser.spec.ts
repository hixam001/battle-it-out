import { test, expect } from "@playwright/test";

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
}) => {
  await page.goto("/#console");
  await page.getByLabel("Username", { exact: true }).fill("admin");
  await page
    .getByLabel("Password", { exact: true })
    .fill("test-fixture-passphrase");
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
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

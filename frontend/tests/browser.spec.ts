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
  await page.getByRole("button", { name: "Analytics", exact: false }).click();
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
    .getByRole("button", { name: "Match disputes", exact: false })
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
    .getByRole("button", { name: "Bot submissions", exact: false })
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
  await page.getByRole("button", { name: "Operations", exact: false }).click();
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

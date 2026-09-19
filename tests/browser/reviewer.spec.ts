import { expect, test } from "@playwright/test";
import type { Page } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import { readFile } from "node:fs/promises";
import { readFileSync } from "node:fs";
import type { Report } from "../../src/types";

const fixture = JSON.parse(
  readFileSync(new URL("./fixture.json", import.meta.url), "utf8"),
) as Report;

const file = {
  name: "same-paper.pdf",
  mimeType: "application/pdf",
  buffer: Buffer.from("%PDF-1.7 test fixture"),
};

function eventsFor(revision = 1) {
  const report = structuredClone(fixture);
  report.review_id = `fixture-review-${revision}`;
  report.paper.title = `Research manuscript ${revision}`;
  return [
    { type: "status", message: "Reading PDF…" },
    { type: "paper", paper: report.paper },
    ...report.results.flatMap((result, index) => [
      { type: "section_start", section_id: result.section_id },
      {
        type: "section_result",
        result,
        summary: {
          ...report.summary,
          complete: false,
          decision: "Review in progress",
          reviewed: index + 1,
        },
      },
    ]),
    { type: "complete", report },
  ];
}

async function mockReview(page: Page, delay = 0) {
  let requests = 0;
  await page.route("**/api/review", async (route) => {
    const revision = ++requests;
    if (delay) await new Promise((resolve) => setTimeout(resolve, delay));
    await route
      .fulfill({
        contentType: "application/x-ndjson",
        body:
          eventsFor(revision)
            .map((e) => JSON.stringify(e))
            .join("\n") + "\n",
      })
      .catch(() => undefined);
  });
  return () => requests;
}

async function nav(page: Page, name: string) {
  const menu = page.getByRole("button", {
    name: "Open navigation",
    exact: true,
  });
  if (await menu.isVisible()) await menu.click();
  await page.getByRole("button", { name, exact: false }).first().click();
}

test.beforeEach(async ({ page }) => {
  await page.route("**/api/health", (route) =>
    route.fulfill({ json: { configured: true, model: "jev-fixture" } }),
  );
  await page.goto("/");
  await page
    .getByLabel("Target venue", { exact: true })
    .selectOption({ label: "General research review" });
  await page.evaluate(() => document.fonts.ready);
});

test("workspace is responsive and passes automated accessibility checks", async ({
  page,
}) => {
  await expect(
    page.getByRole("heading", { name: /Good research deserves/ }),
  ).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  expect(
    (
      await new AxeBuilder({ page })
        .withTags(["wcag2a", "wcag2aa", "wcag21aa"])
        .analyze()
    ).violations,
  ).toEqual([]);
});

test("uploads, scores every section, exposes distributions, and exports real LaTeX", async ({
  page,
}) => {
  await mockReview(page);
  await page.getByTestId("pdf-input").setInputFiles(file);
  await expect(
    page.getByText("YOUR REVIEW IS READY", { exact: true }),
  ).toBeVisible();
  await expect(page.locator(".section-row")).toHaveCount(8);
  await page.getByRole("button", { name: /3 Methods/ }).click();
  await expect(
    page
      .getByRole("region", { name: "Selected section review" })
      .getByRole("heading", { name: "3 Methods" }),
  ).toBeVisible();
  await page.locator(".dimension-toggle").first().click();
  await expect(page.getByText("Level 4", { exact: true })).toBeVisible();
  await page.getByRole("tab", { name: "Extracted manuscript" }).click();
  await expect(
    page.getByText("This is the extracted text.", { exact: false }),
  ).toBeVisible();
  const downloadPromise = page.waitForEvent("download");
  await page.getByRole("button", { name: "Export LaTeX" }).click();
  const download = await downloadPromise;
  expect(download.suggestedFilename()).toMatch(/\.tex$/);
  expect(await readFile((await download.path())!, "utf8")).toContain(
    "\\end{document}",
  );
});

test("the identical filename can be uploaded again and creates two reviews", async ({
  page,
}) => {
  const requests = await mockReview(page);
  await page.getByTestId("pdf-input").setInputFiles(file);
  await expect(
    page.getByText("YOUR REVIEW IS READY", { exact: true }),
  ).toBeVisible();
  await page.getByTestId("pdf-input").setInputFiles(file);
  await expect(
    page.getByRole("heading", { name: "Research manuscript 2", exact: true }),
  ).toBeVisible();
  expect(requests()).toBe(2);
  await nav(page, "Review history");
  await expect(page.locator(".history-card")).toHaveCount(2);
  await page.locator(".history-card").last().click();
  await expect(
    page.getByRole("heading", { name: "Research manuscript 1", exact: true }),
  ).toBeVisible();
});

test("late responses from a replaced PDF cannot overwrite the new review", async ({
  page,
}) => {
  let requests = 0;
  await page.route("**/api/review", async (route) => {
    const revision = ++requests;
    if (revision === 1)
      await new Promise((resolve) => setTimeout(resolve, 800));
    await route
      .fulfill({
        contentType: "application/x-ndjson",
        body: eventsFor(revision)
          .map((e) => JSON.stringify(e))
          .join("\n"),
      })
      .catch(() => undefined);
  });
  await page.getByTestId("pdf-input").setInputFiles(file);
  await expect.poll(() => requests).toBe(1);
  await page
    .getByTestId("pdf-input")
    .setInputFiles({ ...file, name: "new-draft.pdf" });
  await expect(
    page.getByRole("heading", { name: "Research manuscript 2", exact: true }),
  ).toBeVisible();
  await page.waitForTimeout(1000);
  await expect(
    page.getByRole("heading", { name: "Research manuscript 2", exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "Research manuscript 1", exact: true }),
  ).toHaveCount(0);
});

test("shows provisional scores while an incremental stream is still arriving", async ({
  page,
}) => {
  const events = eventsFor();
  await page.evaluate((payload) => {
    const original = window.fetch;
    window.fetch = async (input, init) => {
      if (input !== "/api/review") return original(input, init);
      const encoder = new TextEncoder();
      return new Response(
        new ReadableStream({
          start(controller) {
            let i = 0;
            const timer = setInterval(() => {
              if (init?.signal?.aborted) {
                clearInterval(timer);
                controller.error(new DOMException("Aborted", "AbortError"));
                return;
              }
              // Two pieces per event exercise buffering of incomplete NDJSON lines.
              const line = encoder.encode(JSON.stringify(payload[i++]) + "\n");
              const split = Math.floor(line.length / 2);
              controller.enqueue(line.slice(0, split));
              controller.enqueue(line.slice(split));
              if (i === payload.length) {
                clearInterval(timer);
                controller.close();
              }
            }, 100);
          },
        }),
        { headers: { "Content-Type": "application/x-ndjson" } },
      );
    };
  }, events);
  await page.getByTestId("pdf-input").setInputFiles(file);
  await expect(page.locator(".row-score").first()).toContainText("75.0");
  await expect(
    page.getByText("PROVISIONAL ASSESSMENT", { exact: true }),
  ).toBeVisible();
  await expect(page.getByRole("button", { name: "Export LaTeX" })).toHaveCount(
    0,
  );
  await expect(
    page.getByText("YOUR REVIEW IS READY", { exact: true }),
  ).toBeVisible();
});

test("invalid files and incomplete reviews never display a final decision", async ({
  page,
}) => {
  await page
    .getByTestId("pdf-input")
    .setInputFiles({ ...file, name: "notes.txt" });
  await expect(page.getByRole("status")).toContainText(
    "Please choose a PDF file.",
  );
  const events = eventsFor().slice(0, 4);
  await page.route("**/api/review", (route) =>
    route.fulfill({
      contentType: "application/x-ndjson",
      body: [...events, { type: "error", message: "Fixture API unavailable" }]
        .map((e) => JSON.stringify(e))
        .join("\n"),
    }),
  );
  await page.getByTestId("pdf-input").setInputFiles(file);
  await expect(page.getByRole("alert")).toContainText(
    "Fixture API unavailable",
  );
  await expect(page.getByText("PARTIAL REVIEW", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Export LaTeX" })).toHaveCount(
    0,
  );
});

test("completed review and rubric remain accessible and fit the screen", async ({
  page,
}) => {
  await mockReview(page);
  await page.getByTestId("pdf-input").setInputFiles(file);
  await expect(
    page.getByText("YOUR REVIEW IS READY", { exact: true }),
  ).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  expect(
    (
      await new AxeBuilder({ page })
        .withTags(["wcag2a", "wcag2aa", "wcag21aa"])
        .analyze()
    ).violations,
  ).toEqual([]);
  await nav(page, "Scoring rubric");
  await expect(
    page.getByRole("heading", { name: "Clarity", exact: true }),
  ).toBeVisible();
  expect(
    (
      await new AxeBuilder({ page })
        .withTags(["wcag2a", "wcag2aa", "wcag21aa"])
        .analyze()
    ).violations,
  ).toEqual([]);
});

test("help supports keyboard focus and Escape", async ({ page }) => {
  const menu = page.getByRole("button", {
    name: "Open navigation",
    exact: true,
  });
  if (await menu.isVisible()) await menu.click();
  await page.getByRole("button", { name: "A few things to know" }).click();
  await expect(page.getByRole("dialog")).toBeVisible();
  await expect(page.getByRole("button", { name: "Close help" })).toBeFocused();
  await page.keyboard.press("Shift+Tab");
  await expect(
    page.getByRole("link", { name: "TypeSafe data policies" }),
  ).toBeFocused();
  await page.keyboard.press("Tab");
  await expect(page.getByRole("button", { name: "Close help" })).toBeFocused();
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog")).toHaveCount(0);
});

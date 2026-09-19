import { expect, test } from "@playwright/test";
import type { Page } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import { readFileSync } from "node:fs";
import { readFile } from "node:fs/promises";
import type { Report, VenueContext } from "../../src/types";

const fixture = JSON.parse(
  readFileSync(new URL("./fixture.json", import.meta.url), "utf8"),
) as Report;
const file = {
  name: "same-paper.pdf",
  mimeType: "application/pdf",
  buffer: Buffer.from("%PDF-1.7 fixture"),
};
const venue: VenueContext = {
  name: "NeurIPS 2026",
  website: "https://neurips.cc/Conferences/2026/ReviewerGuidelines",
  track: "General",
  sources: [
    {
      url: "https://neurips.cc/Conferences/2026/ReviewerGuidelines",
      title: "Fixture reviewer guidelines",
      retrieved_at: "2026-09-19T12:00:00+00:00",
      sha256: "a".repeat(64),
      passages: [
        "Fixture scientific criteria: the research should state its assumptions and connect conclusions to specific supporting evidence.",
      ],
    },
  ],
  warnings: ["Fixture guidance for browser behavior tests."],
};

function eventsFor(target: VenueContext, revision: number) {
  const report = structuredClone(fixture);
  report.review_id = `venue-review-${revision}`;
  report.rubric_version = "folio-1.1";
  report.venue = structuredClone(target);
  report.results = report.results.map((result) => ({
    ...result,
    score: 60,
    dimensions: [
      ...result.dimensions.map((d) => ({ ...d, weight: d.weight * 0.8 })),
      {
        key: "venue_fit",
        label: "Venue fit",
        score: 0,
        confidence: 0.8,
        weight: 0.2,
        probabilities: { "0": 1, "1": 0, "2": 0, "3": 0, "4": 0 },
        finding: "Fixture: the manuscript does not match the venue scope.",
        suggestion:
          "Explain the connection to the venue's scientific priorities.",
      },
    ],
  }));
  report.summary.score = 60;
  report.summary.dimensions.venue_fit = 0;
  return (
    [
      { type: "status", message: "Reading published venue guidance…" },
      { type: "venue", venue: target },
      { type: "paper", paper: report.paper, venue: target },
      ...report.results.map((result) => ({
        type: "section_result",
        result,
        summary: { ...report.summary, complete: false },
      })),
      { type: "complete", report },
    ]
      .map((event) => JSON.stringify(event))
      .join("\n") + "\n"
  );
}

async function expectDefaultVenue(page: Page) {
  await expect(
    page.getByLabel("Target venue", { exact: true }).locator("option:checked"),
  ).toHaveText("NeurIPS 2026");
  await expect(page.getByLabel("Venue name & edition")).toHaveValue(venue.name);
  await expect(
    page.getByLabel("Official website or review guidelines"),
  ).toHaveValue(venue.website);
  await expect(page.getByLabel("Track / category")).toHaveValue(venue.track);
}

test.beforeEach(async ({ page }) => {
  await page.route("**/api/health", (route) =>
    route.fulfill({ json: { configured: true, model: "jev-fixture" } }),
  );
  await page.route("**/api/venues", (route) =>
    route.fulfill({ json: { presets: [venue] } }),
  );
  await page.goto("/");
});

test("venue guidance is inspectable, accessible, used on each upload and exported", async ({
  page,
}) => {
  const requests: string[] = [];
  await page.route("**/api/venue", (route) => route.fulfill({ json: venue }));
  await page.route("**/api/review", (route) => {
    requests.push(route.request().postData() ?? "");
    return route.fulfill({
      contentType: "application/x-ndjson",
      body: eventsFor(venue, requests.length),
    });
  });
  await expectDefaultVenue(page);
  await page.getByRole("button", { name: "Preview venue guidance" }).click();
  const preview = page.getByRole("region", {
    name: "Venue guidance preview",
    exact: true,
  });
  await expect(preview).toBeVisible();
  await preview.getByText("Inspect the guidance", { exact: true }).click();
  await expect(
    preview.getByText(venue.sources[0].passages[0], { exact: true }),
  ).toBeVisible();
  expect(
    (
      await new AxeBuilder({ page })
        .withTags(["wcag2a", "wcag2aa", "wcag21aa"])
        .analyze()
    ).violations,
  ).toEqual([]);
  for (let i = 1; i <= 2; i++) {
    await page.getByTestId("pdf-input").setInputFiles(file);
    await expect(
      page.getByText("YOUR REVIEW IS READY", { exact: true }),
    ).toBeVisible();
    await expect.poll(() => requests.length).toBe(i);
  }
  expect(
    requests.every(
      (body) =>
        body.includes('name="venue_website"') &&
        body.includes(venue.website) &&
        body.includes("NeurIPS 2026"),
    ),
  ).toBe(true);
  await expect(page.locator(".dimension-cards > *")).toHaveCount(5);
  const sources = page.getByRole("region", {
    name: "Venue sources used in this review",
    exact: true,
  });
  await sources.getByText("Inspect the guidance", { exact: true }).click();
  await expect(
    sources.getByRole("link", { name: venue.sources[0].title }),
  ).toHaveAttribute("href", venue.sources[0].url);
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
  const downloaded = page.waitForEvent("download");
  await page.getByRole("button", { name: "Export LaTeX" }).click();
  const tex = await readFile((await (await downloaded).path())!, "utf8");
  expect(tex).toContain("Target venue and website grounding");
  expect(tex).toContain("NeurIPS 2026");
  expect(tex).toContain(venue.sources[0].sha256.slice(0, 32));
});

test("changing venues starts a fresh assessment and history retains original sources", async ({
  page,
}) => {
  let requests = 0;
  let target = structuredClone(venue);
  await page.route("**/api/review", (route) => {
    requests++;
    expect(route.request().postData()).toContain(target.website);
    return route.fulfill({
      contentType: "application/x-ndjson",
      body: eventsFor(target, requests),
    });
  });
  await expectDefaultVenue(page);
  await page.getByTestId("pdf-input").setInputFiles(file);
  await expect(
    page.getByText("YOUR REVIEW IS READY", { exact: true }),
  ).toBeVisible();
  await page.getByText("Change target venue", { exact: true }).click();
  await page.getByLabel("Target venue", { exact: true }).selectOption("custom");
  target = {
    ...venue,
    name: "Journal of Research",
    website: "https://journal.example.org/scope",
    track: "Theory",
  };
  await page.getByLabel("Venue name & edition").fill(target.name);
  await page
    .getByLabel("Official website or review guidelines")
    .fill(target.website);
  await page.getByLabel("Track / category").fill(target.track);
  const sources = page.getByRole("region", {
    name: "Venue sources used in this review",
    exact: true,
  });
  await expect(sources).toContainText("NeurIPS 2026");
  await page.getByRole("button", { name: "Review for this venue" }).click();
  await expect(sources).toContainText("Journal of Research");
  expect(requests).toBe(2);
  const menu = page.getByRole("button", {
    name: "Open navigation",
    exact: true,
  });
  if (await menu.isVisible()) await menu.click();
  await page.getByRole("button", { name: /Review history/ }).click();
  await page
    .locator(".history-card")
    .filter({ hasText: "NeurIPS 2026" })
    .click();
  await expect(sources).toContainText("NeurIPS 2026");
  await page.getByText("Change target venue", { exact: true }).click();
  await expect(
    page.getByLabel("Official website or review guidelines"),
  ).toHaveValue(venue.website);
});

test("unreadable venue guidance prevents a false final result and can be corrected", async ({
  page,
}) => {
  await expectDefaultVenue(page);
  await page.route("**/api/venue", (route) =>
    route.fulfill({
      status: 422,
      json: { detail: "Fixture venue guidance unavailable" },
    }),
  );
  await page.getByRole("button", { name: "Preview venue guidance" }).click();
  await expect(page.getByRole("alert")).toContainText(
    "Fixture venue guidance unavailable",
  );
  await page.route("**/api/review", (route) =>
    route.fulfill({
      contentType: "application/x-ndjson",
      body:
        JSON.stringify({
          type: "error",
          message: "Fixture venue guidance unavailable",
        }) + "\n",
    }),
  );
  await page.getByTestId("pdf-input").setInputFiles(file);
  await expect(page.getByRole("alert")).toContainText(
    "Fixture venue guidance unavailable",
  );
  await expect(
    page.getByText("YOUR REVIEW IS READY", { exact: true }),
  ).toHaveCount(0);
  await expect(
    page.getByRole("region", {
      name: "Venue sources used in this review",
      exact: true,
    }),
  ).toHaveCount(0);
  await page.route("**/api/review", (route) =>
    route.fulfill({
      contentType: "application/x-ndjson",
      body: eventsFor(venue, 1),
    }),
  );
  await page.getByRole("button", { name: "Review for this venue" }).click();
  await expect(
    page.getByText("YOUR REVIEW IS READY", { exact: true }),
  ).toBeVisible();
});

test("late preview responses cannot ground a changed venue", async ({
  page,
}) => {
  let calls = 0;
  await page.route("**/api/venue", async (route) => {
    calls++;
    await new Promise((resolve) => setTimeout(resolve, 400));
    await route.fulfill({ json: venue }).catch(() => undefined);
  });
  await expectDefaultVenue(page);
  await page.getByRole("button", { name: "Preview venue guidance" }).click();
  await expect.poll(() => calls).toBe(1);
  await page.getByLabel("Venue name & edition").fill("Different conference");
  await page.waitForTimeout(600);
  await expect(
    page.getByRole("region", { name: "Venue guidance preview", exact: true }),
  ).toHaveCount(0);
  await expect(
    page.getByRole("button", { name: "Preview venue guidance" }),
  ).toBeEnabled();
});

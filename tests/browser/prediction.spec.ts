import { expect, test } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import { readFileSync } from "node:fs";
import { readFile } from "node:fs/promises";
import type {
  AcceptancePrediction,
  Report,
  ResearchStudy,
} from "../../src/types";

const fixture = JSON.parse(
  readFileSync(new URL("./fixture.json", import.meta.url), "utf8"),
) as Report;
const labels = [
  "Strong reject",
  "Reject",
  "Weak reject",
  "Weak accept",
  "Accept",
  "Strong accept",
] as const;
const boundaries = [0, 0.15, 0.3, 0.5, 0.7, 0.85, 1];
const bands = labels.map((label, i) => ({
  label,
  minimum: boundaries[i],
  maximum: boundaries[i + 1],
}));
const metrics = {
  accuracy: 0.6,
  balanced_accuracy: 0.6,
  roc_auc: 0.64,
  brier: 0.24,
  log_loss: 0.69,
  confusion_matrix: [
    [3, 2],
    [2, 3],
  ],
  bootstrap_95_ci: {
    accuracy: [0.3, 0.9],
    roc_auc: [0.2, 0.9],
    brier: [0.1, 0.4],
  },
};
const study: ResearchStudy = {
  status: "ready",
  bands,
  model_id: "browser-fixture-only",
  counts: {
    train: { total: 30, accepted: 15, rejected: 15 },
    calibration: { total: 10, accepted: 5, rejected: 5 },
    test: { total: 10, accepted: 5, rejected: 5 },
  },
  metrics,
  baseline: { ...metrics, accuracy: 0.5, roc_auc: 0.5, brier: 0.25 },
  sources: [
    {
      url: "https://huggingface.co/datasets/weathon/iclr_2026",
      revision: "fixture-snapshot",
    },
  ],
};
const venue = {
  name: "ICLR 2026",
  website: "https://openreview.net/group?id=ICLR.cc/2026/Conference",
  track: "Main conference",
  openreview_id: "ICLR.cc/2026/Conference",
  sources: [],
  warnings: [],
};
const file = {
  name: "same-paper.pdf",
  mimeType: "application/pdf",
  buffer: Buffer.from("%PDF-1.7 test"),
};

function events(index: number, complete = true) {
  const report = structuredClone(fixture);
  report.review_id = `prediction-fixture-${index}`;
  report.venue = venue;
  report.summary.decision = "Accept";
  report.prediction = {
    ...study,
    status: "ready",
    bands,
    label: labels[index],
    acceptance_probability: (boundaries[index] + boundaries[index + 1]) / 2,
    binary_prediction: index < 3 ? "Reject" : "Accept",
    known_paper: { forum_id: "fixture", split: "train", decision: "Reject" },
    limitations: ["Retrospective fixture study with revision leakage."],
  } as AcceptancePrediction;
  const stream: unknown[] = [
    { type: "paper", paper: report.paper, venue },
    ...report.results.map((result) => ({
      type: "section_result",
      result,
      summary: {
        ...report.summary,
        complete: false,
        decision: "Review in progress",
      },
    })),
  ];
  if (complete) stream.push({ type: "complete", report });
  return stream.map((event) => JSON.stringify(event)).join("\n") + "\n";
}

test.beforeEach(async ({ page }) => {
  await page.route("**/api/health", (route) =>
    route.fulfill({ json: { configured: true, model: "fixture" } }),
  );
  await page.route("**/api/venues", (route) =>
    route.fulfill({ json: { presets: [venue] } }),
  );
  await page.route("**/api/research", (route) =>
    route.fulfill({ json: study }),
  );
  await page.goto("/");
});

test("all six outcomes update on reupload, expose their basis, and export", async ({
  page,
}) => {
  let index = 0;
  await page.route("**/api/review", (route) =>
    route.fulfill({
      contentType: "application/x-ndjson",
      body: events(index++),
    }),
  );
  const panel = page.getByRole("region", {
    name: "Final acceptance prediction",
    exact: true,
  });
  for (const label of labels) {
    await page.getByTestId("pdf-input").setInputFiles(file);
    await expect(
      panel.getByRole("heading", { name: label, exact: true }),
    ).toBeVisible();
    await expect(panel.locator(".decision-bands li")).toHaveCount(6);
    await expect(panel.locator('[aria-current="step"]')).toContainText(label);
  }
  await expect(panel).toContainText("Predicted outcome: Accept");
  await expect(panel).toContainText("92.5%");
  await expect(panel).toContainText("not independent of training");
  await panel.getByText("Validation and limits", { exact: true }).click();
  await expect(panel).toContainText("50.0% majority baseline");
  await expect(panel).toContainText("30.0%–90.0%");
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
  const download = page.waitForEvent("download");
  await page.getByRole("button", { name: "Export LaTeX" }).click();
  const latex = await readFile((await (await download).path())!, "utf8");
  expect(latex).toContain("Acceptance prediction");
  expect(latex).toContain("92.5\\%");
  expect(latex).toContain("browser-fixture-only");
});

test("an interrupted review cannot display a previous acceptance estimate", async ({
  page,
}) => {
  let calls = 0;
  await page.route("**/api/review", (route) =>
    route.fulfill({
      contentType: "application/x-ndjson",
      body: events(4, ++calls === 1),
    }),
  );
  await page.getByTestId("pdf-input").setInputFiles(file);
  await expect(
    page.getByRole("region", {
      name: "Final acceptance prediction",
      exact: true,
    }),
  ).toBeVisible();
  await page.getByTestId("pdf-input").setInputFiles(file);
  await expect(page.getByRole("alert")).toBeVisible();
  await expect(
    page.getByRole("region", {
      name: "Final acceptance prediction",
      exact: true,
    }),
  ).toHaveCount(0);
});

test("the evidence browser exposes accepted, rejected and held-out records", async ({
  page,
}) => {
  const papers = [
    {
      forum_id: "a",
      title: "Accepted fixture paper",
      decision: "Accept (Poster)",
      label: 1,
      split: "train",
      forum_url: "https://openreview.net/forum?id=a",
      mirror_url: "https://huggingface.co/a.pdf",
    },
    {
      forum_id: "b",
      title: "Rejected fixture paper",
      decision: "Reject",
      label: 0,
      split: "test",
      forum_url: "https://openreview.net/forum?id=b",
      mirror_url: "https://huggingface.co/b.pdf",
    },
  ];
  await page.route("**/api/research/papers", (route) =>
    route.fulfill({ json: { papers } }),
  );
  const evidence = page.getByRole("region", {
    name: "ICLR 2026 training evidence",
    exact: true,
  });
  await expect(evidence).toContainText("50 labeled papers");
  await evidence.getByText("Inspect the evidence", { exact: true }).click();
  await evidence
    .getByRole("button", { name: "Explore the labeled papers" })
    .click();
  await evidence.getByLabel("Show papers").selectOption("1");
  await expect(
    evidence.getByRole("link", { name: "Accepted fixture paper", exact: true }),
  ).toBeVisible();
  await expect(
    evidence.getByRole("link", { name: "Rejected fixture paper", exact: true }),
  ).toHaveCount(0);
  await evidence.getByLabel("Show papers").selectOption("0");
  await expect(
    evidence.getByRole("link", { name: "Rejected fixture paper", exact: true }),
  ).toBeVisible();
  await evidence.getByLabel("Show papers").selectOption("test");
  await expect(evidence).toContainText("1 papers");
  await expect(
    evidence.getByRole("link", {
      name: "Download PDF: Rejected fixture paper",
    }),
  ).toHaveAttribute("href", papers[1].mirror_url);
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

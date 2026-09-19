# Folio

A thoughtful paper reviewer built with **Jev**, FastAPI, and React. Upload a PDF and see section scores appear as they are evaluated. Every upload—including the same filename—starts a new review. Replacing an upload cancels pending requests and prevents old results from changing the new review.

![Folio workspace with a target venue](reports/screenshots/venue-setup-desktop.png)

## Run locally

Requires Python 3.11+, [uv](https://docs.astral.sh/uv/), and Node.js 20.19+.

```bash
uv sync
npm ci
npm run dev
```

Open **http://127.0.0.1:5173**. The API runs on port 8000.

Put your key in the root `.env` file. An existing `.env` is never overwritten; `.env.example` documents the available settings.

```dotenv
JEV_API_KEY=your_typesafe_key
JEV_MODEL=jev-1.13.0
JEV_CONCURRENCY=3
```

`TYPESAFE_API_KEY` is also accepted. Credentials are only used on the server, never sent to the browser or embedded in the build. Restart the API after changing `.env`.

For the compiled application on a single origin:

```bash
npm run build
npm start
```

Open **http://127.0.0.1:8000**. The included commands bind to loopback and are intended for a personal research workspace. A public deployment needs authentication, per-user quotas, upload/request limits at the reverse proxy, and appropriate data handling controls.

## What it does

- Drag-and-drop upload, a file picker, and an original synthetic example PDF.
- Layout-aware section extraction with page references and an inspectable manuscript view.
- Separate research, survey, and theory profiles.
- Four core Jev Score questions per passage: clarity, rigor, evidence, and completeness; a fifth measures venue fit when a venue is selected.
- A target conference or journal, official website, and optional track; published website passages ground each section's assessment.
- Live NDJSON results, provisional totals, final recommendation, and visible confidence distributions.
- Fresh reviews on every upload, including identical files; request cancellation and stale-result guards.
- Session-only history for up to 20 completed reviews.
- Downloadable LaTeX and JSON reports with provenance, section weights, and limitations.
- Responsive layouts, keyboard interaction, reduced-motion support, and accessible color contrast.

## Ground a review in a venue

**NeurIPS 2026** is selected by default, using the official [reviewer guidelines](https://neurips.cc/Conferences/2026/ReviewerGuidelines) and the General category. Change **Target venue** to **Custom conference or journal** to enter another venue's name, edition, official website or guidelines URL, and optional track. General research reviews remain available. Your chosen venue stays selected when you start another review in the same session.

**Preview venue guidance** shows the selected website passages and their source links before uploading. Each upload independently retrieves current guidance, then supplies those passages to Jev for every section and criterion. **Venue fit** contributes 20% of the score; the four core dimensions contribute 80%. These are Folio's weights, not the venue's official scoring scale or acceptance odds. On a completed review, **Change target venue → Review for this venue** assesses the same PDF again. History retains the venue and sources actually used for each saved review.

The source panel records URLs, retrieval times, page hashes, and the selected passages. JSON exports retain the complete selected context; LaTeX exports include source provenance and a short excerpt. The reader accepts public HTTPS HTML pages, follows up to two relevant links on the same site, and prioritizes headings and the requested track. Prefer a direct review-guidelines, call-for-papers, or aims-and-scope page. Login-protected pages, JavaScript-only content, and PDF guidelines are unsupported. If no usable guidance is retrieved, the venue review stops with an actionable error. Selected excerpts do not establish exhaustive policy compliance or verify that a user-supplied site is official.

## Scoring

Jev is a structured decision model, not a generative reviewer. It evaluates five descriptive levels (0–4), and the application normalizes its scores to 0–100. Readable findings are **rubric-derived templates**, and source excerpts are provided as context rather than asserted model rationales.

The section score is `0.20 × clarity + 0.35 × rigor + 0.30 × evidence + 0.15 × completeness`. Overall section weights are grouped by role; a role's weight is divided among its sections by word count. Multiple subsections therefore do not receive extra influence merely because they are split apart. The complete rubric and thresholds are available in the interface and in `server/rubric.py`.

With venue grounding, the section score is `0.16 × clarity + 0.28 × rigor + 0.24 × evidence + 0.12 × completeness + 0.20 × venue fit`. The website context informs all five judgments. The role aggregation, provisional scoring, confidence check, and recommendation thresholds remain the same. Rubric version `folio-1.1` records this addition; the original general-review study below used `folio-1.0`.

| Overall score | Recommendation              |
| ------------- | --------------------------- |
| 85–100        | Strong submission           |
| 70–<85        | Promising · minor revisions |
| 55–<70        | Major revisions suggested   |
| <55           | Needs substantial work      |

Mean model confidence below 45% changes the recommendation to **Expert review needed**. Incomplete or failed reviews never receive a final recommendation. Confidence measures concentration of the returned distribution, not scientific correctness. Thresholds and weights have not been calibrated against expert reviews.

Limits: 20 MB, 120 pages, 400,000 extracted characters, and 64 review units. Long sections are evaluated in non-overlapping passages of at most 9,000 UTF-8 bytes; every extracted character is included. The title, section outline, and an explicitly bounded abstract excerpt provide context. Passage scores are weighted by character count.

Scanned PDFs require OCR before upload. The text pipeline does not verify references, novelty, figure content, numerical results, or mathematical proofs. Headings and column order remain heuristic. Inspect the extracted manuscript for unusual layouts. Portable LaTeX exports transliterate non-ASCII text; the JSON export preserves exact Unicode.

## Data handling

The server sends extracted text to `https://api.typesafe.ai/v1/systemone`. Folio does not persist uploaded manuscripts or completed reports on the server. Framework upload buffering can create temporary files, which are closed after reading. Browser memory retains completed reviews and their files until reload, with a maximum history of 20. No localStorage or third-party analytics is used; fonts are bundled locally. TypeSafe's handling of API data is governed by its own [policies](https://docs.typesafe.ai/legal).

For venue reviews, the server also reads the supplied website and sends selected public passages to Jev. Website requests include no manuscript, API credential, or browser cookies. Connections are pinned to validated public IP addresses, with same-site redirect checks, a 2 MB page limit, and a 35-second retrieval deadline. No venue-response cache is used.

The checked-in example and study artifacts were deliberately generated by the benchmark script; ordinary uploads do not create these artifacts. The configured secret `.env` is ignored by Git.

## Validation and findings

- **72 backend tests**: PDF parsing, scoring, cancellation, exports, plus venue-source retrieval, public-address restrictions, track selection, source provenance, five-question Jev requests, venue weighting, retrieval failures, and fresh sources on repeated uploads.
- **24 browser tests** across desktop and mobile: real-time streams, uploads, stale responses, exports, history, rubric inspection, venue selection, source previews, venue changes, retrieval errors, and automated accessibility checks.
- **Nine live API reviews**: three repetitions each for a structured synthetic manuscript, a deliberately vague variant, and _On Calibration of Modern Neural Networks_ (Guo et al., 2017).
- **Two live venue reviews**: repeated uploads of the structured synthetic manuscript using NeurIPS 2026 guidance. Both completed all eight sections with five criteria, scoring 77.4/100; venue-fit scores were 65.2 and 65.9. Total latencies including website retrieval were 1.49 s and 1.14 s. These are integration observations, not scientific-validity measurements.

The measured mean full-review latencies were 0.71 s, 0.66 s, and 1.24 s respectively. Corresponding scores were 80.7, 20.5, and 68.8. **The synthetic manuscript outscored the published paper; these numbers are not a validated ranking of scientific merit.** This small study establishes integration behavior, response times in this environment, and sensitivity to a controlled writing change. It does not establish peer-review accuracy or human agreement.

See [the LaTeX findings](reports/findings.tex), [compiled report](reports/findings.pdf), and [raw measurements](reports/benchmark-results.json). An actual [example review](reports/example-review.tex) and its [compiled PDF](reports/example-review.pdf) are also included.

The venue extension has separate [live measurements](reports/venue-validation.json) and a [LaTeX example](reports/venue-example-review.tex) with its [compiled PDF](reports/venue-example-review.pdf).

```bash
npm test
npx playwright install chromium
npm run test:e2e
npm run build
uv run ruff check server tests scripts
```

The automated tests mock Jev and do not spend API credits. To repeat the live study (requires the running server and uses the configured API key):

```bash
uv run python scripts/benchmark.py --public --repeats 3
uv run python scripts/benchmark_venue.py
uv run --with matplotlib python scripts/plot_findings.py
npm run report
```

`npm run report` requires a LaTeX installation with `latexmk` and `pdflatex`. The findings narrative records the delivered study; if new measurements differ, update that narrative as well as regenerating its tables and figures.

## Project map

```text
src/                    React interface, stream consumer, browser exports
server/pdf.py           PDF extraction and passage splitting
server/jev.py           Authenticated Jev requests, validation, retries
server/rubric.py        Questions, section weighting, recommendation policy
server/venue.py         Venue guidance retrieval, passage selection, provenance
server/app.py           Upload, stream, health, rubric, and export endpoints
server/export.py        Escaped, portable LaTeX report generation
tests/                  Backend tests and desktop/mobile browser scenarios
scripts/                Reproducible live integration study and figure generation
reports/                Findings, measurements, example review, screenshots
```

Implementation follows the official [Jev introduction](https://docs.typesafe.ai/introduction), [Score primitive](https://docs.typesafe.ai/primitives/score), [HTTP API](https://docs.typesafe.ai/api), and [model documentation](https://docs.typesafe.ai/models).

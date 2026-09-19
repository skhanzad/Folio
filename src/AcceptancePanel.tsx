import { useEffect, useState } from "react";
import {
  ArrowUpRight,
  ChevronDown,
  FlaskConical,
  Info,
  Landmark,
  Check,
} from "lucide-react";
import type {
  AcceptancePrediction,
  ResearchStudy,
  StudyMetrics,
} from "./types";

const percent = (value: number) => `${(value * 100).toFixed(1)}%`;

function ValidationLine({
  metrics,
  baseline,
}: {
  metrics: StudyMetrics;
  baseline?: StudyMetrics;
}) {
  return (
    <p className="study-validation-line">
      Held-out accuracy <strong>{percent(metrics.accuracy)}</strong>
      {baseline && <> · majority baseline {percent(baseline.accuracy)}</>} ·
      AUROC {metrics.roc_auc.toFixed(3)}. A small retrospective test;
      future-submission accuracy is unvalidated.
    </p>
  );
}

function Metrics({
  metrics,
  baseline,
}: {
  metrics: StudyMetrics;
  baseline?: StudyMetrics;
}) {
  return (
    <div className="study-metrics">
      <div>
        <span>Test accuracy</span>
        <strong>{percent(metrics.accuracy)}</strong>
        <small>
          {baseline
            ? `${percent(baseline.accuracy)} majority baseline`
            : "On held-out papers"}
        </small>
      </div>
      <div>
        <span>Ranking · AUROC</span>
        <strong>{metrics.roc_auc.toFixed(3)}</strong>
        <small>0.5 is chance; 1.0 is perfect</small>
      </div>
      <div>
        <span>Probability error · Brier</span>
        <strong>{metrics.brier.toFixed(3)}</strong>
        <small>
          {baseline
            ? `${baseline.brier.toFixed(3)} prevalence baseline; lower is better`
            : "Lower is better"}
        </small>
      </div>
    </div>
  );
}

export function ResearchEvidence() {
  const [study, setStudy] = useState<ResearchStudy | null>(null);
  const [papers, setPapers] = useState<
    | {
        forum_id: string;
        title: string;
        decision: string;
        split: string;
        forum_url: string;
        mirror_url: string;
        label: number;
      }[]
    | null
  >(null);
  const [filter, setFilter] = useState("all");
  const [error, setError] = useState("");
  useEffect(() => {
    const abort = new AbortController();
    fetch("/api/research", { signal: abort.signal })
      .then((r) => {
        if (!r.ok) throw new Error("The study could not be loaded.");
        return r.json();
      })
      .then(setStudy)
      .catch((e) => {
        if (!abort.signal.aborted) setError(e.message);
      });
    return () => abort.abort();
  }, []);
  async function loadPapers() {
    try {
      const response = await fetch("/api/research/papers");
      if (!response.ok)
        throw new Error("The dataset manifest could not be loaded.");
      setPapers((await response.json()).papers);
    } catch (e) {
      setError(
        e instanceof Error ? e.message : "The papers could not be loaded.",
      );
    }
  }
  const counts = study?.counts;
  const total = counts
    ? Object.values(counts).reduce((sum, split) => sum + split.total, 0)
    : 0;
  const filtered = (papers ?? []).filter(
    (p) =>
      filter === "all" ||
      (filter === "test" ? p.split === "test" : p.label === Number(filter)),
  );
  return (
    <section
      className="research-evidence panel"
      aria-label="ICLR 2026 training evidence"
    >
      <div className="research-evidence-heading">
        <span className="research-icon">
          <FlaskConical size={20} />
        </span>
        <div>
          <span className="eyebrow">LEARNING FROM OPENREVIEW</span>
          <h3>ICLR 2026 · a measured second opinion.</h3>
          <p>
            {study?.status === "ready"
              ? `${total} labeled papers · ${counts!.train.total} training · ${counts!.calibration.total} calibration · ${counts!.test.total} held out`
              : (study?.reason ?? "Loading the acceptance study…")}
          </p>
        </div>
        <span className="format-tag">EXPERIMENTAL PILOT</span>
      </div>
      {study?.metrics && (
        <ValidationLine metrics={study.metrics} baseline={study.baseline} />
      )}
      <details className="research-details">
        <summary>
          Inspect the evidence <ChevronDown size={14} />
        </summary>
        {study?.metrics && (
          <Metrics metrics={study.metrics} baseline={study.baseline} />
        )}
        <p>
          Jev scores the manuscript. A classifier learns how those scores relate
          to the archived final decisions. Human reviews and decisions are
          excluded from prediction inputs.
        </p>
        <p className="study-caveat">
          This is a retrospective study of a selected public PDF archive. Some
          accepted PDFs include revisions made after acceptance. It has not
          established accuracy for future submissions.
        </p>
        {study?.sources?.map((source) => (
          <a
            className="study-source"
            href={source.url}
            target="_blank"
            rel="noreferrer"
            key={source.url}
          >
            {new URL(source.url).hostname} · snapshot{" "}
            {source.revision.slice(0, 10)} <ArrowUpRight size={12} />
          </a>
        ))}
        {study?.status === "ready" && (
          <button className="text-button" onClick={() => void loadPapers()}>
            Explore the labeled papers <ArrowUpRight size={13} />
          </button>
        )}
        {papers && (
          <div className="corpus-browser">
            <label htmlFor="corpus-filter">Show papers</label>
            <select
              id="corpus-filter"
              value={filter}
              onChange={(e) => setFilter(e.target.value)}
            >
              <option value="all">All decisions</option>
              <option value="1">Accepted</option>
              <option value="0">Rejected</option>
              <option value="test">Held-out test papers</option>
            </select>
            <p>
              {filtered.length} papers · showing the first{" "}
              {Math.min(filtered.length, 12)}
            </p>
            <ul>
              {filtered.slice(0, 12).map((paper) => (
                <li key={paper.forum_id}>
                  <div>
                    <a href={paper.forum_url} target="_blank" rel="noreferrer">
                      {paper.title} <ArrowUpRight size={12} />
                    </a>
                    <span>
                      {paper.decision} · {paper.split}
                    </span>
                  </div>
                  <a
                    href={paper.mirror_url}
                    target="_blank"
                    rel="noreferrer"
                    aria-label={`Download PDF: ${paper.title}`}
                  >
                    PDF <ArrowUpRight size={12} />
                  </a>
                </li>
              ))}
            </ul>
            <a
              className="text-button"
              href="/api/research/papers"
              download="iclr2026-manifest.json"
            >
              Download complete dataset manifest
            </a>
          </div>
        )}
      </details>
      {error && <p role="alert">{error}</p>}
    </section>
  );
}

export default function AcceptancePanel({
  prediction,
}: {
  prediction: AcceptancePrediction;
}) {
  if (prediction.status !== "ready")
    return (
      <section
        className="prediction-unavailable panel"
        aria-label="Acceptance prediction unavailable"
      >
        <Info size={19} />
        <div>
          <h3>Acceptance estimate unavailable</h3>
          <p>{prediction.reason}</p>
          <p>
            Section scores remain available. No acceptance probability has been
            inferred.
          </p>
        </div>
      </section>
    );
  const probability = prediction.acceptance_probability!;
  return (
    <section
      className={`acceptance-panel panel ${probability >= 0.5 ? "leans-accept" : "leans-reject"}`}
      aria-label="Final acceptance prediction"
    >
      <div className="card-topline">
        <span className="eyebrow">
          <Landmark size={15} /> ICLR 2026 · ACCEPTANCE PREDICTION
        </span>
        <span className="format-tag">EXPERIMENTAL</span>
      </div>
      <div className="acceptance-headline">
        <div>
          <h2>{prediction.label}</h2>
          <p>
            Predicted outcome: <strong>{prediction.binary_prediction}</strong>
          </p>
        </div>
        <div className="acceptance-probability">
          <strong>{percent(probability)}</strong>
          <span>
            estimated acceptance
            <br />
            in the pilot cohort
          </span>
        </div>
      </div>
      <ol
        className="decision-bands"
        aria-label="Six possible recommendation bands"
      >
        {prediction.bands.map((band) => (
          <li
            key={band.label}
            className={prediction.label === band.label ? "selected" : ""}
            aria-current={prediction.label === band.label ? "step" : undefined}
          >
            <span>
              {prediction.label === band.label && <Check size={12} />}
              {band.label}
            </span>
            <small>
              {Math.round(band.minimum * 100)}–{Math.round(band.maximum * 100)}%
            </small>
          </li>
        ))}
      </ol>
      <p className="prediction-explainer">
        Learned from accepted and rejected OpenReview papers. The six labels are
        ranges of the model’s acceptance estimate, not six ground-truth decision
        classes.
      </p>
      {prediction.metrics && (
        <ValidationLine
          metrics={prediction.metrics}
          baseline={prediction.baseline}
        />
      )}
      {prediction.known_paper && (
        <div className="known-paper-note">
          <Info size={16} />
          <p>
            This manuscript is in the{" "}
            <strong>{prediction.known_paper.split}</strong> split. Its recorded
            decision is <strong>{prediction.known_paper.decision}</strong>.{" "}
            {prediction.known_paper.split === "train"
              ? "This prediction is not independent of training."
              : prediction.known_paper.split === "calibration"
                ? "This paper helped calibrate probabilities; it is not an independent test."
                : "This paper was held out from training and calibration. Its recorded decision was not supplied to Jev."}
          </p>
        </div>
      )}
      <details className="research-details">
        <summary>
          Validation and limits <ChevronDown size={14} />
        </summary>
        {prediction.metrics && (
          <Metrics
            metrics={prediction.metrics}
            baseline={prediction.baseline}
          />
        )}
        {prediction.metrics?.bootstrap_95_ci && (
          <p>
            Test accuracy 95% bootstrap interval:{" "}
            {prediction.metrics.bootstrap_95_ci.accuracy.map(percent).join("–")}
            .
          </p>
        )}
        <ul>
          {prediction.limitations?.map((note) => (
            <li key={note}>{note}</li>
          ))}
        </ul>
        <small>Model {prediction.model_id}</small>
      </details>
      <p className="study-caveat">
        Retrospective pilot with possible revision leakage. Future-submission
        accuracy is unvalidated.
      </p>
    </section>
  );
}

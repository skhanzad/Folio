import { useEffect, useRef, useState } from "react";
import {
  ArrowRight,
  ArrowUpRight,
  Check,
  ChevronDown,
  Compass,
  Globe2,
  LoaderCircle,
  RefreshCw,
} from "lucide-react";
import type { VenueContext, VenueRequest } from "./types";

export function VenueSources({
  venue,
  preview = false,
}: {
  venue: VenueContext;
  preview?: boolean;
}) {
  return (
    <section
      className="venue-sources"
      aria-label={
        preview ? "Venue guidance preview" : "Venue sources used in this review"
      }
    >
      <div className="venue-source-heading">
        <span className="venue-source-icon">
          <Compass size={19} />
        </span>
        <div>
          <span className="eyebrow">
            {preview ? "GUIDANCE PREVIEW" : "GROUNDED IN VENUE GUIDANCE"}
          </span>
          <h3>
            {venue.name}
            {venue.track && <span> · {venue.track}</span>}
          </h3>
          <a href={venue.website} target="_blank" rel="noreferrer">
            {new URL(venue.website).hostname}
            <ArrowUpRight size={12} />
          </a>
        </div>
        <span className="venue-source-count">
          <Check size={12} /> {venue.sources.length}{" "}
          {venue.sources.length === 1 ? "source" : "sources"}
        </span>
      </div>
      <details className="venue-source-details">
        <summary>
          Inspect the guidance <ChevronDown size={14} />
        </summary>
        <p>
          Selected website passages inform all criteria. Venue fit contributes
          20% to the score. The weights and recommendation thresholds are
          Folio’s, and do not estimate acceptance odds.
        </p>
        {venue.sources.map((source) => (
          <article key={source.url}>
            <a href={source.url} target="_blank" rel="noreferrer">
              {source.title}
              <ArrowUpRight size={13} />
            </a>
            <small>
              Retrieved {new Date(source.retrieved_at).toLocaleString()} ·
              source {source.sha256.slice(0, 12)}
            </small>
            {source.passages.map((passage, i) => (
              <blockquote key={i}>{passage}</blockquote>
            ))}
          </article>
        ))}
        {venue.warnings.map((warning) => (
          <p key={warning}>{warning}</p>
        ))}
      </details>
    </section>
  );
}

export default function VenueSettings({
  value,
  onChange,
  disabled = false,
  onApply,
}: {
  value: VenueRequest | null;
  onChange: (value: VenueRequest | null) => void;
  disabled?: boolean;
  onApply?: () => void;
}) {
  const [presets, setPresets] = useState<VenueRequest[]>([]);
  const [preview, setPreview] = useState<VenueContext | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const abort = useRef<AbortController | null>(null);
  const version = useRef(0);

  useEffect(() => {
    const controller = new AbortController();
    fetch("/api/venues", { signal: controller.signal })
      .then((r) => (r.ok ? r.json() : { presets: [] }))
      .then((data) => setPresets(data.presets))
      .catch(() => undefined);
    return () => {
      controller.abort();
      abort.current?.abort();
    };
  }, []);
  useEffect(() => {
    version.current++;
    abort.current?.abort();
    setPreview(null);
    setError("");
    setLoading(false);
  }, [value]);

  function update(key: keyof VenueRequest, text: string) {
    if (value) onChange({ ...value, [key]: text });
  }
  async function loadGuidance() {
    if (!value || !value.name.trim() || !value.website.trim()) {
      setError("Enter the venue name and its official website.");
      return;
    }
    abort.current?.abort();
    const controller = new AbortController();
    abort.current = controller;
    const current = ++version.current;
    setLoading(true);
    setError("");
    setPreview(null);
    try {
      const response = await fetch("/api/venue", {
        method: "POST",
        signal: controller.signal,
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(value),
      });
      const body = await response.json();
      if (!response.ok)
        throw new Error(
          typeof body.detail === "string"
            ? body.detail
            : "The venue guidance could not be read. Check the name and website.",
        );
      if (current === version.current) setPreview(body);
    } catch (error) {
      if (!controller.signal.aborted && current === version.current)
        setError(
          error instanceof Error
            ? error.message
            : "The website could not be read.",
        );
    } finally {
      if (current === version.current) setLoading(false);
    }
  }
  const presetIndex = value
    ? presets.findIndex(
        (p) => p.name === value.name && p.website === value.website,
      )
    : -1;
  const choice = !value
    ? "general"
    : presetIndex >= 0
      ? String(presetIndex)
      : "custom";

  return (
    <section
      className="venue-settings panel"
      aria-labelledby="venue-settings-title"
    >
      <div className="venue-settings-top">
        <div>
          <span className="eyebrow">
            <Globe2 size={14} /> A REVIEW WITH A DESTINATION
          </span>
          <h2 id="venue-settings-title">Where will this paper belong?</h2>
        </div>
        <div className="venue-destination">
          <label htmlFor="review-destination">Target venue</label>
          <div className="select-wrap">
            <select
              id="review-destination"
              value={choice}
              disabled={disabled}
              onChange={(event) => {
                const selection = event.target.value;
                onChange(
                  selection === "general"
                    ? null
                    : selection === "custom"
                      ? { name: "", website: "", track: "" }
                      : { ...presets[Number(selection)] },
                );
              }}
            >
              <option value="general">General research review</option>
              {presets.map((preset, i) => (
                <option value={String(i)} key={preset.website}>
                  {preset.name}
                </option>
              ))}
              <option value="custom">Custom conference or journal</option>
            </select>
            <ChevronDown size={14} />
          </div>
        </div>
      </div>
      {value ? (
        <>
          <fieldset className="venue-fields" disabled={disabled}>
            <legend className="screen-reader-only">Venue details</legend>
            <div>
              <label htmlFor="venue-name">Venue name & edition</label>
              <input
                id="venue-name"
                value={value.name}
                maxLength={160}
                placeholder="e.g. NeurIPS 2026"
                onChange={(e) => update("name", e.target.value)}
              />
            </div>
            <div className="venue-website-field">
              <label htmlFor="venue-website">
                Official website or review guidelines
              </label>
              <input
                id="venue-website"
                type="url"
                value={value.website}
                maxLength={2000}
                placeholder="https://venue.org/reviewer-guidelines"
                onChange={(e) => update("website", e.target.value)}
              />
            </div>
            <div>
              <label htmlFor="venue-track">
                Track / category <span>(optional)</span>
              </label>
              <input
                id="venue-track"
                value={value.track}
                maxLength={160}
                placeholder="e.g. Main track"
                onChange={(e) => update("track", e.target.value)}
              />
            </div>
          </fieldset>
          <div className="venue-settings-actions">
            <p>
              We’ll read the venue’s scope and review criteria before scoring
              your PDF.
            </p>
            <div>
              <button
                className="button secondary"
                disabled={disabled || loading}
                onClick={() => void loadGuidance()}
              >
                {loading ? (
                  <LoaderCircle className="spin" size={14} />
                ) : (
                  <RefreshCw size={14} />
                )}
                {loading ? "Reading guidance…" : "Preview venue guidance"}
              </button>
              {onApply && (
                <button
                  className="button primary"
                  disabled={disabled || loading}
                  onClick={onApply}
                >
                  Review for this venue <ArrowRight size={14} />
                </button>
              )}
            </div>
          </div>
          {error && (
            <p className="venue-error" role="alert">
              {error}
            </p>
          )}
          {preview && <VenueSources venue={preview} preview />}
        </>
      ) : (
        <div className="venue-settings-actions">
          <p>
            Choose a conference or journal to ground the review in its published
            guidance.
          </p>
          {onApply && (
            <button
              className="button secondary"
              disabled={disabled}
              onClick={onApply}
            >
              Run a general review <ArrowRight size={14} />
            </button>
          )}
        </div>
      )}
    </section>
  );
}

import { useCallback, useEffect, useRef, useState } from "react";
import type { ChangeEvent, DragEvent } from "react";
import {
  ArrowDownToLine,
  ArrowRight,
  ArrowUpRight,
  Asterisk,
  BookOpen,
  Check,
  CheckCheck,
  ChevronDown,
  ChevronRight,
  CircleHelp,
  Clock3,
  FileCheck2,
  FileText,
  History,
  Info,
  LayoutDashboard,
  LoaderCircle,
  Menu,
  Plus,
  RotateCcw,
  ScanText,
  ShieldCheck,
  SlidersHorizontal,
  Sparkles,
  Target,
  Upload,
  X,
  AlertCircle,
  BarChart3,
  Compass,
} from "lucide-react";
import { downloadBlob, exportLatex, streamReview } from "./api";
import VenueSettings, { VenueSources } from "./VenueSettings";
import type {
  Dimension,
  Profile,
  Report,
  ReviewState,
  Rubric,
  Section,
  SectionResult,
  StreamEvent,
  VenueRequest,
} from "./types";

const initialState: ReviewState = {
  status: "idle",
  results: [],
  active: [],
  message: "",
};
const dimensionIcons = [BookOpen, Target, BarChart3, CheckCheck, Compass];
const profileNames = {
  research: "Research paper",
  survey: "Review / survey",
  theory: "Theory / position",
};
const scoreColor = (score: number) =>
  score >= 70 ? "green" : score >= 55 ? "amber" : "coral";
const humanRole = (role: string) => role.replaceAll("_", " ");

function ScoreRing({
  value,
  small = false,
}: {
  value: number | null;
  small?: boolean;
}) {
  const circumference = 2 * Math.PI * 65;
  return (
    <div className={`score-ring ${small ? "small" : ""}`}>
      <svg viewBox="0 0 160 160" aria-hidden="true">
        <circle className="ring-track" cx="80" cy="80" r="65" />
        {value !== null && (
          <circle
            className={`ring-fill ${scoreColor(value)}`}
            cx="80"
            cy="80"
            r="65"
            strokeDasharray={circumference}
            strokeDashoffset={circumference * (1 - value / 100)}
          />
        )}
      </svg>
      <div className="ring-value">
        <strong>{value === null ? "—" : value.toFixed(1)}</strong>
        <span>OUT OF 100</span>
      </div>
    </div>
  );
}

function PaperArt() {
  return (
    <div className="paper-art" aria-hidden="true">
      <div className="orbit orbit-one" />
      <div className="orbit orbit-two" />
      <span className="art-dot dot-one" />
      <span className="art-dot dot-two" />
      <div className="art-paper paper-back" />
      <div className="art-paper paper-front">
        <div className="paper-top">
          <Asterisk size={19} />
          <span>THE NEXT GOOD IDEA</span>
        </div>
        <div className="art-title">
          A little more
          <br />
          <i>perspective.</i>
        </div>
        <div className="art-lines">
          <i />
          <i />
          <i />
        </div>
        <div className="art-chart">
          <span />
          <span />
          <span />
          <span />
          <span />
          <span />
        </div>
        <div className="art-paper-footer">
          <span>RESEARCH, CONSIDERED.</span>
          <ArrowUpRight size={16} />
        </div>
      </div>
      <div className="art-label label-rigor">
        <span />
        <span>Rigor, examined.</span>
        <Check size={12} />
      </div>
      <div className="art-label label-clarity">
        <Sparkles size={13} />
        <span>Clarity, revealed.</span>
      </div>
    </div>
  );
}

function DimensionDetail({ dimension }: { dimension: Dimension }) {
  const [expanded, setExpanded] = useState(false);
  return (
    <div className="dimension-detail">
      <button
        className="dimension-toggle"
        onClick={() => setExpanded(!expanded)}
        aria-expanded={expanded}
      >
        <span>
          {dimension.label}
          <span className="dimension-weight">
            {Math.round(dimension.weight * 100)}% weight
          </span>
        </span>
        <span className="dimension-numbers">
          <b>{dimension.score.toFixed(1)}</b>
          <ChevronDown size={14} className={expanded ? "rotated" : ""} />
        </span>
      </button>
      <div className="mini-track">
        <div
          className={scoreColor(dimension.score)}
          style={{ width: `${dimension.score}%` }}
        />
      </div>
      <p>{dimension.finding}</p>
      {expanded && (
        <div className="probability-panel">
          <span className="micro-label">
            MODEL DISTRIBUTION · {Math.round(dimension.confidence * 100)}%
            CONFIDENCE
          </span>
          <div className="probabilities">
            {Object.entries(dimension.probabilities).map(
              ([level, probability]) => (
                <div key={level}>
                  <span>{Math.round(probability * 100)}%</span>
                  <div className="probability-track">
                    <i
                      style={{ height: `${Math.max(2, probability * 100)}%` }}
                    />
                  </div>
                  <small>Level {level}</small>
                </div>
              ),
            )}
          </div>
          {dimension.score < 75 && (
            <p>
              <b>Revision prompt:</b> {dimension.suggestion}
            </p>
          )}
        </div>
      )}
    </div>
  );
}

function SectionDetail({
  section,
  result,
  active,
}: {
  section: Section;
  result?: SectionResult;
  active: boolean;
}) {
  return (
    <section
      className="section-detail panel"
      aria-label="Selected section review"
    >
      <div className="detail-heading">
        <div>
          <span className="eyebrow">A CLOSER LOOK</span>
          <h3>{section.title}</h3>
        </div>
        {result ? (
          <span className={`score-pill ${scoreColor(result.score)}`}>
            {result.score.toFixed(1)}
            <small>/100</small>
          </span>
        ) : (
          <span className="pending-badge">{active ? "Reading" : "Queued"}</span>
        )}
      </div>
      <div className="detail-meta">
        <span>
          Pages {section.page_start}
          {section.page_end !== section.page_start
            ? `–${section.page_end}`
            : ""}
        </span>
        <span>{section.word_count.toLocaleString()} words</span>
        {result && (
          <span>{Math.round(result.confidence * 100)}% confidence</span>
        )}
      </div>
      {result ? (
        <>
          <div className="dimension-details">
            {result.dimensions.map((d) => (
              <DimensionDetail key={d.key} dimension={d} />
            ))}
          </div>
          <details className="source-details">
            <summary>
              <ScanText size={15} /> Source excerpt <ChevronDown size={14} />
            </summary>
            <blockquote>
              {result.excerpt}
              {section.text.length > result.excerpt.length ? "…" : ""}
            </blockquote>
            <p>
              Opening excerpt for context; this is not a verified rationale for
              the scores.
            </p>
          </details>
          <p className="detail-footnote">
            Rubric-derived feedback · {result.chunk_count}{" "}
            {result.chunk_count === 1 ? "passage" : "passages"} reviewed
          </p>
        </>
      ) : (
        <div className="section-waiting">
          {active ? (
            <LoaderCircle className="spin" size={26} />
          ) : (
            <Clock3 size={26} />
          )}
          <h4>
            {active
              ? "Reading between the lines."
              : "A thoughtful read takes a moment."}
          </h4>
          <p>
            {active
              ? "Jev is evaluating this section against the review criteria."
              : "This section will be evaluated shortly. Results appear as they arrive."}
          </p>
        </div>
      )}
    </section>
  );
}

export default function App() {
  const [view, setView] = useState<"workspace" | "history" | "rubric">(
    "workspace",
  );
  const [tab, setTab] = useState<"overview" | "manuscript">("overview");
  const [state, setState] = useState<ReviewState>(initialState);
  const [history, setHistory] = useState<Report[]>([]);
  const [profile, setProfile] = useState<Profile>("research");
  const [venue, setVenue] = useState<VenueRequest | null>({
    name: "NeurIPS 2026",
    website: "https://neurips.cc/Conferences/2026/ReviewerGuidelines",
    track: "General",
  });
  const [selected, setSelected] = useState("");
  const [health, setHealth] = useState<{
    configured: boolean;
    model: string;
  } | null>(null);
  const [healthError, setHealthError] = useState(false);
  const [rubric, setRubric] = useState<Rubric | null>(null);
  const [rubricError, setRubricError] = useState(false);
  const [dragging, setDragging] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);
  const [isMobile, setIsMobile] = useState(
    () => window.matchMedia("(max-width: 760px)").matches,
  );
  const [helpOpen, setHelpOpen] = useState(false);
  const helpDialog = useRef<HTMLElement>(null);
  const [exporting, setExporting] = useState(false);
  const [notice, setNotice] = useState("");
  const input = useRef<HTMLInputElement>(null);
  const abort = useRef<AbortController | null>(null);
  const generation = useRef(0);
  const lastFile = useRef<File | null>(null);
  const files = useRef(new Map<string, File>());
  const dragDepth = useRef(0);
  const busy = state.status === "uploading" || state.status === "reviewing";
  const grounded = state.paper ? Boolean(state.venue) : Boolean(venue);
  const activeDimensions = grounded
    ? rubric?.venue_dimensions
    : rubric?.dimensions;

  useEffect(() => {
    let cancelled = false;
    fetch("/api/health")
      .then((r) => {
        if (!r.ok) throw new Error();
        return r.json();
      })
      .then((data) => {
        if (!cancelled) setHealth(data);
      })
      .catch(() => {
        if (!cancelled) setHealthError(true);
      });
    fetch("/api/rubric")
      .then((r) => {
        if (!r.ok) throw new Error();
        return r.json();
      })
      .then((data) => {
        if (!cancelled) setRubric(data);
      })
      .catch(() => {
        if (!cancelled) setRubricError(true);
      });
    return () => {
      cancelled = true;
    };
  }, []);
  useEffect(() => () => abort.current?.abort(), []);
  useEffect(() => {
    const media = window.matchMedia("(max-width: 760px)");
    const changed = () => setIsMobile(media.matches);
    media.addEventListener("change", changed);
    return () => media.removeEventListener("change", changed);
  }, []);
  useEffect(() => {
    if (!helpOpen) return;
    const previous = document.activeElement as HTMLElement | null;
    const dialog = helpDialog.current;
    const trapFocus = (event: KeyboardEvent) => {
      if (event.key !== "Tab" || !dialog) return;
      const items = Array.from(
        dialog.querySelectorAll<HTMLElement>(
          'button, a[href], select, [tabindex="0"]',
        ),
      );
      const first = items[0];
      const last = items[items.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last?.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first?.focus();
      }
    };
    dialog?.addEventListener("keydown", trapFocus);
    return () => {
      dialog?.removeEventListener("keydown", trapFocus);
      previous?.focus();
    };
  }, [helpOpen]);
  useEffect(() => {
    if (!notice) return;
    const id = setTimeout(() => setNotice(""), 6000);
    return () => clearTimeout(id);
  }, [notice]);
  useEffect(() => {
    const handler = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setHelpOpen(false);
        setMenuOpen(false);
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, []);

  const startReview = useCallback(
    async (file: File, nextProfile: Profile = profile) => {
      if (!file.name.toLowerCase().endsWith(".pdf")) {
        setNotice("Please choose a PDF file.");
        return;
      }
      if (file.size > 20 * 1024 * 1024) {
        setNotice("This PDF is too large. The limit is 20 MB.");
        return;
      }
      if (!file.size) {
        setNotice("This file is empty. Please choose another PDF.");
        return;
      }
      if (venue && (venue.name.trim().length < 2 || !venue.website.trim())) {
        setNotice(
          "Enter both the target venue name and its official website before uploading.",
        );
        return;
      }
      abort.current?.abort();
      const controller = new AbortController();
      abort.current = controller;
      const run = ++generation.current;
      lastFile.current = file;
      setProfile(nextProfile);
      setView("workspace");
      setTab("overview");
      setSelected("");
      setNotice("");
      setState({
        ...initialState,
        status: "uploading",
        filename: file.name,
        message: "Opening your manuscript…",
      });
      const onEvent = (event: StreamEvent) => {
        if (run !== generation.current) return;
        if (event.type === "paper") {
          setState((prev) => ({
            ...prev,
            paper: event.paper,
            venue: event.venue ?? null,
            status: "reviewing",
            message: "Reviewing each section with Jev…",
          }));
          setSelected(event.paper.sections[0]?.id ?? "");
        } else if (event.type === "venue") {
          setState((prev) => ({ ...prev, venue: event.venue }));
        } else if (event.type === "section_start") {
          setState((prev) => ({
            ...prev,
            active: [...prev.active, event.section_id],
          }));
        } else if (event.type === "section_result") {
          setState((prev) => ({
            ...prev,
            results: [
              ...prev.results.filter(
                (r) => r.section_id !== event.result.section_id,
              ),
              event.result,
            ],
            summary: event.summary,
            active: prev.active.filter((id) => id !== event.result.section_id),
          }));
        } else if (event.type === "complete") {
          setState((prev) => ({
            ...prev,
            status: "complete",
            results: event.report.results,
            summary: event.report.summary,
            report: event.report,
            venue: event.report.venue ?? null,
            active: [],
            message: "Your review is ready.",
          }));
          setHistory((prev) =>
            [
              event.report,
              ...prev.filter((r) => r.review_id !== event.report.review_id),
            ].slice(0, 20),
          );
          files.current.set(event.report.review_id, file);
          if (files.current.size > 20)
            files.current.delete(files.current.keys().next().value!);
        } else if (event.type === "error") {
          setState((prev) => ({
            ...prev,
            status: "error",
            error: event.message,
            active: [],
          }));
        } else if (event.type === "status" || event.type === "heartbeat") {
          setState((prev) => ({ ...prev, message: event.message }));
        }
      };
      try {
        await streamReview(
          file,
          nextProfile,
          controller.signal,
          onEvent,
          venue,
        );
      } catch (error) {
        if (controller.signal.aborted || run !== generation.current) return;
        setState((prev) => ({
          ...prev,
          status: "error",
          active: [],
          error:
            error instanceof Error
              ? error.message
              : "Something went wrong. Please try again.",
        }));
      }
    },
    [profile, venue],
  );

  function stopReview() {
    abort.current?.abort();
    generation.current++;
    setState((prev) => ({
      ...prev,
      status: "cancelled",
      active: [],
      message: "Review stopped. Re-upload to start again.",
    }));
  }
  function openReport(report: Report) {
    abort.current?.abort();
    generation.current++;
    setState({
      status: "complete",
      paper: report.paper,
      results: report.results,
      summary: report.summary,
      report,
      venue: report.venue ?? null,
      active: [],
      message: "Your review is ready.",
    });
    lastFile.current = files.current.get(report.review_id) ?? null;
    setSelected(report.paper.sections[0]?.id ?? "");
    setProfile(report.profile);
    setVenue(
      report.venue
        ? {
            name: report.venue.name,
            website: report.venue.website,
            track: report.venue.track,
          }
        : null,
    );
    setView("workspace");
    setTab("overview");
  }
  function newReview() {
    abort.current?.abort();
    generation.current++;
    setState(initialState);
    setView("workspace");
    setMenuOpen(false);
    lastFile.current = null;
  }
  function navigate(next: typeof view) {
    setView(next);
    setMenuOpen(false);
  }
  function uploadChanged(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (file) void startReview(file);
  }
  function drop(event: DragEvent) {
    event.preventDefault();
    dragDepth.current = 0;
    setDragging(false);
    const file = event.dataTransfer.files[0];
    if (file) void startReview(file);
  }
  async function trySample() {
    try {
      const response = await fetch("/api/sample.pdf");
      if (!response.ok)
        throw new Error(
          "The sample could not be loaded. Check that the server is running.",
        );
      await startReview(
        new File([await response.blob()], "folio-example.pdf", {
          type: "application/pdf",
        }),
      );
    } catch (error) {
      setNotice(
        error instanceof Error ? error.message : "Could not load the sample.",
      );
    }
  }
  async function downloadLatex() {
    if (!state.report) return;
    setExporting(true);
    try {
      await exportLatex(state.report);
      setNotice("Your LaTeX review has been downloaded.");
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "Export failed.");
    } finally {
      setExporting(false);
    }
  }

  const currentSection =
    state.paper?.sections.find((s) => s.id === selected) ??
    state.paper?.sections[0];
  const progress = state.paper
    ? (state.results.length / state.paper.sections.length) * 100
    : 0;
  const connection = healthError
    ? "Server unavailable"
    : !health
      ? "Connecting to Jev"
      : health.configured
        ? "Jev is configured"
        : "API key needed";

  return (
    <div
      className="app-shell"
      onDragEnter={(e) => {
        e.preventDefault();
        if (e.dataTransfer.types.includes("Files")) {
          dragDepth.current++;
          setDragging(true);
        }
      }}
      onDragLeave={(e) => {
        e.preventDefault();
        dragDepth.current--;
        if (dragDepth.current <= 0) setDragging(false);
      }}
      onDragOver={(e) => e.preventDefault()}
      onDrop={drop}
    >
      <input
        type="file"
        ref={input}
        accept="application/pdf,.pdf"
        onChange={uploadChanged}
        className="file-input"
        aria-label="Upload a research paper PDF"
        data-testid="pdf-input"
      />
      {dragging && (
        <div className="drop-overlay">
          <Upload size={42} />
          <h2>Make room for a new perspective.</h2>
          <p>Drop your PDF to begin a fresh review.</p>
        </div>
      )}
      {menuOpen && (
        <button
          className="sidebar-scrim"
          aria-label="Close navigation"
          onClick={() => setMenuOpen(false)}
        />
      )}
      <aside
        className={`sidebar ${menuOpen ? "open" : ""}`}
        inert={isMobile && !menuOpen}
      >
        <button className="brand" onClick={newReview} aria-label="Folio home">
          <Asterisk strokeWidth={2.5} />
          <span>
            folio<span className="brand-period">.</span>
          </span>
        </button>
        <div className="workspace-label">
          <span className="workspace-avatar">R</span>
          <div>
            Research workspace<small>YOUR PERSONAL READING ROOM</small>
          </div>
        </div>
        <button className="new-review-button" onClick={newReview}>
          <Plus size={17} /> New review <span>↗</span>
        </button>
        <span className="nav-caption">WORKSPACE</span>
        <nav aria-label="Main navigation">
          <button
            className={view === "workspace" ? "nav-item active" : "nav-item"}
            onClick={() => navigate("workspace")}
          >
            <LayoutDashboard size={17} /> Review workspace{" "}
            {busy && <span className="live-dot" />}
          </button>
          <button
            className={view === "history" ? "nav-item active" : "nav-item"}
            onClick={() => navigate("history")}
          >
            <History size={17} /> Review history{" "}
            <span className="nav-count">{history.length}</span>
          </button>
          <button
            className={view === "rubric" ? "nav-item active" : "nav-item"}
            onClick={() => navigate("rubric")}
          >
            <SlidersHorizontal size={17} /> Scoring rubric
          </button>
        </nav>
        <div className="sidebar-note">
          <span className="tiny-spark">✳</span>
          <p>
            Great ideas deserve
            <br />a thoughtful second look.
          </p>
          <span>MAKE EVERY DRAFT COUNT.</span>
        </div>
        <div className="sidebar-bottom">
          <button className="help-button" onClick={() => setHelpOpen(true)}>
            <CircleHelp size={17} /> A few things to know{" "}
            <ArrowUpRight size={14} />
          </button>
          <div className="connection">
            <span
              className={`status-dot ${health?.configured ? "" : "muted-dot"}`}
            />
            <span>
              {connection}
              <small>{health?.model ?? "Typesafe AI"}</small>
            </span>
            <ShieldCheck size={17} />
          </div>
        </div>
      </aside>
      <div className="main-shell">
        <header className="topbar">
          <div className="breadcrumbs">
            <button
              className="mobile-menu"
              onClick={() => setMenuOpen(true)}
              aria-label="Open navigation"
            >
              <Menu size={20} />
            </button>
            <span>Workspace</span>
            <ChevronRight size={13} />
            <strong>
              {view === "history"
                ? "Review history"
                : view === "rubric"
                  ? "Scoring rubric"
                  : state.paper
                    ? "Paper review"
                    : "New review"}
            </strong>
          </div>
          <div className="topbar-right">
            <span className="powered">
              <Asterisk size={16} /> Powered by <b>Jev</b>
            </span>
            <div className="avatar" title="Research workspace">
              R
            </div>
          </div>
        </header>
        <main id="main-content">
          {view === "workspace" && (
            <>
              {!state.paper && !busy && state.status !== "error" && (
                <>
                  <div className="page-heading welcome-heading">
                    <div>
                      <span className="eyebrow">
                        <span /> A FRESH PERSPECTIVE ON YOUR RESEARCH
                      </span>
                      <h1>
                        Good research deserves
                        <br />a <em>closer read.</em>
                      </h1>
                      <p>
                        From first draft to final submission. Get a thoughtful,
                        section-by-section
                        <br className="desktop-break" /> review of your paper,
                        with clear scores and a path forward.
                      </p>
                    </div>
                    <div className="heading-note">
                      <span className="handwritten">
                        For the next
                        <br />
                        great idea.
                      </span>
                      <svg viewBox="0 0 75 35" aria-hidden="true">
                        <path d="M68 2C46 26 23 29 7 15M7 15l3 13M7 15l16 1" />
                      </svg>
                    </div>
                  </div>
                  <VenueSettings value={venue} onChange={setVenue} />
                  <div className="welcome-grid">
                    <section className="upload-card panel">
                      <div className="upload-card-top">
                        <span className="eyebrow">START A NEW REVIEW</span>
                        <span className="format-tag">PDF</span>
                      </div>
                      <div className="upload-area">
                        <div className="upload-icon">
                          <FileText size={31} strokeWidth={1.3} />
                          <span>
                            <Plus size={12} />
                          </span>
                        </div>
                        <h2>Your next draft starts here.</h2>
                        <p>
                          Drop your paper here, or choose a file to get started.
                        </p>
                        <button
                          className="button primary upload-main"
                          onClick={() => input.current?.click()}
                        >
                          <Upload size={16} /> Upload a paper{" "}
                          <ArrowUpRight size={16} />
                        </button>
                        <span className="upload-hint">
                          PDF up to 20 MB · Up to 120 pages
                        </span>
                      </div>
                      <div className="upload-options">
                        <label htmlFor="paper-profile">
                          <SlidersHorizontal size={15} /> Review as
                        </label>
                        <div className="select-wrap">
                          <select
                            id="paper-profile"
                            value={profile}
                            onChange={(e) =>
                              setProfile(e.target.value as Profile)
                            }
                          >
                            {Object.entries(profileNames).map(([key, name]) => (
                              <option value={key} key={key}>
                                {name}
                              </option>
                            ))}
                          </select>
                          <ChevronDown size={14} />
                        </div>
                      </div>
                      <div className="sample-row">
                        <span>Just looking around?</span>
                        <button onClick={() => void trySample()}>
                          Try an example paper <ArrowRight size={14} />
                        </button>
                      </div>
                    </section>
                    <section className="perspective-card">
                      <div className="perspective-copy">
                        <span className="eyebrow">
                          MORE THAN A SINGLE SCORE
                        </span>
                        <h2>
                          See the details.
                          <br />
                          <em>Find the bigger picture.</em>
                        </h2>
                      </div>
                      <PaperArt />
                      <div className="perspective-bottom">
                        <span className="status-dot" />
                        <span>Every section. Every perspective.</span>
                      </div>
                    </section>
                  </div>
                  <section className="how-it-works">
                    <div className="section-heading">
                      <h2>A thoughtful review, in three steps.</h2>
                      <span>LESS GUESSWORK. MORE PROGRESS.</span>
                    </div>
                    <div className="steps-grid">
                      {[
                        {
                          icon: ScanText,
                          title: "The whole paper, unpacked.",
                          body: "Your manuscript is organized into sections, with the original text always in view.",
                        },
                        {
                          icon: BarChart3,
                          title: "Feedback as it happens.",
                          body: "Watch scores arrive for clarity, rigor, evidence, and completeness.",
                        },
                        {
                          icon: FileCheck2,
                          title: "A clearer way forward.",
                          body: "Get an overall assessment and take your findings with you as a LaTeX report.",
                        },
                      ].map((step, i) => (
                        <div className="step" key={step.title}>
                          <div className="step-top">
                            <step.icon size={21} strokeWidth={1.4} />
                            <span>0{i + 1}</span>
                          </div>
                          <h3>{step.title}</h3>
                          <p>{step.body}</p>
                        </div>
                      ))}
                    </div>
                  </section>
                  <p className="privacy-note">
                    <ShieldCheck size={14} /> Extracted text is sent to Jev.
                    Your reviews stay in this browser session.
                  </p>
                </>
              )}
              {!state.paper && busy && (
                <div className="opening-state panel">
                  <div className="opening-art">
                    <ScanText size={44} strokeWidth={1} />
                    <span />
                  </div>
                  <span className="eyebrow">
                    A NEW PERSPECTIVE IS ON ITS WAY
                  </span>
                  <h1>Opening your manuscript.</h1>
                  <p>{state.filename}</p>
                  <div className="opening-status">
                    <LoaderCircle className="spin" size={16} /> {state.message}
                  </div>
                  <button className="button secondary" onClick={stopReview}>
                    Cancel review
                  </button>
                </div>
              )}
              {state.status === "error" && (
                <div className="error-banner" role="alert">
                  <AlertCircle size={22} />
                  <div>
                    <strong>This review needs another try.</strong>
                    <p>{state.error}</p>
                    {state.paper && (
                      <p>
                        Partial scores below are provisional. No final decision
                        has been issued.
                      </p>
                    )}
                  </div>
                  <button
                    className="button secondary"
                    onClick={() =>
                      lastFile.current
                        ? void startReview(lastFile.current)
                        : input.current?.click()
                    }
                  >
                    <RotateCcw size={14} /> Try again
                  </button>
                </div>
              )}
              {state.status === "error" && !state.paper && (
                <VenueSettings
                  value={venue}
                  onChange={setVenue}
                  onApply={
                    lastFile.current
                      ? () => void startReview(lastFile.current!)
                      : undefined
                  }
                />
              )}
              {state.status === "cancelled" && (
                <div className="info-banner">
                  <Info size={18} />
                  <p>Review stopped. Any scores shown are provisional.</p>
                  <button onClick={() => input.current?.click()}>
                    Upload a paper <ArrowRight size={14} />
                  </button>
                </div>
              )}
              {state.paper && (
                <>
                  <div className="review-heading">
                    <div>
                      <span className="eyebrow">
                        <span className={busy ? "live-dot" : "status-dot"} />{" "}
                        {busy
                          ? "A CLOSER READ, IN PROGRESS"
                          : state.status === "complete"
                            ? "YOUR REVIEW IS READY"
                            : "PARTIAL REVIEW"}
                      </span>
                      <h1>
                        A clearer <em>perspective.</em>
                      </h1>
                    </div>
                    <div className="review-actions">
                      <button
                        className="button secondary"
                        onClick={() => input.current?.click()}
                      >
                        <Upload size={15} />{" "}
                        {busy ? "Replace PDF" : "Upload new PDF"}
                      </button>
                      {state.report && (
                        <button
                          className="button primary"
                          onClick={() => void downloadLatex()}
                          disabled={exporting}
                        >
                          {exporting ? (
                            <LoaderCircle size={15} className="spin" />
                          ) : (
                            <ArrowDownToLine size={15} />
                          )}{" "}
                          Export LaTeX
                        </button>
                      )}
                    </div>
                  </div>
                  <section className="document-banner">
                    <div className="document-icon">
                      <FileText size={23} strokeWidth={1.4} />
                    </div>
                    <div className="document-title">
                      <h2>{state.paper.title}</h2>
                      <p>
                        <span>{state.paper.filename}</span>
                        <span>{state.paper.pages} pages</span>
                        <span>
                          {state.paper.word_count.toLocaleString()} words
                        </span>
                        <span>{profileNames[profile]}</span>
                      </p>
                    </div>
                    {state.report && (
                      <button
                        className="icon-button"
                        title="Run a fresh review"
                        aria-label="Review this PDF again"
                        onClick={() =>
                          lastFile.current && void startReview(lastFile.current)
                        }
                        disabled={!lastFile.current}
                      >
                        <RotateCcw size={17} />
                      </button>
                    )}
                  </section>
                  {state.venue && <VenueSources venue={state.venue} />}
                  <details className="change-venue">
                    <summary>
                      <Compass size={14} />{" "}
                      {state.venue
                        ? "Change target venue"
                        : "Add a target venue"}{" "}
                      <ChevronDown size={13} />
                    </summary>
                    <VenueSettings
                      value={venue}
                      onChange={setVenue}
                      disabled={busy}
                      onApply={
                        lastFile.current
                          ? () => void startReview(lastFile.current!)
                          : undefined
                      }
                    />
                    <p>
                      Changes take effect when you start a fresh review or
                      upload another PDF. Each report retains the guidance used
                      for that review.
                    </p>
                  </details>
                  {state.paper.warnings.length > 0 && (
                    <div className="extraction-notes">
                      <Info size={16} />
                      <div>
                        {state.paper.warnings.map((w) => (
                          <p key={w}>{w}</p>
                        ))}
                      </div>
                    </div>
                  )}
                  <div className="review-summary-grid">
                    <section className="overall-card panel">
                      <div className="card-topline">
                        <span className="eyebrow">
                          {state.summary?.complete
                            ? "OVERALL ASSESSMENT"
                            : "PROVISIONAL ASSESSMENT"}
                        </span>
                        <span className={`live-badge ${busy ? "is-live" : ""}`}>
                          {busy ? (
                            <>
                              <span className="live-dot" /> LIVE
                            </>
                          ) : state.summary?.complete ? (
                            <>
                              <Check size={12} /> COMPLETE
                            </>
                          ) : (
                            "PARTIAL"
                          )}
                        </span>
                      </div>
                      <div className="overall-content">
                        <ScoreRing value={state.summary?.score ?? null} />
                        <div className="overall-copy">
                          <span className="micro-label">
                            {state.summary?.complete
                              ? "RECOMMENDATION"
                              : "CURRENT STATUS"}
                          </span>
                          <h2>
                            {state.summary?.complete
                              ? state.summary.decision
                              : busy
                                ? "Reading with care."
                                : "Review incomplete."}
                          </h2>
                          <p>
                            {state.summary?.complete
                              ? "An assessment of your manuscript, grounded in an explicit review rubric."
                              : "The score updates with each reviewed section. The final recommendation appears when all sections are complete."}
                          </p>
                          {state.summary?.confidence != null && (
                            <span className="confidence-label">
                              <span className="status-dot" />{" "}
                              {Math.round(state.summary.confidence * 100)}% mean
                              model confidence{" "}
                              <button
                                className="inline-help"
                                onClick={() => setHelpOpen(true)}
                                aria-label="About model confidence"
                              >
                                <Info size={12} />
                              </button>
                            </span>
                          )}
                        </div>
                      </div>
                    </section>
                    <section className="progress-card panel">
                      <div className="card-topline">
                        <span className="eyebrow">THE READING ROOM</span>
                        <BookOpen size={17} />
                      </div>
                      <div className="progress-numbers">
                        <strong>
                          {state.results.length}
                          <span> / {state.paper.sections.length}</span>
                        </strong>
                        <span>sections reviewed</span>
                      </div>
                      <div
                        className="progress-track"
                        role="progressbar"
                        aria-label="Review progress"
                        aria-valuenow={state.results.length}
                        aria-valuemax={state.paper.sections.length}
                        aria-valuemin={0}
                      >
                        <span style={{ width: `${progress}%` }} />
                      </div>
                      <div className="progress-status">
                        {busy ? (
                          <LoaderCircle size={14} className="spin" />
                        ) : state.report ? (
                          <CheckCheck size={15} />
                        ) : (
                          <Info size={14} />
                        )}
                        <span>
                          {busy
                            ? "Feedback is arriving in real time"
                            : state.report
                              ? `Completed in ${(state.report.elapsed_ms / 1000).toFixed(1)} seconds`
                              : "No final recommendation yet"}
                        </span>
                      </div>
                      {busy ? (
                        <button className="text-button" onClick={stopReview}>
                          Stop review <X size={12} />
                        </button>
                      ) : (
                        <button
                          className="text-button"
                          onClick={() => navigate("rubric")}
                        >
                          See how we score <ArrowUpRight size={13} />
                        </button>
                      )}
                    </section>
                  </div>
                  <div
                    className={`dimension-cards ${state.venue ? "has-venue" : ""}`}
                  >
                    {Object.entries(
                      activeDimensions ?? {
                        clarity: { label: "Clarity", weight: 0.2 },
                        rigor: { label: "Rigor", weight: 0.35 },
                        support: { label: "Evidence", weight: 0.3 },
                        completeness: { label: "Completeness", weight: 0.15 },
                      },
                    ).map(([key, dimension], i) => {
                      const Icon = dimensionIcons[i];
                      return (
                        <div className="dimension-card" key={key}>
                          <div>
                            <Icon size={16} />
                            <span>{dimension.label}</span>
                            <small>{Math.round(dimension.weight * 100)}%</small>
                          </div>
                          <strong>
                            {state.summary?.dimensions[key]?.toFixed(1) ?? "—"}
                            <span>/100</span>
                          </strong>
                          <div className="mini-track">
                            <span
                              style={{
                                width: `${state.summary?.dimensions[key] ?? 0}%`,
                              }}
                            />
                          </div>
                        </div>
                      );
                    })}
                  </div>
                  <div className="review-tabs">
                    <div role="tablist" aria-label="Review views">
                      <button
                        id="overview-tab"
                        role="tab"
                        aria-selected={tab === "overview"}
                        aria-controls="review-panel"
                        className={tab === "overview" ? "selected" : ""}
                        onClick={() => setTab("overview")}
                      >
                        <LayoutDashboard size={15} /> Section reviews{" "}
                        <span>{state.paper.sections.length}</span>
                      </button>
                      <button
                        id="manuscript-tab"
                        role="tab"
                        aria-selected={tab === "manuscript"}
                        aria-controls="review-panel"
                        className={tab === "manuscript" ? "selected" : ""}
                        onClick={() => setTab("manuscript")}
                      >
                        <FileText size={15} /> Extracted manuscript
                      </button>
                    </div>
                    {state.report && (
                      <button
                        className="text-button json-export"
                        onClick={() =>
                          downloadBlob(
                            new Blob([JSON.stringify(state.report, null, 2)], {
                              type: "application/json",
                            }),
                            "folio-review.json",
                          )
                        }
                      >
                        Download JSON <ArrowDownToLine size={13} />
                      </button>
                    )}
                  </div>
                  <div
                    id="review-panel"
                    role="tabpanel"
                    aria-labelledby={
                      tab === "overview" ? "overview-tab" : "manuscript-tab"
                    }
                  >
                    {tab === "overview" ? (
                      <div className="section-grid">
                        <section className="section-list panel">
                          <div className="list-title">
                            <h3>The paper, section by section.</h3>
                            <p>Select a section to explore its review.</p>
                          </div>
                          {state.paper.sections.map((section, i) => {
                            const result = state.results.find(
                              (r) => r.section_id === section.id,
                            );
                            const active = state.active.includes(section.id);
                            return (
                              <button
                                key={section.id}
                                className={`section-row ${selected === section.id ? "selected" : ""}`}
                                onClick={() => setSelected(section.id)}
                                aria-pressed={selected === section.id}
                              >
                                <span className="section-index">
                                  {String(i + 1).padStart(2, "0")}
                                </span>
                                <span className="section-name">
                                  <strong>{section.title}</strong>
                                  <span>
                                    p. {section.page_start}
                                    {section.page_end !== section.page_start
                                      ? `–${section.page_end}`
                                      : ""}{" "}
                                    <i>·</i> {humanRole(section.role)}
                                    {state.summary &&
                                      ` · ${(state.summary.section_weights[section.id] * 100).toFixed(1)}% weight`}
                                  </span>
                                </span>
                                <span className="row-score">
                                  {result ? (
                                    <>
                                      <span
                                        className={scoreColor(result.score)}
                                      >
                                        {result.score.toFixed(1)}
                                      </span>
                                      <Check size={12} />
                                    </>
                                  ) : active ? (
                                    <LoaderCircle size={17} className="spin" />
                                  ) : (
                                    <span className="pending-dash">—</span>
                                  )}
                                </span>
                                <ChevronRight size={14} />
                              </button>
                            );
                          })}
                          <div className="section-list-footer">
                            <Info size={13} /> Scores assess extracted text;
                            figures need a human read.
                          </div>
                        </section>
                        {currentSection && (
                          <SectionDetail
                            key={currentSection.id}
                            section={currentSection}
                            result={state.results.find(
                              (r) => r.section_id === currentSection.id,
                            )}
                            active={state.active.includes(currentSection.id)}
                          />
                        )}
                      </div>
                    ) : (
                      <section className="manuscript panel">
                        <div className="manuscript-heading">
                          <ScanText size={20} />
                          <p>
                            This is the text used for evaluation. Check the
                            section boundaries and reading order against your
                            original PDF.
                          </p>
                        </div>
                        {state.paper.sections.map((section) => (
                          <article key={section.id}>
                            <span className="micro-label">
                              PAGE {section.page_start}
                              {section.page_end !== section.page_start
                                ? `–${section.page_end}`
                                : ""}
                            </span>
                            <h2>{section.title}</h2>
                            <p>{section.text}</p>
                          </article>
                        ))}
                      </section>
                    )}
                  </div>
                  {state.report && (
                    <div className="findings-grid">
                      <section className="findings-card">
                        <span className="eyebrow">
                          <Sparkles size={15} /> WHAT'S WORKING
                        </span>
                        <h2>Build on your strengths.</h2>
                        {state.summary?.strengths.length ? (
                          <ul>
                            {state.summary.strengths.map((s) => (
                              <li key={s}>{s}</li>
                            ))}
                          </ul>
                        ) : (
                          <p>
                            No criterion reached the strength threshold in this
                            review. Use the section feedback to guide your next
                            draft.
                          </p>
                        )}
                      </section>
                      <section className="findings-card improvements">
                        <span className="eyebrow">
                          <Target size={15} /> THE NEXT DRAFT
                        </span>
                        <h2>Where to focus next.</h2>
                        {state.summary?.improvements.length ? (
                          <ul>
                            {state.summary.improvements.map((s) => (
                              <li key={s}>{s}</li>
                            ))}
                          </ul>
                        ) : (
                          <p>
                            All criteria met the revision threshold. Expert
                            checks of claims, figures, and sources remain
                            valuable.
                          </p>
                        )}
                      </section>
                    </div>
                  )}
                  <div className="review-limitations">
                    <Info size={16} />
                    <div>
                      <strong>
                        A second perspective, with the limits in view.
                      </strong>
                      <p>
                        Scores reflect the extracted text. They do not verify
                        novelty, references, figures, or mathematical
                        correctness. Model confidence is not a probability of
                        scientific validity. Recommendations use an uncalibrated
                        rubric and support expert judgment.
                      </p>
                      {state.report &&
                        state.summary?.notes
                          .filter(
                            (n) =>
                              n.includes("Long sections") ||
                              n.includes("below 45%"),
                          )
                          .map((n) => <p key={n}>{n}</p>)}
                    </div>
                  </div>
                </>
              )}
            </>
          )}
          {view === "history" && (
            <>
              <div className="page-heading">
                <span className="eyebrow">YOUR READING TRAIL</span>
                <h1>
                  Every draft.
                  <br />
                  <em>A little further.</em>
                </h1>
                <p>
                  Revisit completed reviews from this session. Your history
                  clears when you reload.
                </p>
              </div>
              {history.length === 0 ? (
                <div className="empty-state panel">
                  <History size={36} strokeWidth={1.2} />
                  <h2>A fresh page.</h2>
                  <p>Your completed reviews will find a home here.</p>
                  <button className="button primary" onClick={newReview}>
                    Review your first paper <ArrowRight size={15} />
                  </button>
                </div>
              ) : (
                <div className="history-list">
                  {history.map((report, i) => (
                    <button
                      className="history-card panel"
                      key={report.review_id}
                      onClick={() => openReport(report)}
                    >
                      <span className="history-index">
                        {String(history.length - i).padStart(2, "0")}
                      </span>
                      <div>
                        <span className="micro-label">
                          {new Date(report.created_at).toLocaleTimeString([], {
                            hour: "2-digit",
                            minute: "2-digit",
                          })}{" "}
                          · {profileNames[report.profile]}
                          {report.venue
                            ? ` · ${report.venue.name}`
                            : " · General review"}
                        </span>
                        <h2>{report.paper.title}</h2>
                        <p>
                          {report.paper.filename} · {report.results.length}{" "}
                          sections · {report.summary.decision}
                        </p>
                      </div>
                      <ScoreRing value={report.summary.score} small />
                      <ArrowUpRight size={19} />
                    </button>
                  ))}
                </div>
              )}
            </>
          )}
          {view === "rubric" && (
            <>
              <div className="page-heading">
                <span className="eyebrow">NO BLACK BOXES</span>
                <h1>
                  A score with
                  <br />
                  <em>something behind it.</em>
                </h1>
                <p>
                  {grounded ? "Five" : "Four"} criteria. Explicit weights. Every
                  judgment open to inspection.
                </p>
              </div>
              {rubric ? (
                <>
                  <div className="rubric-intro panel">
                    <Asterisk size={25} />
                    <div>
                      <h3>Small judgments, thoughtfully combined.</h3>
                      <p>
                        Jev evaluates {grounded ? "five" : "four"} independent
                        questions for each section. Each uses five descriptive
                        levels, mapped to a 0–100 score. The final score
                        combines these judgments using the weights below.
                      </p>
                    </div>
                    <span className="format-tag">{rubric.version}</span>
                  </div>
                  <div className="rubric-grid">
                    {Object.entries(activeDimensions ?? rubric.dimensions).map(
                      ([key, d], i) => {
                        const Icon = dimensionIcons[i];
                        return (
                          <section className="rubric-card panel" key={key}>
                            <div className="rubric-card-top">
                              <Icon size={22} />
                              <span>
                                {Math.round(d.weight * 100)}
                                <small>%</small>
                              </span>
                            </div>
                            <h2>{d.label}</h2>
                            <p>{d.question}</p>
                            <ol start={0}>
                              {d.criteria.map((criterion, level) => (
                                <li key={criterion}>
                                  <span>{level}</span>
                                  {criterion}
                                </li>
                              ))}
                            </ol>
                          </section>
                        );
                      },
                    )}
                  </div>
                  <div className="rubric-bottom-grid">
                    <section className="panel rubric-method">
                      <h2>The overall picture.</h2>
                      <p>
                        Role weights are normalized across the sections found in
                        your paper. If a role contains several sections, its
                        weight is split by word count. This prevents extra
                        subsections from receiving extra influence.
                      </p>
                      <div className="role-weights">
                        {Object.entries(rubric.role_weights).map(
                          ([role, weight]) => (
                            <div key={role}>
                              <span>{humanRole(role)}</span>
                              <b>{weight}</b>
                            </div>
                          ),
                        )}
                      </div>
                      <p className="muted">
                        These are relative weights, not percentages. Absent
                        roles are omitted; extracted section weights always sum
                        to 100%.
                      </p>
                    </section>
                    <section className="panel rubric-method">
                      <h2>From score to next step.</h2>
                      {rubric.thresholds.map((t, i) => (
                        <div className="threshold" key={t.minimum}>
                          <b>
                            {t.minimum}
                            {i === 0
                              ? "–100"
                              : `–${rubric.thresholds[i - 1].minimum - 0.1}`}
                          </b>
                          <span>{t.label}</span>
                        </div>
                      ))}
                      <div className="rubric-confidence">
                        <Info size={18} />
                        <p>
                          Below {rubric.confidence_floor * 100}% mean
                          confidence, the recommendation becomes “Expert review
                          needed.” Confidence measures model certainty, not
                          paper correctness.
                        </p>
                      </div>
                      <p className="muted">
                        The weights and thresholds are design choices. They have
                        not been calibrated against a dataset of expert reviews.
                      </p>
                    </section>
                  </div>
                </>
              ) : (
                <div className="empty-state panel">
                  {rubricError ? (
                    <>
                      <AlertCircle size={26} />
                      <p>
                        The rubric could not be loaded. Check that the API
                        server is running, then reload the page.
                      </p>
                    </>
                  ) : (
                    <>
                      <LoaderCircle className="spin" />
                      <p>Loading the scoring rubric…</p>
                    </>
                  )}
                </div>
              )}
            </>
          )}
          <footer className="footer">
            <span>
              <Asterisk size={15} /> folio<span className="footer-dot">·</span>A
              little perspective goes a long way.
            </span>
            <a
              href="https://docs.typesafe.ai/introduction"
              target="_blank"
              rel="noreferrer"
            >
              Built with Jev <ArrowUpRight size={12} />
            </a>
          </footer>
        </main>
      </div>
      <div className="screen-reader-only" aria-live="polite" aria-atomic="true">
        {busy
          ? `${state.results.length} of ${state.paper?.sections.length ?? "unknown"} sections reviewed. ${state.message}`
          : state.status === "complete"
            ? `Review complete. Overall score ${state.summary?.score}. ${state.summary?.decision}.`
            : state.message}
      </div>
      {notice && (
        <div className="toast" role="status">
          <Info size={17} />
          <p>{notice}</p>
          <button
            onClick={() => setNotice("")}
            aria-label="Dismiss notification"
          >
            <X size={15} />
          </button>
        </div>
      )}
      {(health?.configured === false || healthError) &&
        view === "workspace" &&
        state.status === "idle" && (
          <div className="setup-notice">
            <AlertCircle size={17} />
            <p>
              {healthError
                ? "Start the API server to connect this workspace to Jev."
                : "Add JEV_API_KEY to your server’s .env file, then restart to enable live reviews."}
            </p>
          </div>
        )}
      {helpOpen && (
        <div className="modal-backdrop" onClick={() => setHelpOpen(false)}>
          <section
            className="help-modal panel"
            ref={helpDialog}
            role="dialog"
            aria-modal="true"
            aria-labelledby="help-title"
            onClick={(e) => e.stopPropagation()}
          >
            <button
              className="modal-close icon-button"
              autoFocus
              onClick={() => setHelpOpen(false)}
              aria-label="Close help"
            >
              <X size={20} />
            </button>
            <span className="eyebrow">A FEW THINGS TO KNOW</span>
            <h2 id="help-title">Perspective, with context.</h2>
            <h3>What gets reviewed?</h3>
            <p>
              Selectable PDF text is sent to TypeSafe’s Jev API. Scans need OCR
              first. Figures, complex equations, and section layouts may not
              extract correctly; inspect the manuscript tab.
            </p>
            <h3>What do the numbers mean?</h3>
            <p>
              Scores reflect a five-level rubric. Confidence describes how
              concentrated Jev’s probabilities are, not the chance that your
              science is correct. Findings are readable rubric templates, not
              generated expert commentary.
            </p>
            <h3>What happens to my paper?</h3>
            <p>
              Folio does not retain manuscripts or reports on the server. Upload
              buffering can use temporary files, which are closed after reading.
              The browser retains up to 20 reviews during this session. Jev
              processes the extracted text under TypeSafe’s own data policies.
            </p>
            <h3>Can I review a revised draft?</h3>
            <p>
              Yes. Upload it again—even with the same filename. Each upload
              cancels any pending review and starts a fresh assessment.
            </p>
            <a
              href="https://docs.typesafe.ai/legal"
              target="_blank"
              rel="noreferrer"
            >
              TypeSafe data policies <ArrowUpRight size={13} />
            </a>
          </section>
        </div>
      )}
    </div>
  );
}

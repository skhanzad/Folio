"""Produce portable LaTeX without executing manuscript content."""

import unicodedata

from .models import ReviewReport


def tex(value: object) -> str:
    value = str(value).translate(
        str.maketrans({"–": "-", "—": "--", "’": "'", "“": '"', "”": '"', "·": ";", "−": "-"})
    )
    # Portable pdflatex output. The JSON export retains exact Unicode text.
    value = unicodedata.normalize("NFKD", value).encode("ascii", "replace").decode()
    escapes = {
        "\\": r"\textbackslash{}",
        "&": r"\&",
        "%": r"\%",
        "$": r"\$",
        "#": r"\#",
        "_": r"\_",
        "{": r"\{",
        "}": r"\}",
        "~": r"\textasciitilde{}",
        "^": r"\textasciicircum{}",
    }
    return "".join(escapes.get(c, c) for c in value if c in "\n\t" or ord(c) >= 32)


def latex_report(report: ReviewReport) -> str:
    summary = report.summary
    weights = (
        "Clarity contributes 16\\%, rigor 28\\%, evidence 24\\%, completeness 12\\%, and venue fit 20\\%. "
        if report.venue
        else "Clarity contributes 20\\%, rigor 35\\%, evidence 30\\%, and completeness 15\\%. "
    )
    lines = [
        r"\documentclass[11pt]{article}",
        r"\usepackage[T1]{fontenc}",
        r"\usepackage[margin=1in]{geometry}",
        r"\usepackage{booktabs,longtable,microtype,hyperref}",
        r"\hypersetup{hidelinks}",
        r"\setlength{\parindent}{0pt}",
        r"\setlength{\parskip}{6pt}",
        r"\setlength{\emergencystretch}{3em}",
        r"\title{Folio: Manuscript Assessment}",
        r"\author{Jev-assisted review}",
        r"\date{" + tex(report.created_at[:10]) + "}",
        r"\begin{document}",
        r"\maketitle",
        r"\section{Manuscript}",
        tex(report.paper.title),
        r"\par File: \texttt{" + tex(report.paper.filename) + "}",
        r"\par Review ID: \texttt{" + tex(report.review_id) + "}",
        r"\par SHA-256: \texttt{"
        + tex(report.paper.sha256[:32])
        + r"}\allowbreak\texttt{"
        + tex(report.paper.sha256[32:])
        + "}",
        f"Pages: {report.paper.pages}. Review units: {len(report.paper.sections)}. Profile: {tex(report.profile)}.",
        r"\section{Overall assessment}",
        f"Rubric score: {summary.score if summary.score is not None else 'Unavailable'}/100. Rubric recommendation: {tex(summary.decision)}.",
        f"Review status: {'Complete' if summary.complete else 'Incomplete; no final recommendation'}. Mean model confidence: {(summary.confidence or 0) * 100:.1f}\\%.",
        r"\section{Method}",
        (
            f"Each passage is evaluated on {'five' if report.venue else 'four'} five-level Jev Score questions. Scores are mapped from [0,4] to [0,100]. "
            + weights
            + "Long-section passage scores are weighted by character count. Section weights are fixed by role and divided within a role by word count. "
            "Mean confidence describes concentration of model outputs, not the probability that the paper is correct. "
            "Findings and suggestions below are rubric-derived templates, not generated expert explanations. Source excerpts are context, not verified rationales."
        ),
        r"\section{Section scores}",
        r"\begin{longtable}{p{.44\textwidth}rrrr}",
        r"\toprule Section & Pages & Score & Conf. & Weight \\ \midrule\endhead",
    ]
    by_id = {s.id: s for s in report.paper.sections}
    for result in report.results:
        section = by_id[result.section_id]
        lines.append(
            f"{tex(section.title)} & {section.page_start}--{section.page_end} & {result.score:.1f} & {result.confidence * 100:.0f}\\% & {summary.section_weights.get(section.id, 0) * 100:.1f}\\% \\"
        )
        lines[-1] += "\\"
    lines.extend([r"\bottomrule\end{longtable}", r"\section{Detailed findings}"])
    if report.prediction:
        prediction = report.prediction
        assessment = [r"\section{Acceptance prediction}"]
        if prediction.get("status") == "ready":
            assessment += [
                r"\textbf{" + tex(prediction.get("label", "")) + "}",
                f"Estimated acceptance probability in the pilot cohort: {float(prediction['acceptance_probability']) * 100:.1f}\\%. Binary prediction: {tex(prediction.get('binary_prediction', ''))}.",
                r"\par This is a trained classifier of Jev outputs, fitted to archived final accept/reject decisions. The six labels are probability bands, not six ground-truth classes.",
                r"\par Model: \texttt{" + tex(prediction.get("model_id", "")) + "}.",
            ]
            metrics = prediction.get("metrics", {})
            assessment.append(
                f"Held-out accuracy: {float(metrics.get('accuracy', 0)) * 100:.1f}\\%; AUROC: {float(metrics.get('roc_auc', 0)):.3f}; Brier score: {float(metrics.get('brier', 0)):.3f}."
            )
            if prediction.get("known_paper"):
                known = prediction["known_paper"]
                assessment.append(
                    f"This manuscript is in the {tex(known['split'])} split. Its observed decision is {tex(known['decision'])}; this decision was not an input to Jev."
                )
                if known["split"] in ("train", "calibration"):
                    assessment.append(
                        "This manuscript contributed to fitting or calibration; its prediction is not an independent test."
                    )
            assessment.extend(
                [
                    r"\begin{itemize}",
                    *[r"\item " + tex(note) for note in prediction.get("limitations", [])],
                    r"\end{itemize}",
                ]
            )
        else:
            assessment.append(tex(prediction.get("reason", "No trained acceptance prediction is available.")))
        lines[-1:-1] = assessment
    if report.venue:
        grounding = [
            r"\section{Target venue and website grounding}",
            r"\textbf{" + tex(report.venue.name) + "}",
            r"\par Supplied website: \url{" + tex(report.venue.website) + "}",
            r"\par Track/category: " + tex(report.venue.track or "Not specified"),
            r"\par Retrieved website passages inform all criteria. Venue fit contributes 20\% to the overall score. These are Folio's application weights, not the venue's official scale or an estimate of acceptance probability. The JSON export contains all selected passages.",
        ]
        for source in report.venue.sources:
            words = " ".join(source.passages).split()
            excerpt = " ".join(words[:25]) + (" ..." if len(words) > 25 else "")
            grounding.extend(
                [
                    r"\subsection*{" + tex(source.title) + "}",
                    r"\url{" + tex(source.url) + "}",
                    r"\par Retrieved: " + tex(source.retrieved_at),
                    r"\par Source SHA-256: \texttt{"
                    + tex(source.sha256[:32])
                    + r"}\allowbreak\texttt{"
                    + tex(source.sha256[32:])
                    + "}",
                    r"\begin{quote}\small " + tex(excerpt) + r"\end{quote}",
                ]
            )
        # Put source provenance before the detailed section feedback.
        lines[-1:-1] = grounding
    for result in report.results:
        section = by_id[result.section_id]
        lines.extend([r"\subsection{" + tex(section.title) + "}"])
        for d in result.dimensions:
            lines.append(r"\par\textbf{" + tex(d.label) + f" ({d.score:.1f}/100):" + "} " + tex(d.finding))
            if d.score < 75:
                lines.append(r"\par Revision prompt: " + tex(d.suggestion))
        lines.extend(
            [
                r"\begin{quote}\small " + tex(result.excerpt) + r"\end{quote}",
                f"Passages evaluated: {result.chunk_count}. Model: {tex(result.model)}.",
            ]
        )
    lines.extend([r"\section{Limitations and provenance}", r"\begin{itemize}"])
    lines.extend(r"\item " + tex(note) for note in summary.notes)
    lines.extend(
        [
            r"\item The manuscript rubric weights and thresholds are design choices. Any separate acceptance estimate uses the labeled study and limitations reported above.",
            r"\item Non-ASCII characters are transliterated or replaced in this portable LaTeX export; use JSON for exact text.",
            r"\end{itemize}",
            (
                f"Rubric: {tex(report.rubric_version)}. Time: {report.elapsed_ms / 1000:.2f} seconds. "
                f"Input tokens: {report.input_tokens}; output tokens: {report.output_tokens}."
            ),
            r"\par API documentation: \url{https://docs.typesafe.ai/primitives/score}",
            r"\end{document}",
        ]
    )
    return "\n".join(lines) + "\n"

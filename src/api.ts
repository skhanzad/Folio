import type { Report, StreamEvent, VenueRequest } from "./types";

export async function streamReview(
  file: File,
  profile: string,
  signal: AbortSignal,
  onEvent: (event: StreamEvent) => void,
  venue?: VenueRequest | null,
) {
  const data = new FormData();
  data.append("file", file);
  data.append("profile", profile);
  if (venue) {
    data.append("venue_name", venue.name.trim());
    data.append("venue_website", venue.website.trim());
    data.append("venue_track", venue.track.trim());
  }
  const response = await fetch("/api/review", {
    method: "POST",
    body: data,
    signal,
  });
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    throw new Error(
      typeof body?.detail === "string"
        ? body.detail
        : `Review could not start (HTTP ${response.status}).`,
    );
  }
  if (!response.body)
    throw new Error("Your browser does not support streaming responses.");
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let terminal = false;
  function consume(line: string) {
    if (!line.trim()) return;
    const event = JSON.parse(line) as StreamEvent;
    onEvent(event);
    if (event.type === "complete" || event.type === "error") terminal = true;
  }
  try {
    while (true) {
      const { done, value } = await reader.read();
      buffer += decoder.decode(value, { stream: !done });
      const lines = buffer.split("\n");
      buffer = lines.pop() ?? "";
      lines.forEach(consume);
      if (done) break;
    }
    consume(buffer);
    if (!terminal && !signal.aborted)
      throw new Error(
        "The review connection ended early. Re-upload the PDF to retry.",
      );
  } finally {
    await reader.cancel().catch(() => undefined);
    reader.releaseLock();
  }
}

export function downloadBlob(blob: Blob, name: string) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export async function exportLatex(report: Report) {
  const response = await fetch("/api/export/latex", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(report),
  });
  if (!response.ok)
    throw new Error(
      "The LaTeX export could not be prepared. Please try again.",
    );
  downloadBlob(
    await response.blob(),
    `${report.paper.filename.replace(/\.pdf$/i, "")}-review.tex`,
  );
}

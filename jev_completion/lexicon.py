"""A pinned word-list snapshot and a frequency-ranked prefix index."""
from __future__ import annotations

from bisect import bisect_left
import gzip
import hashlib
import importlib.metadata
import json
from pathlib import Path
import re
import urllib.request

REVISION = "20f5cc9b3f0ccc8ce45d814c532b7c2031bba31c"
BASE_URL = f"https://raw.githubusercontent.com/dwyl/english-words/{REVISION}"
SOURCE_SHA256 = {
    "words_alpha.txt": "3ed0c94610d8bcf7c11bbb49c56aa49c7234d32b66824df91f554169e572da48",
    "LICENSE.md": "b5065838cbac452dfc855ba6e6e031481ad2c68406f70d21ead9321374653e6c",
}


def prepare(data_dir: Path = Path("data")) -> dict:
    from wordfreq import zipf_frequency

    raw_dir = data_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    sources = []
    for filename in ("words_alpha.txt", "LICENSE.md"):
        path = raw_dir / filename
        url = f"{BASE_URL}/{filename}"
        if not path.exists():
            with urllib.request.urlopen(url, timeout=60) as response:
                payload = response.read()
            path.write_bytes(payload)
        payload = path.read_bytes()
        if hashlib.sha256(payload).hexdigest() != SOURCE_SHA256[filename]:
            raise ValueError(f"Source checksum mismatch for {path}; delete that file and rerun prepare.")
        sources.append(dict(url=url, sha256=hashlib.sha256(payload).hexdigest(), bytes=len(payload)))
    raw = (raw_dir / "words_alpha.txt").read_text().splitlines()
    words = sorted({w.strip().lower() for w in raw if re.fullmatch(r"[a-zA-Z]+", w.strip())})
    # Frequencies order options only; no corpus, n-gram predictor, or LLM is trained.
    ranks = {w: round(zipf_frequency(w, "en"), 3) for w in words}
    blob = json.dumps(ranks, separators=(",", ":"), sort_keys=True).encode()
    (data_dir / "lexicon.json.gz").write_bytes(gzip.compress(blob, mtime=0))
    (data_dir / "DICTIONARY_LICENSE.md").write_bytes((raw_dir / "LICENSE.md").read_bytes())
    manifest = dict(repository="https://github.com/dwyl/english-words", revision=REVISION,
                    sources=sources, raw_lines=len(raw), unique_words=len(words),
                    normalization="ASCII letters only, lowercase, deduplicate, sort",
                    lexicon_sha256=hashlib.sha256(blob).hexdigest(),
                    frequency_package=f"wordfreq=={importlib.metadata.version('wordfreq')}",
                    frequency_data_license="CC BY-SA 4.0; see https://github.com/rspeer/wordfreq#license",
                    scope="A broad English word-list snapshot, not every word in every dictionary.")
    (data_dir / "manifest.json").write_text(json.dumps(manifest, indent=2)+"\n")
    return manifest


class Lexicon:
    def __init__(self, scores: dict[str, float]):
        if not scores:
            raise ValueError("The dictionary must contain words.")
        self.scores = scores
        self.words = sorted(scores)
        self._ranked: dict[str, list[str]] = {}

    @classmethod
    def load(cls, path: Path = Path("data/lexicon.json.gz")) -> "Lexicon":
        if not path.exists():
            raise FileNotFoundError("Dictionary missing. Run: jev prepare")
        with gzip.open(path, "rt") as handle:
            return cls(json.load(handle))

    def matching(self, prefix: str) -> list[str]:
        left = bisect_left(self.words, prefix)
        right = bisect_left(self.words, prefix + "{")
        return self.words[left:right]

    def ranked(self, prefix: str = "") -> list[str]:
        if prefix not in self._ranked:
            self._ranked[prefix] = sorted(self.matching(prefix), key=lambda w: (-self.scores[w], w))
        return self._ranked[prefix]

    def options(self, prefix: str, excluded: set[str], shortlist: int, extra: list[str] = ()) -> tuple[dict, dict]:
        """Disjoint exact-word leaves plus prefix branches covering every remaining word."""
        candidates = []
        for word in [*extra, *self.ranked(prefix)[:shortlist+len(excluded)+len(extra)]]:
            if word.startswith(prefix) and word not in excluded and word not in candidates:
                candidates.append(word)
            if len(candidates) == shortlist:
                break
        remaining = set(self.matching(prefix)) - excluded - set(candidates)
        # Include a terminal word even if it is too rare for the frequency shortlist.
        if prefix in remaining:
            candidates.append(prefix)
            remaining.remove(prefix)
        criteria = {f"w{i}": word for i, word in enumerate(candidates)}
        actions = {f"w{i}": ("word", word) for i, word in enumerate(candidates)}
        for letter in sorted({w[len(prefix)] for w in remaining}):
            child = prefix+letter
            label = "p_"+child
            criteria[label] = f"A different word beginning with '{child}', absent from the complete words listed."
            actions[label] = ("prefix", child)
        return criteria, actions

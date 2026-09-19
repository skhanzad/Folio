"""Assemble text from Jev Choice or Noul decisions, with explicit stop reasons."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
import re
import string
import time

from .client import BudgetExceeded, JevClient, call_summary
from .lexicon import Lexicon

NEXT_WORD = (
    "We are composing a response that follows 'request'. The field 'text' is the response written so far. "
    "Pick its next word, to append immediately after 'text'. If 'text' is empty, pick the FIRST word of the response. "
    "Do not echo or repeat the request's instructions. Continue the response naturally, grammatically, and factually."
)
END = "__END__"
PUNCTUATION = {".": "Append a period to finish this sentence.",
               ",": "Append a comma and continue the sentence.",
               "?": "Append a question mark to finish this sentence.",
               "!": "Append an exclamation mark to finish this sentence."}


@dataclass
class Config:
    mode: str = "tournament"
    max_units: int = 24
    pool_size: int = 4096
    shortlist: int = 160
    group_size: int = 240
    finalists: int = 2
    max_depth: int = 24
    min_probability: float = 0.0
    scorer: str = "choice"
    stop_gate: bool = True
    stop_threshold: float = 0.90

    def __post_init__(self):
        if self.mode not in {"tree", "shortlist", "tournament", "character"}:
            raise ValueError("Unknown decoding mode.")
        if self.scorer not in {"choice", "noul"}:
            raise ValueError("Scorer must be choice or noul.")
        if not 2 <= self.shortlist <= 220 or not 2 <= self.group_size <= 250:
            raise ValueError("Shortlist must be 2–220; group size must be 2–250.")
        if not 2 <= self.pool_size <= 12_000 or not 1 <= self.finalists <= 3:
            raise ValueError("Pool must be 2–12000; finalists must be 1–3.")
        if not 1 <= self.max_units <= 2048 or not 1 <= self.max_depth <= 64:
            raise ValueError("Output/depth limits must be positive and bounded.")
        if not 0 <= self.min_probability <= 1:
            raise ValueError("Minimum probability must be in [0,1].")
        if not 0 <= self.stop_threshold <= 1:
            raise ValueError("Stop threshold must be in [0,1].")
        if self.scorer == "noul" and self.mode != "shortlist":
            raise ValueError("Noul scoring is available with shortlist mode.")


@dataclass
class Decision:
    selected: str
    probability: float
    confidence: float | None
    top: list[tuple[str, float]]
    request_hash: str
    kind: str = "choice"


@dataclass
class Completion:
    prompt: str
    prefix: str
    completion: str
    text: str
    stop_reason: str
    config: dict
    steps: list[dict]
    usage: dict
    elapsed_s: float

    def to_dict(self) -> dict:
        return asdict(self)


def append_word(text: str, word: str) -> str:
    if word in PUNCTUATION:
        return text.rstrip() + word
    if word == "i":
        word = "I"
    elif not text.strip() or text.rstrip().endswith((".", "?", "!")):
        word = word[:1].upper() + word[1:]
    return text + ("" if not text or text[-1].isspace() else " ") + word


def repeated(text: str) -> bool:
    words = re.findall(r"\w+|[^\w\s]", text.lower())
    for size in range(1, 5):
        if len(words) >= 3*size and words[-size:] == words[-2*size:-size] == words[-3*size:-2*size]:
            return True
    return False


class Decoder:
    def __init__(self, client: JevClient, lexicon: Lexicon | None, config: Config):
        self.client, self.lexicon, self.config = client, lexicon, config
        if config.mode != "character" and lexicon is None:
            raise ValueError("Word modes require a prepared dictionary.")

    def choose(self, state: dict, criteria: dict, instructions: str = NEXT_WORD) -> Decision:
        criteria = self.present_words(state, criteria)
        call = self.client.evaluate(state, {"next": dict(type="choice", instructions=instructions, criteria=criteria)})
        answer = call.response["answers"]["next"]
        chosen = answer["choice"]
        return Decision(chosen, answer["probabilities"][chosen], answer["confidence"],
                        sorted(answer["probabilities"].items(), key=lambda x: -x[1])[:5], call.request_hash)

    def present_words(self, state: dict, criteria: dict) -> dict:
        # Sentence-initial candidates need the same case as the emitted text.
        # Otherwise capitalized instruction words copied from the request can
        # dominate lowercase alternatives for purely orthographic reasons.
        return {key: append_word(state["text"], value)[len(state["text"]):].strip()
                if key.startswith("w") else value for key, value in criteria.items()}

    def terminal_options(self) -> dict:
        return {**PUNCTUATION, END: "Stop: the existing text already fully satisfies the request; append nothing."}

    def extras(self, state: dict) -> list[str]:
        # Copy words/numbers from user context. This is not an answer lookup table.
        return list(dict.fromkeys(re.findall(r"[A-Za-z]+(?:'[A-Za-z]+)?|\d+", state["request"] + " " + state["text"])))[:48]

    def word(self, state: dict) -> tuple[str, list[Decision]]:
        config = self.config
        if config.mode == "tournament":
            return self.tournament(state)
        criteria, actions = self.lexicon.options("", set(), config.shortlist, self.extras(state))
        if config.mode == "shortlist":
            criteria = {key: value for key, value in criteria.items() if actions[key][0] == "word"}
        criteria.update(self.terminal_options())
        if config.scorer == "noul":
            questions = {key: {"type": "noul", "instructions":
                f"Is this a natural, coherent next continuation of the unfinished text that satisfies the writing request? Candidate: {value}"}
                for key, value in criteria.items()}
            call = self.client.evaluate(state, questions)
            probs = {key: answer["noul"] for key, answer in call.response["answers"].items()}
            selected = max(probs, key=probs.get)
            decisions = [Decision(selected, probs[selected], None,
                                  sorted(probs.items(), key=lambda x: -x[1])[:5], call.request_hash, "noul")]
        else:
            decisions = [self.choose(state, criteria)]
            selected = decisions[-1].selected
        excluded = {value for kind, value in actions.values() if kind == "word"}
        while selected in actions and actions[selected][0] == "prefix":
            if len(decisions) >= config.max_depth:
                return "__DEPTH__", decisions
            prefix = actions[selected][1]
            criteria, actions = self.lexicon.options(prefix, excluded, config.shortlist)
            if len(criteria) == 1:
                # A singleton branch needs no paid classification.
                selected = next(iter(criteria))
                break
            decision = self.choose(state, criteria, NEXT_WORD+f" The next word starts with '{prefix}'.")
            decisions.append(decision)
            selected = decision.selected
            excluded.update(value for kind, value in actions.values() if kind == "word")
        return actions[selected][1] if selected in actions else selected, decisions

    def tournament(self, state: dict) -> tuple[str, list[Decision]]:
        """Batch independent groups, then compare their finalists in a new call.

        Probabilities from different groups are never treated as globally calibrated.
        This restricted vocabulary route deliberately makes no full-dictionary claim.
        """
        config = self.config
        pool = list(dict.fromkeys([*self.extras(state), *self.lexicon.ranked()[:config.pool_size]]))
        decisions = []
        while len(pool) > 250:
            # Keep total question input manageable by packing at most 12 groups.
            # Each winner remains a candidate in the subsequent reduction round.
            groups = [pool[i:i+config.group_size] for i in range(0, len(pool), config.group_size)]
            finalists = []
            for offset in range(0, len(groups), 12):
                questions = {}
                mappings = {}
                for i, group in enumerate(groups[offset:offset+12]):
                    if len(group) == 1:
                        finalists.extend(group)
                        continue
                    name = f"group_{offset+i}"
                    mappings[name] = {f"w{j}": word for j, word in enumerate(group)}
                    questions[name] = dict(type="choice", instructions=NEXT_WORD,
                                           criteria=self.present_words(state, mappings[name]))
                if not questions:
                    continue
                call = self.client.evaluate(state, questions)
                for name, answer in call.response["answers"].items():
                    ranked = sorted(answer["probabilities"].items(), key=lambda x: -x[1])
                    finalists.extend(mappings[name][label] for label, _ in ranked[:config.finalists])
                    decisions.append(Decision(mappings[name][answer["choice"]],
                                              answer["probabilities"][answer["choice"]], answer["confidence"],
                                              [(mappings[name][label], prob) for label, prob in ranked[:5]], call.request_hash))
            pool = list(dict.fromkeys(finalists))
        criteria = {f"w{i}": word for i, word in enumerate(pool)}
        criteria.update(self.terminal_options())
        decision = self.choose(state, criteria)
        decisions.append(decision)
        return criteria[decision.selected] if decision.selected.startswith("w") else decision.selected, decisions

    def character(self, state: dict) -> tuple[str, list[Decision]]:
        characters = string.ascii_lowercase + string.ascii_uppercase + string.digits + " .,!?;:'-\n"
        mapping = {f"c{i}": ch for i, ch in enumerate(characters)}
        criteria = {key: ("Space between words" if char == " " else "Newline" if char == "\n" else repr(char))
                    for key, char in mapping.items()}
        criteria[END] = "The text is complete. Append nothing."
        decision = self.choose(state, criteria,
            "Choose the single next character to append to the unfinished text, continuing it naturally and factually to satisfy the writing request. Preserve spaces and spelling.")
        return mapping.get(decision.selected, END), [decision]

    def complete(self, prompt: str, prefix: str = "", on_step=None) -> Completion:
        start = time.perf_counter()
        first_call = len(self.client.calls)
        text = prefix
        steps = []
        stop = "max_units"
        for index in range(self.config.max_units):
            state = {"request": prompt, "text": text}
            try:
                # An inexpensive yes/no gate avoids scanning the vocabulary just
                # to emit a period. Never gate the supplied prefix or characters.
                if self.config.stop_gate and index > 0 and self.config.mode != "character":
                    call = self.client.evaluate(state, {"finished": dict(type="noul", instructions=
                        "Does the text already form a grammatically complete sentence that fulfills the writing request, "
                        "requiring only final punctuation? Answer no for fragments, dangling conjunctions, or unfinished clauses.")})
                    p = call.response["answers"]["finished"]["noul"]
                    if p >= self.config.stop_threshold:
                        token = "."
                        decisions = [Decision(".", p, None, [("finished", p)], call.request_hash, "noul_stop")]
                    else:
                        token, decisions = self.word(state)
                else:
                    token, decisions = self.character(state) if self.config.mode == "character" else self.word(state)
            except BudgetExceeded:
                stop = "budget"
                break
            steps.append(dict(index=index, token=token, decisions=[asdict(d) for d in decisions]))
            if token == "__DEPTH__":
                stop = "max_depth"
                break
            if decisions[-1].probability < self.config.min_probability:
                stop = "low_probability"
                break
            if token == END:
                stop = "model_end"
                break
            text = text+token if self.config.mode == "character" else append_word(text, token)
            if on_step:
                on_step(text, steps[-1])
            if repeated(text[len(prefix):]):
                stop = "repetition"
                break
            if token in {".", "?", "!"}:
                stop = "sentence_end"
                break
        return Completion(prompt, prefix, text[len(prefix):], text, stop, asdict(self.config), steps,
                          call_summary(self.client.calls[first_call:]), time.perf_counter()-start)


def rerank(client: JevClient, prompt: str, candidates: list[str]) -> dict:
    """One-call shortcut when complete candidate sentences already exist."""
    candidates = list(dict.fromkeys(candidates))
    if not 2 <= len(candidates) <= 254 or any(not c.strip() for c in candidates):
        raise ValueError("Provide 2–254 distinct, nonempty candidate sentences.")
    criteria = {f"s{i}": sentence for i, sentence in enumerate(candidates)}
    criteria["none"] = "None of these sentences adequately satisfies the request."
    first_call = len(client.calls)
    call = client.evaluate(prompt, {"sentence": dict(type="choice", instructions=
        "Select the sentence that best answers or fulfills the request, accurately and naturally.", criteria=criteria)})
    answer = call.response["answers"]["sentence"]
    return dict(prompt=prompt, candidates=candidates,
                text=None if answer["choice"] == "none" else criteria[answer["choice"]],
                answer=answer, usage=call_summary(client.calls[first_call:]), request_hash=call.request_hash)

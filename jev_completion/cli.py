from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from .client import JevClient, JevError, Ledger, api_key
from .decoder import Config, Decoder, rerank
from .lexicon import Lexicon, prepare


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Complete text by composing Jev decisions. Input tokens are billed; output tokens are free.")
    commands = p.add_subparsers(dest="command", required=True)
    prepare_cmd = commands.add_parser("prepare", help="Download and index the pinned 370k-word English dictionary")
    prepare_cmd.add_argument("--data-dir", type=Path, default=Path("data"))
    for name in ("complete", "rerank", "usage"):
        sub = commands.add_parser(name)
        sub.add_argument("--ledger", type=Path, default=Path(".jev/ledger.sqlite"))
        sub.add_argument("--budget", type=float, default=0.25, help="Cumulative USD cap for this ledger, not per invocation")
        sub.add_argument("--rate", type=float, default=0.042, help="USD per million input tokens; verify current pricing")
        if name == "usage":
            continue
        sub.add_argument("prompt")
        sub.add_argument("--model", default="jev-1.13.0")
        sub.add_argument("--no-cache", action="store_true")
        sub.add_argument("--offline", action="store_true", help="Use existing cached responses only")
        sub.add_argument("--json", action="store_true", dest="as_json")
        sub.add_argument("--output", type=Path, help="Write complete result and decision traces as JSON")
        if name == "rerank":
            sub.add_argument("--candidates", required=True, type=Path, help="JSON array of existing sentences")
        else:
            sub.add_argument("--prefix", default="", help="Existing text to continue verbatim")
            sub.add_argument("--mode", choices=["tournament", "tree", "shortlist", "character"], default="tournament")
            sub.add_argument("--scorer", choices=["choice", "noul"], default="choice")
            sub.add_argument("--max-units", type=int, default=24, help="Words/punctuation, or characters in character mode")
            sub.add_argument("--pool-size", type=int, default=4096)
            sub.add_argument("--shortlist", type=int, default=160)
            sub.add_argument("--min-probability", type=float, default=0)
            sub.add_argument("--dictionary", type=Path, default=Path("data/lexicon.json.gz"))
            sub.add_argument("--stream", action="store_true")
    return p


def main(argv=None) -> int:
    args = parser().parse_args(argv)
    client = None
    ledger = None
    try:
        if args.command == "prepare":
            print(json.dumps(prepare(args.data_dir), indent=2))
            return 0
        ledger = Ledger(args.ledger, args.budget, args.rate)
        if args.command == "usage":
            print(json.dumps(ledger.summary(), indent=2))
            return 0
        client = JevClient("" if args.offline else api_key(), ledger, args.model,
                           use_cache=not args.no_cache, offline=args.offline)
        if args.command == "rerank":
            candidates = json.loads(args.candidates.read_text())
            if not isinstance(candidates, list) or not all(isinstance(c, str) for c in candidates):
                raise ValueError("Candidates must be a JSON array of strings.")
            result = rerank(client, args.prompt, candidates)
        else:
            config = Config(mode=args.mode, max_units=args.max_units, pool_size=args.pool_size,
                            shortlist=args.shortlist, min_probability=args.min_probability, scorer=args.scorer)
            lexicon = None if args.mode == "character" else Lexicon.load(args.dictionary)
            callback = (lambda text, step: print(text, file=sys.stderr, flush=True)) if args.stream else None
            result = Decoder(client, lexicon, config).complete(args.prompt, args.prefix, callback).to_dict()
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(result, indent=2, ensure_ascii=False)+"\n")
        if args.as_json:
            print(json.dumps(result, indent=2, ensure_ascii=False))
        else:
            print(result["text"] if result["text"] is not None else "No candidate was suitable.")
            usage = result["usage"]
            print(f"{usage['requests']} paid requests; {usage['cache_hits']} cache hits; "
                  f"{usage['input_tokens']} input tokens; estimated ${usage['cost_usd']:.8f}; "
                  f"stop={result.get('stop_reason','selection')}", file=sys.stderr)
        return 0
    except (JevError, ValueError, FileNotFoundError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    finally:
        if client:
            client.close()
        elif ledger:
            ledger.close()


if __name__ == "__main__":
    raise SystemExit(main())

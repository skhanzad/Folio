"""Run the fixed diagnostic suite; expected labels never enter candidate selection.

Run from the repository root: python -m experiments.run --stage completion
Raw requests/responses contain only the public synthetic experiment prompts.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import datetime, timezone
import gzip
import hashlib
import json
from pathlib import Path
import re
import subprocess

from jev_completion.client import JevClient, Ledger, api_key
from jev_completion.decoder import Config, Decoder, NEXT_WORD, rerank
from jev_completion.lexicon import Lexicon


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--stage',choices=['completion','open','rerank'],required=True)
    p.add_argument('--budget',type=float,default=.25)
    p.add_argument('--output',type=Path,default=Path('results/benchmark'))
    args=p.parse_args()
    args.output.mkdir(parents=True,exist_ok=True)
    suite_bytes=Path('experiments/suite.json').read_bytes()
    suite=json.loads(suite_bytes)
    client=JevClient(api_key(),Ledger(Path('.jev/ledger.sqlite'),args.budget),use_cache=False)
    lex=Lexicon.load()
    code_hash=hashlib.sha256(b''.join(path.read_bytes() for path in sorted(Path('jev_completion').glob('*.py')))).hexdigest()
    metadata=dict(started_utc=datetime.now(timezone.utc).isoformat(),stage=args.stage,
                  suite_sha256=hashlib.sha256(suite_bytes).hexdigest(),source_sha256=code_hash,
                  git_revision=subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),
                  word_instructions=NEXT_WORD,cache_enabled=False,price_usd_per_million=.042)
    (args.output/f'{args.stage}_metadata.json').write_text(json.dumps(metadata,indent=2)+'\n')
    variants={
        'choice_160':Config(mode='shortlist',shortlist=160,max_units=6),
        'noul_160':Config(mode='shortlist',shortlist=160,scorer='noul',max_units=6),
        'tournament_512':Config(mode='tournament',pool_size=512,max_units=6),
        'tournament_2048':Config(mode='tournament',pool_size=2048,max_units=6),
    }
    try:
        if args.stage=='completion':
            jobs=[(case,name,config) for case in suite['completion_cases'] for name,config in variants.items()]
        elif args.stage=='open':
            jobs=[(case,'tournament_2048',Config(mode='tournament',pool_size=2048,max_units=16)) for case in suite['open_cases']]
        else:
            jobs=[(case,'rerank',None) for case in suite['rerank_cases']]
        for case,name,config in jobs:
            path=args.output/f"{args.stage}_{case['id']}_{name}.json"
            if path.exists():
                print('Skipping existing result:',path,flush=True)
                continue
            before=len(client.calls)
            if config is None:
                sentences=json.loads(Path('examples/sentences.json').read_text())
                result=rerank(client,case['prompt'],sentences)
                expected=None if case['expected_index'] is None else sentences[case['expected_index']]
                result['exact_selection_match']=result['text']==expected
            else:
                prompt=case.get('prompt','Finish this sentence with a short factual continuation.')
                result=Decoder(client,lex,config).complete(prompt,case.get('prefix','')).to_dict()
                if 'expected_first_words' in case:
                    words=re.findall(r'[a-z]+',result['completion'].lower())
                    result['expected_first_words']=case['expected_first_words']
                    result['first_word_match']=bool(words) and words[0] in case['expected_first_words']
                    pool=set(lex.ranked()[:config.pool_size if config.mode=='tournament' else config.shortlist])
                    pool.update(Decoder(client,lex,config).extras({'request':prompt,'text':case['prefix']}))
                    result['any_expected_in_initial_pool']=any(w in pool for w in case['expected_first_words'])
            result.update(case_id=case['id'],variant=name)
            path.write_text(json.dumps(result,indent=2)+'\n')
            with gzip.open(path.with_suffix('.calls.jsonl.gz'),'wt') as handle:
                for call in client.calls[before:]:handle.write(json.dumps(asdict(call))+'\n')
            print(case['id'],name,repr(result['text']),result['usage'],flush=True)
            client.calls.clear()  # Raw calls are persisted; bound memory between cases.
        (args.output/f'{args.stage}_ledger.json').write_text(json.dumps(client.ledger.summary(),indent=2)+'\n')
    finally:
        client.close()


if __name__=='__main__':
    main()

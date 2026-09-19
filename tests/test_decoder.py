from types import SimpleNamespace

import pytest

from jev_completion.client import BudgetExceeded, Call
from jev_completion.decoder import Config, Decoder, END, append_word, repeated, rerank
from jev_completion.lexicon import Lexicon


class FakeClient:
    def __init__(self, chooser):
        self.calls=[]
        self.chooser=chooser

    def evaluate(self,state,questions):
        answers={}
        for name,q in questions.items():
            selected=self.chooser(state,q)
            if q['type']=='noul':
                answers[name]={'type':'noul','noul':selected}
            else:
                assert selected in q['criteria']
                answers[name]={'type':'choice','choice':selected,'confidence':1,
                    'probabilities':{k:float(k==selected) for k in q['criteria']}}
        c=Call({'model':'fake','answers':answers},'fake-hash',False,0.1,10,5,.00000042)
        self.calls.append(c)
        return c


def test_prefix_tree_covers_every_word_exactly_even_at_rare_terminal():
    lex=Lexicon({'a':0,'at':2,'atom':1,'apple':3,'boat':4,'be':2,'bee':1})
    leaves=[]
    def walk(prefix,excluded):
        criteria,actions=lex.options(prefix,excluded,2)
        assert len(criteria)<=255
        exact={v for kind,v in actions.values() if kind=='word'}
        leaves.extend(exact)
        branches=[v for kind,v in actions.values() if kind=='prefix']
        for branch in branches:
            walk(branch,excluded|exact)
    walk('',set())
    assert sorted(leaves)==lex.words
    assert len(leaves)==len(set(leaves))


def test_completion_punctuation_and_cheap_stop_gate():
    c=FakeClient(lambda state,q: .99 if q['type']=='noul' else
                 next(k for k,v in q['criteria'].items() if v=='blue'))
    result=Decoder(c,Lexicon({'blue':3,'the':4}),Config(mode='shortlist',shortlist=20)).complete('Finish.', 'The sky is')
    assert result.text=='The sky is blue.'
    assert result.completion==' blue.' and result.stop_reason=='sentence_end'
    assert result.usage['requests']==2


def test_budget_stop_never_fabricates_a_completed_sentence():
    c=FakeClient(lambda *_:None)
    c.evaluate=lambda *_: (_ for _ in ()).throw(BudgetExceeded('cap'))
    result=Decoder(c,Lexicon({'a':1,'b':1}),Config(mode='shortlist')).complete('Finish.', 'A')
    assert result.stop_reason=='budget' and result.text=='A'


def test_tournament_compares_finalists_instead_of_cross_group_scores():
    words={f'word{i:03}':1 for i in range(510)}
    words['target']=2
    c=FakeClient(lambda state,q: next((k for k,v in q['criteria'].items() if v.lower()=='target'),next(iter(q['criteria']))))
    decoder=Decoder(c,Lexicon(words),Config(mode='tournament',pool_size=511,stop_gate=False))
    word,decisions=decoder.word({'request':'Continue','text':'Existing'})
    assert word=='target'
    assert len(c.calls)==2  # All three groups shared state in one request, plus final.
    assert len(decisions)==4


def test_character_mode_keeps_spaces_and_stops_at_period():
    chars=iter(['H','i',' ','.'])
    def choose(state,q):
        char=next(chars)
        desc='Space between words' if char==' ' else repr(char)
        return next(k for k,v in q['criteria'].items() if v==desc)
    result=Decoder(FakeClient(choose),None,Config(mode='character',max_units=5)).complete('Say hi')
    assert result.text=='Hi .' and result.stop_reason=='sentence_end'


def test_rerank_can_abstain():
    result=rerank(FakeClient(lambda *_:'none'),'Answer',['Alpha.','Beta.'])
    assert result['text'] is None


def test_initial_word_options_match_rendered_case():
    d=Decoder(FakeClient(lambda *_:None),Lexicon({'a':1,'the':1}),Config())
    assert d.present_words({'text':''},{'w0':'a','w1':'the',END:'stop'})=={'w0':'A','w1':'The',END:'stop'}


def test_rendering_and_repetition():
    assert append_word('Hello',',')=='Hello,'
    assert append_word('','the')=='The'
    assert append_word('and','i')=='and I'
    assert repeated('a b a b a b')
    assert not repeated('a b a b')

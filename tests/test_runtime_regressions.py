from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from app import config, embeddings, llm, worker, jobs


def test_embedding_batches_are_bounded_and_ordered(monkeypatch):
    import numpy as np
    model = Mock()
    model.encode.side_effect = lambda texts, **kw: np.array([[float(t)] for t in texts])
    monkeypatch.setattr(embeddings, '_get_model', lambda: model)
    monkeypatch.setattr(config, 'EMBEDDING_BATCH_SIZE', 2, raising=False)
    progress = []
    assert embeddings.embed_texts(['0', '1', '2', '3', '4'], on_progress=lambda a,b: progress.append((a,b))) == [[0.], [1.], [2.], [3.], [4.]]
    assert [len(c.args[0]) for c in model.encode.call_args_list] == [2,2,1]
    assert progress == [(2,5),(4,5),(5,5)]


def test_provider_reasoning_is_explicit_and_not_sent_to_unknown_provider(monkeypatch):
    monkeypatch.setattr(config, 'LLM_REASONING_EFFORT', 'none', raising=False)
    assert llm.completion_options()['reasoning_effort'] == 'none'
    monkeypatch.setattr(config, 'LLM_REASONING_EFFORT', '')
    assert 'reasoning_effort' not in llm.completion_options()


def test_stream_uses_options_closes_and_only_emits_answer(monkeypatch):
    class Stream:
        closed = False
        def __iter__(self):
            yield SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content=None))])
            yield SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content='answer'))])
        def close(self): self.closed = True
    stream = Stream()
    create = Mock(return_value=stream)
    monkeypatch.setattr(llm, '_client', SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create))))
    monkeypatch.setattr(config, 'LLM_REASONING_EFFORT', 'none', raising=False)
    assert list(llm.chat_stream([{'role':'user','content':'hello'}])) == ['answer']
    assert stream.closed and create.call_args.kwargs['reasoning_effort'] == 'none'


def test_model_value_error_is_retryable_and_diagnostics_are_safe(monkeypatch, caplog):
    monkeypatch.setattr(jobs, 'claim', lambda _: {'id': 5, 'token': 't'})
    fail = Mock(return_value=True)
    monkeypatch.setattr(jobs, 'fail', fail)
    def broken(_):
        raise worker.IngestionError('embedding', ValueError('PRIVATE BODY'))
    monkeypatch.setattr(worker, 'process', broken)
    worker.run_one('test')
    assert fail.call_args.kwargs['permanent'] is False
    assert fail.call_args.kwargs['stage'] == 'embedding'
    assert 'PRIVATE BODY' not in caplog.text


def test_parsing_error_is_terminal(monkeypatch):
    monkeypatch.setattr(jobs, 'claim', lambda _: {'id': 5, 'token': 't'})
    fail = Mock(return_value=True)
    monkeypatch.setattr(jobs, 'fail', fail)
    def broken(_):
        raise worker.IngestionError('parse', ValueError('bad file'))
    monkeypatch.setattr(worker, 'process', broken)
    worker.run_one('test')
    assert fail.call_args.kwargs['permanent'] is True

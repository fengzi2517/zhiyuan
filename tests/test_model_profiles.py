import json
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest

from app import llm, model_profiles


@pytest.fixture
def profiles(monkeypatch):
    monkeypatch.setenv('PROFILE_SECRET', 'private-key')
    monkeypatch.setenv('CHAT_MODEL_PROFILES', json.dumps([
        dict(id='text', name='Text', model='text-model', vision=False,
             fast_options={'extra_body': {'thinking': False}}),
        dict(id='vision', name='Vision', model='vision-model', vision=True,
             fast_options={'reasoning_effort': 'none'},
             deep_options={'extra_body': {'thinking': True}},
             api_key_env='PROFILE_SECRET', base_url='https://private.invalid/v1',
             context_chars=12000, max_images=3),
    ]))


def test_registry_capabilities_and_private_configuration(profiles):
    public = model_profiles.get_profiles()
    assert public[0]['supports_deep_thinking'] is False
    assert public[1]['supports_vision'] is True
    assert 'private' not in json.dumps(public)
    selection = model_profiles.resolve_selection('vision', 'deep', True)
    assert selection.profile.context_chars == 12000
    assert selection.public_metadata()['thinking_mode'] == 'deep'
    with pytest.raises(Exception):
        selection.thinking_mode = 'fast'
    options = selection.request_options()
    options['extra_body']['thinking'] = False
    assert selection.request_options()['extra_body']['thinking'] is True


@pytest.mark.parametrize('args', [('missing', 'fast', False), ('text', 'deep', False),
                                  ('text', 'fast', True), ('vision', 'invalid', False)])
def test_unsupported_options_rejected(profiles, args):
    with pytest.raises(ValueError):
        model_profiles.resolve_selection(*args)


def test_concurrent_request_options_are_isolated(profiles, monkeypatch):
    calls = []
    def create(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content='answer'))])
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    monkeypatch.setattr(llm, '_client', client)
    monkeypatch.setattr(llm, '_client_for_selection', lambda _: client)
    selections = [model_profiles.resolve_selection('vision', 'deep', True),
                  model_profiles.resolve_selection('vision', 'fast', False)] * 8
    with ThreadPoolExecutor(max_workers=4) as pool:
        assert list(pool.map(lambda s: llm.chat([{'role': 'user', 'content': 'hello'}], selection=s), selections)) == ['answer'] * 16
    assert sum(c.get('reasoning_effort') == 'none' for c in calls) == 8
    assert sum(c.get('extra_body', {}).get('thinking') is True for c in calls) == 8
    llm.chat([{'role': 'user', 'content': 'utility'}])
    assert calls[-1]['model'] == llm.config.LLM_MODEL


def test_stream_yields_content_only_and_closes(profiles, monkeypatch):
    class Stream:
        closed = False
        def __iter__(self):
            yield SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content=None, reasoning='hidden'))])
            yield SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content='visible', reasoning=None))])
        def close(self):
            self.closed = True
    stream = Stream()
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=lambda **_: stream)))
    monkeypatch.setattr(llm, '_client_for_selection', lambda _: client)
    assert list(llm.chat_stream([], selection=model_profiles.resolve_selection('vision', 'deep'))) == ['visible']
    assert stream.closed


def test_default_fast_mode_is_truthful(monkeypatch):
    monkeypatch.delenv('CHAT_MODEL_PROFILES', raising=False)
    monkeypatch.setattr(model_profiles.config, 'LLM_MODEL', 'sensenova-6.8-flash-lite')
    monkeypatch.setattr(model_profiles.config, 'LLM_REASONING_EFFORT', 'high')
    selection = model_profiles.resolve_selection()
    assert selection.request_options()['reasoning_effort'] == 'none'
    assert selection.public_metadata()['thinking_label'] == '快速'
    assert model_profiles.get_profiles()[0]['supports_fast_control'] is True
    monkeypatch.setattr(model_profiles.config, 'LLM_MODEL', 'unknown-provider-model')
    assert model_profiles.get_profiles()[0]['supports_fast_control'] is False
    assert model_profiles.resolve_selection().public_metadata()['thinking_label'] == '供应商默认'


@pytest.mark.parametrize('options', [
    {'extra_body': {'model': 'other'}}, {'extra_body': {'messages': []}},
    {'extra_body': {'stream': False}}, {'max_tokens': None}, {'max_tokens': -1},
    {'max_tokens': 32769}, {'max_tokens': True},
    {'max_tokens': 100, 'max_completion_tokens': 200},
    {'extra_body': {'max_tokens': 100}},
])
def test_invalid_request_override_rejected(monkeypatch, options):
    monkeypatch.setenv('CHAT_MODEL_PROFILES', json.dumps([dict(id='x', model='x', fast_options=options)]))
    with pytest.raises(ValueError):
        model_profiles.resolve_selection()


def test_budget_bounds_and_completion_token_alias(monkeypatch):
    entry = dict(id='x', model='x', fast_options={'max_completion_tokens': 128})
    monkeypatch.setenv('CHAT_MODEL_PROFILES', json.dumps([entry]))
    assert model_profiles.resolve_selection().request_options() == {'max_completion_tokens': 128}
    entry['context_chars'] = 200001
    monkeypatch.setenv('CHAT_MODEL_PROFILES', json.dumps([entry]))
    with pytest.raises(ValueError):
        model_profiles.resolve_selection()


def test_empty_explicit_fast_options_uses_default_label(monkeypatch):
    monkeypatch.setenv('CHAT_MODEL_PROFILES', json.dumps([dict(id='x', model='x', fast_options={}, deep_options={})]))
    assert model_profiles.get_profiles()[0]['fast_mode_label'] == '供应商默认'
    assert model_profiles.resolve_selection(thinking_mode='deep').public_metadata()['thinking_label'] == '深度思考'

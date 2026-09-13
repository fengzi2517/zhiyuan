"""Server-owned model capabilities and immutable per-request selection.

Options remain JSON internally so callers cannot mutate nested shared settings.
Only capability metadata is exposed to clients, never endpoint or credentials.
"""
from dataclasses import dataclass, field
import json
import os

from . import config


@dataclass(frozen=True)
class ModelProfile:
    id: str
    name: str
    model: str
    supports_vision: bool
    context_chars: int
    max_images: int
    fast_options_json: str = field(repr=False)
    deep_options_json: str | None = field(repr=False)
    base_url: str = field(repr=False)
    api_key: str = field(repr=False)

    @property
    def supports_fast_control(self):
        return bool(json.loads(self.fast_options_json))

    @property
    def fast_mode_label(self):
        return '快速' if self.supports_fast_control else '供应商默认'

    def public_metadata(self):
        return dict(id=self.id, name=self.name, model=self.model,
                    supports_vision=self.supports_vision,
                    supports_deep_thinking=self.deep_options_json is not None,
                    supports_fast_control=self.supports_fast_control,
                    fast_mode_label=self.fast_mode_label,
                    context_chars=self.context_chars, max_images=self.max_images)


@dataclass(frozen=True)
class ModelSelection:
    profile: ModelProfile
    thinking_mode: str
    vision_enabled: bool

    @property
    def model(self):
        return self.profile.model

    def request_options(self):
        encoded = (self.profile.deep_options_json if self.thinking_mode == 'deep'
                   else self.profile.fast_options_json)
        options = json.loads(encoded)
        if not {'max_tokens', 'max_completion_tokens'} & options.keys():
            _token_budget(config.LLM_MAX_TOKENS)
            options['max_tokens'] = config.LLM_MAX_TOKENS
        return options

    def public_metadata(self):
        return dict(model_id=self.profile.id, model=self.model, model_name=self.profile.name,
                    thinking_mode=self.thinking_mode, vision_enabled=self.vision_enabled,
                    thinking_label='深度思考' if self.thinking_mode == 'deep' else self.profile.fast_mode_label)


def _token_budget(value):
    if type(value) is not int or not 1 <= value <= 32768:
        raise ValueError('模型输出预算必须是 1 到 32768 的整数')


def _options(value):
    if not isinstance(value, dict):
        raise ValueError('模型模式配置必须是 JSON 对象')
    # Routing and response delivery belong to the application, not mode options.
    if {'model', 'messages', 'stream', 'api_key', 'base_url'} & value.keys():
        raise ValueError('模型模式配置包含保留字段')
    extra = value.get('extra_body', {})
    if not isinstance(extra, dict):
        raise ValueError('extra_body 必须是 JSON 对象')
    if {'model', 'messages', 'stream', 'api_key', 'base_url', 'max_tokens', 'max_completion_tokens'} & extra.keys():
        raise ValueError('extra_body 包含保留字段；输出预算请配置在顶层')
    budget_fields = {'max_tokens', 'max_completion_tokens'} & value.keys()
    if len(budget_fields) > 1:
        raise ValueError('不能同时配置两种输出预算字段')
    for key in budget_fields:
        _token_budget(value[key])
    return json.dumps(value, allow_nan=False)


def _registry():
    raw = os.getenv('CHAT_MODEL_PROFILES', '').strip()
    if raw:
        try:
            entries = json.loads(raw)
        except (TypeError, ValueError) as exc:
            raise ValueError('CHAT_MODEL_PROFILES 不是有效 JSON') from exc
    else:
        sense = config.LLM_MODEL.startswith('sensenova-6.8')
        # Interactive controls are independent of auxiliary LLM defaults.
        fast = {'reasoning_effort': 'none'} if sense else {}
        entries = [dict(id='default', name=config.LLM_MODEL, model=config.LLM_MODEL,
                        vision=sense, fast_options=fast,
                        # SenseNova defaults to thinking when no override is sent.
                        deep_options={} if sense else None)]
    if not isinstance(entries, list) or not entries:
        raise ValueError('CHAT_MODEL_PROFILES 必须是非空数组')
    profiles = []
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError('模型配置必须是对象')
        ident, model = entry.get('id'), entry.get('model')
        if not isinstance(ident, str) or not ident.strip() or not isinstance(model, str) or not model.strip():
            raise ValueError('模型配置缺少 id 或 model')
        if any(p.id == ident for p in profiles):
            raise ValueError('模型 id 重复')
        vision = entry.get('vision', False)
        chars, images = entry.get('context_chars', 24000), entry.get('max_images', 5)
        if not isinstance(vision, bool) or type(chars) is not int or not 2000 <= chars <= 200000 or type(images) is not int or not 0 <= images <= 20:
            raise ValueError('模型上下文或视觉限制无效')
        deep = entry.get('deep_options')
        key_env = entry.get('api_key_env')
        profiles.append(ModelProfile(
            id=ident, name=str(entry.get('name') or model), model=model,
            supports_vision=vision, context_chars=chars, max_images=images,
            fast_options_json=_options(entry.get('fast_options', {})),
            deep_options_json=None if deep is None else _options(deep),
            base_url=entry.get('base_url') or config.LLM_BASE_URL,
            api_key=os.getenv(key_env, '') if key_env else config.LLM_API_KEY,
        ))
    return tuple(profiles)


def get_profiles():
    return [profile.public_metadata() for profile in _registry()]


def resolve_selection(model_id=None, thinking_mode='fast', vision_enabled=False):
    profiles = _registry()
    profile = next((p for p in profiles if p.id == (model_id or profiles[0].id)), None)
    if profile is None:
        raise ValueError('未知模型')
    if thinking_mode not in ('fast', 'deep'):
        raise ValueError('未知思考模式')
    if thinking_mode == 'deep' and profile.deep_options_json is None:
        raise ValueError('当前模型未配置深度思考模式')
    if not isinstance(vision_enabled, bool):
        raise ValueError('视觉选项必须是布尔值')
    if vision_enabled and not profile.supports_vision:
        raise ValueError('当前模型不支持视觉')
    return ModelSelection(profile, thinking_mode, vision_enabled)

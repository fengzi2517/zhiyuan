import time
import json
import re
import logging
import httpx
from openai import OpenAI
from . import config
from .model_profiles import ModelSelection
from functools import lru_cache
from .query_understanding import QueryUnderstanding, understand_query

logger = logging.getLogger(__name__)
_client = OpenAI(base_url=config.LLM_BASE_URL, api_key=config.LLM_API_KEY,
                 timeout=httpx.Timeout(config.LLM_TIMEOUT_SECONDS, connect=10),
                 max_retries=config.LLM_MAX_RETRIES)

def completion_options() -> dict:
    options = {'max_tokens': config.LLM_MAX_TOKENS}
    if config.LLM_REASONING_EFFORT:
        options['reasoning_effort'] = config.LLM_REASONING_EFFORT
    return options


@lru_cache(maxsize=16)
def _profile_client(base_url, api_key):
    return OpenAI(base_url=base_url, api_key=api_key,
                  timeout=httpx.Timeout(config.LLM_TIMEOUT_SECONDS, connect=10),
                  max_retries=config.LLM_MAX_RETRIES)


def _client_for_selection(selection):
    if (selection.profile.base_url == config.LLM_BASE_URL
            and selection.profile.api_key == config.LLM_API_KEY):
        return _client
    return _profile_client(selection.profile.base_url, selection.profile.api_key)


def chat(messages: list[dict], *, selection: ModelSelection | None = None, timeout_seconds: float | None = None) -> str:
    """One interactive request; any SDK retries are explicit configuration."""
    started = time.perf_counter()
    try:
        client = _client_for_selection(selection) if selection else _client
        resp = client.chat.completions.create(
            model=selection.model if selection else config.LLM_MODEL, messages=messages,
            **({'timeout': timeout_seconds} if timeout_seconds is not None else {}),
            **(selection.request_options() if selection else completion_options()))
        return resp.choices[0].message.content
    finally:
        logger.info('llm mode=sync elapsed_ms=%s', round((time.perf_counter()-started)*1000))


def chat_stream(messages: list[dict], *, selection: ModelSelection | None = None):
    """Yield text deltas from an OpenAI-compatible streaming completion."""
    started = time.perf_counter()
    first_event_ms = first_token_ms = None
    response = None
    try:
        client = _client_for_selection(selection) if selection else _client
        response = client.chat.completions.create(
            model=selection.model if selection else config.LLM_MODEL, messages=messages, stream=True,
            **(selection.request_options() if selection else completion_options()),
        )
        for chunk in response:
            if first_event_ms is None:
                first_event_ms = round((time.perf_counter()-started)*1000)
            delta = chunk.choices[0].delta.content if chunk.choices else None
            if delta:
                if first_token_ms is None:
                    first_token_ms = round((time.perf_counter()-started)*1000)
                yield delta
    finally:
        close = getattr(response, "close", None)
        if close:
            close()
        logger.info('llm mode=stream first_event_ms=%s first_token_ms=%s elapsed_ms=%s',
                    first_event_ms, first_token_ms, round((time.perf_counter()-started)*1000))

def _parse_json(text: str) -> dict | None:
    """容错解析 LLM 输出的 JSON（截取首个 {...} 块）"""
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except Exception:
        return None

# ---------- 意图识别 + 查询改写（合并为一次 LLM 调用） ----------
UNDERSTAND_TMPL = """你是问答系统的查询理解模块。知识库内容不限领域（取决于用户上传的资料），
因此不要预设领域，先理解用户目的，再决定处理路径。按以下顺序判定 intent：

判定顺序（命中即停）：
1. "chitchat"：仅限——寒暄问候（你好/谢谢）、询问你自身（你是谁/你能做什么）、纯情感闲聊（今天心情不好）。
   注意：任何实质性提问（哪怕与资料领域无关，如菜谱、编程、医疗）都不算 chitchat，走默认路径
2. "web"：明确需要实时/最新信息：含"最新、今年、现在、新闻、价格、政策发布"等时效词
3. "kb"：其余一切实质性提问（默认）。知识库是否真的有相关资料由后续检索判定，
   你不需要猜测知识库里有什么

示例：
- "你好" → chitchat
- "帮我写个Python爬虫" → kb（实质性提问，默认检索）
- "今年出台了哪些新法规" → web
- "红烧肉怎么做" → kb（实质性提问，默认检索）
- "刚才说的那个方案具体怎么实施"（历史在聊方案）→ kb，query 需消解指代

输出 JSON（只输出 JSON，不要其他内容）：
{{"intent": "kb|web|chitchat", "query": "改写后的检索 query", "reason": "判定理由（一句话）"}}

query 要求：结合历史消解指代（"它/上面那个"→具体实体）、补全省略的主语，使其可独立检索；chitchat 时原样返回问题。

对话历史（最近几轮）：
{history}
用户最新问题：{question}"""

def understand(question: str, history: list[str]) -> dict:
    """返回 {"intent": "kb|web|chitchat", "query": 改写后的问题, "reason": 判定理由}，解析失败安全降级"""
    default = {"intent": "kb", "query": question, "reason": "意图识别降级，默认走知识库检索"}
    try:
        out = chat([{"role": "user", "content":
                     UNDERSTAND_TMPL.format(history="\n".join(history[-6:]) or "（无）",
                                            question=question)}])
        parsed = _parse_json(out)
        if parsed and parsed.get("intent") in ("kb", "web", "chitchat") and parsed.get("query"):
            return {"intent": parsed["intent"],
                    "query": str(parsed["query"]).strip(),
                    "reason": str(parsed.get("reason", ""))[:100]}
    except Exception:
        pass
    return default


STRUCTURED_UNDERSTAND_TMPL = """你是查询理解模块。把问题分类为：
- chitchat：寒暄或轻量闲聊
- create：写作、润色、改写、翻译或创作
- knowledge：不依赖当前时间的知识解释
- current：需要今天、最新、价格、政策等时效信息
- mixed：同时需要用户资料和当前网络信息

只输出符合下面 JSON Schema 的 JSON，不要 Markdown：
{schema}

最近对话：
{history}
用户问题：{question}"""


def understand_structured(question: str, history: list[str]) -> QueryUnderstanding:
    """Use deterministic signals first, then validate one exact JSON object."""
    def classify(_: str) -> dict:
        prompt = STRUCTURED_UNDERSTAND_TMPL.format(
            schema=json.dumps(QueryUnderstanding.model_json_schema(), ensure_ascii=False),
            history="\n".join(history[-6:]) or "（无）",
            question=question,
        )
        output = chat([{"role": "user", "content": prompt}])
        return json.loads(output)

    try:
        return understand_query(question, classify)
    except Exception:
        return understand_query(question)


REWRITE_SEARCH_TMPL = """将下面的问题改写为更适合检索知识库的中文查询。
要求：补全省略主语，保留专有名词，只输出改写后的查询，不要解释。

原问题：{question}"""


def rewrite_for_search(question: str) -> str:
    try:
        output = chat([{"role": "user", "content": REWRITE_SEARCH_TMPL.format(question=question)}])
        rewritten = (output or "").strip()
        return rewritten or question
    except Exception:
        return question

# ---------- 会话长期记忆增量更新（参考 MemGPT/mem0 分层记忆） ----------
MEMORY_TMPL = """你是会话记忆管理器。将【现有记忆】与【新对话】合并为更新后的记忆。

输出格式（严格遵守，不要输出其他内容）：
[摘要]
（不超过 300 字的对话全局脉络：双方聊过的话题、用户关注点与结论）
[要点]
- 每行一条关键事实（用户身份/项目背景/关键实体/共识或决策）
- 保留仍然有效的旧要点，删除过时项，最多 15 条

【现有记忆】
[摘要]
{summary}
[要点]
{facts}

【新对话】
用户：{question}
助手：{answer}"""

def update_memory(old: dict | None, question: str, answer: str) -> dict | None:
    """增量合并记忆；解析失败返回 None（保留旧记忆）"""
    try:
        old = old or {}
        out = chat([{"role": "user", "content":
                     MEMORY_TMPL.format(summary=old.get("summary", "") or "（无）",
                                        facts=old.get("facts", "") or "（无）",
                                        question=question, answer=answer[:2000])}])
        # 分段解析：[摘要] 与 [要点] 两个标记之间提取
        import re as _re
        m_sum = _re.search(r"\[摘要\]\s*(.*?)(?:\[要点\]|$)", out, _re.S)
        m_fac = _re.search(r"\[要点\]\s*(.*)$", out, _re.S)
        summary = m_sum.group(1).strip() if m_sum else ""
        facts = m_fac.group(1).strip() if m_fac else ""
        if summary or facts:
            return {"summary": summary[:1000], "facts": facts[:1500]}
    except Exception as e:
        logger.warning('memory update failed error_type=%s', type(e).__name__)
    return None

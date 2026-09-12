import os
from pathlib import Path
from threading import Lock

# 模型离线加载：指向项目内 .hf-cache 并跳过 HuggingFace 在线检查
# （在线 HEAD 检查在网络不佳时超时重试，会让向量化任务卡死数分钟）
_HF_CACHE = Path(__file__).resolve().parent.parent / ".hf-cache"
if _HF_CACHE.is_dir():
    os.environ.setdefault("HF_HOME", str(_HF_CACHE))
    os.environ.setdefault("HF_HUB_OFFLINE", "1")

from sentence_transformers import SentenceTransformer, CrossEncoder
from . import config

_model = None   # 懒加载单例，避免拖慢应用启动
_model_lock = Lock()
_reranker = None
_reranker_failed = False   # 模型不可用时降级为相似度排序

def _get_model() -> SentenceTransformer:
    global _model
    if _model is None:
        with _model_lock:
            if _model is None:
                _model = SentenceTransformer(config.EMBEDDING_MODEL)
    return _model

def _get_reranker():
    global _reranker, _reranker_failed
    if _reranker is None and not _reranker_failed:
        try:
            _reranker = CrossEncoder(config.RERANK_MODEL, max_length=512)
        except Exception:
            _reranker_failed = True   # 模型缺失时降级，不阻断主流程
    return _reranker

# bge v1.5 中文系列需要查询侧加指令前缀；bge-m3 多语言模型不需要
_QUERY_PREFIX = "" if "bge-m3" in config.EMBEDDING_MODEL.lower() else \
    "为这个句子生成表示以用于检索相关文章："

def embed_texts(texts: list[str], is_query: bool = False, *, on_progress=None) -> list[list[float]]:
    if not texts:
        return []
    if is_query and _QUERY_PREFIX:
        texts = [_QUERY_PREFIX + t for t in texts]
    model = _get_model()
    result = []
    for start in range(0, len(texts), config.EMBEDDING_BATCH_SIZE):
        batch = texts[start:start + config.EMBEDDING_BATCH_SIZE]
        vectors = model.encode(batch, batch_size=config.EMBEDDING_BATCH_SIZE,
                               normalize_embeddings=True, show_progress_bar=False)
        result.extend(v.tolist() for v in vectors)
        if on_progress:
            on_progress(len(result), len(texts))
    return result

def rerank(query: str, docs: list[str]) -> list[float] | None:
    """交叉编码器精排，返回各文档相关性分数（sigmoid 后 0~1）。
    模型不可用返回 None，由调用方降级为向量相似度排序。"""
    m = _get_reranker()
    if m is None or not docs:
        return None
    scores = m.predict([(query, d) for d in docs])
    return [float(s) for s in scores]


def rerank_sources(query: str, sources: list[dict]) -> list[dict]:
    """Rerank structured results while preserving their location metadata."""
    scores = rerank(query, [source["content"] for source in sources])
    if scores is None:
        return [{**source, "_rerank_applied": False} for source in sources]
    ranked = []
    for source, score in zip(sources, scores):
        ranked.append({**source, "score": score, "_rerank_applied": True})
    return sorted(ranked, key=lambda source: source["score"], reverse=True)

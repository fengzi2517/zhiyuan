import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()   # 本机裸跑时从项目根目录 .env 加载配置

UPLOAD_DIR = Path(os.getenv("UPLOAD_DIR", Path(__file__).resolve().parent.parent / "uploads"))

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+psycopg://rag:rag@127.0.0.1:5435/rag")

# LLM（OpenAI 兼容接口，SenseNova）
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "https://token.sensenova.cn/v1")
LLM_API_KEY = os.getenv("LLM_API_KEY", "")
LLM_MODEL = os.getenv("LLM_MODEL", "sensenova-6.8-flash-lite")
LLM_REASONING_EFFORT = os.getenv("LLM_REASONING_EFFORT", "none" if LLM_MODEL.startswith("sensenova-6.8") else "")
LLM_MAX_TOKENS = max(64, int(os.getenv("LLM_MAX_TOKENS", "4096")))
LLM_TIMEOUT_SECONDS = max(5, float(os.getenv("LLM_TIMEOUT_SECONDS", "60")))
LLM_MAX_RETRIES = max(0, int(os.getenv("LLM_MAX_RETRIES", "0")))
EMBEDDING_BATCH_SIZE = max(1, int(os.getenv("EMBEDDING_BATCH_SIZE", "4")))

# 联网搜索（Tavily）
TAVILY_API_KEY = os.getenv("TAVILY_API_KEY", "")

# 本地向量化模型：bge-m3 多语言（中英混合），1024 维，8192 token 上下文
EMBEDDING_MODEL = "BAAI/bge-m3"
EMBEDDING_DIM = 1024

# 本地重排序模型（交叉编码器，替代 LLM 逐条评分）
RERANK_MODEL = "BAAI/bge-reranker-base"

# 检索链路默认参数（前端设置可覆盖 sim_threshold / top_k）
CANDIDATE_K = 8            # 向量召回候选数（粗召回后再精排）
SIM_THRESHOLD = 0.4        # 向量相似度粗筛阈值（bge-m3 实测：相关 0.54-0.73，
                           #   领域近义无关 ~0.52，泛无关 0.28-0.38；粗筛放行给重排器精判）
RERANK_THRESHOLD = 0.3     # 重排序相关性阈值（实测：相关 0.46+，无关 <0.06，区分度好）

from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional
from enum import Enum

class Environment(str, Enum):
    DEVELOPMENT = "development"
    TESTING = "testing"
    PRODUCTION = "production"

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", case_sensitive=True)
    # Application
    APP_NAME: str = "Data Analytics System"
    ENVIRONMENT: Environment = Environment.DEVELOPMENT
    DEBUG: bool = True
    SECRET_KEY: str
    
    # Database
    DATABASE_URL: str
    DATABASE_CONNECT_TIMEOUT: int = 3  # секунд — быстрый отказ без PostgreSQL
    DATABASE_POOL_SIZE: int = 20
    DATABASE_MAX_OVERFLOW: int = 40
    
    # JWT
    JWT_ALGORITHM: str = "HS256"
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    JWT_REFRESH_TOKEN_EXPIRE_DAYS: int = 7
    
    # AI / Local LLM (in-process: llama-cpp или transformers)
    # Путь к GGUF или каталогу HF-модели (приоритет над LLAMA_GGUF_FILE)
    LLAMA_MODEL_PATH: Optional[str] = None
    LLAMA_CONTEXT_SIZE: int = 2048
    LLAMA_MODELS_DIR: str = "./models"
    LLAMA_HF_REPO: str = "Qwen/Qwen2.5-1.5B-Instruct-GGUF"
    LLAMA_GGUF_FILE: str = "qwen2.5-1.5b-instruct-q4_k_m.gguf"
    LLAMA_N_THREADS: Optional[int] = None
    LLAMA_N_GPU_LAYERS: int = -1  # -1 = все слои на GPU (llama-cpp); 0 = только CPU
    # auto | cuda | cpu — устройство для transformers/torch
    LLM_DEVICE: str = "auto"
    LLM_USE_CUDA: bool = True
    EMBEDDING_DEVICE: str = "auto"  # auto | cuda | cpu
    EMBEDDING_USE_CUDA: bool = True
    # auto | llama_cpp | transformers
    LLM_BACKEND: str = "auto"
    TRANSFORMERS_MODEL_ID: str = "Qwen/Qwen2.5-1.5B-Instruct"
    # Отдельная модель для NL/SQL-запросов (если не задана — используется основная)
    SQL_LLAMA_MODEL_PATH: Optional[str] = None
    SQL_TRANSFORMERS_MODEL_ID: Optional[str] = None
    LLM_MODEL: Optional[str] = None  # устаревший alias, см. LLAMA_MODEL_PATH
    LLM_TIMEOUT: int = 900
    LLM_MAX_TOKENS: int = 800
    LLM_TEMPERATURE: float = 0.4
    LLM_REPETITION_PENALTY: float = 1.18
    AI_ANALYZE_MAX_TOKENS: int = 700
    AI_CONTEXT_MAX_CHARS: int = 8000
    EMBEDDING_MODEL: str = "sentence-transformers/all-MiniLM-L6-v2"
    
    # RAG
    CHROMA_PERSIST_DIR: str = "./chroma_db"
    CHROMA_STARTUP_CHECK: bool = False  # health Chroma при старте (может замедлять запуск)
    RAG_TOP_K: int = 5
    KNOWLEDGE_MAX_TEXT_BYTES: int = 2_000_000  # ~2 МБ текста на документ
    KNOWLEDGE_MAX_CHUNKS: int = 200  # макс. фрагментов за одну индексацию
    EMBEDDING_BATCH_SIZE: int = 2  # меньше = меньше пик RAM при encode
    EMBEDDING_TORCH_THREADS: int = 2
    KNOWLEDGE_INDEX_PAUSE_MS: int = 100  # пауза между пакетами (снижает пик RAM/CPU)
    KNOWLEDGE_MIN_FREE_RAM_MB: int = 800  # минимум свободной RAM перед индексацией
    KNOWLEDGE_USE_SUBPROCESS: bool = True  # индексация в отдельном процессе
    KNOWLEDGE_FORCE_BACKGROUND: bool = True  # всегда ставить индексацию в очередь jobs
    KNOWLEDGE_BACKGROUND_MIN_BYTES: int = 1  # порог «крупного» файла (1 = почти всегда фон)
    KNOWLEDGE_SUBPROCESS_TIMEOUT: int = 3600  # секунд на subprocess индексации
    
    # File Storage
    UPLOAD_DIR: str = "./uploads"
    REPORT_DIR: str = "./reports"
    KNOWLEDGE_DIR: str = "./knowledge"
    USER_DATA_DIR: str = "./data"
    MAX_UPLOAD_SIZE: int = 104857600  # 100MB
    DATAFRAME_CACHE_TTL: int = 600  # секунд

    # Dev server: reload только .py; data-директории исключены (см. main.py)
    UVICORN_RELOAD: bool = False

    # Предупреждение при большой группировке (строк в результате)
    GROUP_RESULT_WARN_ROWS: int = 10_000
    
    # Logging
    LOG_LEVEL: str = "INFO"
    LOG_FILE: Optional[str] = None

    DB_USER: str = "postgres"  # Значение по умолчанию
    DB_PASSWORD: str = "postgres"
    DB_NAME: str = "analytics_db"
    
settings = Settings()

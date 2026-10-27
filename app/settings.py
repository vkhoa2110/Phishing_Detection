from dataclasses import dataclass
from pathlib import Path
import os

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env", override=False)


@dataclass(frozen=True)
class Settings:
    root: Path = ROOT
    model_dir: str = os.getenv("MODEL_DIR", "models/inference_XGBoost_d6_s42")
    endpoint: str = os.getenv("FPT_ENDPOINT", "https://mkp-api.fptcloud.com/v1/chat/completions")
    llm_model: str = os.getenv("FPT_MODEL", "DeepSeek-V4-Flash")
    api_key: str = os.getenv("FPT_API_KEY", "")
    allowed_hosts: tuple[str, ...] = tuple(
        x.strip().lower() for x in os.getenv("LLM_ALLOWED_HOSTS", "mkp-api.fptcloud.com").split(",") if x.strip()
    )
    timeout_seconds: float = float(os.getenv("LLM_TIMEOUT_SECONDS", "45"))
    max_tokens: int = int(os.getenv("LLM_MAX_TOKENS", "1024"))


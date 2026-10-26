from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator

Risk = Literal["HIGH", "WARNING", "LOW", "UNKNOWN"]


class InputData(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: Literal["url", "text"] = "text"
    text: str = Field(min_length=1, max_length=8000)

    @field_validator("text")
    @classmethod
    def strip_input(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Nội dung không được để trống.")
        return value


class AnalyzeInput(InputData):
    use_llm: bool = True
    include_ml: bool = True
    consent: bool = False
    llm_text: str | None = Field(default=None, max_length=8000)
    endpoint: str = Field(default="", max_length=500)
    model: str = Field(default="", max_length=150)
    api_key: SecretStr = Field(default_factory=lambda: SecretStr(""))

    @field_validator("api_key")
    @classmethod
    def limit_key(cls, value: SecretStr) -> SecretStr:
        if len(value.get_secret_value()) > 2048:
            raise ValueError("API key quá dài.")
        return value


class Evidence(BaseModel):
    model_config = ConfigDict(extra="forbid")
    quote: str = Field(min_length=1, max_length=400)
    reason: str = Field(min_length=1, max_length=600)


class LLMVerdict(BaseModel):
    model_config = ConfigDict(extra="forbid")
    risk_level: Risk
    summary: str = Field(min_length=1, max_length=1000)
    evidence: list[Evidence] = Field(default_factory=list, max_length=6)
    recommended_actions: list[str] = Field(default_factory=list, max_length=5)

    @field_validator("recommended_actions")
    @classmethod
    def limit_actions(cls, items: list[str]) -> list[str]:
        if any(not item.strip() or len(item) > 500 for item in items):
            raise ValueError("Hướng dẫn không hợp lệ.")
        return items


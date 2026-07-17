from abc import ABC, abstractmethod
from pydantic import BaseModel


class LLMClassification(BaseModel):
    summary: str
    category: str
    priority: str


class BaseLLMAdapter(ABC):
    @abstractmethod
    async def classify(self, title: str, description: str) -> LLMClassification:
        pass

    @abstractmethod
    def classify_sync(self, title: str, description: str) -> LLMClassification:
        pass

    @abstractmethod
    async def close(self) -> None:
        pass
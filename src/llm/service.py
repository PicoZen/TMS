import logging
import os
from typing import Optional

from src.llm.adapters import BaseLLMAdapter, LLMClassification, OpenAIAdapter, OllamaAdapter, MistralAdapter, MockLLMAdapter
from src.common.config import settings

logger = logging.getLogger(__name__)


class LLMService:
    def __init__(self):
        self._adapter: Optional[BaseLLMAdapter] = None

    @property
    def adapter(self) -> BaseLLMAdapter:
        if self._adapter is None:
            self._adapter = self._create_adapter()
        return self._adapter

    def _create_adapter(self) -> BaseLLMAdapter:
        # Use mock adapter in test mode
        if os.environ.get("PYTEST_CURRENT_TEST") or "pytest" in os.environ.get("_", ""):
            return MockLLMAdapter()
            
        provider = settings.llm_provider.lower()
        if provider == "openai":
            return OpenAIAdapter()
        elif provider == "ollama":
            return OllamaAdapter()
        elif provider == "mistral":
            return MistralAdapter()
        else:
            # Default to OpenAI
            return OpenAIAdapter()

    async def classify(self, title: str, description: str) -> LLMClassification:
        """Single-attempt classification call, no retry loop here.

        Retries live at the Celery task layer (`classify_ticket_task` in
        src/tasks/classification_tasks.py), via `self.retry(countdown=...)`
        with exponential backoff, up to `settings.llm_max_retries`. Each
        retry there is a brand-new task execution, which is what lets a
        transient failure be retried cleanly instead of retried inside a
        single long-lived call. Keeping this method single-attempt avoids
        two independent retry loops (this one + Celery's) stacking their
        delays on top of each other.
        """
        return await self.adapter.classify(title, description)

    def classify_sync(self, title: str, description: str) -> LLMClassification:
        """Single-attempt synchronous call, used by the Celery task.

        See `classify()` above - retry/backoff is Celery's job, not this
        method's.
        """
        return self.adapter.classify_sync(title, description)


llm_service = LLMService()
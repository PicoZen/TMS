import json
import os

import httpx

from src.llm.adapters import BaseLLMAdapter, LLMClassification
from src.common.config import settings


class OllamaAdapter(BaseLLMAdapter):
    def __init__(self):
        self.base_url = settings.ollama_base_url or os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
        self.model = "llama3.1"
        self.async_client = httpx.AsyncClient(timeout=settings.llm_timeout)
        self.sync_client = httpx.Client(timeout=settings.llm_timeout)

    async def classify(self, title: str, description: str) -> LLMClassification:
        prompt = f"""
Analyze the following support ticket and return a JSON response with:
- summary: A concise 1-2 sentence summary
- category: One of TECHNICAL, ACCOUNT, BILLING, OTHER
- priority: One of LOW, MEDIUM, HIGH

Ticket:
Title: {title}
Description: {description}

Return ONLY valid JSON.
"""

        try:
            response = await self.async_client.post(
                f"{self.base_url}/api/generate",
                json={
                    "model": self.model,
                    "prompt": prompt,
                    "stream": False,
                    "format": "json",
                    "options": {"temperature": 0.1},
                },
            )
            response.raise_for_status()
            data = response.json()
            result = json.loads(data.get("response", "{}"))

            return LLMClassification(
                summary=result.get("summary", ""),
                category=result.get("category", "OTHER"),
                priority=result.get("priority", "MEDIUM"),
            )
        except Exception as e:
            raise RuntimeError(f"Ollama classification failed: {e}")

    def classify_sync(self, title: str, description: str) -> LLMClassification:
        """Synchronous version for use in Celery tasks"""
        prompt = f"""
Analyze the following support ticket and return a JSON response with:
- summary: A concise 1-2 sentence summary
- category: One of TECHNICAL, ACCOUNT, BILLING, OTHER
- priority: One of LOW, MEDIUM, HIGH

Ticket:
Title: {title}
Description: {description}

Return ONLY valid JSON.
"""

        try:
            response = self.sync_client.post(
                f"{self.base_url}/api/generate",
                json={
                    "model": self.model,
                    "prompt": prompt,
                    "stream": False,
                    "format": "json",
                    "options": {"temperature": 0.1},
                },
            )
            response.raise_for_status()
            data = response.json()
            result = json.loads(data.get("response", "{}"))

            return LLMClassification(
                summary=result.get("summary", ""),
                category=result.get("category", "OTHER"),
                priority=result.get("priority", "MEDIUM"),
            )
        except Exception as e:
            raise RuntimeError(f"Ollama classification failed: {e}")

    async def close(self):
        await self.async_client.aclose()
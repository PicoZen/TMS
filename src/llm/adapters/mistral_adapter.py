import json
import os

import httpx

from src.llm.adapters import BaseLLMAdapter, LLMClassification
from src.common.config import settings


class MistralAdapter(BaseLLMAdapter):
    def __init__(self):
        self.api_key = settings.mistral_api_key or os.getenv("MISTRAL_API_KEY", "")
        self.base_url = "https://api.mistral.ai/v1"
        self.model = settings.mistral_model or "mistral-large-latest"
        self.async_client = httpx.AsyncClient(timeout=settings.llm_timeout)
        self.sync_client = httpx.Client(timeout=settings.llm_timeout)

    async def classify(self, title: str, description: str) -> LLMClassification:
        prompt = f"""Analyze the following support ticket and return a JSON response with:
- summary: A concise 1-2 sentence summary
- category: One of TECHNICAL, ACCOUNT, BILLING, OTHER
- priority: One of LOW, MEDIUM, HIGH

Ticket:
Title: {title}
Description: {description}

Return ONLY valid JSON."""

        try:
            response = await self.async_client.post(
                f"{self.base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self.model,
                    "messages": [
                        {
                            "role": "system",
                            "content": "You are a support ticket classifier. Return only JSON.",
                        },
                        {"role": "user", "content": prompt},
                    ],
                    "temperature": 0.1,
                    "max_tokens": 200,
                    "response_format": {"type": "json_object"},
                },
            )
            response.raise_for_status()
            data = response.json()
            content = data["choices"][0]["message"]["content"]

            result = json.loads(content)

            return LLMClassification(
                summary=result.get("summary", ""),
                category=result.get("category", "OTHER"),
                priority=result.get("priority", "MEDIUM"),
            )
        except Exception as e:
            raise RuntimeError(f"Mistral classification failed: {e}")

    def classify_sync(self, title: str, description: str) -> LLMClassification:
        """Synchronous version for use in Celery tasks"""
        prompt = f"""Analyze the following support ticket and return a JSON response with:
- summary: A concise 1-2 sentence summary
- category: One of TECHNICAL, ACCOUNT, BILLING, OTHER
- priority: One of LOW, MEDIUM, HIGH

Ticket:
Title: {title}
Description: {description}

Return ONLY valid JSON."""

        try:
            response = self.sync_client.post(
                f"{self.base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self.model,
                    "messages": [
                        {
                            "role": "system",
                            "content": "You are a support ticket classifier. Return only JSON.",
                        },
                        {"role": "user", "content": prompt},
                    ],
                    "temperature": 0.1,
                    "max_tokens": 200,
                    "response_format": {"type": "json_object"},
                },
            )
            response.raise_for_status()
            data = response.json()
            content = data["choices"][0]["message"]["content"]

            result = json.loads(content)

            return LLMClassification(
                summary=result.get("summary", ""),
                category=result.get("category", "OTHER"),
                priority=result.get("priority", "MEDIUM"),
            )
        except Exception as e:
            raise RuntimeError(f"Mistral classification failed: {e}")

    async def close(self):
        await self.async_client.aclose()
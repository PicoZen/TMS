import json
import os
from typing import Any

import httpx
from openai import AsyncOpenAI, OpenAI

from src.llm.adapters import BaseLLMAdapter, LLMClassification
from src.common.config import settings


class OpenAIAdapter(BaseLLMAdapter):
    def __init__(self):
        self.async_client = AsyncOpenAI(
            api_key=settings.openai_api_key or os.getenv("OPENAI_API_KEY", "")
        )
        self.sync_client = OpenAI(
            api_key=settings.openai_api_key or os.getenv("OPENAI_API_KEY", "")
        )
        self.model = settings.llm_model
        self.timeout = settings.llm_timeout

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
            response = await self.async_client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": "You are a support ticket classifier. Return only JSON.",
                    },
                    {"role": "user", "content": prompt},
                ],
                temperature=0.1,
                max_tokens=200,
                response_format={"type": "json_object"},
                timeout=self.timeout,
            )

            content = response.choices[0].message.content
            result = json.loads(content)

            return LLMClassification(
                summary=result.get("summary", ""),
                category=result.get("category", "OTHER"),
                priority=result.get("priority", "MEDIUM"),
            )
        except Exception as e:
            raise RuntimeError(f"OpenAI classification failed: {e}")

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
            response = self.sync_client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": "You are a support ticket classifier. Return only JSON.",
                    },
                    {"role": "user", "content": prompt},
                ],
                temperature=0.1,
                max_tokens=200,
                response_format={"type": "json_object"},
                timeout=self.timeout,
            )

            content = response.choices[0].message.content
            result = json.loads(content)

            return LLMClassification(
                summary=result.get("summary", ""),
                category=result.get("category", "OTHER"),
                priority=result.get("priority", "MEDIUM"),
            )
        except Exception as e:
            raise RuntimeError(f"OpenAI classification failed: {e}")
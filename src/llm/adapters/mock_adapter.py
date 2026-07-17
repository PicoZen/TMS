from src.llm.adapters.base import BaseLLMAdapter, LLMClassification


class MockLLMAdapter(BaseLLMAdapter):
    """Mock LLM adapter for testing"""
    
    def __init__(self):
        pass
    
    async def classify(self, title: str, description: str) -> LLMClassification:
        """Mock async classification"""
        return self.classify_sync(title, description)
    
    def classify_sync(self, title: str, description: str) -> LLMClassification:
        """Mock synchronous classification for testing"""
        return LLMClassification(
            summary=f"Mock summary for: {title}",
            category="TECHNICAL",
            priority="MEDIUM",
        )
    
    async def close(self) -> None:
        pass
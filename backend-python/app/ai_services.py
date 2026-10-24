"""Lazy provider selection: no credential lookup or paid calls at app startup."""
from .providers import create_provider
from .recommendations import RecommendationService

class ConfiguredRecommendationService:
    def __init__(self, configuration=None, transport=None):
        self.configuration=configuration
        self.transport=transport

    async def recommend(self, preferences):
        provider=create_provider(configuration=self.configuration,transport=self.transport)
        return await RecommendationService(provider).recommend(preferences)

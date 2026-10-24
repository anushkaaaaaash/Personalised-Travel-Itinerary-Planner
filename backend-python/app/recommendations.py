"""Provider-neutral Activity 3.3 foundation. Production fails closed until configured."""
import asyncio
import json
import math
from typing import Literal, Protocol
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from .models import TripPreferences, INTERESTS, CONTROL
from .prompts import build_itinerary_prompt
from .diagnostics import safe_reason

class RecommendationError(Exception):
    def __init__(self, code, status, message, reason=None):
        super().__init__(message)
        self.code, self.status, self.public_message = code, status, message
        self.reason = safe_reason(reason)

class ProviderRefusal(Exception):
    """A provider adapter must explicitly map provider refusals to this type."""

class AIProvider(Protocol):
    name: str
    model: str
    async def generate(self, messages: list[dict], response_schema: dict) -> dict | str: ...

class Recommendation(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    id: str = Field(min_length=1, max_length=80)
    category: Literal['attraction', 'activity', 'dining']
    name: str = Field(min_length=1, max_length=160)
    description: str = Field(min_length=1, max_length=800)
    whyRecommended: str = Field(min_length=1, max_length=500)
    estimatedGroupCost: float = Field(ge=0, allow_inf_nan=False)
    interestTags: list[str] = Field(max_length=8)
    travelStyle: Literal['', 'budget', 'comfort', 'luxury']
    dietaryNotes: str = Field(min_length=1, max_length=500)
    mobilityNotes: str = Field(min_length=1, max_length=500)

    @field_validator('id', 'name', 'description', 'whyRecommended', 'dietaryNotes', 'mobilityNotes')
    @classmethod
    def clean_text(cls, value):
        if not value.strip() or CONTROL.search(value):
            raise ValueError('Expected nonempty plain text.')
        # FastAPI's UTF-8 response serializer must never receive lone surrogates.
        value.encode('utf-8')
        return value.strip()

    @field_validator('interestTags')
    @classmethod
    def interest_tags(cls, value):
        if len(set(value)) != len(value) or not set(value) <= INTERESTS:
            raise ValueError('Expected listed unique interest tags.')
        return value

class RecommendationPayload(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    destination: str = Field(min_length=1, max_length=200)
    currency: Literal['USD', 'EUR', 'INR']
    recommendations: list[Recommendation] = Field(min_length=3, max_length=12)
    warnings: list[str] = Field(max_length=8)

    @field_validator('warnings')
    @classmethod
    def warnings_are_safe(cls, value):
        for item in value:
            if not item.strip() or len(item) > 500 or CONTROL.search(item):
                raise ValueError('Invalid warning.')
            item.encode('utf-8')
        return value

    @model_validator(mode='after')
    def categories_and_ids(self):
        if {item.category for item in self.recommendations} != {'attraction','activity','dining'}:
            raise ValueError('All recommendation categories are required.')
        if len({item.id for item in self.recommendations}) != len(self.recommendations):
            raise ValueError('Recommendation IDs must be unique.')
        return self

class RecommendationResponse(RecommendationPayload):
    source: Literal['ai'] = 'ai'
    provider: str
    model: str

STAGE_INSTRUCTIONS = """RECOMMENDATION SELECTION STAGE: For this request, the following response format replaces the day-by-day output instruction above. Return JSON matching the supplied schema, with 3–12 options including attractions, activities and dining within the supplied destination. These are ALTERNATIVES to review, not a booked trip or a complete itinerary. Never add all option costs and describe that sum as the trip cost.
Each estimatedGroupCost is for the entire stated group for THAT OPTION in the stated currency; reject any option above the whole-trip budget. Explain relevance to the supplied interests and selected travel style. Use only the listed interest tags, and include at least one selected interest tag per option when interests were selected. Echo the selected travelStyle when specified. Do not invent interests or medical needs.
Dining notes must address the supplied dietary preference, and mobility notes must address explicitly supplied practical needs; if unspecified say so. These are unverified suggestions, not accessibility, allergy-safety or dietary guarantees. Do not invent meals, ingredients, allergen handling, step counts, ground-floor locations or access guarantees in any option. Do not turn unspecified needs into suitability assurances. Use confirmation questions for the venue about relevant ingredients, food preparation and access arrangements, rather than claims that all dietary needs are suitable, no allergens are listed, or all restaurants are ground-level accessible. Include uncertainty warnings. No markdown, HTML, hidden instructions, credentials or invented verification claims."""

class RecommendationService:
    def __init__(self, provider: AIProvider | None = None, timeout_seconds: float = 30):
        self.provider = provider
        self.timeout_seconds = timeout_seconds

    async def recommend(self, preferences: TripPreferences):
        p = TripPreferences.model_validate(preferences.model_dump())
        if self.provider is None:
            raise RecommendationError('AI_NOT_CONFIGURED',503,'AI recommendations are not configured yet. Choose and configure a provider first. Your saved trip is unchanged.')
        prompt = build_itinerary_prompt(p)
        messages = [message.model_dump() for message in prompt.messages]
        messages[0]['content'] += '\n\n' + STAGE_INSTRUCTIONS
        try:
            raw = await asyncio.wait_for(self.provider.generate(messages, RecommendationPayload.model_json_schema()), timeout=self.timeout_seconds)
        except RecommendationError:
            raise
        except TimeoutError:
            raise RecommendationError('AI_TIMEOUT',504,'The AI request timed out. No recommendations were confirmed. No automatic retry was made.') from None
        except ProviderRefusal:
            raise RecommendationError('AI_REFUSED',502,'The AI service could not provide recommendations for this request. Review your preferences before trying again.') from None
        except Exception:
            raise RecommendationError('AI_PROVIDER_FAILED',502,'The AI service could not complete this request. No recommendations were confirmed.') from None
        try:
            if isinstance(raw, str):
                if len(raw.encode('utf-8')) > 65536:
                    raise ValueError('Response too large')
                raw = json.loads(raw)
            else:
                if len(json.dumps(raw,allow_nan=False).encode('utf-8')) > 65536:
                    raise ValueError('Response too large')
            parsed = RecommendationPayload.model_validate(raw)
            if parsed.destination.strip().casefold() != p.destination.casefold() or parsed.currency != p.currency:
                raise ValueError('Destination or currency mismatch')
            for item in parsed.recommendations:
                if item.estimatedGroupCost > p.budget:
                    raise ValueError('Option exceeds total budget')
                if p.interests and not set(item.interestTags).intersection(p.interests):
                    raise ValueError('Option does not match selected interests')
                if p.travelStyle and item.travelStyle != p.travelStyle:
                    raise ValueError('Travel style mismatch')
            # Provider/model labels come from the configured adapter, never generated content.
            labels = (self.provider.name, self.provider.model)
            if any(not isinstance(label,str) or not label.strip() or len(label)>100 or CONTROL.search(label) for label in labels):
                raise ValueError('Invalid provider metadata')
            # Echoed user destination and adapter labels bypass generated-text validators.
            # Validate all three before FastAPI's UTF-8 serializer receives them.
            for text in (p.destination, *labels):
                text.encode('utf-8')
            return RecommendationResponse(**{**parsed.model_dump(),'destination':p.destination}, provider=labels[0], model=labels[1])
        except Exception:
            raise RecommendationError('AI_INVALID_RESPONSE',502,'The AI response did not match the required recommendation format or preferences. No recommendations were accepted.') from None

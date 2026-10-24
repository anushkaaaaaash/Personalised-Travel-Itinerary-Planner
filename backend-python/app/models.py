"""Strict public API contract; database names and credentials never belong here."""
import math
import re
from datetime import date
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

INTERESTS = {'culture', 'food', 'adventure', 'nature', 'nightlife', 'shopping', 'relaxation', 'history'}
CONTROL = re.compile(r'[\x00-\x1f\x7f]')
JS_WHITESPACE = ' \t\n\r\v\f\u00a0\u1680\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009\u200a\u2028\u2029\u202f\u205f\u3000\ufeff'
def js_trim(value):
    return value.strip(JS_WHITESPACE)
def js_length(value):
    return len(value.encode('utf-16-le', errors='surrogatepass')) // 2

class TripPreferences(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    destination: str
    departureCity: str
    startDate: str
    endDate: str
    travelers: int = Field(ge=1, le=20)
    budget: float = Field(gt=0, allow_inf_nan=False)
    currency: Literal['USD', 'EUR', 'INR']
    interests: list[str]
    dietaryNeeds: Literal['', 'vegetarian', 'vegan', 'jain', 'halal']
    travelPace: Literal['relaxed', 'balanced', 'fast']
    travelStyle: Literal['', 'budget', 'comfort', 'luxury'] = ''
    mobilityConcerns: str = ''

    @field_validator('destination', 'departureCity')
    @classmethod
    def place(cls, value):
        if not js_trim(value) or js_length(js_trim(value)) > 200 or CONTROL.search(value):
            raise ValueError('Enter a place of 1–200 characters without control characters.')
        return js_trim(value)

    @field_validator('startDate', 'endDate')
    @classmethod
    def calendar_date(cls, value):
        if not re.fullmatch(r'[0-9]{4}-[0-9]{2}-[0-9]{2}', value):
            raise ValueError('Use a real YYYY-MM-DD date.')
        date.fromisoformat(value)
        return value

    @field_validator('travelers', mode='before')
    @classmethod
    def integral_travelers(cls, value):
        if type(value) is float and math.isfinite(value) and value.is_integer():
            return int(value)
        return value

    @field_validator('budget', mode='before')
    @classmethod
    def numeric_budget(cls, value):
        try:
            valid = type(value) in (int, float) and math.isfinite(value)
        except OverflowError:
            valid = False
        if not valid:
            raise ValueError('Budget must be a finite number greater than zero.')
        return value

    @field_validator('interests')
    @classmethod
    def unique_interests(cls, value):
        if len(value) > len(INTERESTS) or len(set(value)) != len(value) or not set(value) <= INTERESTS:
            raise ValueError('Choose unique interests from the listed options.')
        return value

    @field_validator('mobilityConcerns')
    @classmethod
    def mobility(cls, value):
        if js_length(js_trim(value)) > 500 or CONTROL.search(value):
            raise ValueError('Use at most 500 characters without control characters.')
        return js_trim(value)

    @model_validator(mode='after')
    def dates_in_order(self):
        if self.endDate < self.startDate:
            raise ValueError('End date must be on or after start date.')
        return self

class SavedTrip(BaseModel):
    id: int | str

class TripResponse(BaseModel):
    trip: SavedTrip

class Message(BaseModel):
    role: Literal['system', 'user']
    content: str

class PromptResponse(BaseModel):
    version: str
    messages: list[Message]
    tripDays: int
    totalGroupBudget: float
    indicativeDailyGroupBudget: str
    currency: str
    generated: Literal[False] = False

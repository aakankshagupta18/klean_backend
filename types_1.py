from pydantic import BaseModel
from typing import List, Dict
# Request model


class IngredientRequest(BaseModel):
    ingredients: List[str]

class Ingredient(BaseModel):
     id : str
     name: str
     is_safe: bool
     percentageifany: str = None
     description: str = None
     cases_where_harmful: List[str] = None

class IngredientResponse(BaseModel):
    known: List[Ingredient]
    unknown: List[str]

class SafetyPercentageRequest(BaseModel):
    payload: IngredientResponse


class AskRequest(BaseModel):
    question: str

class AskResponse(BaseModel):
    answer: str


class InputText(BaseModel):
    input_text: str
"""Closed label sets and request/response schemas for the Laya decision engine.

Laya may only pick from these predefined options. It never invents a category.
"""
from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field

MAX_TEXT_CHARS = 2000


class DQCategory(str, Enum):
    MISSING_REQUIRED_FIELD = "MISSING_REQUIRED_FIELD"
    DUPLICATE_RECORD = "DUPLICATE_RECORD"
    INVALID_DATE = "INVALID_DATE"
    INVALID_NUMERIC_VALUE = "INVALID_NUMERIC_VALUE"
    ORPHAN_FOREIGN_KEY = "ORPHAN_FOREIGN_KEY"
    INCONSISTENT_CATEGORY = "INCONSISTENT_CATEGORY"
    INVALID_BUSINESS_STATUS = "INVALID_BUSINESS_STATUS"
    TYPE_CONVERSION_ERROR = "TYPE_CONVERSION_ERROR"
    BUSINESS_RULE_VIOLATION = "BUSINESS_RULE_VIOLATION"
    UNKNOWN_ERROR = "UNKNOWN_ERROR"


class RouteCategory(str, Enum):
    KPI_QUERY = "KPI_QUERY"
    BUSINESS_ANALYSIS = "BUSINESS_ANALYSIS"
    DATA_QUALITY = "DATA_QUALITY"
    PIPELINE_STATUS = "PIPELINE_STATUS"
    REPROCESSING_REQUEST = "REPROCESSING_REQUEST"
    TECHNICAL_SUPPORT = "TECHNICAL_SUPPORT"
    GENERAL_QUESTION = "GENERAL_QUESTION"
    UNKNOWN = "UNKNOWN"


# Label descriptions given to Laya as `choice` criteria. Kept short and bilingual-neutral.
DQ_CRITERIA: dict[str, str] = {
    "MISSING_REQUIRED_FIELD": "A mandatory field is empty, blank or missing.",
    "DUPLICATE_RECORD": "The same record or the same ID appears more than once.",
    "INVALID_DATE": "A date value is impossible or cannot be parsed as a calendar date.",
    "INVALID_NUMERIC_VALUE": "A field that should be a number contains text or a non-numeric token.",
    "ORPHAN_FOREIGN_KEY": "A referenced ID does not exist in its master/parent table.",
    "INCONSISTENT_CATEGORY": "The same category is spelled with different casing, spacing or wording.",
    "INVALID_BUSINESS_STATUS": "A status value is not in the list of allowed statuses.",
    "TYPE_CONVERSION_ERROR": "Casting or converting a value to a database data type failed.",
    "BUSINESS_RULE_VIOLATION": "Values are well-formed but break a business rule, e.g. negative amount or end before start.",
    "UNKNOWN_ERROR": "An error with no identifiable cause or detail.",
}

ROUTE_CRITERIA: dict[str, str] = {
    "KPI_QUERY": "Asks for a specific metric value or count, e.g. total revenue, number of orders.",
    "BUSINESS_ANALYSIS": "Asks to compare, explain trends, causes or give business recommendations.",
    "DATA_QUALITY": "Asks about rejected, invalid, missing or quarantined data and validation results.",
    "PIPELINE_STATUS": "Asks whether the ETL pipeline ran, finished, failed, or when data was refreshed.",
    "REPROCESSING_REQUEST": "Asks to rerun, reload or reprocess data or a table.",
    "TECHNICAL_SUPPORT": "Asks for help with connections, errors, tools, setup or bot usage.",
    "GENERAL_QUESTION": "Greeting, asks what the assistant can do, or a general business/analytics concept.",
    "UNKNOWN": "Gibberish or a request unrelated to company analytics, data or this assistant.",
}

SEVERITY_LEVELS: list[str] = [
    "LOW: cosmetic issue, data still usable after standardisation",
    "MEDIUM: record must be corrected before it can be loaded",
    "HIGH: affects financial figures or many records; correct urgently",
]

TaskName = Literal["dq_category", "agent_route"]


class PredictRequest(BaseModel):
    task: TaskName
    text: str = Field(min_length=1, max_length=MAX_TEXT_CHARS)
    request_id: str | None = Field(default=None, max_length=64)
    run_id: str | None = Field(default=None, max_length=64)


class Decision(BaseModel):
    request_id: str
    task: TaskName
    label: str
    confidence: float
    band: Literal["HIGH", "MEDIUM", "LOW"]
    action: Literal["ACCEPT", "REVIEW", "FALLBACK"]
    source: Literal["laya", "rule_fallback"]
    checkpoint: str | None
    latency_ms: float
    fallback_used: bool
    error: str | None = None

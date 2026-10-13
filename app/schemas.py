"""
Pydantic schemas for the API request/response contract.
"""

from __future__ import annotations

from typing import Optional
from pydantic import BaseModel, Field


class ConfidenceScores(BaseModel):
    vendor: float = Field(..., ge=0.0, le=1.0)
    invoice_number: float = Field(..., ge=0.0, le=1.0)
    invoice_date: float = Field(..., ge=0.0, le=1.0)
    due_date: float = Field(..., ge=0.0, le=1.0)
    currency: float = Field(..., ge=0.0, le=1.0)
    subtotal: float = Field(..., ge=0.0, le=1.0)
    tax: float = Field(..., ge=0.0, le=1.0)
    total: float = Field(..., ge=0.0, le=1.0)


class ExtractionResult(BaseModel):
    vendor: str
    invoice_number: Optional[str] = None
    invoice_date: Optional[str] = None   # ISO YYYY-MM-DD or null
    due_date: Optional[str] = None       # ISO YYYY-MM-DD or null
    currency: str
    subtotal: Optional[float] = None
    tax: Optional[float] = None
    total: Optional[float] = None
    confidence: ConfidenceScores
    warnings: list[str] = Field(default_factory=list)


class HealthResponse(BaseModel):
    status: str = "ok"

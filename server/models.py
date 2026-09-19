from typing import Literal

from pydantic import BaseModel, Field


class VenueRequest(BaseModel):
    name: str = Field(min_length=2, max_length=160)
    website: str = Field(min_length=8, max_length=2000)
    track: str = Field(default="", max_length=160)


class VenueSource(BaseModel):
    url: str
    title: str
    retrieved_at: str
    sha256: str
    passages: list[str]


class VenueContext(BaseModel):
    name: str
    website: str
    track: str = ""
    sources: list[VenueSource]
    warnings: list[str] = Field(default_factory=list)


class Section(BaseModel):
    id: str
    title: str
    role: str
    page_start: int
    page_end: int
    text: str
    word_count: int


class Paper(BaseModel):
    title: str
    filename: str
    pages: int
    word_count: int
    sha256: str
    sections: list[Section]
    warnings: list[str] = Field(default_factory=list)


class Dimension(BaseModel):
    key: str
    label: str
    score: float = Field(ge=0, le=100)
    confidence: float = Field(ge=0, le=1)
    weight: float
    probabilities: dict[str, float]
    finding: str
    suggestion: str


class SectionResult(BaseModel):
    section_id: str
    score: float
    confidence: float
    dimensions: list[Dimension]
    excerpt: str
    chunk_count: int
    latency_ms: int
    model: str


class Summary(BaseModel):
    score: float | None
    confidence: float | None
    decision: str
    complete: bool
    reviewed: int
    total: int
    dimensions: dict[str, float]
    section_weights: dict[str, float]
    strengths: list[str]
    improvements: list[str]
    notes: list[str]


class ReviewReport(BaseModel):
    review_id: str
    created_at: str
    paper: Paper
    results: list[SectionResult]
    summary: Summary
    rubric_version: str
    profile: Literal["research", "survey", "theory"]
    elapsed_ms: int
    input_tokens: int = 0
    output_tokens: int = 0
    venue: VenueContext | None = None

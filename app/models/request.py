"""Request models for SEO Outreach Agent API."""

from typing import Optional
from pydantic import BaseModel, Field, field_validator
from app.utils.validation import sanitize_query, sanitize_location, sanitize_url


class SEOOutreachRequest(BaseModel):
    """Request model for SEO outreach processing."""

    query: str = Field(
        ...,
        min_length=1,
        max_length=200,
        description="Search keyword for Google Maps (e.g., 'restaurants', 'dentists')",
    )
    location: Optional[str] = Field(
        None,
        max_length=200,
        description="Location for search (e.g., 'New York, NY')",
    )
    max_results: Optional[int] = Field(
        default=20,
        ge=1,
        le=100,
        description="Maximum number of companies to process (1-100)",
    )
    send_emails: bool = Field(
        default=False,
        description="Whether to actually send emails (default: False)",
    )
    generate_pdf: bool = Field(
        default=False,
        description="Whether to generate PDF reports for SEO analysis (default: False)",
    )

    @field_validator("query")
    @classmethod
    def validate_query(cls, v: str) -> str:
        """Validate and sanitize query."""
        return sanitize_query(v)

    @field_validator("location")
    @classmethod
    def validate_location(cls, v: Optional[str]) -> Optional[str]:
        """Validate and sanitize location."""
        if v is None:
            return None
        return sanitize_location(v)

    @field_validator("max_results")
    @classmethod
    def validate_max_results(cls, v: Optional[int]) -> int:
        """Validate max_results."""
        if v is None:
            return 20
        if v < 1:
            raise ValueError("max_results must be at least 1")
        if v > 100:
            raise ValueError("max_results cannot exceed 100")
        return v

    class Config:
        """Pydantic config."""

        json_schema_extra = {
            "example": {
                "query": "digital marketing agency",
                "location": "California, USA",
                "max_results": 10,
                "send_emails": False,
                "generate_pdf": False,
            }
        }


class EmailFindRequest(BaseModel):
    """Request model for finding emails from a website."""

    website: str = Field(
        ...,
        description="Website URL to scrape for emails",
    )

    @field_validator("website")
    @classmethod
    def validate_website(cls, v: str) -> str:
        """Validate and sanitize website URL."""
        return sanitize_url(v)

    class Config:
        """Pydantic config."""

        json_schema_extra = {
            "example": {
                "website": "https://example.com",
            }
        }


class SEOAnalysisRequest(BaseModel):
    """Request model for SEO analysis."""

    website_url: str = Field(
        ...,
        description="Website URL to analyze",
    )
    analyze_multiple_pages: bool = Field(
        default=True,
        description="If True, also analyze key pages (About, Services, Contact)",
    )

    @field_validator("website_url")
    @classmethod
    def validate_website_url(cls, v: str) -> str:
        """Validate and sanitize website URL."""
        return sanitize_url(v)

    class Config:
        """Pydantic config."""

        json_schema_extra = {
            "example": {
                "website_url": "https://example.com",
                "analyze_multiple_pages": True,
            }
        }


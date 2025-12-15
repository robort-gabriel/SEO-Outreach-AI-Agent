"""Response models for SEO Outreach Agent API."""

from typing import Optional, List, Dict, Any
from datetime import datetime
from pydantic import BaseModel, Field


class CompanyInfo(BaseModel):
    """Company information model."""

    name: str = Field(..., description="Company name")
    address: Optional[str] = Field(None, description="Company address")
    phone: Optional[str] = Field(None, description="Phone number")
    website: Optional[str] = Field(None, description="Website URL")
    email: Optional[str] = Field(None, description="Contact email")
    email_subject: Optional[str] = Field(None, description="Generated email subject")
    email_body: Optional[str] = Field(None, description="Generated email body (HTML)")
    email_sending_status: Optional[str] = Field(
        None, description="Email sending status"
    )
    seo_score: Optional[int] = Field(None, description="SEO score (0-100)")
    rating: Optional[float] = Field(None, description="Google Maps rating")
    reviews: Optional[int] = Field(None, description="Number of reviews")


class SEOOutreachResponse(BaseModel):
    """Response model for SEO outreach processing."""

    query: str = Field(..., description="Search query")
    location: Optional[str] = Field(None, description="Search location")
    status: str = Field(..., description="Processing status")
    timestamp: str = Field(..., description="Timestamp of response")
    results: Dict[str, Any] = Field(
        ...,
        description="Results containing companies and statistics",
    )
    error: Optional[str] = Field(None, description="Error message if any")

    class Config:
        """Pydantic config."""

        json_schema_extra = {
            "example": {
                "query": "digital marketing agency",
                "location": "California, USA",
                "status": "completed",
                "timestamp": "2024-01-15T10:30:00",
                "results": {
                    "total_companies": 10,
                    "companies_with_emails": 8,
                    "companies_with_seo_analysis": 10,
                    "emails_generated": 8,
                    "emails_sent": 0,
                    "companies": [],
                },
            }
        }


class EmailFindResponse(BaseModel):
    """Response model for email finding."""

    success: bool = Field(..., description="Whether the operation was successful")
    website: str = Field(..., description="Website URL")
    emails: List[str] = Field(default_factory=list, description="Found email addresses")
    phone_numbers: List[str] = Field(
        default_factory=list, description="Found phone numbers"
    )
    error: Optional[str] = Field(None, description="Error message if any")

    class Config:
        """Pydantic config."""

        json_schema_extra = {
            "example": {
                "success": True,
                "website": "https://example.com",
                "emails": ["contact@example.com", "info@example.com"],
                "phone_numbers": ["+1-555-123-4567"],
            }
        }


class SEOAnalysisResponse(BaseModel):
    """Response model for SEO analysis."""

    success: bool = Field(..., description="Whether the analysis was successful")
    website_url: str = Field(..., description="Website URL analyzed")
    overall_score: int = Field(..., description="Overall SEO score (0-100)")
    seo_audit: Dict[str, Any] = Field(
        ..., description="Detailed SEO audit results"
    )
    pages_analyzed: int = Field(..., description="Number of pages analyzed")
    error: Optional[str] = Field(None, description="Error message if any")

    class Config:
        """Pydantic config."""

        json_schema_extra = {
            "example": {
                "success": True,
                "website_url": "https://example.com",
                "overall_score": 75,
                "pages_analyzed": 4,
                "seo_audit": {
                    "overall_seo_score": 75,
                    "priority_fixes": [],
                },
            }
        }


class HealthResponse(BaseModel):
    """Health check response model."""

    status: str = Field(..., description="Service status")
    timestamp: str = Field(..., description="Current timestamp")
    version: str = Field(..., description="API version")

    class Config:
        """Pydantic config."""

        json_schema_extra = {
            "example": {
                "status": "healthy",
                "timestamp": "2024-01-15T10:30:00",
                "version": "1.0.0",
            }
        }


class ErrorResponse(BaseModel):
    """Error response model."""

    detail: str = Field(..., description="Error message")
    error_id: Optional[str] = Field(None, description="Error ID for tracking")
    timestamp: str = Field(..., description="Error timestamp")

    class Config:
        """Pydantic config."""

        json_schema_extra = {
            "example": {
                "detail": "An error occurred",
                "error_id": "ValidationException",
                "timestamp": "2024-01-15T10:30:00",
            }
        }


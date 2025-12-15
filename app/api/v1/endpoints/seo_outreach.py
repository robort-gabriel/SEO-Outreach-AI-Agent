"""SEO Outreach API endpoints."""

import logging
from datetime import datetime
from fastapi import APIRouter, Request, HTTPException, status
from slowapi.util import get_remote_address

from app.models.request import SEOOutreachRequest
from app.models.response import SEOOutreachResponse
from app.core.exceptions import (
    ValidationException,
    ProcessingException,
    ExternalServiceException,
)
from app.config import settings
from app.middleware import limiter

# Import the agent
import sys
from pathlib import Path

# Add parent directory to path to import agent
# app/api/v1/endpoints/seo_outreach.py -> seo_outreach_agent/
ROOT_DIR = Path(__file__).resolve().parents[3]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from seo_outreach_agent import SEOOutreachAgent

logger = logging.getLogger(__name__)

router = APIRouter()

# Initialize agent (singleton)
_agent_instance = None


def get_agent() -> SEOOutreachAgent:
    """Get or create SEO Outreach Agent instance."""
    global _agent_instance
    if _agent_instance is None:
        _agent_instance = SEOOutreachAgent()
    return _agent_instance


@router.post(
    "/process",
    response_model=SEOOutreachResponse,
    status_code=status.HTTP_200_OK,
    summary="Process complete SEO outreach workflow",
    description="""
    Run the complete SEO outreach workflow end-to-end:
    1. Extract companies from Google Maps based on query and location
    2. Enrich companies with email addresses from their websites
    3. Analyze websites for SEO issues and opportunities
    4. Optionally generate PDF reports for SEO analysis (if generate_pdf=True)
    5. Generate personalized outreach emails highlighting SEO problems
    6. Optionally send emails with PDF attachments (if send_emails=True)
    
    This is the main endpoint - it runs the entire workflow in one request, just like the original agent.
    """,
)
@limiter.limit(f"{settings.rate_limit_per_minute}/minute")
async def process_seo_outreach(
    request: Request, payload: SEOOutreachRequest
) -> SEOOutreachResponse:
    """
    Process SEO outreach workflow.

    This endpoint:
    1. Extracts companies from Google Maps based on query and location
    2. Enriches companies with email addresses
    3. Analyzes websites for SEO issues
    4. Optionally generates PDF reports (if generate_pdf=True)
    5. Generates personalized outreach emails
    6. Optionally sends emails with PDF attachments (if send_emails=True)

    Args:
        request: FastAPI request object
        payload: SEO outreach request payload

    Returns:
        SEOOutreachResponse: Results with companies and statistics

    Raises:
        HTTPException: If processing fails
    """
    try:
        logger.info(
            f"Processing SEO outreach: query='{payload.query}', "
            f"location='{payload.location}', max_results={payload.max_results}"
        )

        # Get agent instance
        agent = get_agent()

        # Process the request
        result = await agent.process(
            query=payload.query,
            location=payload.location,
            max_results=payload.max_results,
            send_emails=payload.send_emails,
            generate_pdf=payload.generate_pdf,
            save_output=True,
        )

        # Check for errors
        if result.get("status") == "failed" or result.get("error"):
            raise ProcessingException(
                result.get("error", "Processing failed"),
                error_id="ProcessingFailed",
            )

        # Return response
        return SEOOutreachResponse(
            query=result.get("query", payload.query),
            location=result.get("location", payload.location),
            status=result.get("status", "completed"),
            timestamp=result.get("timestamp", datetime.now().isoformat()),
            results=result.get("results", {}),
            error=result.get("error"),
        )

    except ValidationException as e:
        logger.error(f"Validation error: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(e.message),
        )
    except ProcessingException as e:
        logger.error(f"Processing error: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e.message),
        )
    except ExternalServiceException as e:
        logger.error(f"External service error: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="External service error. Please try again later.",
        )
    except Exception as e:
        logger.error(f"Unexpected error: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred. Please try again later.",
        )

"""Custom exception classes for SEO Outreach Agent API."""


class SEOOutreachException(Exception):
    """Base exception for SEO Outreach Agent."""

    def __init__(self, message: str, error_id: str = None):
        """Initialize exception."""
        self.message = message
        self.error_id = error_id or self.__class__.__name__
        super().__init__(self.message)


class ValidationException(SEOOutreachException):
    """Exception for validation errors."""

    pass


class ProcessingException(SEOOutreachException):
    """Exception for processing errors."""

    pass


class ExternalServiceException(SEOOutreachException):
    """Exception for external service errors."""

    pass


class RateLimitException(SEOOutreachException):
    """Exception for rate limit errors."""

    pass


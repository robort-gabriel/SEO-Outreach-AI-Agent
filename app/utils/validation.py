"""Input validation and sanitization utilities."""

import re
import html
from typing import Optional
from urllib.parse import urlparse


def sanitize_string(input_str: str, max_length: Optional[int] = None) -> str:
    """
    Sanitize user input to prevent XSS and injection attacks.

    Args:
        input_str: Input string to sanitize
        max_length: Maximum length allowed (None for no limit)

    Returns:
        Sanitized string
    """
    if not isinstance(input_str, str):
        input_str = str(input_str)

    # Remove HTML tags
    cleaned = re.sub(r"<[^>]+>", "", input_str)
    # Escape HTML entities
    cleaned = html.escape(cleaned)
    # Remove null bytes
    cleaned = cleaned.replace("\x00", "")
    # Remove control characters except newlines and tabs
    cleaned = re.sub(r"[\x00-\x08\x0B-\x0C\x0E-\x1F\x7F]", "", cleaned)
    # Trim whitespace
    cleaned = cleaned.strip()

    # Apply length limit if specified
    if max_length and len(cleaned) > max_length:
        cleaned = cleaned[:max_length]

    return cleaned


def validate_url(url: str) -> bool:
    """
    Validate URL format.

    Args:
        url: URL to validate

    Returns:
        True if valid, False otherwise
    """
    if not url or not isinstance(url, str):
        return False

    try:
        result = urlparse(url)
        return all([result.scheme, result.netloc]) and result.scheme in [
            "http",
            "https",
        ]
    except Exception:
        return False


def sanitize_url(url: str) -> str:
    """
    Sanitize and validate URL.

    Args:
        url: URL to sanitize

    Returns:
        Sanitized URL

    Raises:
        ValueError: If URL is invalid
    """
    if not url:
        raise ValueError("URL cannot be empty")

    url = sanitize_string(url, max_length=2048)
    url = url.strip()

    if not validate_url(url):
        raise ValueError("Invalid URL format")

    return url


def validate_email(email: str) -> bool:
    """
    Validate email format.

    Args:
        email: Email to validate

    Returns:
        True if valid, False otherwise
    """
    if not email or not isinstance(email, str):
        return False

    # Basic email regex pattern
    pattern = r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$"
    return bool(re.match(pattern, email))


def sanitize_email(email: str) -> str:
    """
    Sanitize and validate email.

    Args:
        email: Email to sanitize

    Returns:
        Sanitized email

    Raises:
        ValueError: If email is invalid
    """
    if not email:
        raise ValueError("Email cannot be empty")

    email = sanitize_string(email, max_length=254).lower().strip()

    if not validate_email(email):
        raise ValueError("Invalid email format")

    return email


def sanitize_query(query: str) -> str:
    """
    Sanitize search query.

    Args:
        query: Search query to sanitize

    Returns:
        Sanitized query
    """
    if not query:
        raise ValueError("Query cannot be empty")

    query = sanitize_string(query, max_length=200)
    if not query:
        raise ValueError("Query cannot be empty after sanitization")

    return query


def sanitize_location(location: str) -> str:
    """
    Sanitize location string.

    Args:
        location: Location string to sanitize

    Returns:
        Sanitized location
    """
    if not location:
        return ""

    return sanitize_string(location, max_length=200)


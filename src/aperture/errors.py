"""Shared error foundation for the aperture library.

Provides a common ``ApertureError`` base so consumers can distinguish
library-raised validation failures from arbitrary bugs, plus small typed
helpers (e.g. :func:`require_nonempty`) used to unify recurring validation.

Backward compatibility note: library-specific errors are layered onto the
appropriate built-in via *multiple inheritance* (e.g. ``EmptyFieldError``
subclasses both ``ApertureError`` and ``ValueError``) so existing call sites
that catch the built-in (``except ValueError``/``except KeyError``/
``except RuntimeError``) keep working unchanged.
"""

from __future__ import annotations

__all__ = [
    "ApertureError",
    "EmptyFieldError",
    "require_nonempty",
]


class ApertureError(Exception):
    """Base for all errors raised by the aperture library.

    Consumers can ``except ApertureError`` to distinguish library validation
    failures from arbitrary bugs. Concrete error types additionally inherit
    from the relevant built-in (e.g. ``ValueError``) via multiple inheritance,
    so pre-existing ``except <builtin>`` handlers continue to match.
    """


class EmptyFieldError(ApertureError, ValueError):
    """Raised when a required string field is missing or blank.

    Inherits from ``ValueError`` so existing ``except ValueError`` handlers
    around the unified empty-field validation keep working.
    """


def require_nonempty(value: str, field: str) -> None:
    """Validate that ``value`` is a non-empty, non-whitespace string.

    Raises :class:`EmptyFieldError` (an ``ApertureError`` and ``ValueError``)
    when ``value`` is ``None`` or strips to the empty string. Used to unify
    the empty ``reason``/``by`` validation across the library.

    Args:
        value: The string to validate.
        field: Human-readable field name used in the error message.
    """
    if value is None or not value.strip():
        raise EmptyFieldError(f"{field} requires a non-empty value")

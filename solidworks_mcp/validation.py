"""Tool argument validation with hints a model can act on.

Checks run before the document guard, so a bad call never binds a document or
reaches COM. Unknown argument names are always rejected, also when a schema
allows extra properties: a misspelled name would otherwise fall back silently
to the handler default.
"""

import difflib
from typing import Dict

from jsonschema.exceptions import best_match


class ArgumentError(ValueError):
    """An argument does not match the tool schema."""

    def __init__(self, argument: str, message: str):
        super().__init__(message)
        self.argument = argument


def _closest(value, candidates):
    matches = difflib.get_close_matches(str(value), [str(item) for item in candidates],
                                        n=1, cutoff=0.6)
    return matches[0] if matches else None


def _path(parts) -> str:
    text = ""
    for part in parts:
        text += f"[{part}]" if isinstance(part, int) else (f".{part}" if text else str(part))
    return text


def validate_arguments(schema: Dict, validator, arguments: Dict) -> Dict:
    """Return the arguments without top-level None values, or raise ArgumentError."""
    cleaned = {key: value for key, value in arguments.items() if value is not None}
    properties = schema.get("properties")
    if properties is not None:
        for key in sorted(cleaned):
            if key in properties:
                continue
            guess = _closest(key, properties)
            hint = (f"Did you mean '{guess}'?" if guess
                    else f"Valid arguments: {', '.join(sorted(properties))}.")
            raise ArgumentError(key, f"Unknown argument '{key}'. {hint}")
    error = best_match(sorted(validator.iter_errors(cleaned), key=lambda error: list(error.absolute_path)))
    if error is None:
        return cleaned
    parts = list(error.absolute_path)
    if error.validator == "required":
        missing = error.message.split("'")[1]
        parts = parts + [missing]
    argument = _path(parts) or "arguments"
    message = f"Invalid argument '{argument}': {error.message}"
    if error.validator == "enum":
        guess = _closest(error.instance, error.validator_value)
        if guess is not None:
            message += f". Did you mean '{guess}'?"
    raise ArgumentError(argument, message)

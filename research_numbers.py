"""Small numeric helpers shared by research modules (previously copied per file)."""
import math


def finite_number(value):
    """A real finite int/float (numpy floats included); booleans are not numbers."""
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def strict_finite_number(value):
    """Exactly a built-in int or float and finite (subclasses such as numpy floats excluded)."""
    return type(value) in (int, float) and math.isfinite(value)


def parse_number(value):
    """float(value) when finite, else None; booleans are rejected."""
    if isinstance(value, bool):
        return None
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (ValueError, TypeError):
        return None


def clamp(value, low, high):
    return max(low, min(high, value))

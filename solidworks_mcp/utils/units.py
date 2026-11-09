"""
SolidWorks MCP Unit Conversion
------------------------------
Handle unit conversions for SolidWorks API (which uses meters internally).
"""

from enum import Enum
from typing import Union, Tuple
import logging

from ..core.contracts import QuantityValidationError

logger = logging.getLogger(__name__)


class Unit(Enum):
    """Supported units"""
    METER = "m"
    MILLIMETER = "mm"
    CENTIMETER = "cm"
    INCH = "inch"
    FOOT = "ft"


# Conversion factors TO meters (multiply input by factor)
TO_METERS = {
    Unit.METER: 1.0,
    Unit.MILLIMETER: 0.001,
    Unit.CENTIMETER: 0.01,
    Unit.INCH: 0.0254,
    Unit.FOOT: 0.3048,
}

# Conversion factors FROM meters (multiply meters by factor)
FROM_METERS = {unit: 1.0 / factor for unit, factor in TO_METERS.items()}

# String aliases for units
UNIT_ALIASES = {
    "m": Unit.METER,
    "meter": Unit.METER,
    "meters": Unit.METER,
    "mm": Unit.MILLIMETER,
    "millimeter": Unit.MILLIMETER,
    "millimeters": Unit.MILLIMETER,
    "cm": Unit.CENTIMETER,
    "centimeter": Unit.CENTIMETER,
    "centimeters": Unit.CENTIMETER,
    "inch": Unit.INCH,
    "in": Unit.INCH,
    "inches": Unit.INCH,
    "\"": Unit.INCH,
    "ft": Unit.FOOT,
    "foot": Unit.FOOT,
    "feet": Unit.FOOT,
    "'": Unit.FOOT,
}


class UnitConverter:
    """
    Handle unit conversions for SolidWorks API
    
    SolidWorks API uses meters internally for all dimensions.
    This class converts user-friendly units to/from meters.
    
    Example:
        converter = UnitConverter("mm")
        meters = converter.to_meters(50)  # 0.05
        mm = converter.from_meters(0.05)  # 50.0
    """
    
    def __init__(self, default_unit: str = "mm"):
        """
        Initialize converter with default unit
        
        Args:
            default_unit: Default unit for conversions (mm, inch, m, cm, ft)
        """
        self._default_unit = self._parse_unit(default_unit)
        logger.debug(f"UnitConverter initialized with default: {self._default_unit.value}")
    
    @property
    def default_unit(self) -> Unit:
        """Get default unit"""
        return self._default_unit
    
    @default_unit.setter
    def default_unit(self, value: str):
        """Set default unit"""
        self._default_unit = self._parse_unit(value)
    
    def _parse_unit(self, unit: Union[str, Unit]) -> Unit:
        """
        Parse unit string to Unit enum.

        Args:
            unit: Unit string or enum

        Returns:
            Unit enum value

        Raises:
            QuantityValidationError: if the unit is not a known length unit.
                Silently falling back to millimetres used to turn a typo such as
                ``unit="furlong"`` into a valid but wrong geometry, so an
                unknown unit is refused instead.
        """
        if isinstance(unit, Unit):
            return unit

        if isinstance(unit, str):
            unit_lower = unit.lower().strip()
            if unit_lower in UNIT_ALIASES:
                return UNIT_ALIASES[unit_lower]

        choices = ", ".join(sorted(UNIT_ALIASES))
        raise QuantityValidationError(
            f"Unsupported unit '{unit}'. Supported units: {choices}."
        )
    
    def to_meters(self, value: float, unit: str = None) -> float:
        """
        Convert value to meters for SolidWorks API
        
        Args:
            value: Dimension value
            unit: Unit of value (uses default if None)
        
        Returns:
            Value in meters
        
        Example:
            converter.to_meters(50, "mm")  # Returns 0.05
            converter.to_meters(2, "inch")  # Returns 0.0508
        """
        if unit is None:
            parsed_unit = self._default_unit
        else:
            parsed_unit = self._parse_unit(unit)
        
        return value * TO_METERS[parsed_unit]
    
    def from_meters(self, value: float, unit: str = None) -> float:
        """
        Convert value from meters to display unit
        
        Args:
            value: Value in meters
            unit: Target unit (uses default if None)
        
        Returns:
            Value in specified unit
        
        Example:
            converter.from_meters(0.05, "mm")  # Returns 50.0
            converter.from_meters(0.0254, "inch")  # Returns 1.0
        """
        if unit is None:
            parsed_unit = self._default_unit
        else:
            parsed_unit = self._parse_unit(unit)
        
        return value * FROM_METERS[parsed_unit]
    
    def convert(self, value: float, from_unit: str, to_unit: str) -> float:
        """
        Convert between any two units
        
        Args:
            value: Input value
            from_unit: Source unit
            to_unit: Target unit
        
        Returns:
            Converted value
        
        Example:
            converter.convert(25.4, "mm", "inch")  # Returns 1.0
        """
        meters = self.to_meters(value, from_unit)
        return self.from_meters(meters, to_unit)
    
    def format_dimension(self, value_meters: float, unit: str = None, precision: int = 2) -> str:
        """
        Format dimension with unit suffix
        
        Args:
            value_meters: Value in meters
            unit: Display unit (uses default if None)
            precision: Decimal places
        
        Returns:
            Formatted string like "50.00mm"
        """
        if unit is None:
            parsed_unit = self._default_unit
        else:
            parsed_unit = self._parse_unit(unit)
        
        display_value = self.from_meters(value_meters, unit)
        return f"{display_value:.{precision}f}{parsed_unit.value}"


# ============================================================================
# Convenience Functions
# ============================================================================

def mm(value: float) -> float:
    """Convert millimeters to meters"""
    return value * 0.001


def cm(value: float) -> float:
    """Convert centimeters to meters"""
    return value * 0.01


def inch(value: float) -> float:
    """Convert inches to meters"""
    return value * 0.0254


def ft(value: float) -> float:
    """Convert feet to meters"""
    return value * 0.3048


def to_mm(meters: float) -> float:
    """Convert meters to millimeters"""
    return meters * 1000


def to_inch(meters: float) -> float:
    """Convert meters to inches"""
    return meters / 0.0254


# ============================================================================
# Global Converter Instance
# ============================================================================

# Default converter (uses mm)
_default_converter = UnitConverter("mm")


def get_converter() -> UnitConverter:
    """Get global unit converter"""
    return _default_converter


def set_default_unit(unit: str) -> None:
    """Set default unit for global converter"""
    _default_converter.default_unit = unit
    logger.info(f"Default unit set to: {unit}")

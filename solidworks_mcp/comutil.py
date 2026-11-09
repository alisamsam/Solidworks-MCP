"""
COM member access helpers for SolidWorks automation.

SolidWorks exposes some members as properties and others as methods, and the
distinction is not predictable from the type library. See docs/api-findings.md.
"""

import inspect
from typing import Any


def com(obj: Any, name: str, *args) -> Any:
    """
    Access a COM member regardless of whether it is a property or a method.

    win32com returns a bound method only when DISPATCH_PROPERTYGET failed;
    otherwise attribute access has already returned the value. Testing with
    callable() does not work, because CDispatch is always callable.

    Args:
        obj: COM object
        name: Member name
        *args: Arguments, if the member takes any

    Returns:
        The member value
    """
    value = getattr(obj, name)
    return value(*args) if inspect.ismethod(value) else value


def set_com(obj: Any, name: str, value: Any) -> None:
    """
    Set a COM property that ``com()`` can only read.

    A property put is a plain attribute assignment in dynamic dispatch: calling
    ``obj.Member(value)`` would dispatch ``DISPATCH_PROPERTYGET`` with an
    argument instead, which SolidWorks silently ignores for members such as
    ``ISketchSegment.ConstructionGeometry``.
    """
    setattr(obj, name, value)

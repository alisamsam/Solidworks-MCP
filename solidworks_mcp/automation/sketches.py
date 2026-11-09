"""
SolidWorks Sketch Operations
----------------------------
Create sketches and draw 2D geometry.
"""

import math
import logging
import traceback
from typing import Optional, Dict, List, Tuple

import win32com.client
import pythoncom

from ..constants import SwErrors, SwPlanes

logger = logging.getLogger(__name__)


class SketchOperations:
    """
    Mixin class for sketch operations
    
    Requires parent class to have:
    - get_active_doc(): Document access method
    - _result(): Result factory method
    - _units: UnitConverter instance
    """
    
    def create_sketch(self, plane: str = "Front", exact_geometry: bool = False) -> Dict:
        """
        Create a new sketch on specified plane
        
        Args:
            plane: Plane name - "Front", "Top", or "Right"
            exact_geometry: Disable automatic relations and snapping while drawing
        
        Returns:
            Result dictionary
        """
        try:
            doc, err = self.get_active_doc()
            if err:
                return err
            
            # Only the three standard planes; SwPlanes.get would silently
            # map any other name to Front Plane.
            if str(plane).lower() not in ("front", "top", "right"):
                return self._result(False,
                    f"Unknown plane '{plane}'. Use Front, Top or Right, or "
                    "create_sketch_on_plane for a named plane.",
                    SwErrors.swInvalidInput)
            plane_name = SwPlanes.get(plane)
            
            # Create empty variant for callout parameter
            empty_callout = win32com.client.VARIANT(pythoncom.VT_DISPATCH, None)
            
            # Select plane
            result = doc.Extension.SelectByID2(
                plane_name, "PLANE", 0, 0, 0, False, 0, empty_callout, 0
            )
            
            if not result:
                return self._result(False, f"Could not select {plane_name}",
                                  SwErrors.swSelectionError)
            
            # Insert sketch
            doc.InsertSketch2(True)
            doc.SketchManager.AddToDB = exact_geometry
            
            return self._result(True, f"Sketch created on {plane_name}",
                              SwErrors.swSuccess, {"plane": plane_name,
                                                   "exact_geometry": exact_geometry})
            
        except Exception as e:
            logger.error(f"Create sketch error: {e}\n{traceback.format_exc()}")
            return self._result(False, f"Error: {e}", SwErrors.swSketchError)
    
    def create_sketch_on_face(self, x: float = 0, y: float = 0, z: float = 0,
                              unit: str = None, exact_geometry: bool = False) -> Dict:
        """
        Create a new sketch on a face selected by coordinate.
        ADDED v4.1: Enables cut-extrude on existing body faces (not just ref planes).
        
        Args:
            x, y, z: Coordinates (in user units) of a point ON the target face
            unit: Unit for coordinates (uses default if None)
        
        Returns:
            Result dictionary
        """
        try:
            doc, err = self.get_active_doc()
            if err:
                return err
            
            # Convert to meters
            x_m = self._units.to_meters(x, unit)
            y_m = self._units.to_meters(y, unit)
            z_m = self._units.to_meters(z, unit)
            unit_str = unit or self._units.default_unit.value
            
            # Clear any selection
            doc.ClearSelection2(True)
            
            # Select face at the given coordinates
            empty_callout = win32com.client.VARIANT(pythoncom.VT_DISPATCH, None)
            selected = doc.Extension.SelectByID2(
                "", "FACE", x_m, y_m, z_m, False, 0, empty_callout, 0
            )
            
            if not selected:
                return self._result(False,
                    f"No face found at ({x}{unit_str}, {y}{unit_str}, {z}{unit_str}). "
                    f"Coordinates must be on an existing body face.",
                    SwErrors.swSelectionError)
            
            # Insert sketch on the selected face
            doc.InsertSketch2(True)
            doc.SketchManager.AddToDB = exact_geometry
            
            return self._result(True,
                f"Sketch created on face at ({x}, {y}, {z}) {unit_str}",
                SwErrors.swSuccess,
                {"face_point": {"x": x, "y": y, "z": z}, "unit": unit_str,
                 "exact_geometry": exact_geometry})
            
        except Exception as e:
            logger.error(f"Create sketch on face error: {e}\n{traceback.format_exc()}")
            return self._result(False, f"Error: {e}", SwErrors.swSketchError)
    
    def exit_sketch(self) -> Dict:
        """
        Exit the current sketch
        
        Returns:
            Result dictionary
        """
        try:
            doc, err = self.get_active_doc()
            if err:
                return err
            
            doc.SketchManager.AddToDB = False
            doc.InsertSketch2(True)
            
            return self._result(True, "Exited sketch", SwErrors.swSuccess)
            
        except Exception as e:
            return self._result(False, f"Error: {e}", SwErrors.swSketchError)
    
    def draw_line(self, x1: float = 0, y1: float = 0, 
                  x2: float = 100, y2: float = 0, unit: str = None) -> Dict:
        """
        Draw a line in the active sketch
        
        Args:
            x1, y1: Start point coordinates
            x2, y2: End point coordinates
            unit: Unit for coordinates (uses default if None)
        
        Returns:
            Result dictionary
        """
        try:
            doc, err = self.get_active_doc()
            if err:
                return err
            
            # Convert to meters
            x1_m = self._units.to_meters(x1, unit)
            y1_m = self._units.to_meters(y1, unit)
            x2_m = self._units.to_meters(x2, unit)
            y2_m = self._units.to_meters(y2, unit)
            
            # Draw line
            line = doc.SketchManager.CreateLine(x1_m, y1_m, 0, x2_m, y2_m, 0)
            
            if line is None:
                return self._result(False, "Failed - ensure sketch is active",
                                  SwErrors.swSketchError)
            
            # Calculate length
            length_m = math.sqrt((x2_m - x1_m)**2 + (y2_m - y1_m)**2)
            length_display = self._units.from_meters(length_m, unit)
            unit_str = unit or self._units.default_unit.value
            
            return self._result(True, f"Line: {length_display:.2f}{unit_str}",
                              SwErrors.swSuccess,
                              {"length": length_display, "unit": unit_str})
            
        except Exception as e:
            logger.error(f"Draw line error: {e}\n{traceback.format_exc()}")
            return self._result(False, f"Error: {e}", SwErrors.swSketchError)
    
    def draw_circle(self, x: float = 0, y: float = 0, 
                    radius: float = 25, unit: str = None) -> Dict:
        """
        Draw a circle in the active sketch
        
        Args:
            x, y: Center point coordinates
            radius: Circle radius
            unit: Unit for dimensions (uses default if None)
        
        Returns:
            Result dictionary
        """
        try:
            doc, err = self.get_active_doc()
            if err:
                return err
            
            # Convert to meters
            x_m = self._units.to_meters(x, unit)
            y_m = self._units.to_meters(y, unit)
            radius_m = self._units.to_meters(radius, unit)
            
            # Draw circle (center point and edge point)
            circle = doc.SketchManager.CreateCircle(
                x_m, y_m, 0,              # Center
                x_m + radius_m, y_m, 0    # Edge point
            )
            
            if circle is None:
                return self._result(False, "Failed - ensure sketch is active",
                                  SwErrors.swSketchError)
            
            unit_str = unit or self._units.default_unit.value
            
            return self._result(True, f"Circle: r={radius}{unit_str}",
                              SwErrors.swSuccess,
                              {"radius": radius, "unit": unit_str,
                               "center_x": x, "center_y": y})
            
        except Exception as e:
            logger.error(f"Draw circle error: {e}\n{traceback.format_exc()}")
            return self._result(False, f"Error: {e}", SwErrors.swSketchError)
    
    def draw_rectangle(self, x1: float = -50, y1: float = -25,
                       x2: float = 50, y2: float = 25, unit: str = None) -> Dict:
        """
        Draw a rectangle in the active sketch
        
        Args:
            x1, y1: First corner coordinates
            x2, y2: Opposite corner coordinates
            unit: Unit for dimensions
        
        Returns:
            Result dictionary
        """
        try:
            doc, err = self.get_active_doc()
            if err:
                return err
            
            # Convert to meters
            x1_m = self._units.to_meters(x1, unit)
            y1_m = self._units.to_meters(y1, unit)
            x2_m = self._units.to_meters(x2, unit)
            y2_m = self._units.to_meters(y2, unit)
            
            # Draw rectangle
            rect = doc.SketchManager.CreateCornerRectangle(
                x1_m, y1_m, 0, x2_m, y2_m, 0
            )
            
            if rect is None:
                return self._result(False, "Failed - ensure sketch is active",
                                  SwErrors.swSketchError)
            
            width = abs(x2 - x1)
            height = abs(y2 - y1)
            unit_str = unit or self._units.default_unit.value
            
            return self._result(True, f"Rectangle: {width}x{height}{unit_str}",
                              SwErrors.swSuccess,
                              {"width": width, "height": height, "unit": unit_str})
            
        except Exception as e:
            logger.error(f"Draw rectangle error: {e}\n{traceback.format_exc()}")
            return self._result(False, f"Error: {e}", SwErrors.swSketchError)
    
    def draw_arc_center(self, cx: float = 0, cy: float = 0, radius: float = 25,
                        start_angle: float = 0, end_angle: float = 90,
                        unit: str = None) -> Dict:
        """
        Draw an arc by center point and angles
        
        Args:
            cx, cy: Center point
            radius: Arc radius
            start_angle: Start angle in degrees
            end_angle: End angle in degrees
            unit: Unit for radius
        
        Returns:
            Result dictionary
        """
        try:
            doc, err = self.get_active_doc()
            if err:
                return err
            
            # Convert to meters
            cx_m = self._units.to_meters(cx, unit)
            cy_m = self._units.to_meters(cy, unit)
            radius_m = self._units.to_meters(radius, unit)
            
            # Convert angles to radians
            start_rad = math.radians(start_angle)
            end_rad = math.radians(end_angle)
            
            # Calculate start and end points
            x1 = cx_m + radius_m * math.cos(start_rad)
            y1 = cy_m + radius_m * math.sin(start_rad)
            x2 = cx_m + radius_m * math.cos(end_rad)
            y2 = cy_m + radius_m * math.sin(end_rad)
            
            # Draw arc (center, start, end, direction)
            arc = doc.SketchManager.CreateArc(
                cx_m, cy_m, 0,   # Center
                x1, y1, 0,       # Start
                x2, y2, 0,       # End
                1                # Direction (1 = counter-clockwise)
            )
            
            if arc is None:
                return self._result(False, "Failed - ensure sketch is active",
                                  SwErrors.swSketchError)
            
            unit_str = unit or self._units.default_unit.value
            # CreateArc direction 1 runs counter-clockwise from start to end.
            arc_angle = (end_angle - start_angle) % 360
            
            return self._result(True, f"Arc: r={radius}{unit_str}, {arc_angle}°",
                              SwErrors.swSuccess,
                              {"radius": radius, "start_angle": start_angle,
                               "end_angle": end_angle, "arc_angle": arc_angle,
                               "unit": unit_str})
            
        except Exception as e:
            logger.error(f"Draw arc error: {e}\n{traceback.format_exc()}")
            return self._result(False, f"Error: {e}", SwErrors.swSketchError)

    def draw_spline(self, points: List[List[float]], unit: str = None) -> Dict:
        """Draw a spline through at least two 2D points in the active sketch."""
        try:
            doc, err = self.get_active_doc()
            if err:
                return err
            if len(points) < 2 or any(len(point) != 2 for point in points):
                return self._result(False, "Spline requires at least two [x, y] points.",
                                    SwErrors.swInvalidInput)
            flat_points = []
            for x, y in points:
                flat_points.extend([
                    self._units.to_meters(x, unit),
                    self._units.to_meters(y, unit),
                    0.0,
                ])
            point_array = win32com.client.VARIANT(
                pythoncom.VT_ARRAY | pythoncom.VT_R8, flat_points)
            sketch_manager = doc.SketchManager
            create_spline = getattr(sketch_manager, "CreateSpline", None)
            if create_spline is None:
                sketch_manager._FlagAsMethod("CreateSpline")
                create_spline = getattr(sketch_manager, "CreateSpline")
            spline = create_spline(point_array)
            if spline is None:
                return self._result(False, "SolidWorks did not create the spline.",
                                    SwErrors.swSketchError)
            return self._result(True, f"Spline created through {len(points)} points.",
                                SwErrors.swSuccess,
                                {"point_count": len(points),
                                 "unit": unit or self._units.default_unit.value})
        except Exception as e:
            logger.error(f"Draw spline error: {e}\n{traceback.format_exc()}")
            return self._result(False, f"Error: {e}", SwErrors.swSketchError)

    def draw_arc_3point(self, start_x: float, start_y: float,
                        end_x: float, end_y: float,
                        point_x: float, point_y: float,
                        unit: str = None) -> Dict:
        """Draw an arc from start to end through a third point."""
        try:
            doc, err = self.get_active_doc()
            if err:
                return err
            values = [self._units.to_meters(value, unit) for value in
                      (start_x, start_y, end_x, end_y, point_x, point_y)]
            arc = doc.SketchManager.Create3PointArc(
                values[0], values[1], 0.0,
                values[2], values[3], 0.0,
                values[4], values[5], 0.0)
            if arc is None:
                return self._result(False, "SolidWorks did not create the 3-point arc.",
                                    SwErrors.swSketchError)
            return self._result(True, "3-point arc created.", SwErrors.swSuccess, {
                "start": [start_x, start_y], "end": [end_x, end_y],
                "point_on_arc": [point_x, point_y],
                "unit": unit or self._units.default_unit.value,
            })
        except Exception as e:
            logger.error(f"Draw 3-point arc error: {e}\n{traceback.format_exc()}")
            return self._result(False, f"Error: {e}", SwErrors.swSketchError)

    def draw_slot(self, x1: float, y1: float, x2: float, y2: float,
                  width: float, unit: str = None) -> Dict:
        """Draw a straight center-to-center slot in the active sketch."""
        try:
            doc, err = self.get_active_doc()
            if err:
                return err
            if width <= 0:
                return self._result(False, "Slot width must be greater than zero.",
                                    SwErrors.swInvalidInput)
            if x1 == x2 and y1 == y2:
                return self._result(False, "Slot center points must be different.",
                                    SwErrors.swInvalidInput)

            values = [self._units.to_meters(value, unit) for value in
                      (x1, y1, x2, y2, width)]
            slot = doc.SketchManager.CreateSketchSlot(
                0,      # swSketchSlotCreationType_line
                0,      # swSketchSlotLengthType_CenterCenter
                values[4],
                values[0], values[1], 0.0,
                values[2], values[3], 0.0,
                0.0, 0.0, 0.0,
                1, False)
            if slot is None:
                return self._result(False, "SolidWorks did not create the slot.",
                                    SwErrors.swSketchError)

            unit_str = unit or self._units.default_unit.value
            center_distance = math.hypot(x2 - x1, y2 - y1)
            return self._result(True, "Straight slot created.", SwErrors.swSuccess, {
                "start": [x1, y1], "end": [x2, y2], "width": width,
                "center_distance": center_distance, "unit": unit_str,
                "length_type": "center_to_center",
            })
        except Exception as e:
            logger.error(f"Draw slot error: {e}\n{traceback.format_exc()}")
            return self._result(False, f"Error: {e}", SwErrors.swSketchError)
    
    def draw_polygon(self, cx: float = 0, cy: float = 0, radius: float = 25,
                     sides: int = 6, unit: str = None) -> Dict:
        """
        Draw a regular polygon
        
        Args:
            cx, cy: Center point
            radius: Circumscribed radius
            sides: Number of sides (3-100)
            unit: Unit for radius
        
        Returns:
            Result dictionary
        """
        try:
            doc, err = self.get_active_doc()
            if err:
                return err
            
            if sides < 3 or sides > 100:
                return self._result(False, "Sides must be between 3 and 100",
                                  SwErrors.swInvalidInput)
            
            # Convert to meters
            cx_m = self._units.to_meters(cx, unit)
            cy_m = self._units.to_meters(cy, unit)
            radius_m = self._units.to_meters(radius, unit)
            
            # Draw polygon
            polygon = doc.SketchManager.CreatePolygon(
                cx_m, cy_m, 0,               # Center
                cx_m + radius_m, cy_m, 0,    # Vertex
                sides,                        # Number of sides
                False                         # Inscribed (False = circumscribed)
            )
            
            if polygon is None:
                return self._result(False, "Failed - ensure sketch is active",
                                  SwErrors.swSketchError)
            
            unit_str = unit or self._units.default_unit.value
            
            return self._result(True, f"{sides}-sided polygon: r={radius}{unit_str}",
                              SwErrors.swSuccess,
                              {"sides": sides, "radius": radius, "unit": unit_str})
            
        except Exception as e:
            logger.error(f"Draw polygon error: {e}\n{traceback.format_exc()}")
            return self._result(False, f"Error: {e}", SwErrors.swSketchError)
    
    def draw_centerline(self, x1: float = 0, y1: float = -50,
                        x2: float = 0, y2: float = 50, unit: str = None) -> Dict:
        """
        Draw a centerline (for revolve axis)
        
        Args:
            x1, y1: Start point
            x2, y2: End point
            unit: Unit for coordinates
        
        Returns:
            Result dictionary
        """
        try:
            doc, err = self.get_active_doc()
            if err:
                return err
            
            # Convert to meters
            x1_m = self._units.to_meters(x1, unit)
            y1_m = self._units.to_meters(y1, unit)
            x2_m = self._units.to_meters(x2, unit)
            y2_m = self._units.to_meters(y2, unit)
            
            # Draw centerline
            line = doc.SketchManager.CreateCenterLine(x1_m, y1_m, 0, x2_m, y2_m, 0)
            
            if line is None:
                return self._result(False, "Failed - ensure sketch is active",
                                  SwErrors.swSketchError)
            
            return self._result(True, "Centerline created",
                              SwErrors.swSuccess)
            
        except Exception as e:
            logger.error(f"Draw centerline error: {e}\n{traceback.format_exc()}")
            return self._result(False, f"Error: {e}", SwErrors.swSketchError)

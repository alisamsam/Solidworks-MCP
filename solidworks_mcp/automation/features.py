"""
SolidWorks Feature Operations
-----------------------------
Create 3D features: extrude, cut, fillet, chamfer, etc.

Version: 4.0.0 (Fixed for SolidWorks 2025 - v33)
Author: Samsaam Ali Baig

Fixes v4.0.0:
- FeatureExtrusion2 now uses correct 23 parameters for SW 2025
- Proper sketch close + select before extrude (fixes multi-profile sketches)
- Property vs method fixes (FirstFeature, GetNextFeature, GetTypeName2)
- Added _find_last_sketch helper for reliable sketch selection
- Added _get_sketch_info helper for better error diagnostics
- Better error messages with sketch profile count
"""

import logging
import math
import traceback
from pathlib import Path
from typing import Optional, Dict

import win32com.client
import pythoncom

from ..comutil import com
from ..constants import SwErrors, SwEndConditions
from ..core.policy import OperationClass

logger = logging.getLogger(__name__)


def _edge_inputs(size, unit, edge_points, tangent_propagation, edge_indices=None):
    def finite(value):
        return isinstance(value,(int,float)) and not isinstance(value,bool) and math.isfinite(value)
    if not finite(size) or size <= 0:
        raise ValueError('Edge size must be a positive finite number.')
    if unit not in (None,'mm','cm','m','inch'):
        raise ValueError('Unsupported edge dimension unit.')
    if type(tangent_propagation) is not bool:
        raise ValueError('tangent_propagation must be boolean.')
    if edge_indices is not None:
        if edge_points is not None:
            raise ValueError('Supply edge_indices or edge_points, not both.')
        if not isinstance(edge_indices,(list,tuple)) or not 1<=len(edge_indices)<=256 or any(
                type(i) is not int or i<0 for i in edge_indices) or len(set(edge_indices))!=len(edge_indices):
            raise ValueError('edge_indices must contain 1 to 256 distinct nonnegative integers.')
    if edge_points is not None:
        if not isinstance(edge_points,(list,tuple)) or not 1 <= len(edge_points) <= 256:
            raise ValueError('edge_points must contain 1 to 256 distinct edge points, or be omitted.')
        if any(not isinstance(p,(list,tuple)) or len(p)!=3 or not all(finite(v) for v in p)
               for p in edge_points):
            raise ValueError('Each edge point must contain three finite coordinates.')
        if len({tuple(p) for p in edge_points}) != len(edge_points):
            raise ValueError('Duplicate edge points are not permitted.')


class FeatureOperations:
    """
    Mixin class for feature operations
    
    Requires parent class to have:
    - get_active_doc(): Document access method
    - _result(): Result factory method
    - _units: UnitConverter instance
    """
    
    # ========================================================================
    # Helper Methods
    # ========================================================================
    
    def _find_last_sketch(self, doc) -> Optional[str]:
        """
        Find the name of the last sketch in the feature tree.
        Uses properties (not method calls) for SW 2025 compatibility.
        
        Returns:
            Sketch name string or None
        """
        last_sketch = None
        try:
            feat = com(doc, "FirstFeature")
            while feat is not None:
                try:
                    feat_type = com(feat, "GetTypeName2")
                    if feat_type == "ProfileFeature":
                        last_sketch = com(feat, "Name")
                except:
                    pass
                try:
                    feat = com(feat, "GetNextFeature")
                except:
                    break
        except Exception as e:
            logger.debug(f"_find_last_sketch error: {e}")
        return last_sketch
    
    def _get_sketch_info(self, doc) -> Dict:
        """
        Get diagnostic info about sketches in the document.
        Useful for error messages.
        
        Returns:
            Dict with sketch_count, sketch_names, has_active_sketch
        """
        info = {
            "sketch_count": 0,
            "sketch_names": [],
            "has_active_sketch": False,
            "feature_count": 0
        }
        try:
            # Check if sketch is active
            try:
                active_sketch = doc.SketchManager.ActiveSketch
                info["has_active_sketch"] = active_sketch is not None
            except:
                pass
            
            # Count sketches and features
            feat = doc.FirstFeature
            while feat is not None:
                try:
                    feat_type = feat.GetTypeName2
                    info["feature_count"] += 1
                    if feat_type == "ProfileFeature":
                        info["sketch_count"] += 1
                        info["sketch_names"].append(feat.Name)
                except:
                    pass
                try:
                    feat = feat.GetNextFeature
                except:
                    break
        except Exception as e:
            logger.debug(f"_get_sketch_info error: {e}")
        return info
    
    def _close_and_select_sketch(self, doc) -> tuple:
        """
        Close active sketch if open, find and select the last sketch.
        
        Returns:
            Tuple of (success: bool, sketch_name: str, error_msg: str)
        """
        try:
            # Step 1: Close active sketch if one is open
            try:
                doc.SketchManager.AddToDB = False
                active_sketch = doc.SketchManager.ActiveSketch
                if active_sketch is not None:
                    doc.SketchManager.InsertSketch(True)
                    logger.debug("Closed active sketch")
            except:
                # Try closing anyway
                try:
                    doc.InsertSketch2(True)
                except:
                    pass
            
            # Step 2: Clear selection
            doc.ClearSelection2(True)
            
            # Step 3: Find the last sketch
            sketch_name = self._find_last_sketch(doc)
            if not sketch_name:
                return False, "", "No sketch found in feature tree"
            
            # Step 4: Select the sketch
            empty_callout = win32com.client.VARIANT(pythoncom.VT_DISPATCH, None)
            selected = doc.Extension.SelectByID2(
                sketch_name, "SKETCH", 0, 0, 0, False, 0, empty_callout, 0
            )
            
            if not selected:
                # Fallback: try pythoncom.Nothing
                selected = doc.Extension.SelectByID2(
                    sketch_name, "SKETCH", 0, 0, 0, False, 0, pythoncom.Nothing, 0
                )
            
            if not selected:
                return False, sketch_name, f"Could not select sketch '{sketch_name}'"
            
            return True, sketch_name, ""
            
        except Exception as e:
            return False, "", f"Error in sketch selection: {e}"
    
    # ========================================================================
    # Extrude
    # ========================================================================
    
    def extrude_sketch(self, depth: float = 10, both_directions: bool = False,
                       unit: str = None) -> Dict:
        """
        Extrude the active sketch (Boss-Extrude)
        FIXED v4.0: Properly closes sketch, selects it, uses 23-param FeatureExtrusion2
        
        Args:
            depth: Extrusion depth
            both_directions: Extrude in both directions (mid-plane)
            unit: Unit for depth
        
        Returns:
            Result dictionary
        """
        try:
            doc, err = self.get_active_doc()
            if err:
                return err
            
            # Convert depth to meters
            depth_m = self._units.to_meters(depth, unit)
            unit_str = unit or self._units.default_unit.value
            
            # Step 1: Close sketch and select it
            success, sketch_name, error_msg = self._close_and_select_sketch(doc)
            if not success:
                sketch_info = self._get_sketch_info(doc)
                return self._result(False,
                    f"Extrusion failed: {error_msg}. "
                    f"Sketches found: {sketch_info['sketch_count']} {sketch_info['sketch_names']}. "
                    f"Active sketch: {sketch_info['has_active_sketch']}. "
                    f"Try: create_sketch → draw geometry → extrude_sketch",
                    SwErrors.swFeatureError,
                    {"diagnostics": sketch_info})
            
            # Step 2: Determine end condition
            end_cond = 6 if both_directions else 0  # 6=MidPlane, 0=Blind
            
            # Step 3: Try extrusion methods
            feat = None
            method_used = ""
            
            # Method 1: FeatureExtrusion2 with 23 params (SW 2025 / v33)
            try:
                feat = doc.FeatureManager.FeatureExtrusion2(
                    True,           # Sd - single direction
                    False,          # Flip
                    False,          # Dir - direction
                    end_cond,       # T1 - end condition (0=Blind, 6=MidPlane)
                    0,              # T2 - end condition 2
                    depth_m,        # D1 - depth
                    depth_m,        # D2 - depth 2
                    False,          # Dchk1 - draft on/off
                    False,          # Dchk2 - draft on/off 2
                    False,          # Ddir1 - draft outward
                    False,          # Ddir2 - draft outward 2
                    0.0,            # Dang1 - draft angle (radians)
                    0.0,            # Dang2 - draft angle 2
                    False,          # OffsetReverse1
                    False,          # OffsetReverse2
                    False,          # TranslateSurface1
                    False,          # TranslateSurface2
                    True,           # Merge - merge result
                    True,           # UseFeatScope
                    True,           # UseAutoSelect
                    0,              # T0 - start condition
                    0.0,            # StartOffset
                    False           # FlipStartOffset
                )
                if feat:
                    method_used = "FeatureExtrusion2_23p"
            except Exception as e:
                logger.debug(f"FeatureExtrusion2 (23p) failed: {e}")
            
            # Method 2: FeatureExtrusion2 with 20 params (older SW versions)
            if feat is None:
                try:
                    feat = doc.FeatureManager.FeatureExtrusion2(
                        True, False, False, end_cond, 0,
                        depth_m, depth_m,
                        False, False, False, False,
                        0.0, 0.0,
                        False, False, False,
                        True, True, True, True
                    )
                    if feat:
                        method_used = "FeatureExtrusion2_20p"
                except Exception as e:
                    logger.debug(f"FeatureExtrusion2 (20p) failed: {e}")
            
            # Method 3: FeatureExtrusion3 (some SW versions)
            if feat is None:
                try:
                    feat = doc.FeatureManager.FeatureExtrusion3(
                        True, False, False, end_cond, 0,
                        depth_m, 0,
                        False, False, False, False,
                        0.0, 0.0,
                        False, False, False,
                        True, True, True,
                        0, 0.0, False
                    )
                    if feat:
                        method_used = "FeatureExtrusion3"
                except Exception as e:
                    logger.debug(f"FeatureExtrusion3 failed: {e}")
            
            if feat is None:
                sketch_info = self._get_sketch_info(doc)
                return self._result(False,
                    f"Extrusion failed on sketch '{sketch_name}'. "
                    f"Ensure sketch has a closed profile (circle, rectangle, etc). "
                    f"Sketches in model: {sketch_info['sketch_names']}",
                    SwErrors.swFeatureError,
                    {"sketch_name": sketch_name, "diagnostics": sketch_info})
            
            direction = "both directions (mid-plane)" if both_directions else "one direction"
            
            return self._result(True,
                f"Extruded {depth}{unit_str} ({direction}) [{method_used}]",
                SwErrors.swSuccess,
                {"depth": depth, "unit": unit_str,
                 "both_directions": both_directions,
                 "sketch_name": sketch_name,
                 "api_method": method_used})
            
        except Exception as e:
            logger.error(f"Extrude error: {e}\n{traceback.format_exc()}")
            return self._result(False, f"Error: {e}", SwErrors.swFeatureError)
    
    # ========================================================================
    # Cut Extrude
    # ========================================================================
    
    def cut_extrude(self, depth: float = 10, through_all: bool = False,
                    both_directions: bool = False, unit: str = None,
                    flip_direction: Optional[bool] = None) -> Dict:
        """
        Cut extrude (remove material)
        FIXED v4.0: Proper sketch handling and parameter counts
        
        Args:
            depth: Cut depth (ignored if through_all=True)
            through_all: Cut through entire model
            both_directions: Cut in both directions
            unit: Unit for depth
            flip_direction: Explicit SolidWorks Dir value. None tries the default
                direction first and retries once in the opposite direction.
        
        Returns:
            Result dictionary
        """
        try:
            doc, err = self.get_active_doc()
            if err:
                return err
            
            # Convert depth to meters
            depth_m = self._units.to_meters(depth, unit)
            unit_str = unit or self._units.default_unit.value
            
            # Step 1: Close sketch and select it
            success, sketch_name, error_msg = self._close_and_select_sketch(doc)
            if not success:
                sketch_info = self._get_sketch_info(doc)
                return self._result(False,
                    f"Cut failed: {error_msg}. "
                    f"Sketches: {sketch_info['sketch_names']}. "
                    f"Ensure sketch is on an existing face.",
                    SwErrors.swFeatureError,
                    {"diagnostics": sketch_info})
            
            # Determine end condition
            if through_all:
                if both_directions:
                    end_cond = 2  # swEndCondThroughAllBoth
                else:
                    end_cond = 1  # swEndCondThroughAll
                cut_depth = 0
            else:
                if both_directions:
                    end_cond = 6  # swEndCondMidPlane
                else:
                    end_cond = 0  # swEndCondBlind
                cut_depth = depth_m
            
            feat = None
            method_used = ""
            used_direction = False
            directions = [bool(flip_direction)] if flip_direction is not None else [False, True]

            for direction in directions:
                # FeatureCut3 is the live-verified SolidWorks 2025 path.
                try:
                    feat = doc.FeatureManager.FeatureCut3(
                    True,           # Sd - single direction
                    False,          # Flip
                    direction,      # Dir
                    end_cond,       # T1 - end condition
                    0,              # T2 - end condition 2
                    cut_depth,      # D1 - depth
                    0,              # D2 - depth 2
                    False, False,   # Dchk1, Dchk2 - draft on/off
                    False, False,   # Ddir1, Ddir2 - draft direction
                    0.0, 0.0,       # Dang1, Dang2 - draft angle
                    False, False,   # OffsetReverse1, OffsetReverse2
                    False, False,   # TranslateSurface1, TranslateSurface2
                    False, False, False,  # NormalCut, UseFeatScope, UseAutoSelect
                    False, False, False,  # AssemblyFeatureScope, AutoSelectComponents, PropagateFeatureToParts
                    0,              # T0 - start condition
                    0.0,            # StartOffset
                    False           # FlipStartOffset
                    )
                    if feat:
                        method_used = "FeatureCut3"
                        used_direction = direction
                        break
                except Exception as e:
                    logger.debug(f"FeatureCut3 (26p, Dir={direction}) failed: {e}")

                # Compatibility fallback for installations exposing FeatureCut4.
                try:
                    feat = doc.FeatureManager.FeatureCut4(
                        True,           # Sd
                        False,          # Flip
                        direction,      # Dir
                        end_cond,       # T1
                        0,              # T2
                        cut_depth,      # D1
                        0,              # D2
                        False, False,   # Dchk1, Dchk2
                        False, False,   # Ddir1, Ddir2
                        0.0, 0.0,       # Dang1, Dang2
                        False, False,   # OffsetReverse1, OffsetReverse2
                        False, False,   # TranslateSurface1, TranslateSurface2
                        False, False, False,  # NormalCut, UseFeatScope, UseAutoSelect
                        False, False, False,  # AssemblyFeatureScope, AutoSelectComponents, PropagateFeatureToParts
                        0,              # T0
                        0.0,            # StartOffset
                        False,          # FlipStartOffset
                        False           # OptimizeGeometry (extra param in Cut4)
                    )
                    if feat:
                        method_used = "FeatureCut4"
                        used_direction = direction
                        break
                except Exception as e:
                    logger.debug(f"FeatureCut4 (Dir={direction}) failed: {e}")
            
            if feat is None:
                return self._result(False,
                    f"Cut failed on sketch '{sketch_name}'. "
                    f"Ensure sketch is drawn on an existing face with a closed profile.",
                    SwErrors.swFeatureError,
                    {"sketch_name": sketch_name})
            
            cut_type = "through all" if through_all else f"{depth}{unit_str}"
            
            return self._result(True, f"Cut extrude: {cut_type} [{method_used}]",
                              SwErrors.swSuccess,
                              {"depth": depth, "through_all": through_all,
                               "sketch_name": sketch_name,
                               "api_method": method_used,
                               "flip_direction": used_direction})
            
        except Exception as e:
            logger.error(f"Cut extrude error: {e}\n{traceback.format_exc()}")
            return self._result(False, f"Error: {e}", SwErrors.swFeatureError)
    
    # ========================================================================
    # Fillet
    # ========================================================================

    def revolve_sketch(self, angle: float = 360,
                       axis: str = "centerline") -> Dict:
        """Revolve the latest closed sketch around its construction centerline."""
        try:
            doc, err = self.get_active_doc()
            if err:
                return err
            if angle <= 0 or angle > 360:
                return self._result(False,
                                    "Revolve angle must be greater than 0 and at most 360 degrees.",
                                    SwErrors.swInvalidInput)
            if axis.lower() != "centerline":
                return self._result(False,
                                    "Only an internal sketch centerline is currently supported as the revolve axis.",
                                    SwErrors.swInvalidInput)

            success, sketch_name, error_msg = self._close_and_select_sketch(doc)
            if not success:
                return self._result(False, f"Revolve failed: {error_msg}",
                                    SwErrors.swFeatureError)

            feature = doc.FeatureManager.FeatureRevolve2(
                True, True, False, False, False, False,
                0, 0, math.radians(angle), 0.0,
                False, False, 0.0, 0.0,
                0, 0.0, 0.0,
                True, True, True,
            )
            if feature is None:
                return self._result(False,
                                    f"Revolve failed on sketch '{sketch_name}'. The sketch needs one closed profile and one construction centerline.",
                                    SwErrors.swFeatureError,
                                    {"sketch_name": sketch_name})

            feature_name = com(feature, "Name")
            return self._result(True,
                                f"Revolved {angle} degrees around the sketch centerline.",
                                SwErrors.swSuccess, {
                                    "angle_degrees": angle,
                                    "axis": "centerline",
                                    "sketch_name": sketch_name,
                                    "feature_name": feature_name,
                                    "api_method": "FeatureRevolve2",
                                })
        except Exception as e:
            logger.error(f"Revolve error: {e}\n{traceback.format_exc()}")
            return self._result(False, f"Error: {e}", SwErrors.swFeatureError)
    
    def _select_edge_points(self, doc, edge_points, unit):
        """Select the edges through the given points; None or an error result."""
        if not edge_points:
            return None
        com(doc, "ClearSelection2", True)
        callout = win32com.client.VARIANT(pythoncom.VT_DISPATCH, None)
        for position, point in enumerate(edge_points):
            x, y, z = (self._units.to_meters(value, unit) for value in point)
            if not com(com(doc, "Extension"), "SelectByID2", "", "EDGE",
                       x, y, z, position > 0, 0, callout, 0):
                com(doc, "ClearSelection2", True)
                return self._result(
                    False, f"No edge found at point {list(point)}.",
                    SwErrors.swSelectionError, {"code": "SELECTION_EMPTY"})
        return None

    def _edge_feature_document(self):
        doc,err=self.get_active_doc()
        if err:return None,err
        if com(doc,'GetType')!=1:
            return None,self._result(False,'Edge finishing requires an active part.',SwErrors.swInvalidFileType)
        policy=getattr(self,'_path_policy',None)
        if policy is not None:
            path=com(doc,'GetPathName')
            if path:policy.require_write(Path(path),OperationClass.MUTATE)
        return doc,None

    def _edge_feature_selection(self,doc,edge_points,unit,edge_indices=None):
        if edge_indices is not None:
            from ..tools.inspection import part_edges
            edges=part_edges(doc)
            if any(i>=len(edges) for i in edge_indices):
                return self._result(False,'Edge index missing; re-run list_body_edges.',SwErrors.swSelectionError)
            com(doc,'ClearSelection2',True)
            selection=win32com.client.VARIANT(pythoncom.VT_DISPATCH,None)
            for position,index in enumerate(edge_indices):
                if not com(edges[index]['edge'],'Select4',position>0,selection):
                    com(doc,'ClearSelection2',True)
                    return self._result(False,'Native edge selection failed.',SwErrors.swSelectionError)
        else:
            err=self._select_edge_points(doc,edge_points,unit)
            if err:return err
        manager=com(doc,'SelectionManager')
        count=com(manager,'GetSelectedObjectCount2',-1)
        if not isinstance(count,int) or not 1 <= count <= 256:
            return self._result(False,'Select 1 to 256 model edges.',SwErrors.swSelectionError)
        expected=edge_indices if edge_indices is not None else edge_points
        if expected is not None and count!=len(expected):
            return self._result(False,'Edge points must resolve to distinct edges.',SwErrors.swSelectionError)
        if any(com(manager,'GetSelectedObjectType3',i,-1)!=1 for i in range(1,count+1)):
            return self._result(False,'Selection must contain model edges only.',SwErrors.swSelectionError)
        return None

    @staticmethod
    def _edge_volume(doc):
        mass=com(com(doc,'Extension'),'CreateMassProperty')
        if mass is None:raise ValueError('Part mass properties are unavailable.')
        volume=com(mass,'Volume')
        if isinstance(volume,bool) or not isinstance(volume,(int,float)) or not math.isfinite(volume) or volume<=0:
            raise ValueError('A finite positive solid volume is required.')
        return volume

    def _verify_edge_feature(self,doc,feature,kind,before):
        if feature is None:raise ValueError(f'{kind} did not create a feature; check edge size and selection.')
        if com(doc,'EditRebuild3') is not True:
            raise ValueError(f'{kind} document rebuild failed; inspect the modified model.')
        name=com(feature,'Name')
        persisted=com(doc,'FeatureByName',name)
        if persisted is None or com(persisted,'GetTypeName2')!=kind:
            raise ValueError(f'{kind} feature was not found in the native model tree.')
        warning=win32com.client.VARIANT(pythoncom.VT_BYREF | pythoncom.VT_BOOL,False)
        error=com(persisted,'GetErrorCode2',warning)
        if error!=0 or warning.value:
            raise ValueError(f'{kind} has native error/warning {error}.')
        after=self._edge_volume(doc)
        if abs(after-before)<=1e-15:
            raise ValueError(f'{kind} produced no measurable solid volume change.')
        return {'feature_name':name,'feature_type':kind,'native_error':error,
                'volume_before_mm3':before*1e9,'volume_after_mm3':after*1e9,
                'volume_delta_mm3':(after-before)*1e9,'geometry_verified':True}

    def fillet_edges(self, radius: float = 2, unit: str = None,
                     edge_points=None,tangent_propagation: bool = True,edge_indices=None) -> Dict:
        """Uniform fillet with explicit tangent propagation and native verification."""
        data={'document_may_be_modified':False}
        try:
            _edge_inputs(radius,unit,edge_points,tangent_propagation,edge_indices)
            doc,err=self._edge_feature_document()
            if err:return err
            before=self._edge_volume(doc)
            err=self._edge_feature_selection(doc,edge_points,unit,edge_indices)
            if err:return err
            radius_m=self._units.to_meters(radius,unit)
            empty=win32com.client.VARIANT(pythoncom.VT_VARIANT,None)
            data['document_may_be_modified']=True
            feature=com(com(doc,'FeatureManager'),'FeatureFillet3',
                2 | int(tangent_propagation),radius_m,0.,0.,0,0,0,
                empty,empty,empty,empty,empty,empty,empty)
            data.update(self._verify_edge_feature(doc,feature,'Fillet',before))
            unit_str=unit or self._units.default_unit.value
            data.update(radius=radius,unit=unit_str,tangent_propagation=tangent_propagation)
            return self._result(True,f'Fillet: r={radius}{unit_str}; native geometry verified.',SwErrors.swSuccess,data)
        except Exception as exc:
            code=SwErrors.swFeatureError if data['document_may_be_modified'] else SwErrors.swInvalidInput
            return self._result(False,str(exc),code,data)

    def chamfer_edges(self, distance: float = 2, angle: float = 45,
                      unit: str = None, edge_points=None,
                      chamfer_type: str = 'angle_distance', distance2: float = None,
                      tangent_propagation: bool = True, flip_direction: bool = False,edge_indices=None) -> Dict:
        """Edge chamfer: angle-distance or two distances, with native verification."""
        data={'document_may_be_modified':False}
        try:
            _edge_inputs(distance,unit,edge_points,tangent_propagation,edge_indices)
            if type(flip_direction) is not bool:raise ValueError('flip_direction must be boolean.')
            if chamfer_type not in ('angle_distance','distance_distance'):
                raise ValueError('chamfer_type must be angle_distance or distance_distance.')
            if chamfer_type=='angle_distance':
                if isinstance(angle,bool) or not isinstance(angle,(int,float)) or not math.isfinite(angle) or not 0<angle<90:
                    raise ValueError('Chamfer angle must be finite and between 0 and 90 degrees, exclusive.')
                if distance2 is not None:raise ValueError('distance2 is only valid for distance_distance.')
            else:
                _edge_inputs(distance2,unit,None,tangent_propagation)
            doc,err=self._edge_feature_document()
            if err:return err
            before=self._edge_volume(doc)
            err=self._edge_feature_selection(doc,edge_points,unit,edge_indices)
            if err:return err
            first=self._units.to_meters(distance,unit)
            options=(4 if tangent_propagation else 0) | int(flip_direction)
            if chamfer_type=='angle_distance':
                args=(options,1,first,math.radians(angle),0.,0.,0.,0.)
            else:
                second=self._units.to_meters(distance2,unit)
                # SW2025 runtime edge chamfer: Width + OtherDist. The published
                # VertexChamDist1/2 recipe produced no feature on the live block.
                args=(options,2,first,0.,second,0.,0.,0.)
            data['document_may_be_modified']=True
            feature=com(com(doc,'FeatureManager'),'InsertFeatureChamfer',*args)
            data.update(self._verify_edge_feature(doc,feature,'Chamfer',before))
            unit_str=unit or self._units.default_unit.value
            data.update(distance=distance,distance2=distance2,
                angle=angle if chamfer_type=='angle_distance' else None,unit=unit_str,
                chamfer_type=chamfer_type,tangent_propagation=tangent_propagation,flip_direction=flip_direction)
            return self._result(True,f'Chamfer: {chamfer_type}; native geometry verified.',SwErrors.swSuccess,data)
        except Exception as exc:
            code=SwErrors.swFeatureError if data['document_may_be_modified'] else SwErrors.swInvalidInput
            return self._result(False,str(exc),code,data)

    # ========================================================================
    # List Features (FIXED: properties not methods)
    # ========================================================================
    
    def list_features(self) -> Dict:
        """
        List all features in the active document
        FIXED v4.0: Uses properties (FirstFeature, GetNextFeature, GetTypeName2)
        instead of method calls for SW 2025 compatibility.
        """
        try:
            doc, err = self.get_active_doc()
            if err:
                return err
            
            features = []

            # FIXED: com() resolves whether FirstFeature/GetNextFeature/GetTypeName2
            # are properties or methods -- a bare access can return a bound method
            # object (always truthy), which previously made the loop stop after the
            # first feature (B17: `feat.GetNextFeature` never actually advanced).
            feat = com(doc, "FirstFeature")

            while feat is not None:
                name = com(feat, "Name")
                feat_type = com(feat, "GetTypeName2")

                features.append({
                    "name": name,
                    "type": feat_type,
                    "suppressed": bool(com(feat, "IsSuppressed")),
                })

                feat = com(feat, "GetNextFeature")
            
            return self._result(True, f"{len(features)} features found",
                              SwErrors.swSuccess,
                              {"features": features, "count": len(features)})
            
        except Exception as e:
            logger.error(f"List features error: {e}\n{traceback.format_exc()}")
            return self._result(False, f"Error: {e}", SwErrors.swUnknownError)
    
    # ========================================================================
    # Edge Selection Helper
    # ========================================================================
    
    def select_edge(self, edge_index: int = 1) -> Dict:
        """
        Select an edge by index
        Note: Use execute_python for precise edge selection
        """
        try:
            doc, err = self.get_active_doc()
            if err:
                return err
            
            doc.ClearSelection2(True)
            
            return self._result(True, "Use execute_python for edge selection",
                              SwErrors.swSuccess)
            
        except Exception as e:
            return self._result(False, f"Error: {e}", SwErrors.swSelectionError)

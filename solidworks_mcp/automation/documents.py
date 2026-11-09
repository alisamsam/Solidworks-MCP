"""
SolidWorks Document Operations
------------------------------
Create, open, save, and manage SolidWorks documents.
"""

import os
import logging
import traceback
from pathlib import Path
from typing import Optional, Dict

import win32com.client
import pythoncom

from ..comutil import com
from ..constants import SwErrors, SwDocumentTypes, SwFileTypes
from ..core.policy import OperationClass, WriteDeniedError
from ..utils import find_template
from .document_safety import DocumentSafety, same_document

logger = logging.getLogger(__name__)


class DocumentOperations(DocumentSafety):
    """
    Mixin class for document operations
    
    Requires parent class to have:
    - self._sw_app: SolidWorks application object
    - self.is_connected: Connection status property
    - self.connect(): Connection method
    - self._result(): Result factory method
    - self._units: UnitConverter instance
    """

    def _guard_write(self, path: str | None, operation_class: OperationClass):
        """Return a legacy error result if an installed policy denies a write."""
        policy = getattr(self, "_path_policy", None)
        if policy is None:
            return None
        if not path:
            return self._result(False, "Write denied: unsaved document has no approved output path.",
                                SwErrors.swFileSaveError)
        try:
            policy.require_write(Path(path), operation_class)
        except WriteDeniedError as error:
            return self._result(False, f"Write denied: {error}", SwErrors.swFileSaveError)
        return None
    
    def create_new_part(self) -> Dict:
        """
        Create a new part document
        
        Returns:
            Result dictionary with document info
        """
        try:
            if not self.is_connected:
                r = self.connect()
                if not r["success"]:
                    return r
            
            # Find part template
            template = find_template("part")
            if not template:
                template = ""  # Let SolidWorks use default
                logger.info("Using SolidWorks default part template")
            else:
                logger.info(f"Using template: {template}")
            
            # Create document
            doc = self._sw_app.NewDocument(template, 0, 0, 0)
            
            if doc is None:
                return self._result(False, "Failed to create part document",
                                  SwErrors.swFileLoadError)
            
            # Set view
            try:
                doc.ShowNamedView2("*Isometric", 7)
                doc.ViewZoomtofit2()
            except:
                pass
            
            title = self._get_doc_title(doc)
            
            self._register_managed_document(doc)
            return self._result(True, f"Created part: {title}",
                              SwErrors.swSuccess,
                              {"name": title, "type": "Part"})
            
        except Exception as e:
            logger.error(f"Create part error: {e}\n{traceback.format_exc()}")
            return self._result(False, f"Error: {e}", SwErrors.swFileLoadError)
    
    def create_new_assembly(self) -> Dict:
        """
        Create a new assembly document
        
        Returns:
            Result dictionary with document info
        """
        try:
            if not self.is_connected:
                r = self.connect()
                if not r["success"]:
                    return r
            
            template = find_template("assembly")
            if not template:
                template = ""
            
            doc = self._sw_app.NewDocument(template, 0, 0, 0)
            
            if doc is None:
                return self._result(False, "Failed to create assembly",
                                  SwErrors.swFileLoadError)
            
            try:
                doc.ShowNamedView2("*Isometric", 7)
                doc.ViewZoomtofit2()
            except:
                pass
            
            title = self._get_doc_title(doc)
            
            self._register_managed_document(doc)
            return self._result(True, f"Created assembly: {title}",
                              SwErrors.swSuccess,
                              {"name": title, "type": "Assembly"})
            
        except Exception as e:
            logger.error(f"Create assembly error: {e}\n{traceback.format_exc()}")
            return self._result(False, f"Error: {e}", SwErrors.swFileLoadError)
    
    def create_new_drawing(self, paper_size: str = "A4") -> Dict:
        """
        Create a new drawing document
        
        Args:
            paper_size: Paper size (A4, A3, A2, A1, Letter)
        
        Returns:
            Result dictionary with document info
        """
        try:
            if not self.is_connected:
                r = self.connect()
                if not r["success"]:
                    return r
            
            template = find_template("drawing")
            if not template:
                template = ""
            
            doc = self._sw_app.NewDocument(template, 0, 0, 0)
            
            if doc is None:
                return self._result(False, "Failed to create drawing",
                                  SwErrors.swFileLoadError)
            
            title = self._get_doc_title(doc)
            
            self._register_managed_document(doc)
            return self._result(True, f"Created drawing: {title}",
                              SwErrors.swSuccess,
                              {"name": title, "type": "Drawing", "paper_size": paper_size})
            
        except Exception as e:
            logger.error(f"Create drawing error: {e}\n{traceback.format_exc()}")
            return self._result(False, f"Error: {e}", SwErrors.swFileLoadError)
    
    def open_document(self, filepath: str) -> Dict:
        """
        Open an existing document
        
        Args:
            filepath: Path to SolidWorks file
        
        Returns:
            Result dictionary
        """
        try:
            if not self.is_connected:
                r = self.connect()
                if not r["success"]:
                    return r
            
            if not os.path.exists(filepath):
                return self._result(False, f"File not found: {filepath}",
                                  SwErrors.swFileNotFoundError)
            
            # Determine document type from extension
            ext = os.path.splitext(filepath)[1].lower()
            type_map = {
                ".sldprt": SwDocumentTypes.swDocPART,
                ".sldasm": SwDocumentTypes.swDocASSEMBLY,
                ".slddrw": SwDocumentTypes.swDocDRAWING,
            }
            doc_type = type_map.get(ext, SwDocumentTypes.swDocPART)
            
            # Open document
            errors = win32com.client.VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
            warnings = win32com.client.VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)

            # pywin32's typed gen_py wrapper calls int() on the byref VARIANTs and
            # raises "int() argument ... not 'VARIANT'"; dynamic dispatch forwards
            # them unchanged (api-findings.md 21.1).
            app = win32com.client.dynamic.Dispatch(self._sw_app)
            try:
                was_loaded = com(app, 'GetOpenDocumentByName', str(Path(filepath).resolve())) is not None
            except Exception:
                was_loaded = None
            doc = app.OpenDoc6(filepath, int(doc_type), 0, "", errors, warnings)
            
            if doc is None or errors.value != 0:
                return self._result(False, f"Failed to open (error {errors.value})",
                                  SwErrors.swFileLoadError)
            
            title = self._get_doc_title(doc)
            # OpenDoc6 can return an already-loaded component without activating
            # its document. Subsequent MCP tools always act on ActiveDoc, so do
            # not report success and bind an unrelated container document.
            expected = Path(filepath).resolve()
            active = com(app, 'ActiveDoc')
            if active is None or Path(com(active, 'GetPathName')).resolve() != expected:
                activation_errors = win32com.client.VARIANT(
                    pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
                activated = app.ActivateDoc3(title, False, 0, activation_errors)
                if activated is None or activation_errors.value != 0:
                    return self._result(False,
                        f'Opened but could not activate requested document (error {activation_errors.value})',
                        SwErrors.swFileLoadError)
            active = com(app, 'ActiveDoc')
            if active is None or Path(com(active, 'GetPathName')).resolve() != expected:
                return self._result(False, 'Opened document is not the requested active document.',
                                    SwErrors.swFileLoadError)

            self._adopt_newly_opened_output(active, was_loaded)
            return self._result(True, f"Opened: {title}",
                              SwErrors.swSuccess,
                              {"name": title, "path": filepath})
            
        except Exception as e:
            logger.error(f"Open document error: {e}\n{traceback.format_exc()}")
            return self._result(False, f"Error: {e}", SwErrors.swFileLoadError)
    
    def save_document(self, filepath: str = None) -> Dict:
        """Save only managed, unchanged-by-user output documents, with native diagnostics."""
        try:
            doc, err = self.get_active_doc()
            if err:
                return err
            current = self._get_doc_path(doc)
            target = str(Path(filepath or current).expanduser().resolve()) if (filepath or current) else None
            denied = self._guard_write(target, OperationClass.MUTATE)
            if denied:
                return denied
            denied = self._document_safety_error(doc) or self._guard_user_dependencies(doc)
            if denied:
                return denied
            if self._managed_record(doc).get('partial_failure'):
                return self._result(False, 'A failed MCP operation changed this output. '
                                    'Repair and verify it, or close without saving using recovery.',
                                    SwErrors.swInvalidInput, {'code': 'PARTIAL_OPERATION_OUTPUT'})
            if not target:
                return self._result(False, 'Unsaved document needs an explicit output path.',
                                    SwErrors.swInvalidInput, {'code': 'SAVE_PATH_REQUIRED'})
            # A SaveAs destination does not grant permission to overwrite a source.
            if current:
                denied = self._guard_write(current, OperationClass.MUTATE)
                if denied:
                    return denied
            native = win32com.client.dynamic.Dispatch(doc)
            errors = win32com.client.VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
            warnings = win32com.client.VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
            same_path = bool(current) and Path(current).resolve() == Path(target)
            if not same_path and Path(target).exists():
                if not self._managed_output_matches(target):
                    return self._result(False, 'Existing save destination is not our unchanged output.',
                                        SwErrors.swInvalidInput, {'code': 'SAVE_TARGET_NOT_OWNED'})
                loaded_target = com(self._sw_app, 'GetOpenDocumentByName', target)
                if loaded_target is not None and not same_document(loaded_target, doc):
                    denied = self._document_safety_error(loaded_target)
                    if denied:
                        return denied
            method = 'Save3' if same_path else 'Extension.SaveAs'
            if same_path:
                result = com(native, 'Save3', 1, errors, warnings)
            else:
                Path(target).parent.mkdir(parents=True, exist_ok=True)
                export = win32com.client.VARIANT(pythoncom.VT_DISPATCH, None)
                result = com(com(native, 'Extension'), 'SaveAs', target, 0, 1, export, errors, warnings)
            data = {'path': target, 'method': method, 'api_return': result if isinstance(result, bool) else None,
                    'save_errors': errors.value, 'save_warnings': warnings.value}
            # Unknown tuple/None results must never be interpreted as truthy success.
            if not isinstance(result, bool) or not result or errors.value:
                data['code'] = 'SAVE_FAILED' if isinstance(result, bool) else 'SAVE_OUTCOME_UNKNOWN'
                return self._result(False, 'Save was not confirmed; document remains open.',
                                    SwErrors.swFileSaveError, data)
            if self._get_doc_path(doc) != target and (
                    not self._get_doc_path(doc) or Path(self._get_doc_path(doc)).resolve() != Path(target)):
                data['code'] = 'SAVE_IDENTITY_MISMATCH'
                return self._result(False, 'Save returned success but document path differs.',
                                    SwErrors.swFileSaveError, data)
            if not Path(target).is_file():
                data['code'] = 'SAVE_FILE_MISSING'
                return self._result(False, 'Save returned success but output is missing.',
                                    SwErrors.swFileSaveError, data)
            self._refresh_managed_document(doc)
            self._remember_managed_output(target)
            data['save_outcome'] = 'confirmed'
            return self._result(True, f'Saved: {target} [{method}]', SwErrors.swSuccess, data)
        except Exception as error:
            logger.error('Save error: %s', error)
            return self._result(False, f'Save outcome unknown: {error}. Document remains open.',
                                SwErrors.swFileSaveError, {'code': 'SAVE_OUTCOME_UNKNOWN'})

    def close_document(self, save: bool = False, recovery_script: str = None) -> Dict:
        """Close our document only; explicit discard needs a saved baseline or recovery script."""
        try:
            doc, err = self.get_active_doc()
            if err:
                return self._result(True, 'No document to close')
            path = self._get_doc_path(doc)
            # Retain path-policy enforcement before any save (including protected sources).
            if save:
                denied = self._guard_write(path, OperationClass.MUTATE)
                if denied:
                    return denied
            denied = self._document_safety_error(doc) or self._guard_user_dependencies(doc)
            if denied:
                return denied
            recovery = None
            if save:
                saved = self.save_document()
                if not saved.get('success'):
                    return saved  # Caller may subsequently request a safe explicit discard.
            elif bool(com(doc, 'GetSaveFlag')):
                recovery = self._recovery_file(path) or self._recovery_file(recovery_script, script=True)
                if recovery is None:
                    return self._result(False, 'Unsaved output has no saved baseline or readable '
                                        'recovery script; it remains open.', SwErrors.swInvalidInput,
                                        {'code': 'RECOVERY_REQUIRED'})
            name = path or self._get_doc_title(doc)
            com(self._sw_app, 'CloseDoc', name)
            remaining = com(self._sw_app, 'GetDocuments') or ()
            if any(same_document(doc, child) for child in remaining):
                return self._result(False, 'Document remains loaded (possibly referenced).',
                                    SwErrors.swUnknownError, {'code': 'DOCUMENT_STILL_OPEN'})
            self._managed_documents = [row for row in getattr(self, '_managed_documents', ())
                                       if not same_document(row['document'], doc)]
            return self._result(True, f'Closed: {name}', SwErrors.swSuccess,
                                {'document': name, 'saved': save, 'discarded_changes': bool(recovery),
                                 'recovery_source': recovery})
        except Exception as error:
            logger.error('Close error: %s', error)
            return self._result(False, f'Close not confirmed: {error}', SwErrors.swUnknownError)

    def get_document_info(self) -> Dict:
        """
        Get information about the active document
        
        Returns:
            Result dictionary with document details
        """
        try:
            doc, err = self.get_active_doc()
            if err:
                return err
            
            type_names = {
                0: "None",
                1: "Part",
                2: "Assembly",
                3: "Drawing"
            }
            
            doc_type = com(doc, "GetType")
            title = self._get_doc_title(doc)
            path = self._get_doc_path(doc)
            
            info = {
                "title": title,
                "path": path if path else "Not saved",
                "type": type_names.get(doc_type, "Unknown"),
                "type_code": doc_type,
            }
            
            return self._result(True, f"{title} ({info['type']})",
                              SwErrors.swSuccess, info)
            
        except Exception as e:
            logger.error(f"Get info error: {e}\n{traceback.format_exc()}")
            return self._result(False, f"Error: {e}", SwErrors.swUnknownError)
    
    def list_open_documents(self) -> Dict:
        """
        List all open documents
        
        Returns:
            Result dictionary with document list
        """
        try:
            if not self.is_connected:
                r = self.connect()
                if not r["success"]:
                    return r
            
            docs = []
            unresolved = []
            retained = []
            doc = com(self._sw_app, "GetFirstDocument")

            while doc:
                retained.append(doc)
                if len(retained)>10000:
                    raise ValueError("Open document traversal limit exceeded.")
                try:
                    title = com(doc, "GetTitle")
                    doc_type = com(doc, "GetType")

                    type_names = {1: "Part", 2: "Assembly", 3: "Drawing"}

                    row={"title":title,"type":type_names.get(doc_type,"Unknown")}
                    for key,member in (("path","GetPathName"),("unsaved_changes","GetSaveFlag")):
                        try:row[key]=com(doc,member)
                        except Exception as exc:
                            row[key]=None;unresolved.append(f"{title}: {member}: {exc}")
                    docs.append(row)
                except Exception as exc:
                    unresolved.append(str(exc))

                doc = com(doc, "GetNext")
            
            return self._result(True, f"{len(docs)} document(s) open",
                              SwErrors.swSuccess, {"documents": docs, "complete": not unresolved, "unresolved": unresolved})
            
        except Exception as e:
            logger.error(f"List documents error: {e}\n{traceback.format_exc()}")
            return self._result(False, f"Error: {e}", SwErrors.swUnknownError)

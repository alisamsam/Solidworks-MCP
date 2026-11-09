"""
SolidWorks Automation Base
--------------------------
Core automation class with connection management and utility methods.
"""

import os
import time
import logging
import datetime
import traceback
import threading
from typing import Optional, Dict, Any, Tuple

# COM imports
import win32com.client
import pythoncom

from ..constants import SwErrors, SwPlanes, SwDocumentTypes, SwViews
from ..config import get_config
from ..comutil import com
from ..core.session import DocumentSession, TargetMismatchError
from ..utils import UnitConverter, find_solidworks, find_template

logger = logging.getLogger(__name__)


class ComThreadOwnershipError(RuntimeError):
    """Raised before a SolidWorks COM proxy is touched from another thread."""


class SolidWorksAutomation:
    """
    Core SolidWorks automation class
    
    Handles connection management, document operations, and provides
    utility methods for all automation tasks.
    """
    
    def __init__(self):
        """Initialize automation instance"""
        self._sw_app = None
        self._connected = False
        self._config = get_config()
        self._units = UnitConverter(self._config.default_unit)
        self._sw_exe_path = None
        self._path_policy = self._config.create_path_policy()
        self._document_session = DocumentSession()
        self._com_owner_thread_id = None
        self._com_initialized = False
        
        logger.info("SolidWorksAutomation initialized")

    def set_path_policy(self, policy) -> None:
        """Install the trusted write policy used by document operations."""
        self._path_policy = policy

    def _get_revision_number(self):
        """Read RevisionNumber from both generated-method and dynamic COM bindings."""
        value = self._sw_app.RevisionNumber
        return value() if callable(value) else value
    
    # ========================================================================
    # Properties
    # ========================================================================
    
    @property
    def is_connected(self) -> bool:
        """Check if connected to SolidWorks"""
        if not self._connected or self._sw_app is None:
            return False
        self._require_com_owner()
        
        try:
            # Test connection by accessing a property
            _ = self._get_revision_number()
            return True
        except:
            self._connected = False
            self._sw_app = None
            return False
    
    @property
    def units(self) -> UnitConverter:
        """Get unit converter"""
        return self._units
    
    @property
    def app(self):
        """Get SolidWorks application object"""
        if self._sw_app is not None:
            self._require_com_owner()
        return self._sw_app

    def _require_com_owner(self) -> None:
        owner = getattr(self, "_com_owner_thread_id", None)
        current = threading.get_ident()
        if owner is not None and owner != current:
            raise ComThreadOwnershipError(
                f"SolidWorks COM session belongs to thread {owner}; current thread is {current}."
            )
    
    # ========================================================================
    # Result Helper
    # ========================================================================
    
    def _result(self, success: bool, message: str,
                error_code: SwErrors = SwErrors.swSuccess,
                data: Optional[Dict] = None) -> Dict:
        """
        Create standardized result dictionary
        
        Args:
            success: Operation success status
            message: Human-readable message
            error_code: Error code enum
            data: Optional additional data
        
        Returns:
            Standardized result dictionary
        """
        result = {
            "success": success,
            "message": message,
            "error_code": int(error_code),
            "error_name": error_code.name,
            "timestamp": datetime.datetime.now().isoformat()
        }
        if data:
            result["data"] = data
        return result
    
    # ========================================================================
    # Connection Methods
    # ========================================================================
    
    def _try_connect_com(self) -> bool:
        """
        Try multiple COM connection methods
        
        Returns:
            True if connection successful
        """
        methods = [
            # Method 1: GetObject (running instance)
            lambda: win32com.client.GetObject(Class="SldWorks.Application"),
            # Method 2: Dispatch (creates or gets existing)
            lambda: win32com.client.Dispatch("SldWorks.Application"),
            # Method 3: Dynamic Dispatch
            lambda: win32com.client.dynamic.Dispatch("SldWorks.Application"),
            # Method 4: GetActiveObject
            lambda: win32com.client.GetActiveObject("SldWorks.Application"),
        ]
        
        self._require_com_owner()
        initialized_here = not self._com_initialized
        if initialized_here:
            pythoncom.CoInitialize()
            self._com_initialized = True
            self._com_owner_thread_id = threading.get_ident()

        for i, method in enumerate(methods):
            try:
                logger.debug(f"Trying connection method {i+1}...")
                self._sw_app = method()
                
                if self._sw_app is not None:
                    self._sw_app.Visible = True
                    
                    # Get version (property or method)
                    version = self._get_revision_number()
                    
                    logger.info(f"Connected via method {i+1}: {version}")
                    self._connected = True
                    return True
                    
            except Exception as e:
                logger.debug(f"Method {i+1} failed: {e}")
                continue
        
        if initialized_here:
            pythoncom.CoUninitialize()
            self._com_initialized = False
            self._com_owner_thread_id = None
        return False
    
    def connect(self) -> Dict:
        """
        Connect to SolidWorks - launches if not running
        
        Returns:
            Result dictionary with connection status
        """
        try:
            logger.info("=== Connecting to SolidWorks ===")
            
            # Step 1: Try connecting to running instance
            if self._try_connect_com():
                version = self._get_revision_number()
                
                return self._result(True, f"Connected to SolidWorks {version}",
                                  SwErrors.swSuccess,
                                  {"version": str(version), "launched": False})
            
            # Step 2: Find SolidWorks executable
            if self._sw_exe_path is None:
                if self._config.exe_path != "auto":
                    self._sw_exe_path = self._config.exe_path
                else:
                    self._sw_exe_path = find_solidworks()
            
            if not self._sw_exe_path or not os.path.exists(self._sw_exe_path):
                return self._result(False,
                    f"SolidWorks not found. Set exe_path in config or install SolidWorks.",
                    SwErrors.swSolidWorksNotFound)
            
            # Step 3: Launch SolidWorks
            logger.info(f"Launching SolidWorks: {self._sw_exe_path}")
            os.startfile(self._sw_exe_path)
            
            # Step 4: Wait for SolidWorks to start
            logger.info("Waiting for SolidWorks startup...")
            max_wait = self._config.startup_timeout
            retry_interval = self._config.connection_retry_interval
            start_time = time.time()
            
            while time.time() - start_time < max_wait:
                time.sleep(retry_interval)
                elapsed = int(time.time() - start_time)
                logger.debug(f"Connection attempt at {elapsed}s...")
                
                if self._try_connect_com():
                    version = self._get_revision_number()
                    
                    logger.info(f"Connected after {elapsed}s")
                    return self._result(True,
                        f"Launched and connected to SolidWorks {version} (took {elapsed}s)",
                        SwErrors.swSuccess,
                        {"version": str(version), "launched": True, "startup_time": elapsed})
            
            return self._result(False,
                f"Timeout after {max_wait}s. Close any dialogs and try again.",
                SwErrors.swConnectionError)
            
        except Exception as e:
            logger.error(f"Connection error: {e}\n{traceback.format_exc()}")
            return self._result(False, f"Connection error: {e}",
                              SwErrors.swConnectionError)
    
    def disconnect(self) -> Dict:
        """
        Disconnect from SolidWorks (does not close SolidWorks)
        
        Returns:
            Result dictionary
        """
        self._require_com_owner()
        # Do not retain COM document identities across disconnected sessions.
        self._managed_documents = []
        self._sw_app = None
        self._connected = False
        if self._com_initialized:
            pythoncom.CoUninitialize()
            self._com_initialized = False
            self._com_owner_thread_id = None
        logger.info("Disconnected from SolidWorks")
        return self._result(True, "Disconnected from SolidWorks")
    
    # ========================================================================
    # Document Methods
    # ========================================================================
    
    def get_active_doc(self) -> Tuple[Any, Optional[Dict]]:
        """
        Get active document with auto-connect
        
        Returns:
            Tuple of (document, error_result)
            - If successful: (document, None)
            - If failed: (None, error_dict)
        """
        self._require_com_owner()
        if not self.is_connected:
            result = self.connect()
            if not result["success"]:
                return None, result
        
        doc = self._sw_app.ActiveDoc
        if doc is None:
            return None, self._result(False,
                "No document open. Use create_new_part first.",
                SwErrors.swNoActiveDocument)
        
        return doc, None
    
    def _get_doc_title(self, doc) -> str:
        """Get document title (handles property/method difference)"""
        try:
            title = doc.GetTitle
            if callable(title):
                return title()
            return title
        except:
            return "Unknown"
    
    def _get_doc_path(self, doc) -> str:
        """Get document path (handles property/method difference)"""
        try:
            path = doc.GetPathName
            if callable(path):
                return path()
            return path
        except:
            return ""

    def _capture_document_ref(self, doc):
        """Capture active-document metadata without retaining the COM object."""
        type_names = {1: "part", 2: "assembly", 3: "drawing"}
        document_type = type_names.get(com(doc, "GetType"), "unknown")
        configuration = None
        try:
            manager = com(doc, "ConfigurationManager")
            active = com(manager, "ActiveConfiguration")
            configuration = com(active, "Name") if active is not None else None
        except Exception:
            # Drawings and partially loaded documents may not expose a configuration.
            configuration = None
        return self._document_session.capture(
            title=self._get_doc_title(doc),
            path=self._get_doc_path(doc) or None,
            document_type=document_type,
            configuration=configuration,
        )

    def capture_active_document_ref(self):
        """Return a serializable reference for the current ActiveDoc."""
        doc, error = self.get_active_doc()
        if error:
            return None, error
        return self._capture_document_ref(doc), None

    def bind_active_document(self):
        """Bind the current ActiveDoc as the explicit mutation target."""
        document, error = self.capture_active_document_ref()
        if error:
            raise RuntimeError(error["message"])
        self._check_managed_edit_state()
        self._document_session.state.bind(document)
        return document

    def has_bound_document(self) -> bool:
        return self._document_session.state.target is not None

    def require_bound_active_document(self):
        """Reject an ActiveDoc, configuration, or revision switch before COM mutation."""
        document, error = self.capture_active_document_ref()
        if error:
            raise RuntimeError(error["message"])
        self._document_session.require_bound(document)
        self._check_managed_edit_state()
        return document

    def _check_managed_edit_state(self):
        """Rebinding must not bless edits performed outside MCP operations."""
        if not hasattr(self, '_managed_record'):
            return
        doc, error = self.get_active_doc()
        if not error and self._managed_record(doc) is not None:
            denied = self._document_safety_error(doc)
            if denied:
                raise TargetMismatchError(denied['data']['code'], denied['message'])

    def mark_active_document_mutated(self, before):
        """Advance the MCP revision after a successful document mutation."""
        after = self._document_session.mark_mutated(before)
        if hasattr(self, '_refresh_managed_document'):
            doc, error = self.get_active_doc()
            if not error:
                self._refresh_managed_document(doc)
        return after

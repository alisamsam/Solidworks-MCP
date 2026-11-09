"""Session-local ownership and native edit checks. Never infer ownership from a path."""
from pathlib import Path
import hashlib
from contextlib import contextmanager

from ..comutil import com
from ..constants import SwErrors
from ..core.policy import OperationClass


def same_document(first, second):
    if first is second:
        return True
    try:
        return first._oleobj_ == second._oleobj_
    except AttributeError:
        return False


def edit_snapshot(document):
    try:
        stamp, dirty = com(document, 'GetUpdateStamp'), com(document, 'GetSaveFlag')
        if type(stamp) is not int or type(dirty) is not bool:
            return None
        return (stamp, dirty)
    except Exception:
        return None


class DocumentSafety:
    def _remember_managed_output(self, path):
        """Internal provenance: called only after our confirmed save/verified copy."""
        target = Path(path).resolve()
        if not hasattr(self, '_managed_output_files'):
            self._managed_output_files = {}
        with target.open('rb') as stream:
            self._managed_output_files[target] = hashlib.file_digest(stream, 'sha256').hexdigest()

    def _managed_output_matches(self, path):
        target = Path(path).resolve()
        expected = getattr(self, '_managed_output_files', {}).get(target)
        if expected is None:
            return False
        try:
            with target.open('rb') as stream:
                return hashlib.file_digest(stream, 'sha256').hexdigest() == expected
        except OSError:
            return False

    def _managed_record(self, document):
        return next((row for row in getattr(self, '_managed_documents', ())
                     if same_document(row['document'], document)), None)

    def _register_managed_document(self, document):
        """Internal: only a just-created or newly opened clean output can be registered."""
        if not hasattr(self, '_managed_documents'):
            self._managed_documents = []
        # Reopening an already managed document must not bless intervening UI edits.
        if self._managed_record(document) is None:
            self._managed_documents.append({'document': document, 'snapshot': edit_snapshot(document)})

    def _refresh_managed_document(self, document):
        """Called only after a known MCP mutation, never from a read/rebind."""
        row = self._managed_record(document)
        if row is not None:
            row['snapshot'] = edit_snapshot(document)
            row.pop('partial_failure', None)

    def _begin_managed_operation(self):
        document, error = self.get_active_doc()
        if not error and self._managed_record(document) is not None:
            if self._document_safety_error(document) is None:
                return (document, edit_snapshot(document))
        return None

    def _end_failed_managed_operation(self, token):
        """Attribute partial edits to the guarded failed call; permit recovery discard only."""
        if token is None:
            return
        document, before = token
        row = self._managed_record(document)
        after = edit_snapshot(document)
        if row is not None and after is not None and after != before:
            row['snapshot'] = after
            row['partial_failure'] = True

    def _document_safety_error(self, document):
        row = self._managed_record(document)
        if row is None:
            return self._result(False, 'User/pre-existing document is protected; it was not created '
                                'or newly opened as a clean output by this automation session.',
                                SwErrors.swInvalidInput, {'code': 'USER_DOCUMENT_PROTECTED'})
        actual = edit_snapshot(document)
        if actual is None or row['snapshot'] is None or actual != row['snapshot']:
            return self._result(False, 'Document has untracked edits or its edit state is unavailable. '
                                'It will not be saved or discarded automatically.',
                                SwErrors.swInvalidInput, {'code': 'UNTRACKED_DOCUMENT_EDITS'})
        path = self._get_doc_path(document)
        if (path and Path(path).resolve() in getattr(self, '_managed_output_files', {})
                and not self._managed_output_matches(path)):
            return self._result(False, 'The saved output changed outside the last confirmed operation. '
                                'It will not be overwritten or discarded automatically.',
                                SwErrors.swInvalidInput, {'code': 'SAVED_OUTPUT_CHANGED'})
        return None

    def document_lifecycle_status(self, path):
        """For automatic cleanup: do not treat every clean output as ours."""
        for row in getattr(self, '_managed_documents', ()):
            doc = row['document']
            try:
                current = self._get_doc_path(doc)
                if current and Path(current).resolve() == Path(path).resolve():
                    return {'managed': True, 'safe': self._document_safety_error(doc) is None}
            except Exception:
                continue
        return {'managed': False, 'safe': False}

    def _guard_user_dependencies(self, document):
        """Holders may save/drop loaded children. Refuse if any loaded edits are untracked.

        Conservatively checks all loaded documents, since an incomplete reference tree
        cannot establish that closing a holder leaves another edited document loaded.
        """
        try:
            if com(document, 'GetType') not in (2, 3):
                return None
            loaded = com(self._sw_app, 'GetDocuments') or ()
            for child in loaded:
                if same_document(child, document):
                    continue
                dirty = com(child, 'GetSaveFlag')
                if type(dirty) is not bool:
                    raise ValueError('Unknown child edit state')
                if dirty and self._document_safety_error(child):
                    return self._result(False, 'A loaded document has user/untracked edits; '
                                        'saving or closing this assembly/drawing is unsafe.',
                                        SwErrors.swInvalidInput, {'code': 'USER_DEPENDENCIES_DIRTY'})
        except Exception:
            return self._result(False, 'Could not establish safety of loaded documents.',
                                SwErrors.swInvalidInput, {'code': 'DEPENDENCY_SAFETY_UNKNOWN'})
        return None

    def _adopt_newly_opened_output(self, document, was_loaded):
        if was_loaded is not False:
            return
        try:
            path = self._get_doc_path(document)
            policy = getattr(self, '_path_policy', None)
            if policy is None or not path or com(document, 'GetSaveFlag') is not False:
                return
            policy.require_write(Path(path), OperationClass.MUTATE)
            if not self._managed_output_matches(path):
                return
            self._register_managed_document(document)
        except Exception:
            # Opening for inspection is allowed without permission to save/close it.
            return

    @staticmethod
    def _recovery_file(path, script=False):
        if not path:
            return None
        try:
            candidate = Path(path).expanduser().resolve(strict=True)
            if script and candidate.suffix.casefold() not in ('.py', '.ps1', '.vbs', '.js', '.vb'):
                return None
            if candidate.is_file() and candidate.stat().st_size > 0:
                with candidate.open('rb') as stream:
                    stream.read(1)
                return str(candidate)
        except (OSError, ValueError):
            pass
        return None


@contextmanager
def managed_operation(sw):
    """Attribute failures on the actual target of a multi-document project operation."""
    token = sw._begin_managed_operation() if hasattr(sw, '_begin_managed_operation') else None
    try:
        yield
    except Exception:
        if token is not None:
            sw._end_failed_managed_operation(token)
        raise

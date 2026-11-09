"""Closed-file independent copies, with a verified dependency manifest."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
from uuid import uuid4

from ..comutil import com
from ..constants import SwErrors
from ..core.policy import OperationClass, WriteDeniedError
from ..registry import tool

MANIFEST = '.solidworks-project-copy.json'
NATIVE = {'.sldprt', '.sldasm', '.slddrw'}


def _fail(sw, message, code='PROJECT_COPY_FAILED', **details):
    return sw._result(False, message, SwErrors.swInvalidInput, {'code': code, **details})


def _path(value):
    if not isinstance(value, str) or not value.strip():
        raise ValueError('A non-empty document path is required.')
    return Path(value).expanduser().resolve()


def _hash(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def _within(path, root):
    return path == root or root in path.parents


def _dependencies(app, path):
    raw = com(app, 'GetDocumentDependencies2', str(path), False, False, False)
    if raw is None:
        return []
    if not isinstance(raw, (tuple, list)) or len(raw) % 2:
        raise ValueError(f'Incomplete dependency response for {path}')
    result = []
    for name, value in zip(raw[::2], raw[1::2]):
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f'Unresolved dependency {name} in {path}')
        candidate = Path(value)
        if not candidate.is_absolute():
            candidate = path.parent / candidate
        candidate = candidate.resolve()
        if candidate not in result:
            result.append(candidate)
    return result


def _graph(app, seeds):
    graph = {}
    pending = list(seeds)
    while pending:
        path = pending.pop()
        if path in graph:
            continue
        if len(graph) >= 5000:
            raise ValueError('Project exceeds the 5000-document safety limit.')
        if path.suffix.casefold() not in NATIVE or not path.is_file():
            raise ValueError(f'Missing or unsupported referenced document: {path}')
        refs = _dependencies(app, path)
        graph[path] = refs
        pending.extend(refs)
    return graph


def _seeds(source_path, drawings):
    source = _path(source_path)
    if drawings is None:
        drawings = []
    if not isinstance(drawings, list) or any(not isinstance(p, str) for p in drawings):
        raise ValueError('drawings must be a list of drawing paths.')
    seeds = [source]
    for value in drawings:
        path = _path(value)
        if path.suffix.casefold() != '.slddrw':
            raise ValueError('Additional drawing seeds must be SLDDRW files.')
        seeds.append(path)
    return source, seeds


def _project_graph(app, source, seeds, include_drawings):
    if not isinstance(include_drawings, bool):
        raise ValueError('include_drawings must be boolean.')
    graph = _graph(app, seeds)
    if include_drawings:
        scanned = 0
        for candidate in source.parent.rglob('*'):
            scanned += 1
            if scanned > 20000:
                raise ValueError('Drawing discovery limit exceeded; pass explicit drawings and include_drawings=false.')
            if candidate.suffix.casefold() != '.slddrw' or not candidate.is_file():
                continue
            candidate = candidate.resolve()
            if candidate in graph:
                continue
            refs = _dependencies(app, candidate)
            if any(ref in graph for ref in refs):
                graph.update(_graph(app, [candidate]))
    return graph


def _ensure_app(sw):
    if not sw.is_connected:
        result = sw.connect()
        if not result['success']:
            raise ValueError(result['message'])
    return sw.app


@tool(name='inspect_project_references', description=(
    'Read the saved dependency graph without opening or changing source documents. '
    'Discover related drawings in the source folder; pass external drawings explicitly.'),
    schema={'type': 'object', 'properties': {
        'source_path': {'type': 'string'},
        'drawings': {'type': 'array', 'items': {'type': 'string'}},
        'include_drawings': {'type': 'boolean', 'default': True}}, 'required': ['source_path']},
    operation_class=OperationClass.READ)
def inspect_project_references(sw, source_path: str, drawings=None, include_drawings=True):
    try:
        source, seeds = _seeds(source_path, drawings)
        graph = _project_graph(_ensure_app(sw), source, seeds, include_drawings)
        return sw._result(True, 'Saved project references inspected; source documents unchanged.',
            data={'source': str(source), 'complete': True, 'drawing_discovery': 'related drawings under source folder plus explicit seeds',
                  'documents': [{'path': str(path), 'references': [str(p) for p in refs]}
                                for path, refs in graph.items()]})
    except Exception as error:
        return _fail(sw, str(error), 'PROJECT_REFERENCES_INCOMPLETE')


@tool(name='copy_project', description=(
    'Copy all reachable native CAD dependencies into a NEW approved folder, '
    'relink only closed copies, and verify isolation. Never saves source files. '
    'Discover related drawings in the source folder; pass external drawings explicitly. '
    'Use source_state=saved_files only when explicitly choosing disk state; unsaved edits are excluded. '
    'Does not open the copy or copy arbitrary auxiliary files.'),
    schema={'type': 'object', 'properties': {
        'source_path': {'type': 'string'}, 'destination_folder': {'type': 'string'},
        'drawings': {'type': 'array', 'items': {'type': 'string'}},
        'include_drawings': {'type': 'boolean', 'default': True},
        'source_state': {'type': 'string', 'enum': ['require_clean', 'saved_files'],
                         'default': 'require_clean'}},
        'required': ['source_path', 'destination_folder']},
    operation_class=OperationClass.PROJECT_WRITE)
def copy_project(sw, source_path: str, destination_folder: str, drawings=None, include_drawings=True, source_state="require_clean"):
    destination = None
    created = False
    manifest = {'schema_version': 1, 'project_copy_id': uuid4().hex, 'status': 'preparing', 'files': []}
    try:
        if source_state not in ('require_clean', 'saved_files'):
            raise ValueError('source_state must be require_clean or saved_files.')
        source, seeds = _seeds(source_path, drawings)
        destination = _path(destination_folder)
        policy = getattr(sw, '_path_policy', None)
        if policy is None:
            raise ValueError('An approved output path policy is required.')
        policy.require_write(destination, OperationClass.EXPORT)
        if destination.exists() or _within(destination, source.parent):
            raise ValueError('Destination must be a new folder outside the source project folder.')
        app = _ensure_app(sw)
        graph = _project_graph(app, source, seeds, include_drawings)
        unsaved = []
        for path in graph:
            opened = com(app, 'GetOpenDocumentByName', str(path))
            if opened is not None and com(opened, 'GetSaveFlag'):
                unsaved.append(str(path))
                if source_state == 'require_clean':
                    raise ValueError(f'Source has unsaved changes: {path}; explicitly choose saved_files to copy disk state.')
        manifest.update(source_state=source_state, unsaved_documents_excluded=unsaved,
                        warnings=['Unsaved source edits are excluded; copied saved disk state only.'] if unsaved else [])
        hashes = {path: _hash(path) for path in graph}
        mapping = {}
        for index, path in enumerate(graph):
            # Unique basenames prevent SW resolving a copy to an already open original.
            suffix = hashlib.sha256((manifest['project_copy_id'] + str(path).casefold()).encode()).hexdigest()[:10]
            mapping[path] = destination / f'{path.stem}__copy_{index:04d}_{suffix}{path.suffix}'
        manifest.update(root_document=str(mapping[source]), source=str(source),
            files=[{'source': str(path), 'copy': str(mapping[path]), 'source_sha256': hashes[path]}
                   for path in graph])
        destination.mkdir(parents=True, exist_ok=False)
        created = True
        (destination / MANIFEST).write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
        for path, target in mapping.items():
            policy.require_write(target, OperationClass.EXPORT)
            with path.open('rb') as reader, target.open('xb') as writer:
                shutil.copyfileobj(reader, writer)
            if _hash(target) != hashes[path]:
                raise ValueError(f'Copy checksum differs: {target}')
        for path, refs in graph.items():
            target = mapping[path]
            if com(app, 'GetOpenDocumentByName', str(target)) is not None:
                raise ValueError(f'Copy must remain closed during reference replacement: {target}')
            for ref in refs:
                if not com(app, 'ReplaceReferencedDocument', str(target), str(ref), str(mapping[ref])):
                    raise ValueError(f'Reference replacement failed in {target}: {ref}')
        for path, refs in graph.items():
            actual = set(_dependencies(app, mapping[path]))
            expected = {mapping[ref] for ref in refs}
            if actual != expected:
                raise ValueError(f'Copy still has unexpected/missing references: {mapping[path]}')
        for path in graph:
            if _hash(path) != hashes[path]:
                raise ValueError(f'Source changed during copying: {path}; copy is not verified.')
        manifest['status'] = 'verified'
        manifest['verification'] = 'closed-file references and unchanged source SHA256'
        (destination / MANIFEST).write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
        if hasattr(sw, '_remember_managed_output'):
            for copied_path in mapping.values():
                sw._remember_managed_output(copied_path)
        return sw._result(True, 'Independent project copy verified. Open root_document to adapt it.', data=manifest)
    except Exception as error:
        if created:
            manifest.update(status='failed', error=str(error))
            try:
                (destination / MANIFEST).write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
            except OSError:
                pass
        return _fail(sw, str(error), partial_folder=str(destination) if created else None)


def require_editable_copy(sw, document_path: str, *, edit_original=False):
    """Return a denial unless target is approved and currently isolated."""
    try:
        if not isinstance(edit_original, bool):
            raise ValueError('edit_original must be a boolean.')
        path = _path(document_path)
        policy = getattr(sw, '_path_policy', None)
        if policy is None:
            raise ValueError('Approved output path policy is required.')
        policy.require_write(path, OperationClass.MUTATE)
        if not path.is_file():
            raise ValueError('Editing requires a saved document file.')
        if edit_original:
            return None
        marker = next((p / MANIFEST for p in path.parents if (p / MANIFEST).is_file()), None)
        if marker is None:
            raise ValueError('No verified independent-copy manifest. Copy the project first.')
        manifest = json.loads(marker.read_text(encoding='utf-8'))
        if manifest.get('status') != 'verified' or manifest.get('schema_version') != 1:
            raise ValueError('Project copy has not been verified.')
        allowed = {_path(row['copy']) for row in manifest['files']}
        if path not in allowed or any(not _within(p, marker.parent) for p in allowed):
            raise ValueError('Document is outside the verified copy.')
        app = _ensure_app(sw)
        graph = _graph(app, [path])
        pending = list(graph)
        live_checked = set()
        while pending:
            current = pending.pop()
            if current in live_checked:
                continue
            live_checked.add(current)
            opened = com(app, 'GetOpenDocumentByName', str(current))
            if opened is None:
                continue
            if int(com(opened, 'GetType')) == 2:
                refs = []
                for component in com(opened, 'GetComponents', False) or []:
                    value = com(component, 'GetPathName')
                    if not value:
                        raise ValueError('Virtual/unresolved live component cannot be verified as an independent copy.')
                    refs.append(_path(value))
            else:
                from ..inspection.documents import inspect_dependencies
                inspected = inspect_dependencies(opened)
                if not inspected['complete']:
                    raise ValueError('Open document references cannot be fully verified.')
                refs = [_path(row['path']) for row in inspected['dependencies']]
            for ref in refs:
                if ref not in graph:
                    additional = _graph(app, [ref])
                    graph.update(additional)
                    pending.extend(additional)
        for referenced in graph:
            if referenced in allowed:
                continue
            # A selected occurrence can reference a separately duplicated,
            # verified component. It still must never reference an original.
            other_marker = next((p / MANIFEST for p in referenced.parents if (p / MANIFEST).is_file()), None)
            if other_marker is None:
                raise ValueError('Document references a file without a verified copy manifest.')
            other = json.loads(other_marker.read_text(encoding='utf-8'))
            members = {_path(row['copy']) for row in other.get('files', [])}
            if (other.get('status') != 'verified' or other.get('schema_version') != 1
                    or referenced not in members or any(not _within(p, other_marker.parent) for p in members)):
                raise ValueError('Referenced component copy is not verified.')
            policy.require_write(referenced, OperationClass.MUTATE)
        return None
    except Exception as error:
        return _fail(sw, str(error), 'COPY_ISOLATION_REQUIRED')

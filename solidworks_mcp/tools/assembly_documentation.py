"""Read-only occurrence planning; proposed paths never stand for completed exports."""
import csv
import hashlib
import json
import re
from pathlib import Path
from ..comutil import com
from ..core.policy import OperationClass
from ..registry import tool
from .manufacturing_package import _active, _policy, _failure
from .project_copy import _path, _graph


def _sha(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def _state(doc):
    return (str(com(doc, 'GetPathName')), com(com(com(doc, 'ConfigurationManager'),
        'ActiveConfiguration'), 'Name'), com(doc, 'GetUpdateStamp'), bool(com(doc, 'GetSaveFlag')))


def _proposed(path, purpose):
    return {'path': path, 'purpose': purpose, 'status': 'needs_review', 'created': False}


def _cell(value):
    value = str(value)
    return "'" + value if value.lstrip().startswith(('=', '+', '-', '@')) else value


@tool(name='plan_assembly_documentation',
    description='Read an exact saved active assembly without resolving or changing configurations; write JSON/CSV/Slovenian documentation plan with physical occurrence quantities, proposed STEP/PDF paths and explicit exclusions. Does not create drawings, DXF or STEP files or certify manufacturing readiness.',
    schema={'type': 'object', 'properties': {'document_path': {'type': 'string'},
        'configuration': {'type': 'string'}, 'output_folder': {'type': 'string'}},
        'required': ['document_path', 'configuration', 'output_folder']},
    operation_class=OperationClass.EXPORT)
def plan_assembly_documentation(sw, document_path, configuration, output_folder):
    created = False; folder = None; targets = []; plan = None
    try:
        path = _path(document_path); folder = _path(output_folder)
        _policy(sw, folder)
        if folder.exists(): raise ValueError('output_folder must be a new folder.')
        if not path.is_file() or path.suffix.casefold() != '.sldasm':
            raise ValueError('A saved assembly file is required.')
        if not isinstance(configuration, str) or not configuration.strip():
            raise ValueError('An exact configuration is required.')
        doc = _active(sw, path, configuration)
        if int(com(doc, 'GetType')) != 2: raise ValueError('Active document must be an assembly.')
        before = _state(doc)
        if before[3]: raise ValueError('Assembly must match its saved state; save explicitly first.')
        # Bind saved external master parts and suppressed dependencies too: a
        # copied part may rebuild from those without its own file changing.
        hashes = {p: _sha(p) for p in _graph(sw.app, [path])}
        native = com(doc, 'GetComponents', False)
        if native is None: raise ValueError('GetComponents returned no readable inventory.')
        components = list(native)
        if len(components) > 10000: raise ValueError('Inventory exceeds 10000 occurrences; split scope first.')
        grouped = {}; suppressed = []; unresolved = []; rows = []; loaded = []
        for index, component in enumerate(components):
            row = {'occurrence_index': index}
            try:
                row['instance_name'] = str(com(component, 'Name2'))
                row['suppression_state'] = int(com(component, 'GetSuppression'))
                rows.append((component, row))
            except Exception as error:
                row['reason'] = str(error); unresolved.append(row)
        inactive = {r['instance_name']: r['suppression_state'] for _, r in rows if r['suppression_state'] not in (2, 3)}
        inactive.update({r['instance_name']: None for r in unresolved if 'instance_name' in r})
        # A clean root can still contain unsaved edits in a loaded subassembly.
        for component, row in rows:
            if row['suppression_state'] not in (2, 3): continue
            try:
                child = com(component, 'GetModelDoc2')
                if child is None: raise ValueError('Resolved occurrence has no loaded document.')
                dirty = bool(com(child, 'GetSaveFlag'))
            except Exception as error:
                row['load_error'] = str(error); inactive[row['instance_name']] = None
                continue
            if dirty: raise ValueError('Loaded component has unsaved edits: ' + row['instance_name'])
            loaded.append(child)
        for component, row in rows:
            name = row['instance_name']; state = row['suppression_state']
            ancestors = ['/'.join(name.split('/')[:i]) for i in range(1, len(name.split('/')))]
            if state == 0 or any(inactive.get(a) == 0 for a in ancestors):
                row['reason'] = 'Suppressed occurrence or ancestor.'; suppressed.append(row); continue
            if state not in (2, 3) or 'load_error' in row or any(a in inactive for a in ancestors):
                row['reason'] = 'Unresolved/lightweight occurrence or ancestor; no resolve performed.'
                unresolved.append(row); continue
            try:
                if com(component, 'IsVirtual'): raise ValueError('Virtual document requires independent saved identity.')
                target = _path(com(component, 'GetPathName'))
                cfg = com(component, 'ReferencedConfiguration')
                if not isinstance(cfg, str) or not cfg.strip(): raise ValueError('Missing referenced configuration.')
                if not target.is_file() or target.suffix.casefold() not in ('.sldprt', '.sldasm'):
                    raise ValueError('Missing or unsupported saved component document.')
                hashes.setdefault(target, None)
                if hashes[target] is None: hashes[target] = _sha(target)
                key = (str(target).casefold(), cfg)
                item = grouped.setdefault(key, {'document_path': str(target), 'configuration': cfg,
                    'document_type': 'assembly' if target.suffix.casefold() == '.sldasm' else 'part',
                    'quantity': 0, 'occurrences': [], 'source_sha256': hashes[target],
                    'make_buy': 'needs_review', 'body_classification': 'not_inspected'})
                row['parent_instance'] = name.rsplit('/', 1)[0] if '/' in name else None
                item['quantity'] += 1; item['occurrences'].append(row)
            except Exception as error:
                row['reason'] = str(error); unresolved.append(row)
        items = [grouped[key] for key in sorted(grouped)]
        for index, item in enumerate(items, 1):
            identity = item['document_path'].casefold() + '\n' + item['configuration']
            item['source_key'] = hashlib.sha256(identity.encode('utf-8')).hexdigest()
            item['plan_id'] = f'K{index:04d}'
            label = re.sub(r'[^\w.-]+', '_', Path(item['document_path']).stem + '_' + item['configuration'])[:80]
            stem = item['plan_id'] + '_' + label
            drawing_dir = '05_Sestavne' if item['document_type'] == 'assembly' else '01_Delavniske'
            item['proposed_artifacts'] = [_proposed(f'{drawing_dir}/{stem}.pdf', 'Drawing: template, projection and dimension coverage require review.')]
            if item['document_type'] == 'part':
                item['proposed_artifacts'].append(_proposed(f'90_3D/{stem}.step', 'Generic part STEP, conditional on make/buy; not a per-body tube-laser file.'))
            item['pending'] = ['Confirm make/buy and revision.', 'Inspect bodies, cut-list membership, material and fabrication process.',
                'Confirm drawing template, projection, views, dimensions and tolerances.']
        _active(sw, path, configuration)
        if _state(doc) != before: raise ValueError('Assembly state changed during inventory; retry with stable document.')
        if any(bool(com(child, 'GetSaveFlag')) for child in loaded):
            raise ValueError('Loaded component changed during inventory; retry with stable saved documents.')
        for source, digest in hashes.items():
            if _sha(source) != digest: raise ValueError(f'Saved source changed during inventory: {source}')
        plan = {'schema_version': 1, 'status': 'needs_review', 'document_path': str(path),
            'configuration': configuration, 'source_sha256': hashes[path], 'update_stamp': before[2],
            'inventory_complete': not unresolved, 'active_occurrence_count': sum(i['quantity'] for i in items),
            'items': items, 'suppressed_occurrences': suppressed, 'unresolved_occurrences': unresolved,
            'exports_created': False, 'manufacturing_ready': False, 'tube_profile_format': 'STEP',
            'root_proposed_artifacts': [_proposed('05_Sestavne/SESTAV.pdf', 'Assembly drawing and BOM.'),
                _proposed('06_Montaza/MONTAZA.pdf', 'Installation reference levels, anchors and sequence require engineering inputs.')],
            'limitations': ['Quantities count flattened native physical occurrences once; subassemblies and children are not a purchasing rollup.',
                'Saved file identity only; component loaded geometry and body classifications are not inspected.',
                'No DXF or tube-laser path until exact body and fabrication process are confirmed.',
                'Plan IDs are labels within this plan, not permanent part numbers. Proposed paths are relative to the package root.']}
        # Subset export must bind these ephemeral K IDs to exact current sources,
        # configurations, occurrence paths, quantities and saved geometry hashes.
        plan['source_snapshot']=[{'path':str(p),'sha256':digest} for p,digest in sorted(hashes.items(),key=lambda r:str(r[0]).casefold())]
        def stable_exclusions(rows):
            values=[{k:v for k,v in row.items() if k!='occurrence_index'} for row in rows]
            return sorted(values,key=lambda row:json.dumps(row,sort_keys=True))
        signature={'path':str(path).casefold(),'configuration':configuration,'sha256':hashes[path],
            'saved_dependencies':[[row['path'].casefold(),row['sha256']] for row in plan['source_snapshot']],
            'items':[[i['source_key'],i['source_sha256'],i['quantity'],
                sorted(o['instance_name'] for o in i['occurrences'])] for i in items],
            'suppressed':stable_exclusions(suppressed),'unresolved':stable_exclusions(unresolved)}
        plan['plan_fingerprint']=hashlib.sha256(json.dumps(signature,sort_keys=True).encode('utf-8')).hexdigest()
        # Validate all output targets before the first write.
        overview = folder / '00_Pregled'
        targets = [overview / name for name in ('package-plan.json', 'kazalo.csv', 'PREBERI.md')]
        for target in targets: _policy(sw, target)
        folder.mkdir(parents=True, exist_ok=False); created = True; overview.mkdir()
        targets[0].write_text(json.dumps(plan, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
        with targets[1].open('w', encoding='utf-8-sig', newline='') as stream:
            writer = csv.writer(stream, delimiter=';')
            writer.writerow(['Oznaka', 'Datoteka', 'Konfiguracija', 'Vrsta', 'Kolicina', 'Make/buy', 'Predvidene poti'])
            for item in items:
                writer.writerow([_cell(v) for v in (item['plan_id'], item['document_path'], item['configuration'],
                    item['document_type'], item['quantity'], item['make_buy'],
                    ' | '.join(a['path'] for a in item['proposed_artifacts']))])
        targets[2].write_text('# Načrt dokumentacije sestava\n\n'
            f'Konfiguracija: {configuration}\n\n'
            f'Popisanih pojavitev: {plan["active_occurrence_count"]}; ciljev: {len(items)}; '
            f'izključenih: {len(suppressed)}; nerazrešenih: {len(unresolved)}.\n\n'
            'To je načrt. PDF, DXF in STEP še niso izdelani. Paket ni potrjen za izdelavo.\n\n'
            'kazalo.csv prikazuje količine po točni datoteki in konfiguraciji. package-plan.json '
            'ohrani native imena pojavitev in razloge izključitev. Podsestavov in otrok ne seštevaj v nabavno količino.\n\n'
            'Naslednje: potrdi izdelovalne/kupljene kose, telesa, material in revizijo; nato prave DXF/STEP izvoze '
            'in risbe s predlogo, projekcijo, merami ter tolerancami. Za cevi/profile je prvi format STEP, '
            'vendar je treba najprej potrditi posamezna telesa in zahteve izvajalca.\n', encoding='utf-8')
        plan['plan_files'] = [str(t) for t in targets]
        return sw._result(True, 'Assembly documentation plan written; exports and drawings remain pending.', data=plan)
    except Exception as error:
        if created:
            remaining = [str(t) for t in targets if t.exists()]
            failed = dict(plan or {}, status='failed', error=str(error), exports_created=False, manufacturing_ready=False)
            try:
                targets[0].write_text(json.dumps(failed, indent=2, ensure_ascii=False), encoding='utf-8')
            except Exception:
                pass  # Disk failures can also prevent writing a failed manifest; return paths explicitly.
            return _failure(sw, error, status='failed', output_folder=str(folder), partial_output_paths=remaining)
        return _failure(sw, error)

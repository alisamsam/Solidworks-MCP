"""Shared, CAD-independent parameter register for the local workspace."""

from __future__ import annotations

import json
import math
import sqlite3
from decimal import Decimal, InvalidOperation
from contextlib import contextmanager, closing
from pathlib import Path
from uuid import uuid4


DEFAULT_PATH = Path(__file__).resolve().parents[2] / "output" / "parameter-workspace" / "workspace.sqlite3"


class ValidationError(ValueError):
    pass


class Conflict(ValidationError):
    pass


def _uid():
    return str(uuid4())


def _json(value):
    try:
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    except (ValueError, TypeError) as error:
        raise ValidationError("Podatki morajo biti veljaven JSON brez neskončnih števil.") from error


def _id(value):
    if not isinstance(value, str) or not value.strip():
        raise ValidationError("Manjka veljaven besedilni ID.")
    return value


def _value(value, kind, choices=None):
    if value is None or value == "":
        return None
    if kind in ("number", "integer"):
        if isinstance(value, bool):
            raise ValidationError("Številska vrednost ni veljavna.")
        if kind == "integer":
            try:
                exact = Decimal(str(value).replace(",", "."))
            except (InvalidOperation, ValueError) as error:
                raise ValidationError("Vnesite celo število.") from error
            if not exact.is_finite() or exact != exact.to_integral_value() or abs(exact) > 9007199254740991:
                raise ValidationError("Vnesite točno celo število v razponu ±9007199254740991.")
            return int(exact)
        try:
            number = float(value.replace(",", ".") if isinstance(value, str) else value)
        except (ValueError, TypeError, OverflowError) as error:
            raise ValidationError("Vnesite veljavno število.") from error
        if not math.isfinite(number) or (kind == "integer" and not number.is_integer()):
            raise ValidationError("Vnesite končno število ustrezne vrste.")
        return int(number) if kind == "integer" else number
    if kind == "boolean":
        if not isinstance(value, bool):
            raise ValidationError("Vnesite da ali ne.")
        return value
    if kind in ("text", "enum"):
        if not isinstance(value, str) or len(value) > 2000:
            raise ValidationError("Besedilo ni veljavno.")
        if kind == "enum" and value not in (choices or []):
            raise ValidationError("Izbira ni na seznamu.")
        return value
    raise ValidationError("Nepodprta vrsta vrednosti.")


class ParameterStore:
    def __init__(self, path: Path | str = DEFAULT_PATH):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._db() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS projects (
                    id TEXT PRIMARY KEY, name TEXT NOT NULL, revision INTEGER NOT NULL DEFAULT 0);
                CREATE TABLE IF NOT EXISTS owners (
                    id TEXT PRIMARY KEY, project_id TEXT NOT NULL, parent_id TEXT,
                    kind TEXT NOT NULL, name TEXT NOT NULL, document_id TEXT,
                    document_path TEXT, instance_path TEXT, configuration TEXT,
                    FOREIGN KEY(project_id) REFERENCES projects(id));
                CREATE TABLE IF NOT EXISTS parameters (
                    id TEXT PRIMARY KEY, project_id TEXT NOT NULL, owner_id TEXT NOT NULL,
                    key TEXT NOT NULL, label TEXT NOT NULL, description TEXT NOT NULL DEFAULT '',
                    group_name TEXT NOT NULL DEFAULT 'Splošno', value_type TEXT NOT NULL,
                    unit TEXT, role TEXT NOT NULL, observed_json TEXT, draft_json TEXT,
                    choices_json TEXT, formula_json TEXT, binding_json TEXT,
                    source TEXT, reference TEXT, required INTEGER NOT NULL DEFAULT 0,
                    minimum REAL, maximum REAL,
                    FOREIGN KEY(owner_id) REFERENCES owners(id),
                    UNIQUE(project_id, owner_id, key));
                CREATE TABLE IF NOT EXISTS requests (
                    id TEXT PRIMARY KEY, project_id TEXT NOT NULL, owner_id TEXT,
                    text TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'waiting',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, project_id TEXT NOT NULL,
                    revision INTEGER NOT NULL, action TEXT NOT NULL, detail_json TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
                CREATE INDEX IF NOT EXISTS owners_project ON owners(project_id);
                CREATE INDEX IF NOT EXISTS parameters_project ON parameters(project_id);
                CREATE INDEX IF NOT EXISTS requests_project ON requests(project_id);
                CREATE INDEX IF NOT EXISTS events_project ON events(project_id);
                CREATE TABLE IF NOT EXISTS cad_jobs (
                    id TEXT PRIMARY KEY, project_id TEXT NOT NULL,
                    status TEXT NOT NULL, changes_json TEXT NOT NULL,
                    result_json TEXT, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(project_id) REFERENCES projects(id));
            """)

    def _connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys = ON")
        db.execute("PRAGMA busy_timeout = 10000")
        return db

    @contextmanager
    def _db(self):
        with closing(self._connect()) as db:
            with db:
                yield db

    @contextmanager
    def _write(self, project_id, expected_revision=None):
        _id(project_id)
        if expected_revision is not None and (type(expected_revision) is not int or expected_revision < 0):
            raise ValidationError("Revizija mora biti nenegativno celo število.")
        db = self._connect()
        try:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT revision FROM projects WHERE id=?", (project_id,)).fetchone()
            if row is None:
                raise ValidationError("Projekt ne obstaja.")
            if expected_revision is not None and row["revision"] != expected_revision:
                raise Conflict("Projekt se je medtem spremenil. Osvežite podatke in ohranite svoj osnutek.")
            yield db, row["revision"] + 1
            db.execute("UPDATE projects SET revision=revision+1 WHERE id=?", (project_id,))
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    @staticmethod
    def _event(db, project_id, revision, action, detail):
        db.execute("INSERT INTO events(project_id,revision,action,detail_json) VALUES(?,?,?,?)",
                   (project_id, revision, action, _json(detail)))

    def list_projects(self):
        with self._db() as db:
            return [dict(row) for row in db.execute("SELECT * FROM projects ORDER BY name COLLATE NOCASE")]

    def create_project(self, name):
        if not isinstance(name, str) or not name.strip() or len(name) > 200:
            raise ValidationError("Vnesite ime projekta.")
        project = {"id": _uid(), "name": name.strip(), "revision": 0}
        with self._db() as db:
            db.execute("INSERT INTO projects(id,name,revision) VALUES(?,?,0)",
                       (project["id"], project["name"]))
        return project

    def add_owner(self, project_id, owner, expected_revision=None):
        if not isinstance(owner, dict):
            raise ValidationError("Element mora biti objekt.")
        allowed = {"assembly", "part", "occurrence", "weldment_body", "drawing", "requirement"}
        if not isinstance(owner.get("kind"), str) or owner["kind"] not in allowed or not isinstance(owner.get("name"), str) or not owner["name"].strip():
            raise ValidationError("Vrsta ali ime elementa ni veljavno.")
        for key in ("parent_id", "document_id", "document_path", "instance_path", "configuration"):
            if owner.get(key) is not None and not isinstance(owner[key], str):
                raise ValidationError("Reference elementa morajo biti besedilne.")
        item = {"id": _uid(), "project_id": project_id, **{key: owner.get(key) for key in (
            "parent_id", "kind", "name", "document_id", "document_path", "instance_path", "configuration")}}
        with self._write(project_id, expected_revision) as (db, revision):
            if item["parent_id"] and not db.execute(
                "SELECT 1 FROM owners WHERE id=? AND project_id=?", (item["parent_id"], project_id)).fetchone():
                raise ValidationError("Nadrejeni element ni v tem projektu.")
            db.execute("""INSERT INTO owners(id,project_id,parent_id,kind,name,document_id,
                       document_path,instance_path,configuration) VALUES(?,?,?,?,?,?,?,?,?)""",
                       tuple(item[key] for key in ("id", "project_id", "parent_id", "kind", "name",
                                                   "document_id", "document_path", "instance_path", "configuration")))
            self._event(db, project_id, revision, "owner_added", {"id": item["id"], "name": item["name"]})
        return item

    def create_stair_railing_project(self, name):
        """Seed questions and dependencies, never dimensions or CAD bindings."""
        project = self.create_project(name)
        pid = project["id"]
        root = self.add_owner(pid, {"kind": "assembly", "name": "Stopniščni sklop"})
        stairs = self.add_owner(pid, {"kind": "part", "name": "Stopnice", "parent_id": root["id"]})
        railing = self.add_owner(pid, {"kind": "assembly", "name": "Ograja", "parent_id": root["id"]})
        post = self.add_owner(pid, {"kind": "occurrence", "name": "Levi steber", "parent_id": railing["id"]})

        def field(owner, key, label, kind="number", unit=None, group="Geometrija", reference=None):
            return self.add_parameter(pid, {"owner_id": owner["id"], "key": key,
                "label": label, "value_type": kind, "unit": unit, "role": "input",
                "group": group, "reference": reference, "required": True,
                "source": "Projektna zahteva; uporabnik še ni podal vrednosti"})

        total = field(stairs, "finished_floor_height", "Višina med dokončanima etažama", unit="mm",
                      reference="Od dokončane spodnje do dokončane zgornje etaže")
        count = field(stairs, "rise_count", "Število višin", kind="integer")
        field(stairs, "available_run", "Razpoložljiva tlorisna dolžina", unit="mm")
        field(stairs, "clear_width", "Svetla širina stopnic", unit="mm")
        self.add_parameter(pid, {"owner_id": stairs["id"], "key": "rise_height",
            "label": "Višina posamezne stopnice", "value_type": "number", "unit": "mm",
            "role": "derived", "group": "Geometrija",
            "formula": {"op": "divide", "inputs": [total["id"], count["id"]]},
            "source": "Izračun iz skupne višine in števila višin"})
        field(railing, "railing_height", "Višina ograje", unit="mm",
              reference="Določiti referenco merjenja ob stopnicah in podestu")
        field(railing, "infill", "Vrsta polnila", kind="text", group="Izvedba")
        field(post, "post_profile", "Profil stebra", kind="text", group="Profili")
        field(post, "anchoring", "Način sidranja", kind="text", group="Pritrditev")
        self.add_parameter(pid, {"owner_id": root["id"], "key": "hot_dip_galvanizing",
            "label": "Priprava za vroče cinkanje", "value_type": "boolean", "role": "input",
            "group": "Izdelava", "source": "Uporabnikova odločitev"})
        return self.snapshot(pid)["project"]

    def add_parameter(self, project_id, parameter, expected_revision=None):
        if not isinstance(parameter, dict):
            raise ValidationError("Parameter mora biti objekt.")
        _id(parameter.get("owner_id"))
        role = parameter.get("role", "input")
        kind = parameter.get("value_type")
        if not isinstance(role, str) or role not in {"input", "derived", "measurement", "constraint", "metadata"}:
            raise ValidationError("Vloga parametra ni veljavna.")
        if not isinstance(kind, str) or kind not in {"number", "integer", "boolean", "enum", "text"}:
            raise ValidationError("Vrsta parametra ni veljavna.")
        if any(not isinstance(parameter.get(key), str) or not parameter[key].strip() for key in ("key", "label")):
            raise ValidationError("Ključ in naziv parametra sta obvezna.")
        for key in ("description", "group", "unit", "source", "reference"):
            if parameter.get(key) is not None and not isinstance(parameter[key], str):
                raise ValidationError("Opisni podatki parametra morajo biti besedilni.")
        if parameter.get("binding") is not None and not isinstance(parameter["binding"], dict):
            raise ValidationError("CAD vezava mora biti objekt.")
        choices = parameter.get("choices")
        if kind == "enum" and (not isinstance(choices, list) or not choices or not all(isinstance(x, str) for x in choices)):
            raise ValidationError("Izbirni parameter potrebuje seznam možnosti.")
        formula = parameter.get("formula")
        if role != "derived" and formula is not None:
            raise ValidationError("Formula pripada izračunanemu parametru.")
        if type(parameter.get("required", False)) is not bool:
            raise ValidationError("Obveznost parametra mora biti da/ne.")
        if role == "derived" and (not isinstance(formula, dict) or not isinstance(formula.get("op"), str) or formula.get("op") not in
                                  {"add", "subtract", "multiply", "divide"} or
                                  not isinstance(formula.get("inputs"), list) or len(formula["inputs"]) != 2):
            raise ValidationError("Izračunani parameter potrebuje veljavno formulo.")
        if role == "derived" and kind not in {"number", "integer"}:
            raise ValidationError("Izračunani parameter mora biti številski.")
        if formula and not all(isinstance(value, str) for value in formula["inputs"]):
            raise ValidationError("Vhodi formule morajo biti ID parametrov.")
        item = {"id": _uid(), "project_id": project_id, "owner_id": parameter.get("owner_id"),
                "key": parameter["key"].strip(), "label": parameter["label"].strip(),
                "description": parameter.get("description") or "", "group_name": parameter.get("group") or "Splošno",
                "value_type": kind, "unit": parameter.get("unit") or None, "role": role,
                "observed_value": _value(parameter.get("observed_value"), kind, choices),
                "draft_value": None, "choices": choices, "formula": formula,
                "binding": parameter.get("binding"), "source": parameter.get("source"),
                "reference": parameter.get("reference"), "required": bool(parameter.get("required", False)),
                "minimum": _value(parameter.get("minimum"), "number"),
                "maximum": _value(parameter.get("maximum"), "number")}
        with self._write(project_id, expected_revision) as (db, revision):
            if not db.execute("SELECT 1 FROM owners WHERE id=? AND project_id=?", (item["owner_id"], project_id)).fetchone():
                raise ValidationError("Lastnik parametra ni v tem projektu.")
            if formula:
                input_rows = []
                for dependency in formula["inputs"]:
                    input_row = db.execute("SELECT unit,value_type FROM parameters WHERE id=? AND project_id=?",
                                           (dependency, project_id)).fetchone()
                    if input_row is None:
                        raise ValidationError("Formula vsebuje neznan vhod.")
                    if input_row["value_type"] not in {"number", "integer"}:
                        raise ValidationError("Računski vhodi morajo biti številski.")
                    input_rows.append(input_row)
                first_unit, second_unit = (row["unit"] or None for row in input_rows)
                if formula["op"] in {"add", "subtract"}:
                    expected_unit = first_unit if first_unit == second_unit else object()
                elif formula["op"] == "multiply":
                    expected_unit = first_unit or second_unit if not first_unit or not second_unit else object()
                else:
                    expected_unit = first_unit if not second_unit else (None if first_unit == second_unit else object())
                if item["unit"] != expected_unit:
                    raise ValidationError("Enote formule in rezultata niso skladne.")
            if item["minimum"] is not None and item["maximum"] is not None and item["minimum"] > item["maximum"]:
                raise ValidationError("Spodnja meja presega zgornjo.")
            observed = item["observed_value"]
            if kind in {"number", "integer"} and observed is not None:
                if (item["minimum"] is not None and observed < item["minimum"]) or (item["maximum"] is not None and observed > item["maximum"]):
                    raise ValidationError("Vrednost je zunaj navedenih mej.")
            try:
                db.execute("""INSERT INTO parameters(id,project_id,owner_id,key,label,description,group_name,
                    value_type,unit,role,observed_json,draft_json,choices_json,formula_json,binding_json,
                    source,reference,required,minimum,maximum) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (item["id"], project_id, item["owner_id"], item["key"], item["label"], item["description"],
                     item["group_name"], kind, item["unit"], role, _json(item["observed_value"]), None,
                     _json(choices), _json(formula), _json(item["binding"]), item["source"], item["reference"],
                     int(item["required"]), item["minimum"], item["maximum"]))
            except sqlite3.IntegrityError as error:
                raise ValidationError("Ključ parametra pri tem elementu že obstaja.") from error
            self._event(db, project_id, revision, "parameter_added", {"id": item["id"], "label": item["label"]})
        return item

    def set_draft(self, project_id, parameter_id, value, expected_revision=None):
        _id(parameter_id)
        with self._write(project_id, expected_revision) as (db, revision):
            row = db.execute("SELECT * FROM parameters WHERE id=? AND project_id=?",
                             (parameter_id, project_id)).fetchone()
            if row is None:
                raise ValidationError("Parameter ni v tem projektu.")
            if row["role"] not in {"input", "metadata"}:
                raise ValidationError("Ta parameter je samo za branje; spremenite njegove vhode.")
            normalized = _value(value, row["value_type"], json.loads(row["choices_json"] or "null"))
            if isinstance(normalized, (int, float)) and not isinstance(normalized, bool):
                if row["minimum"] is not None and normalized < row["minimum"]:
                    raise ValidationError("Vrednost je pod spodnjo mejo.")
                if row["maximum"] is not None and normalized > row["maximum"]:
                    raise ValidationError("Vrednost je nad zgornjo mejo.")
            db.execute("UPDATE parameters SET draft_json=? WHERE id=?", (_json(normalized), parameter_id))
            self._event(db, project_id, revision, "draft_changed", {"id": parameter_id,
                "label": row["label"], "owner_id": row["owner_id"], "value": normalized,
                "before": json.loads(row["draft_json"] if row["draft_json"] is not None else row["observed_json"]),
                "before_had_draft": row["draft_json"] is not None})
        return {"id": parameter_id, "draft_value": normalized, "has_draft": True}

    def discard_draft(self, project_id, parameter_id, expected_revision=None):
        _id(parameter_id)
        with self._write(project_id, expected_revision) as (db, revision):
            row = db.execute("SELECT * FROM parameters WHERE id=? AND project_id=?", (parameter_id, project_id)).fetchone()
            if row is None:
                raise ValidationError("Parameter ni v tem projektu.")
            db.execute("UPDATE parameters SET draft_json=NULL WHERE id=?", (parameter_id,))
            self._event(db, project_id, revision, "draft_discarded", {"id": parameter_id,
                "label": row["label"], "owner_id": row["owner_id"],
                "before": json.loads(row["draft_json"] or "null"),
                "value": json.loads(row["observed_json"] or "null")})
        return {"id": parameter_id, "has_draft": False}

    def add_request(self, project_id, text, owner_id=None, expected_revision=None):
        if owner_id is not None:
            _id(owner_id)
        if not isinstance(text, str) or not text.strip() or len(text) > 5000:
            raise ValidationError("Vnesite zahtevo do 5000 znakov.")
        item = {"id": _uid(), "project_id": project_id, "owner_id": owner_id,
                "text": text.strip(), "status": "waiting"}
        with self._write(project_id, expected_revision) as (db, revision):
            if owner_id and not db.execute("SELECT 1 FROM owners WHERE id=? AND project_id=?",
                                            (owner_id, project_id)).fetchone():
                raise ValidationError("Izbrani element ni v tem projektu.")
            db.execute("INSERT INTO requests(id,project_id,owner_id,text,status) VALUES(?,?,?,?,?)",
                       (item["id"], project_id, owner_id, item["text"], "waiting"))
            self._event(db, project_id, revision, "request_added", {"id": item["id"], "text": item["text"]})
        return item

    def update_request(self, project_id, request_id, status, expected_revision=None):
        _id(request_id)
        allowed = {"waiting", "in_progress", "needs_info", "proposed", "completed", "rejected", "cancelled"}
        if not isinstance(status, str) or status not in allowed:
            raise ValidationError("Status zahteve ni veljaven.")
        with self._write(project_id, expected_revision) as (db, revision):
            row = db.execute("SELECT * FROM requests WHERE id=? AND project_id=?", (request_id, project_id)).fetchone()
            if row is None:
                raise ValidationError("Zahteva ni v tem projektu.")
            db.execute("UPDATE requests SET status=? WHERE id=?", (status, request_id))
            self._event(db, project_id, revision, "request_status_changed", {"id": request_id, "status": status})
        return {"id": request_id, "status": status}

    def queue_cad_job(self, project_id, expected_revision):
        if type(expected_revision) is not int: raise ValidationError('Manjka pričakovana revizija.')
        snap = self.snapshot(project_id)
        changes = []
        for p in snap['parameters']:
            if not p['has_draft']: continue
            b = p['binding'] or {}
            if p['role'] != 'input' or b.get('kind') != 'dimension' or p['draft_value'] is None:
                raise ValidationError('Osnutek nima podprte zapisljive CAD vezave: ' + p['label'])
            if p['value_type'] not in {'number','integer'} or p['observed_value'] is None:
                raise ValidationError('CAD mera potrebuje začetno številsko vrednost.')
            if any(not isinstance(b.get(k),str) or not b[k] for k in ('document_path','configuration','name')):
                raise ValidationError('Nepopolna CAD vezava.')
            changes.append({'parameter_id':p['id'], 'document_path':b['document_path'],
                'configuration':b['configuration'],'name':b['name'],'unit':p['unit'],
                'value':p['draft_value'],'expected_value':p['observed_value']})
        if not changes or len(changes)>100: raise ValidationError('Potrebujemo 1 do 100 vezanih osnutkov.')
        job={'id':_uid(),'project_id':project_id,'status':'queued','changes':changes}
        with self._write(project_id,expected_revision) as (db,revision):
            if snap['revision'] != expected_revision: raise Conflict('Projekt se je spremenil.')
            if db.execute("SELECT 1 FROM cad_jobs WHERE project_id=? AND status IN ('queued','running')",(project_id,)).fetchone():
                raise Conflict('Projekt že ima čakajočo CAD operacijo.')
            db.execute('INSERT INTO cad_jobs(id,project_id,status,changes_json) VALUES(?,?,?,?)',
                (job['id'],project_id,'queued',_json(changes)))
            self._event(db,project_id,revision,'cad_queued',{'id':job['id'],'count':len(changes)})
        return job

    def claim_cad_job(self, project_id, job_id):
        with self._write(project_id) as (db,revision):
            row=db.execute('SELECT * FROM cad_jobs WHERE id=? AND project_id=?',(job_id,project_id)).fetchone()
            if row is None: raise ValidationError('CAD operacija ne obstaja.')
            if row['status']!='queued': raise Conflict('CAD operacija ni v čakalni vrsti.')
            changes=json.loads(row['changes_json'])
            for c in changes:
                p=db.execute('SELECT observed_json,draft_json FROM parameters WHERE id=? AND project_id=?',(c['parameter_id'],project_id)).fetchone()
                if p is None or p['draft_json'] is None or json.loads(p['observed_json'])!=c['expected_value'] or json.loads(p['draft_json'])!=c['value']:
                    raise Conflict('Osnutek ali prebrana vrednost se je spremenila; prekličite in oddajte novo operacijo.')
            db.execute("UPDATE cad_jobs SET status='running' WHERE id=?",(job_id,))
            self._event(db,project_id,revision,'cad_running',{'id':job_id})
        return {'id':job_id,'changes':changes}

    def finish_cad_job(self, project_id, job_id, result):
        with self._write(project_id) as (db,revision):
            row=db.execute('SELECT * FROM cad_jobs WHERE id=? AND project_id=?',(job_id,project_id)).fetchone()
            if row is None or row['status']!='running': raise Conflict('Operacija ni v izvajanju.')
            success=result.get('success') is True
            if success:
                for c in json.loads(row['changes_json']):
                    p=db.execute('SELECT draft_json FROM parameters WHERE id=?',(c['parameter_id'],)).fetchone()
                    same=p['draft_json'] is not None and json.loads(p['draft_json'])==c['value']
                    db.execute('UPDATE parameters SET observed_json=?,draft_json=? WHERE id=?',
                        (_json(c['value']),None if same else p['draft_json'],c['parameter_id']))
            db.execute('UPDATE cad_jobs SET status=?,result_json=? WHERE id=?',
                ('completed' if success else 'failed',_json(result),job_id))
            self._event(db,project_id,revision,'cad_completed' if success else 'cad_failed',{'id':job_id})
        return {'id':job_id,'status':'completed' if success else 'failed'}

    def cancel_cad_job(self, project_id, job_id, expected_revision):
        with self._write(project_id,expected_revision) as (db,revision):
            changed=db.execute("UPDATE cad_jobs SET status='cancelled' WHERE id=? AND project_id=? AND status='queued'",(job_id,project_id)).rowcount
            if not changed: raise Conflict('Prekličete lahko samo čakajočo operacijo.')
            self._event(db,project_id,revision,'cad_cancelled',{'id':job_id})
        return {'id':job_id,'status':'cancelled'}

    def snapshot(self, project_id):
        _id(project_id)
        with self._db() as db:
            db.execute("BEGIN")
            project = db.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone()
            if project is None:
                raise ValidationError("Projekt ne obstaja.")
            owners = [dict(r) for r in db.execute("SELECT * FROM owners WHERE project_id=? ORDER BY rowid", (project_id,))]
            params = []
            for row in db.execute("SELECT * FROM parameters WHERE project_id=? ORDER BY rowid", (project_id,)):
                p = dict(row)
                p["has_draft"] = p["draft_json"] is not None
                for key, target in (("observed_json", "observed_value"), ("draft_json", "draft_value"),
                                    ("choices_json", "choices"), ("formula_json", "formula"),
                                    ("binding_json", "binding")):
                    raw = p.pop(key)
                    p[target] = json.loads(raw) if raw is not None else None
                p["group"] = p.pop("group_name")
                p["required"] = bool(p["required"])
                p["binding_state"] = "unverified" if p["binding"] else "unbound"
                p["availability"] = "read_only" if p["role"] not in {"input", "metadata"} else "draft_only"
                p["effective_value"] = p["draft_value"] if p["has_draft"] else p["observed_value"]
                p["completeness"] = "missing" if p["effective_value"] is None else "provided"
                params.append(p)
            self._calculate(params)
            requests = [dict(r) for r in db.execute("SELECT * FROM requests WHERE project_id=? ORDER BY rowid DESC", (project_id,))]
            cad_jobs = []
            for row in db.execute('SELECT * FROM cad_jobs WHERE project_id=? ORDER BY rowid DESC',(project_id,)):
                job=dict(row); job['changes']=json.loads(job.pop('changes_json'))
                job['result']=json.loads(job.pop('result_json') or 'null');cad_jobs.append(job)
            history = [{**dict(r), "detail": json.loads(r["detail_json"])} for r in db.execute(
                "SELECT * FROM events WHERE project_id=? ORDER BY id DESC LIMIT 100", (project_id,))]
            for event in history:
                del event["detail_json"]
            return {"project": dict(project), "revision": project["revision"], "owners": owners,
                      "parameters": params, "requests": requests, "history": history, "cad_jobs": cad_jobs,
                    "schema_version": 1,
                    "cad": {"connected": False, "apply_available": False,
                            "supported_operations": [],
                              "queue_available": True,
                              "reason": "Osnutke izvede agent z MCP orodjem process_parameter_workspace_job; spletna stran sama ne upravlja SolidWorksa."},
                    "coverage": "Projektni parametri in uvožene CAD mere; vezane osnutke izvede MCP agent."}

    @staticmethod
    def _calculate(params):
        values = {}
        for p in params:
            p["calculation_error"] = None
            if p["role"] != "derived":
                values[p["id"]] = p["effective_value"]
                p["computed_value"] = None
                continue
            formula = p["formula"]
            p["effective_value"] = None
            a, b = (values.get(key) for key in formula["inputs"])
            if a is None or b is None:
                p["computed_value"] = None
                p["completeness"] = "missing_input"
                values[p["id"]] = None
                continue
            if not all(isinstance(x, (int, float)) and not isinstance(x, bool) for x in (a, b)):
                p["computed_value"] = None
                p["completeness"] = "invalid_input"
                p["calculation_error"] = "Vhodi izračuna morajo biti številski."
                values[p["id"]] = None
                continue
            op = formula["op"]
            if op == "divide" and b == 0:
                p["calculation_error"] = "Deljenje z nič ni dovoljeno; spremenite drugi vhod."
            try:
                result = {"add": lambda: a + b, "subtract": lambda: a - b,
                          "multiply": lambda: a * b, "divide": lambda: a / b}[op]()
            except (ZeroDivisionError, OverflowError):
                result = None
            try:
                valid = result is not None and math.isfinite(result)
                if valid and p["value_type"] == "integer":
                    valid = float(result).is_integer()
            except OverflowError:
                valid = False
            p["computed_value"] = result if valid else None
            p["effective_value"] = p["computed_value"]
            p["completeness"] = "calculated" if p["computed_value"] is not None else "invalid_input"
            if not valid and not p["calculation_error"]:
                p["calculation_error"] = "Rezultat ni veljavno končno število zahtevane vrste."
            values[p["id"]] = p["computed_value"]


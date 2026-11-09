"""Bounded read of an existing manufacturer article catalogue, not a CAD generator."""
import copy
import hashlib
import json
import math
from pathlib import Path

from ..constants import SwErrors
from ..core.policy import OperationClass
from ..registry import tool
from .routing import _routing_allowed

MAX_CATALOG_BYTES = 4 * 1024 * 1024
MAX_ARTICLES = 1000


def _reject_nonfinite(value):
    raise ValueError(f"Non-finite JSON value is not a catalogue dimension: {value}")


def _finite_json_float(value):
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("JSON numeric value exceeds the finite floating-point range.")
    return number


@tool(
    name="get_routing_library_article",
    description="Read one exact article from an existing local Routing article catalogue JSON (articles array). Returns original dimensions, source and catalogue status plus a SHA256 fingerprint. Offline, no CAD or geometry mutation. Missing dimensions stay missing; catalogue membership does not prove physical geometry or native Routing readiness. Maximum 4MiB/1000 articles.",
    schema={"type": "object", "properties": {
        "catalog_path": {"type": "string", "minLength": 1},
        "article_id": {"type": "string", "minLength": 1}},
        "required": ["catalog_path", "article_id"], "additionalProperties": False},
    operation_class=OperationClass.READ,
    com=False,
)
def get_routing_library_article(sw, catalog_path, article_id):
    if not _routing_allowed():
        return sw._result(False, "Routing is disabled.", SwErrors.swInvalidInput,
                          {"code": "ROUTING_DISABLED"})
    try:
        if not isinstance(catalog_path, str) or not catalog_path or not isinstance(article_id, str) or not article_id:
            raise ValueError("catalog_path and article_id must be non-empty strings.")
        path = Path(catalog_path)
        if not path.is_absolute() or path.is_symlink() or not path.is_file():
            raise ValueError("Supply an existing absolute, non-symlink catalogue file.")
        with path.open("rb") as stream:
            content = stream.read(MAX_CATALOG_BYTES + 1)
        if len(content) > MAX_CATALOG_BYTES:
            raise ValueError("Catalogue exceeds the 4MiB read limit.")
        payload = json.loads(content.decode("utf-8-sig"), parse_constant=_reject_nonfinite,
                             parse_float=_finite_json_float)
        if not isinstance(payload, dict) or payload.get("unit") != "mm":
            raise ValueError("Expected an article catalogue object with unit mm.")
        articles = payload.get("articles")
        if not isinstance(articles, list) or len(articles) > MAX_ARTICLES:
            raise ValueError("Expected an articles array of at most 1000 items.")
        seen = set()
        found = None
        for article in articles:
            if not isinstance(article, dict) or not isinstance(article.get("id"), str) or not article["id"]:
                raise ValueError("Each article requires a non-empty string id.")
            if article["id"] in seen:
                raise ValueError(f"Duplicate article id: {article['id']}")
            seen.add(article["id"])
            if article["id"] == article_id: found = article
        if found is None:
            return sw._result(False, f"Article not found: {article_id}", SwErrors.swInvalidInput,
                              {"code": "ARTICLE_NOT_FOUND", "catalog_path": str(path.resolve())})
        if not isinstance(found.get("dimensions"), dict):
            raise ValueError("Article dimensions must be an object; unknown values must remain explicit.")
        return sw._result(True, "Original Routing library article read; no CAD readiness inferred.", data={
            "catalog_path": str(path.resolve()), "catalog_sha256": hashlib.sha256(content).hexdigest(),
            "catalog_revision": payload.get("revision"), "catalog_unit": "mm",
            "article": copy.deepcopy(found), "cad_inspected": False,
            "notes": ["Raw source dimensions and null values are preserved without numeric guesses.",
                      "Article presence is not a geometry, CPoint, Wizard or live-route verification."]})
    except (OSError, ValueError, TypeError, RecursionError) as exc:
        return sw._result(False, f"Cannot read Routing article: {exc}", SwErrors.swInvalidInput,
                          {"code": "CATALOG_READ_FAILED"})

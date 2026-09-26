"""Catalogue d'actions FlightGear (pour l'assignation et les actions non assignées)."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Optional

from lxml import etree

from .bindings import canonical, is_null
from .props import PNode, element_to_pnode

DATA_DIR = Path(__file__).resolve().parent.parent / "data"

_SPEC_TAGS = [
    ("prop", "property"),
    ("prop2", "property"),
    ("dialog", "dialog-name"),
    ("value", "value"),
    ("step", "step"),
    ("min", "min"),
    ("max", "max"),
    ("offset", "offset"),
    ("factor", "factor"),
    ("power", "power"),
]


def spec_to_xml(spec: dict) -> str:
    """Convertit une description compacte ({cmd, prop, script...}) en <binding>."""
    b = etree.Element("binding")
    etree.SubElement(b, "command").text = spec["cmd"]
    for key, tag in _SPEC_TAGS:
        if key in spec:
            el = etree.SubElement(b, tag)
            el.text = str(spec[key])
            if key in ("step", "offset", "factor", "min", "max"):
                el.set("type", "double")
    if "script" in spec:
        s = etree.SubElement(b, "script")
        txt = spec["script"]
        s.text = etree.CDATA(txt) if any(c in txt for c in "<>&") else txt
    etree.indent(b, space="  ")
    return etree.tostring(b, encoding="unicode")


@dataclass
class Action:
    id: str
    category: str
    label: str
    kind: str  # "button" | "axis"
    press: list[str]  # XML des bindings
    release: list[str] = field(default_factory=list)
    repeatable: bool = False
    patterns: list[list[re.Pattern]] = field(default_factory=list)
    source: str = "catalogue"

    def matches(self, canon: str) -> bool:
        return any(all(p.search(canon) for p in alt) for alt in self.patterns)

    def matches_any(self, bindings: Iterable[PNode]) -> bool:
        return any(self.matches(canonical(b)) for b in bindings if not is_null(b))

    def press_nodes(self) -> list[PNode]:
        return [element_to_pnode(etree.fromstring(x.encode("utf-8")), "binding") for x in self.press]


def _auto_patterns(spec: dict) -> list[list[str]]:
    cmd = spec["cmd"]
    if cmd == "nasal":
        call = spec.get("script", "").strip().rstrip(";")
        return [[re.escape(re.sub(r"\s+", " ", call))]]
    alt = [f"^cmd={re.escape(cmd)}$"]
    if "prop" in spec:
        alt.append("^prop=" + re.escape(spec["prop"].lstrip("/")) + "$")
    if "dialog" in spec:
        alt.append("^dialog=" + re.escape(spec["dialog"]) + "$")
    return [alt]


def _load_file(path: Path, source: str) -> list[Action]:
    data = json.loads(path.read_text(encoding="utf-8"))
    out = []
    for a in data.get("actions", []):
        press = [spec_to_xml(s) for s in a.get("press", [])]
        release = [spec_to_xml(s) for s in a.get("release", [])]
        pats = a.get("match") or (_auto_patterns(a["press"][0]) if a.get("press") else [])
        compiled = [[re.compile(p, re.M | re.I) for p in alt] for alt in pats]
        out.append(Action(
            id=a["id"], category=a.get("cat", "Divers"), label=a["label"], kind=a.get("kind", "button"),
            press=press, release=release, repeatable=bool(a.get("repeatable", False)), patterns=compiled,
            source=source,
        ))
    return out


class Catalog:
    def __init__(self, actions: list[Action]):
        self.actions = actions
        self.by_id = {a.id: a for a in actions}

    @classmethod
    def load(cls, user_file: Optional[Path] = None) -> "Catalog":
        actions = _load_file(DATA_DIR / "actions.json", "catalogue")
        if user_file is not None and user_file.is_file():
            try:
                extra = _load_file(user_file, "utilisateur")
                ids = {a.id for a in extra}
                actions = [a for a in actions if a.id not in ids] + extra
            except (ValueError, KeyError, re.error):
                pass
        return cls(actions)

    def categories(self) -> list[str]:
        seen: dict[str, None] = {}
        for a in self.actions:
            seen.setdefault(a.category, None)
        return list(seen)

    def identify(self, bindings: Iterable[PNode]) -> Optional[Action]:
        bl = [b for b in bindings if not is_null(b)]
        if not bl:
            return None
        canons = [canonical(b) for b in bl]
        for a in self.actions:
            if any(a.matches(c) for c in canons):
                return a
        return None

    def bound_ids(self, binding_lists: Iterable[Iterable[PNode]]) -> set[str]:
        canons = []
        for bl in binding_lists:
            for b in bl:
                if not is_null(b):
                    canons.append(canonical(b))
        out = set()
        for a in self.actions:
            if any(a.matches(c) for c in canons):
                out.add(a.id)
        return out

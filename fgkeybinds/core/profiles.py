"""Profils de raccourcis : export / import (JSON .fgkb ou XML FlightGear)."""

from __future__ import annotations

import datetime as _dt
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from lxml import etree

from . import __version__
from .bindings import MOD_RELEASED, binding_to_xml, mask_path
from .keyboard import KeyboardConfig, Slot, combo_label
from .props import PNode, PropertyLoader, element_to_pnode

FORMAT = "fgkeybinds-profile"


@dataclass
class SlotEntry:
    code: int
    mask: int
    press: list[str] = field(default_factory=list)
    release: list[str] = field(default_factory=list)
    desc: Optional[str] = None
    repeatable: bool = False
    label: str = ""

    @property
    def key(self) -> tuple[int, int]:
        return self.code, self.mask

    def to_json(self) -> dict:
        return {
            "code": self.code, "mask": self.mask, "label": self.label or combo_label(self.code, self.mask),
            "desc": self.desc, "repeatable": self.repeatable, "press": self.press, "release": self.release,
        }

    @classmethod
    def from_json(cls, d: dict) -> "SlotEntry":
        return cls(code=int(d["code"]), mask=int(d.get("mask", 0)), press=list(d.get("press", [])),
                   release=list(d.get("release", [])), desc=d.get("desc"),
                   repeatable=bool(d.get("repeatable", False)), label=d.get("label", ""))

    def press_nodes(self) -> list[PNode]:
        return [element_to_pnode(etree.fromstring(x.encode("utf-8")), "binding") for x in self.press]

    def release_nodes(self) -> list[PNode]:
        return [element_to_pnode(etree.fromstring(x.encode("utf-8")), "binding") for x in self.release]


@dataclass
class JoystickEntry:
    names: list[str]
    xml: str  # fichier de configuration complet

    def to_json(self) -> dict:
        return {"names": self.names, "xml": self.xml}


@dataclass
class Profile:
    name: str
    keyboard: list[SlotEntry] = field(default_factory=list)
    joysticks: list[JoystickEntry] = field(default_factory=list)
    source: dict = field(default_factory=dict)
    created: str = ""
    notes: str = ""

    def to_json(self) -> dict:
        return {
            "format": FORMAT, "version": 1, "app": f"FGKeybinds {__version__}", "name": self.name,
            "created": self.created or _dt.datetime.now().isoformat(timespec="seconds"),
            "source": self.source, "notes": self.notes,
            "keyboard": [e.to_json() for e in self.keyboard],
            "joysticks": [j.to_json() for j in self.joysticks],
        }


def slot_entry(slot: Slot, kb: KeyboardConfig) -> SlotEntry:
    return SlotEntry(
        code=slot.code, mask=slot.mask,
        press=[binding_to_xml(b.node) for b in slot.press if not b.null],
        release=[binding_to_xml(b.node) for b in slot.release if not b.null],
        desc=slot.desc, repeatable=kb.repeatable(slot.code), label=combo_label(slot.code, slot.mask),
    )


def save_profile(profile: Profile, path: Path) -> None:
    path.write_text(json.dumps(profile.to_json(), ensure_ascii=False, indent=2), encoding="utf-8")


def load_profile(path: Path) -> Profile:
    """Charge un profil .fgkb (JSON) ou un fichier clavier XML de FlightGear."""
    raw = path.read_bytes()
    text = raw.lstrip()
    if text.startswith(b"{"):
        d = json.loads(raw.decode("utf-8"))
        if d.get("format") != FORMAT:
            raise ValueError("Ce fichier JSON n'est pas un profil FGKeybinds.")
        return Profile(
            name=d.get("name", path.stem), source=d.get("source", {}), created=d.get("created", ""),
            notes=d.get("notes", ""),
            keyboard=[SlotEntry.from_json(e) for e in d.get("keyboard", [])],
            joysticks=[JoystickEntry(list(j.get("names", [])), j["xml"]) for j in d.get("joysticks", [])],
        )
    return profile_from_keyboard_xml(path)


def profile_from_keyboard_xml(path: Path) -> Profile:
    loader = PropertyLoader(phase="import")
    root = loader.load(path)
    # fichier clavier seul (<PropertyList><key ...>) ou -set.xml (input/keyboard)
    kbnode = root if root.children("key") else root.node("input/keyboard")
    if kbnode is None or not kbnode.children("key"):
        # un fichier de joystick ?
        if root.children("name") and (root.children("axis") or root.children("button")):
            xml = path.read_text(encoding="utf-8", errors="replace")
            return Profile(name=path.stem, joysticks=[JoystickEntry([(n.value or "").strip() for n in root.children("name")], xml)])
        raise ValueError("Aucune touche (<key>) trouvée dans ce fichier.")
    kb = KeyboardConfig(kbnode)
    entries = [slot_entry(s, kb) for s in kb.slots() if s.press or s.release]
    return Profile(name=path.stem, keyboard=entries, source={"file": str(path)})


def keyboard_xml(entries: list[SlotEntry], comment: str = "") -> str:
    """Fichier clavier FlightGear autonome (utilisable avec include=)."""
    root = etree.Element("PropertyList")
    by_code: dict[int, list[SlotEntry]] = {}
    for e in entries:
        by_code.setdefault(e.code, []).append(e)
    for code in sorted(by_code):
        key = etree.SubElement(root, "key", n=str(code))
        etree.SubElement(key, "name").text = combo_label(code, 0)
        es = sorted(by_code[code], key=lambda e: e.mask)
        e0 = next((e for e in es if e.mask == 0), None)
        if e0 is not None and e0.desc:
            etree.SubElement(key, "desc").text = e0.desc
        if any(e.repeatable for e in es):
            etree.SubElement(key, "repeatable", type="bool").text = "true"
        for e in es:
            node = key
            for tag in mask_path(e.mask):
                found = node.find(tag)
                node = found if found is not None else etree.SubElement(node, tag)
            if e.mask and e.desc:
                etree.SubElement(node, "desc").text = e.desc
            for x in e.press:
                node.append(etree.fromstring(x.encode("utf-8")))
            if e.release:
                up = node
                for tag in mask_path(e.mask | MOD_RELEASED)[len(mask_path(e.mask)):]:
                    found = up.find(tag)
                    up = found if found is not None else etree.SubElement(up, tag)
                for x in e.release:
                    up.append(etree.fromstring(x.encode("utf-8")))
    for el in root.iter():
        if isinstance(el.tag, str):
            if el.text is not None and not el.text.strip() and len(el):
                el.text = None
            if el.tail is not None and not el.tail.strip():
                el.tail = None
    etree.indent(root, space="  ")
    body = etree.tostring(root, encoding="unicode")
    head = '<?xml version="1.0" encoding="UTF-8"?>\n'
    if comment:
        head += "<!-- " + comment.replace("--", "—") + " -->\n"
    return head + body + "\n"

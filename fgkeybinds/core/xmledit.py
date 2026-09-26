"""Édition des fichiers XML de FlightGear en préservant leur mise en forme.

Toutes les écritures passent par :func:`save`, qui crée une sauvegarde
``<fichier>.fgkb-backup`` lors de la première modification d'un fichier.
"""

from __future__ import annotations

import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Optional

from lxml import etree

from .bindings import (
    MOD_RELEASED,
    MOD_TAGS,
    mask_path,
    path_mask,
)

BACKUP_SUFFIX = ".fgkb-backup"

_EDIT_PARSER = etree.XMLParser(
    remove_blank_text=False,
    strip_cdata=False,
    remove_comments=False,
    resolve_entities=False,
    huge_tree=True,
    no_network=True,
)


class EditError(Exception):
    pass


# ---------------------------------------------------------------------------
# Lecture / écriture
# ---------------------------------------------------------------------------

def load_for_edit(path: Path) -> etree._ElementTree:
    try:
        return etree.parse(str(path), _EDIT_PARSER)
    except etree.XMLSyntaxError as e:
        raise EditError(f"Le fichier {path} contient une erreur XML et ne peut pas être modifié : {e}") from e
    except OSError as e:
        raise EditError(f"Impossible de lire {path} : {e}") from e


def backup_path(path: Path) -> Path:
    return path.with_name(path.name + BACKUP_SUFFIX)


def ensure_backup(path: Path) -> Optional[Path]:
    if not path.exists():
        return None
    b = backup_path(path)
    if not b.exists():
        shutil.copy2(path, b)
    return b


def save(tree: etree._ElementTree, path: Path, backup: bool = True) -> None:
    crlf = False
    if path.exists():
        with path.open("rb") as fh:
            crlf = b"\r\n" in fh.read(4096)
        if backup:
            ensure_backup(path)
    enc = tree.docinfo.encoding or "UTF-8"
    root = tree.getroot()
    # Sérialisation nœud par nœud : les commentaires placés avant/après la racine
    # restent sur leurs propres lignes.
    before, after = [], []
    node = root.getprevious()
    while node is not None:
        before.insert(0, node)
        node = node.getprevious()
    node = root.getnext()
    while node is not None:
        after.append(node)
        node = node.getnext()
    parts = [f'<?xml version="1.0" encoding="{enc}"?>'.encode("ascii")]
    doctype = tree.docinfo.doctype
    if doctype:
        parts.append(doctype.encode(enc))
    for n in before:
        parts.append(_tostring_node(n, enc))
    parts.append(_tostring_node(root, enc))
    for n in after:
        parts.append(_tostring_node(n, enc))
    data = b"\n".join(parts) + b"\n"
    if crlf:
        data = data.replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".fgkb-tmp")
    tmp.write_bytes(data)
    tmp.replace(path)


def _tostring_node(node: etree._Element, enc: str) -> bytes:
    tail = node.tail
    node.tail = None
    try:
        return etree.tostring(node, encoding=enc, xml_declaration=False).rstrip(b"\r\n")
    finally:
        node.tail = tail


def restore_backup(path: Path) -> bool:
    b = backup_path(path)
    if not b.exists():
        return False
    shutil.copy2(b, path)
    return True


def safe_comment(text: str) -> etree._Element:
    """Commentaire XML valide quel que soit le texte (pas de « -- », pas de « - » final)."""
    t = text
    while "--" in t:
        t = t.replace("--", "- -")
    if t.endswith("-"):
        t += " "
    return etree.Comment(t)


def new_document(root_tag: str = "PropertyList", comment: Optional[str] = None) -> etree._ElementTree:
    root = etree.Element(root_tag)
    tree = etree.ElementTree(root)
    if comment:
        root.addprevious(safe_comment(comment))
    root.text = "\n"
    return tree


# ---------------------------------------------------------------------------
# Indentation
# ---------------------------------------------------------------------------

def _elements(el: etree._Element) -> list[etree._Element]:
    return [c for c in el if isinstance(c.tag, str)]


def indent_of(el: etree._Element) -> str:
    """Indentation (espaces/tabulations) de la ligne où commence ``el``."""
    prev = el.getprevious()
    ws = prev.tail if prev is not None else (el.getparent().text if el.getparent() is not None else "")
    ws = ws or ""
    if "\n" in ws:
        return ws.rsplit("\n", 1)[1]
    return ""


def indent_unit(tree_or_el) -> str:
    root = tree_or_el.getroot() if hasattr(tree_or_el, "getroot") else tree_or_el.getroottree().getroot()
    for c in root.iter():
        if not isinstance(c.tag, str) or c is root:
            continue
        ind = indent_of(c)
        parent = c.getparent()
        pind = indent_of(parent) if parent is not None and parent is not root else ""
        if ind.startswith(pind) and len(ind) > len(pind):
            unit = ind[len(pind):]
            if unit.strip() == "":
                return unit
    return "  "


def child_indent(parent: etree._Element) -> str:
    kids = _elements(parent)
    if kids:
        return indent_of(kids[0])
    root = parent.getroottree().getroot()
    base = "" if parent is root else indent_of(parent)
    return base + indent_unit(parent)


def _closing_indent(parent: etree._Element) -> str:
    root = parent.getroottree().getroot()
    return "" if parent is root else indent_of(parent)


def format_new(el: etree._Element, indent: str, unit: str) -> etree._Element:
    """Met en forme un sous-arbre nouvellement créé."""
    level_kids = _elements(el)
    if not level_kids:
        return el
    inner = indent + unit
    el.text = "\n" + inner
    for i, c in enumerate(level_kids):
        format_new(c, inner, unit)
        c.tail = "\n" + (inner if i < len(level_kids) - 1 else indent)
    return el


def insert_child(parent: etree._Element, child: etree._Element, index: Optional[int] = None) -> etree._Element:
    """Insère ``child`` avec une indentation cohérente (index parmi les éléments)."""
    unit = indent_unit(parent)
    ind = child_indent(parent)
    format_new(child, ind, unit)
    kids = _elements(parent)
    if index is None or index >= len(kids):
        if kids:
            last = parent[-1]
            child.tail = last.tail if last.tail and "\n" in last.tail else "\n" + _closing_indent(parent)
            last.tail = "\n" + ind
            parent.append(child)
        else:
            parent.text = "\n" + ind
            child.tail = "\n" + _closing_indent(parent)
            parent.append(child)
    else:
        ref = kids[index]
        ref.addprevious(child)
        child.tail = "\n" + ind
    return child


def remove_child(child: etree._Element) -> None:
    parent = child.getparent()
    if parent is None:
        return
    if child.getnext() is None:
        # dernier nœud : son « tail » porte l'indentation de la balise fermante du parent
        prev = child.getprevious()
        if prev is not None:
            prev.tail = child.tail
        else:
            parent.text = child.tail
    parent.remove(child)
    if not len(parent) and parent.text is not None and not parent.text.strip():
        parent.text = None


def sub(tag: str, text: Optional[str] = None, attrib: Optional[dict] = None, children: Iterable = ()) -> etree._Element:
    el = etree.Element(tag, attrib or {})
    if text is not None:
        el.text = text
    for c in children:
        el.append(c)
    return el


def binding_element(xml: str) -> etree._Element:
    el = etree.fromstring(xml.strip().encode("utf-8"), _EDIT_PARSER)
    if el.tag != "binding":
        raise EditError("Un binding doit être un élément <binding>.")
    _strip_ws(el)
    _cdata_scripts(el)
    return el


def _strip_ws(el: etree._Element) -> None:
    for e in el.iter():
        if not isinstance(e.tag, str):
            continue
        if e.text is not None and not e.text.strip() and len(e):
            e.text = None
        if e.tail is not None and not e.tail.strip():
            e.tail = None


def _cdata_scripts(el: etree._Element) -> None:
    for s in el.iter("script"):
        txt = s.text or ""
        if any(ch in txt for ch in "<>&") and txt:
            s.text = etree.CDATA(txt)


def ensure_path(root: etree._Element, path: Iterable[str]) -> etree._Element:
    cur = root
    for tag in path:
        found = None
        for c in _elements(cur):
            if c.tag == tag and c.get("n") in (None, "0"):
                found = c
        if found is None:
            found = insert_child(cur, sub(tag))
        cur = found
    return cur


def set_text_child(parent: etree._Element, tag: str, text: str, attrib: Optional[dict] = None,
                   index: Optional[int] = None) -> etree._Element:
    existing = [c for c in _elements(parent) if c.tag == tag]
    if existing:
        el = existing[-1]
        el.text = text
        for k, v in (attrib or {}).items():
            el.set(k, v)
        return el
    return insert_child(parent, sub(tag, text, attrib), index)


def remove_children(parent: etree._Element, tag: str) -> int:
    n = 0
    for c in [c for c in _elements(parent) if c.tag == tag]:
        remove_child(c)
        n += 1
    return n


def prune_empty(el: etree._Element, tags: set[str]) -> None:
    for c in list(_elements(el)):
        if c.tag in tags:
            prune_empty(c, tags)
            if not _elements(c) and not (c.text or "").strip():
                remove_child(c)


def mod_nodes(key_el: etree._Element) -> list[tuple[tuple[str, ...], etree._Element]]:
    """Tous les nœuds (chemin mod-*, élément) sous une touche, racine comprise."""
    out = [((), key_el)]

    def rec(el, path):
        for c in _elements(el):
            if c.tag.startswith("mod-") and c.tag in dict(MOD_TAGS):
                p = path + (c.tag,)
                out.append((p, c))
                rec(c, p)

    rec(key_el, ())
    return out


def get_path(el: etree._Element, path: Iterable[str], create: bool) -> Optional[etree._Element]:
    cur = el
    for tag in path:
        nxt = None
        for c in _elements(cur):
            if c.tag == tag:
                nxt = c
        if nxt is None:
            if not create:
                return None
            nxt = insert_child(cur, sub(tag))
        cur = nxt
    return cur


# ---------------------------------------------------------------------------
# Clavier
# ---------------------------------------------------------------------------

@dataclass
class SlotChange:
    code: int
    mask: int  # sans MOD_RELEASED
    press: list[str] = field(default_factory=list)  # XML des bindings
    release: list[str] = field(default_factory=list)
    desc: Optional[str] = None
    repeatable: Optional[bool] = None
    key_name: Optional[str] = None


@dataclass
class BaseSlotInfo:
    """Bindings déjà présents avant le fichier cible (pour les neutraliser)."""

    indices: dict[tuple[str, ...], list[int]] = field(default_factory=dict)  # chemin -> index de binding
    repeatable: bool = False

    @classmethod
    def from_keyboard(cls, kb, code: int, mask: int) -> "BaseSlotInfo":
        info = cls()
        if kb is None:
            return info
        info.repeatable = kb.repeatable(code)
        slot = kb.slot(code, mask)
        if slot is None:
            return info
        for ref in slot.press + slot.release:
            info.indices.setdefault(ref.path, []).append(ref.node.index)
        return info


def find_key_elements(container: etree._Element, code: int) -> list[etree._Element]:
    return [k for k in _elements(container) if k.tag == "key" and (k.get("n") or "").strip() == str(code)]


def write_key_slot(
    tree: etree._ElementTree,
    container_path: tuple[str, ...],
    change: SlotChange,
    base: Optional[BaseSlotInfo],
) -> None:
    """Remplace les bindings d'un slot de touche dans un fichier clavier.

    ``base`` décrit les bindings hérités (clavier global quand on écrit dans un
    fichier d'avion) : ils sont neutralisés par des bindings ``null`` aux mêmes
    index, et les nouveaux bindings sont écrits à des index libres afin qu'aucun
    paramètre hérité (condition, pas, bornes...) ne se mélange aux nouveaux.
    """
    root = tree.getroot()
    container = ensure_path(root, container_path)
    keys = find_key_elements(container, change.code)
    if keys:
        key_el = keys[-1]
    else:
        key_el = sub("key", attrib={"n": str(change.code)})
        key_el.append(sub("name", change.key_name or str(change.code)))
        insert_child(container, key_el, _key_insert_index(container, change.code))
        key_el = find_key_elements(container, change.code)[-1]

    targets = {change.mask, change.mask | MOD_RELEASED}
    # 1. retirer les bindings existants de ce slot dans ce fichier
    for ke in keys or [key_el]:
        for path, node in mod_nodes(ke):
            if path_mask(path) in targets:
                remove_children(node, "binding")
                if change.desc is not None and path and path_mask(path) == change.mask:
                    remove_children(node, "desc")
        prune_empty(ke, {t for t, _ in MOD_TAGS})

    # 2. neutraliser les bindings hérités
    press_path = mask_path(change.mask)
    release_path = mask_path(change.mask | MOD_RELEASED)
    start = {press_path: 0, release_path: 0}
    if base is not None:
        for path, idxs in base.indices.items():
            if not idxs:
                continue
            node = get_path(key_el, path, create=True)
            for i in sorted(set(idxs)):
                insert_child(node, sub("binding", attrib={"n": str(i)}, children=[sub("command", "null")]),
                             _binding_insert_index(node))
            if path in start:
                start[path] = max(idxs) + 1

    # 3. écrire les nouveaux bindings
    for path, xmls in ((press_path, change.press), (release_path, change.release)):
        if not xmls:
            continue
        node = get_path(key_el, path, create=True)
        for j, xml in enumerate(xmls):
            b = binding_element(xml)
            if start[path]:
                b.set("n", str(start[path] + j))
            insert_child(node, b, _binding_insert_index(node))

    # 4. description
    if change.desc is not None:
        if change.mask == 0:
            if change.desc.strip():
                set_text_child(key_el, "desc", change.desc.strip(), index=_after(key_el, "name"))
        elif change.desc.strip():
            node = get_path(key_el, press_path, create=bool(change.press or change.release))
            if node is not None:
                remove_children(node, "desc")
                insert_child(node, sub("desc", change.desc.strip()), 0)

    # 5. répétition (propriété de la touche entière)
    if change.repeatable is not None:
        reps = [c for c in _elements(key_el) if c.tag == "repeatable"]
        want = "true" if change.repeatable else "false"
        if reps:
            reps[-1].text = want
            reps[-1].set("type", "bool")
        elif change.repeatable or (base is not None and base.repeatable):
            insert_child(key_el, sub("repeatable", want, {"type": "bool"}), _after(key_el, "desc", "name"))

    # 6. nettoyage
    prune_empty(key_el, {t for t, _ in MOD_TAGS})
    if not list(key_el.iter("binding")):
        remove_child(key_el)


def _after(el: etree._Element, *tags: str) -> int:
    kids = _elements(el)
    for tag in tags:
        idx = [i for i, c in enumerate(kids) if c.tag == tag]
        if idx:
            return idx[-1] + 1
    return 0


def _binding_insert_index(node: etree._Element) -> int:
    """Les bindings se placent avant les sous-éléments mod-*."""
    kids = _elements(node)
    for i, c in enumerate(kids):
        if c.tag.startswith("mod-"):
            return i
    return len(kids)


def _key_insert_index(container: etree._Element, code: int) -> Optional[int]:
    kids = _elements(container)
    for i, c in enumerate(kids):
        if c.tag == "key":
            try:
                if int(c.get("n", "0")) > code:
                    return i
            except ValueError:
                continue
    return None


# ---------------------------------------------------------------------------
# Joysticks
# ---------------------------------------------------------------------------

def _platform_index(el: etree._Element, counters: dict[str, int]) -> Optional[int]:
    tag = el.tag
    n = el.get("n")
    if n is not None:
        try:
            idx = int(n)
        except ValueError:
            idx = 0
        counters[tag] = max(counters.get(tag, 0), idx + 1)
    else:
        idx = counters.get(tag, 0)
        counters[tag] = idx + 1
    num = el.find("number")
    if num is not None:
        w = num.find("windows")
        if w is None or not (w.text or "").strip():
            return None
        try:
            return int(float(w.text.strip()))
        except ValueError:
            return None
    return idx


def find_control_elements(root: etree._Element, tag: str, index: int) -> list[etree._Element]:
    counters: dict[str, int] = {}
    out = []
    for c in _elements(root):
        if c.tag != tag:
            if c.tag in ("axis", "button"):
                _platform_index(c, counters)
            continue
        if _platform_index(c, counters) == index:
            out.append(c)
    return out


def get_or_create_control(root: etree._Element, tag: str, index: int) -> etree._Element:
    found = find_control_elements(root, tag, index)
    if found:
        return found[-1]
    el = sub(tag, attrib={"n": str(index)})
    # insertion après le dernier élément du même type
    kids = _elements(root)
    pos = None
    for i, c in enumerate(kids):
        if c.tag == tag:
            pos = i + 1
    if pos is None:
        pos = len(kids)
    insert_child(root, el, pos)
    return find_control_elements(root, tag, index)[-1]


def write_button(root: etree._Element, index: int, desc: Optional[str], press: list[str], release: list[str],
                 repeatable: bool, virtual: Optional[tuple[int, str]] = None) -> None:
    """Remplace les bindings d'un bouton (ou d'un bouton virtuel low/high d'un axe)."""
    if virtual is not None:
        axis = get_or_create_control(root, "axis", virtual[0])
        el = get_path(axis, (virtual[1],), create=True)
    else:
        el = get_or_create_control(root, "button", index)
    remove_children(el, "binding")
    up = get_path(el, ("mod-up",), create=False)
    if up is not None:
        remove_child(up)
    if desc is not None:
        if desc.strip():
            set_text_child(el, "desc", desc.strip(), index=0)
        else:
            remove_children(el, "desc")
    reps = [c for c in _elements(el) if c.tag == "repeatable"]
    if repeatable:
        if reps:
            reps[-1].text = "true"
        else:
            insert_child(el, sub("repeatable", "true", {"type": "bool"}), _after(el, "desc", "number"))
    else:
        for r in reps:
            remove_child(r)
    for xml in press:
        insert_child(el, binding_element(xml), _binding_insert_index(el))
    if release:
        up = insert_child(el, sub("mod-up"))
        for xml in release:
            insert_child(up, binding_element(xml))


def write_axis(root: etree._Element, index: int, desc: Optional[str], bindings: list[str]) -> etree._Element:
    el = get_or_create_control(root, "axis", index)
    remove_children(el, "binding")
    if desc is not None:
        if desc.strip():
            set_text_child(el, "desc", desc.strip(), index=0)
        else:
            remove_children(el, "desc")
    for xml in bindings:
        insert_child(el, binding_element(xml), _binding_insert_index(el))
    return el


def clear_control(root: etree._Element, tag: str, index: int) -> None:
    for el in find_control_elements(root, tag, index):
        remove_child(el)


def set_joystick_names(root: etree._Element, names: list[str]) -> None:
    olds = [c for c in _elements(root) if c.tag == "name"]
    pos = _elements(root).index(olds[0]) if olds else 0
    for o in olds:
        remove_child(o)
    for i, n in enumerate(names):
        insert_child(root, sub("name", n), pos + i)


def sanitize_filename(name: str) -> str:
    s = re.sub(r"[^\w\-. ]+", "_", name, flags=re.UNICODE).strip(" ._")
    return s or "joystick"

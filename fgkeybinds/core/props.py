"""Lecture des fichiers PropertyList de FlightGear.

Reproduit la sémantique de SimGear (props_io.cxx) :

* un élément avec l'attribut ``n`` vise l'enfant d'index ``n`` ;
* un élément sans ``n`` reçoit l'index suivant du compteur propre à son parent
  *dans le fichier en cours de lecture* : un fichier chargé par-dessus un autre
  fusionne donc ses éléments avec ceux de même index ;
* l'attribut ``include`` charge d'abord le fichier référencé dans le nœud, puis
  les enfants de l'élément sont appliqués par-dessus ;
* ``omit-node`` fusionne le contenu dans le parent au lieu de créer un nœud.

Chaque nœud mémorise les fichiers qui y ont contribué (``sources``), ce qui
permet de savoir si un binding vient de la configuration globale ou d'un avion.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterator, Optional

from lxml import etree

_READ_PARSER = etree.XMLParser(
    recover=True,
    remove_comments=True,
    remove_pis=True,
    resolve_entities=False,
    huge_tree=True,
    no_network=True,
)

_seq = itertools.count()


@dataclass(frozen=True)
class Source:
    """Contribution d'un élément XML à un nœud de propriétés."""

    seq: int  # ordre global de lecture (plus grand = appliqué plus tard)
    path: Path
    line: int
    phase: str  # "global", "aircraft", "joystick", ...


class PNode:
    """Nœud de l'arbre de propriétés (équivalent minimal de SGPropertyNode)."""

    __slots__ = ("name", "index", "value", "attrs", "parent", "sources", "_children", "_order")

    def __init__(self, name: str = "", index: int = 0, parent: Optional["PNode"] = None):
        self.name = name
        self.index = index
        self.value: Optional[str] = None
        self.attrs: dict[str, str] = {}
        self.parent = parent
        self.sources: list[Source] = []
        self._children: dict[tuple[str, int], PNode] = {}
        self._order: list[PNode] = []

    # -- navigation -----------------------------------------------------
    def child(self, name: str, index: int = 0, create: bool = False) -> Optional["PNode"]:
        node = self._children.get((name, index))
        if node is None and create:
            node = PNode(name, index, self)
            self._children[(name, index)] = node
            self._order.append(node)
        return node

    def children(self, name: Optional[str] = None) -> list["PNode"]:
        """Enfants dans l'ordre de création (comme ``getChildren``)."""
        if name is None:
            return list(self._order)
        return [c for c in self._order if c.name == name]

    def get(self, path: str, default: Optional[str] = None) -> Optional[str]:
        node = self.node(path)
        if node is None or node.value is None:
            return default
        return node.value

    def text(self, path: str, default: str = "") -> str:
        v = self.get(path)
        return v.strip() if v is not None else default

    def get_bool(self, path: str, default: bool = False) -> bool:
        v = self.get(path)
        if v is None:
            return default
        v = v.strip().lower()
        if v in ("true", "1", "yes", "y"):
            return True
        if v in ("false", "0", "no", "n", ""):
            return False
        try:
            return float(v) != 0.0
        except ValueError:
            return default

    def get_float(self, path: str, default: float = 0.0) -> float:
        v = self.get(path)
        if v is None:
            return default
        try:
            return float(v.strip())
        except ValueError:
            # SimGear interprète "true"/"false" comme 1/0 pour les types numériques
            low = v.strip().lower()
            if low == "true":
                return 1.0
            if low == "false":
                return 0.0
            return default

    def get_int(self, path: str, default: int = 0) -> int:
        return int(self.get_float(path, float(default)))

    def node(self, path: str) -> Optional["PNode"]:
        """Accès par chemin relatif du type ``a/b[2]/c``."""
        cur: Optional[PNode] = self
        for part in [p for p in path.strip("/").split("/") if p]:
            if cur is None:
                return None
            name, idx = _split_index(part)
            cur = cur.child(name, idx)
        return cur

    def walk(self) -> Iterator["PNode"]:
        yield self
        for c in self._order:
            yield from c.walk()

    def remove_child(self, node: "PNode") -> None:
        self._children.pop((node.name, node.index), None)
        if node in self._order:
            self._order.remove(node)

    # -- informations de provenance -------------------------------------
    def latest_source(self) -> Optional[Source]:
        best: Optional[Source] = None
        for n in self.walk():
            for s in n.sources:
                if best is None or s.seq > best.seq:
                    best = s
        return best

    def source_files(self) -> list[Path]:
        seen: dict[Path, None] = {}
        for n in self.walk():
            for s in n.sources:
                seen.setdefault(s.path, None)
        return list(seen)

    def phases(self) -> set[str]:
        return {s.phase for n in self.walk() for s in n.sources}

    # -- conversion -----------------------------------------------------
    def to_element(self, tag: Optional[str] = None) -> etree._Element:
        el = etree.Element(tag or self.name)
        for k, v in self.attrs.items():
            el.set(k, v)
        kids = self.children()
        if kids:
            for c in kids:
                sub = c.to_element()
                el.append(sub)
        elif self.value is not None:
            el.text = self.value
        return el

    def copy(self, parent: Optional["PNode"] = None) -> "PNode":
        n = PNode(self.name, self.index, parent)
        n.value = self.value
        n.attrs = dict(self.attrs)
        n.sources = list(self.sources)
        for c in self._order:
            cc = c.copy(n)
            n._children[(cc.name, cc.index)] = cc
            n._order.append(cc)
        return n

    def __repr__(self) -> str:  # pragma: no cover - aide au débogage
        return f"<PNode {self.name}[{self.index}] value={self.value!r} children={len(self._order)}>"


def _split_index(part: str) -> tuple[str, int]:
    if part.endswith("]") and "[" in part:
        name, idx = part[:-1].split("[", 1)
        try:
            return name, int(idx)
        except ValueError:
            return name, 0
    return part, 0


def element_to_pnode(el: etree._Element, name: Optional[str] = None) -> PNode:
    """Convertit un élément XML autonome (sans include) en PNode."""
    root = PNode(name or el.tag)
    _apply_plain(el, root)
    return root


def _apply_plain(el: etree._Element, node: PNode) -> None:
    counters: dict[str, int] = {}
    has_child = False
    for c in el:
        if not isinstance(c.tag, str):
            continue
        has_child = True
        idx = _next_index(c, counters)
        child = node.child(c.tag, idx, create=True)
        for a, v in c.attrib.items():
            if a not in ("n", "include", "omit-node"):
                child.attrs[a] = v
        _apply_plain(c, child)
    if not has_child:
        node.value = el.text or ""


def _next_index(c: etree._Element, counters: dict[str, int]) -> int:
    name = c.tag
    n = c.get("n")
    if n is not None:
        try:
            idx = int(n.strip())
        except ValueError:
            idx = 0
        counters[name] = max(counters.get(name, 0), idx + 1)
    else:
        idx = counters.get(name, 0)
        counters[name] = idx + 1
    return idx


class IncludeResolver:
    """Résout les chemins ``include`` comme le ResourceManager de SimGear."""

    def __init__(
        self,
        fg_root: Optional[Path],
        aircraft_dir: Optional[Path] = None,
        aircraft_roots: tuple[Path, ...] | list[Path] = (),
    ):
        self.fg_root = fg_root
        self.aircraft_dir = aircraft_dir
        self.aircraft_roots = list(aircraft_roots)

    def resolve(self, inc: str, base_dir: Path) -> Optional[Path]:
        inc = inc.strip().replace("\\", "/")
        if not inc:
            return None
        p = Path(inc)
        if p.is_absolute():
            return p if p.is_file() else None
        cand = base_dir / inc
        if cand.is_file():
            return cand
        parts = [x for x in inc.split("/") if x]
        if len(parts) > 2 and parts[0] == "Aircraft":
            if self.aircraft_dir is not None and parts[1] == self.aircraft_dir.name:
                cand = self.aircraft_dir.joinpath(*parts[2:])
                if cand.is_file():
                    return cand
            for root in self.aircraft_roots:
                cand = root.joinpath(*parts[1:])
                if cand.is_file():
                    return cand
        if self.fg_root is not None:
            cand = self.fg_root / inc
            if cand.is_file():
                return cand
        if self.aircraft_dir is not None:
            cand = self.aircraft_dir / inc
            if cand.is_file():
                return cand
        return None


PathFilter = Callable[[tuple[str, ...]], bool]


class PropertyLoader:
    """Charge des fichiers PropertyList dans un arbre de PNode."""

    _cache: dict[Path, tuple[float, etree._Element]] = {}

    def __init__(
        self,
        resolver: Optional[IncludeResolver] = None,
        phase: str = "global",
        skip: Optional[Callable[[Path, etree._Element, tuple[str, ...]], bool]] = None,
    ):
        self.resolver = resolver
        self.phase = phase
        self.skip = skip  # permet d'ignorer certains éléments (calcul de l'état « hérité »)
        self.errors: list[str] = []
        self.files: list[Path] = []
        self.file_prefixes: list[tuple[Path, tuple[str, ...]]] = []  # chemin où la racine a été appliquée
        self.includes: list[tuple[tuple[str, ...], Path, Path]] = []  # (chemin, fichier parent, fichier inclus)

    # -- lecture de fichiers --------------------------------------------
    @classmethod
    def parse(cls, path: Path) -> Optional[etree._Element]:
        try:
            mtime = path.stat().st_mtime
        except OSError:
            return None
        cached = cls._cache.get(path)
        if cached and cached[0] == mtime:
            return cached[1]
        try:
            tree = etree.parse(str(path), _READ_PARSER)
            root = tree.getroot()
        except (etree.XMLSyntaxError, OSError, ValueError):
            return None
        if root is None:
            return None
        cls._cache[path] = (mtime, root)
        return root

    @classmethod
    def clear_cache(cls) -> None:
        cls._cache.clear()

    def load(
        self,
        path: Path,
        target: Optional[PNode] = None,
        path_filter: Optional[PathFilter] = None,
        prefix: tuple[str, ...] = (),
    ) -> PNode:
        target = target if target is not None else PNode()
        self._read_file(Path(path), target, path_filter, prefix, depth=0)
        return target

    def _read_file(
        self,
        path: Path,
        node: PNode,
        path_filter: Optional[PathFilter],
        prefix: tuple[str, ...],
        depth: int,
    ) -> None:
        if depth > 40:
            self.errors.append(f"Inclusion trop profonde : {path}")
            return
        root = self.parse(path)
        if root is None:
            self.errors.append(f"Fichier illisible : {path}")
            return
        self.files.append(path)
        self.file_prefixes.append((path, prefix))
        self._apply(root, node, path, path_filter, prefix, depth)

    def _apply(
        self,
        el: etree._Element,
        node: PNode,
        path: Path,
        path_filter: Optional[PathFilter],
        prefix: tuple[str, ...],
        depth: int,
    ) -> None:
        inc = el.get("include")
        if inc:
            self._include(inc, node, path, path_filter, prefix, depth)
        counters: dict[str, int] = {}
        has_child = False
        for c in el:
            if not isinstance(c.tag, str):
                continue
            has_child = True
            idx = _next_index(c, counters)
            cpath = prefix + (c.tag,)
            if path_filter is not None and not path_filter(cpath):
                continue
            if self.skip is not None and self.skip(path, c, cpath):
                continue
            omit = (c.get("omit-node") or "").lower() in ("y", "yes", "true", "1")
            if omit:
                self._apply(c, node, path, path_filter, prefix, depth)
                continue
            child = node.child(c.tag, idx, create=True)
            child.sources.append(Source(next(_seq), path, c.sourceline or 0, self.phase))
            for a, v in c.attrib.items():
                if a not in ("n", "include", "omit-node"):
                    child.attrs[a] = v
            self._apply(c, child, path, path_filter, cpath, depth)
        if not has_child and not inc:
            node.value = el.text or ""

    def _include(
        self,
        inc: str,
        node: PNode,
        path: Path,
        path_filter: Optional[PathFilter],
        prefix: tuple[str, ...],
        depth: int,
    ) -> None:
        if self.resolver is not None:
            target = self.resolver.resolve(inc, path.parent)
        else:
            cand = path.parent / inc
            target = cand if cand.is_file() else None
        if target is None:
            self.errors.append(f"Inclusion introuvable « {inc} » dans {path}")
            return
        self.includes.append((prefix, path, target))
        self._read_file(target, node, path_filter, prefix, depth + 1)


def prefix_filter(*allowed: str) -> PathFilter:
    """Filtre ne gardant que les chemins préfixes/descendants des chemins donnés.

    ``prefix_filter("input", "sim/description")`` descend dans ``sim`` mais n'y
    garde que ``description``.
    """
    allowed_t = [tuple(a.strip("/").split("/")) for a in allowed]

    def f(p: tuple[str, ...]) -> bool:
        for a in allowed_t:
            n = min(len(a), len(p))
            if a[:n] == p[:n]:
                return True
        return False

    return f

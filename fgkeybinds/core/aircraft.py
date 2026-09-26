"""Bibliothèque d'aéronefs et chargement de leur configuration clavier."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from lxml import etree

from .keyboard import KeyboardConfig
from .props import IncludeResolver, PNode, PropertyLoader, prefix_filter


@dataclass
class AircraftVariant:
    set_file: Path
    aircraft_dir: Path

    @property
    def id(self) -> str:
        return self.set_file.name[: -len("-set.xml")]

    @property
    def key(self) -> str:
        return str(self.set_file)


@dataclass
class AircraftEntry:
    dir: Path
    root: Path  # dossier de bibliothèque dans lequel il a été trouvé
    variants: list[AircraftVariant] = field(default_factory=list)

    @property
    def name(self) -> str:
        return self.dir.name


def scan_library(roots: list[Path], max_depth: int = 3) -> list[AircraftEntry]:
    """Trouve les dossiers contenant des fichiers ``*-set.xml``."""
    out: list[AircraftEntry] = []
    seen: set[str] = set()

    def visit(d: Path, root: Path, depth: int) -> None:
        try:
            entries = list(os.scandir(d))
        except OSError:
            return
        sets = sorted(Path(e.path) for e in entries if e.is_file() and e.name.endswith("-set.xml"))
        if sets:
            key = str(d.resolve()).lower()
            if key in seen:
                return
            seen.add(key)
            ae = AircraftEntry(d, root)
            ae.variants = [AircraftVariant(s, d) for s in sets]
            out.append(ae)
            return
        if depth >= max_depth:
            return
        for e in entries:
            if e.is_dir() and not e.name.startswith(".") and e.name not in (
                "Models", "Nasal", "Sounds", "Systems", "Instruments", "Instruments-3d", "Generic",
                "ThumbnailCache", "Textures", "Liveries", "gui", "Dialogs", "Engines", "Panels",
            ):
                visit(Path(e.path), root, depth + 1)

    for r in roots:
        visit(r, r, 0)
    out.sort(key=lambda a: a.name.lower())
    return out


_META_FILTER = prefix_filter(
    "sim/description",
    "sim/variant-of",
    "sim/long-description",
    "sim/author",
    "sim/status",
    "sim/flight-model",
    "sim/aircraft-version",
)


@dataclass
class AircraftMeta:
    description: str
    variant_of: str
    author: str
    flight_model: str
    status: str


def read_meta(v: AircraftVariant, fg_root: Optional[Path], roots: list[Path]) -> AircraftMeta:
    loader = PropertyLoader(IncludeResolver(fg_root, v.aircraft_dir, roots), phase="aircraft")
    tree = loader.load(v.set_file, path_filter=_META_FILTER)
    return AircraftMeta(
        description=tree.text("sim/description") or v.id,
        variant_of=tree.text("sim/variant-of"),
        author=" ".join(tree.text("sim/author").split()),
        flight_model=tree.text("sim/flight-model"),
        status=tree.text("sim/status"),
    )


KB_PATH = ("input", "keyboard")


@dataclass
class KeyboardSource:
    """Fichier pouvant recevoir la configuration clavier d'un avion."""

    path: Path
    container: tuple[str, ...]  # chemin de <keyboard> depuis la racine du fichier (() = la racine)
    editable: bool  # situé dans le dossier de l'avion
    exists: bool  # l'élément conteneur existe déjà dans le fichier

    @property
    def dedicated(self) -> bool:
        return self.container == ()


@dataclass
class AircraftInput:
    variant: AircraftVariant
    tree: PNode  # arbre global + avion
    keyboard: KeyboardConfig
    sources: list[KeyboardSource]
    errors: list[str]
    files: list[Path]  # fichiers lus pour la partie avion

    @property
    def primary_keyboard_file(self) -> Optional[KeyboardSource]:
        """Fichier dans lequel écrire les nouvelles touches de l'avion."""
        ed = [s for s in self.sources if s.editable]
        for pred in (lambda s: s.dedicated, lambda s: s.exists, lambda s: s.path == self.variant.set_file):
            c = [s for s in ed if pred(s)]
            if c:
                return c[-1]
        return None

    def source_for_file(self, path: Path) -> Optional[KeyboardSource]:
        for s in self.sources:
            if s.path == path:
                return s
        return None

    def target_for_key(self, code: int) -> Optional[KeyboardSource]:
        """Fichier où modifier la touche ``code`` : celui qui la définit déjà, sinon le principal."""
        kbnode = self.tree.node("input/keyboard")
        key = kbnode.child("key", code) if kbnode is not None else None
        if key is not None:
            for s in sorted(key.sources, key=lambda s: -s.seq):
                if s.phase == "aircraft":
                    src = self.source_for_file(s.path)
                    if src is not None and src.editable:
                        return src
        return self.primary_keyboard_file


def _within(path: Path, folder: Path) -> bool:
    try:
        path.resolve().relative_to(folder.resolve())
        return True
    except ValueError:
        return False


def load_global_tree(fg_root: Path) -> tuple[PNode, list[str]]:
    root = PNode()
    kb = root.child("input", 0, True).child("keyboard", 0, True)
    loader = PropertyLoader(IncludeResolver(fg_root), phase="global")
    loader.load(fg_root / "keyboard.xml", kb, prefix=("input", "keyboard"))
    return root, loader.errors


def load_global_keyboard(fg_root: Path) -> KeyboardConfig:
    tree, _ = load_global_tree(fg_root)
    return KeyboardConfig(tree.node("input/keyboard"))


def load_aircraft_input(v: AircraftVariant, fg_root: Path, roots: list[Path], skip=None) -> AircraftInput:
    tree, errors = load_global_tree(fg_root)
    loader = PropertyLoader(IncludeResolver(fg_root, v.aircraft_dir, roots), phase="aircraft", skip=skip)
    loader.load(v.set_file, tree, path_filter=prefix_filter("input"))
    kbnode = tree.node("input/keyboard")
    kb = KeyboardConfig(kbnode)
    base_tree, _ = load_global_tree(fg_root)
    kb.fix_descriptions(KeyboardConfig(base_tree.node("input/keyboard")))

    sources: list[KeyboardSource] = []
    seen: set[Path] = set()
    for f, prefix in loader.file_prefixes:
        if f in seen or KB_PATH[: len(prefix)] != prefix:
            continue
        container = KB_PATH[len(prefix):]
        exists = _has_container(f, container)
        if not exists and f != v.set_file:
            continue
        seen.add(f)
        sources.append(KeyboardSource(f, container, _within(f, v.aircraft_dir), exists))
    return AircraftInput(v, tree, kb, sources, errors + loader.errors, loader.files)


def _has_container(path: Path, container: tuple[str, ...]) -> bool:
    if not container:
        return True
    root = PropertyLoader.parse(path)
    if root is None:
        return False
    return root.find("/".join(container)) is not None


def set_files_including(target: Path, entry: AircraftEntry, fg_root: Optional[Path], roots: list[Path]) -> list[Path]:
    """Variantes d'un avion dont la configuration lit le fichier ``target``."""
    out = []
    for v in entry.variants:
        loader = PropertyLoader(IncludeResolver(fg_root, v.aircraft_dir, roots), phase="aircraft")
        loader.load(v.set_file, path_filter=prefix_filter("input"))
        if any(f.resolve() == target.resolve() for f in loader.files):
            out.append(v.set_file)
    return out


def xml_is_parsable(path: Path) -> bool:
    try:
        etree.parse(str(path))
        return True
    except (etree.XMLSyntaxError, OSError):
        return False

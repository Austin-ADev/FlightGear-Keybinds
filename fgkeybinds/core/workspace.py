"""Point d'entrée métier : état chargé et opérations d'écriture."""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional

from lxml import etree

from . import aircraft as ac
from . import curves, fgpaths, joystick, layouts, xmledit
from .bindings import MOD_RELEASED, MOD_TAGS, bindings_equal, path_mask
from .catalog import Catalog
from .keyboard import KeyboardConfig, Slot, combo_label
from .profiles import SlotEntry, slot_entry
from .props import IncludeResolver, PropertyLoader
from .settings import Settings, app_dir, journal_path, user_actions_path, user_layouts_dir


@dataclass(frozen=True)
class Context:
    kind: str  # "global" | "aircraft"
    set_file: Optional[Path] = None

    @property
    def key(self) -> str:
        return "" if self.kind == "global" else str(self.set_file)

    @property
    def is_global(self) -> bool:
        return self.kind == "global"


GLOBAL = Context("global")


@dataclass
class ActiveJoystick:
    device: Optional[joystick.Device]
    config: Optional[joystick.JoystickConfig]
    mode: str  # exact | approx | default | none | library

    @property
    def name(self) -> str:
        if self.device is not None:
            return self.device.name
        return self.config.title if self.config else "?"


class Workspace:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.catalog = Catalog.load(user_actions_path())
        self.layouts = layouts.builtin_layouts() + layouts.load_user_layouts(user_layouts_dir())
        self.paths = fgpaths.FGPaths(None, fgpaths.default_fg_home())
        self.global_kb = KeyboardConfig()
        self.library: list[ac.AircraftEntry] = []
        self.joy_lib = joystick.JoystickLibrary([], {}, None)
        self.devices: list[joystick.Device] = []
        self._ai_cache: dict[str, ac.AircraftInput] = {}
        self._meta_cache: dict[str, ac.AircraftMeta] = {}
        self.load_errors: list[str] = []
        self.reload()

    # ------------------------------------------------------------------
    # Chargement
    # ------------------------------------------------------------------
    def reload(self) -> None:
        PropertyLoader.clear_cache()
        s = self.settings
        self.paths = fgpaths.detect(s.fg_root or None, s.fg_home or None, s.extra_aircraft_dirs)
        self._ai_cache.clear()
        self.load_errors = []
        if self.paths.fg_root is not None:
            tree, errs = ac.load_global_tree(self.paths.fg_root)
            self.global_kb = KeyboardConfig(tree.node("input/keyboard"))
            self.load_errors += errs
        else:
            self.global_kb = KeyboardConfig()
        self.library = ac.scan_library(self.paths.aircraft_dirs)
        self.reload_joysticks()

    def reload_joysticks(self) -> None:
        self.joy_lib = joystick.load_library(self.paths.fg_root, self.paths.fg_home)
        self.devices = joystick.list_devices()

    def refresh_global(self) -> None:
        PropertyLoader.clear_cache()
        if self.paths.fg_root is not None:
            tree, _ = ac.load_global_tree(self.paths.fg_root)
            self.global_kb = KeyboardConfig(tree.node("input/keyboard"))
        self._ai_cache.clear()

    @property
    def ok(self) -> bool:
        return self.paths.fg_root is not None

    @property
    def aircraft_roots(self) -> list[Path]:
        return self.paths.aircraft_dirs

    # ------------------------------------------------------------------
    # Aéronefs
    # ------------------------------------------------------------------
    def variants(self) -> list[ac.AircraftVariant]:
        return [v for e in self.library for v in e.variants]

    def variant(self, set_file: Path | str) -> Optional[ac.AircraftVariant]:
        p = str(set_file)
        for v in self.variants():
            if str(v.set_file) == p:
                return v
        return None

    def entry_of(self, v: ac.AircraftVariant) -> Optional[ac.AircraftEntry]:
        for e in self.library:
            if v in e.variants:
                return e
        return None

    def meta(self, v: ac.AircraftVariant) -> ac.AircraftMeta:
        m = self._meta_cache.get(v.key)
        if m is None:
            try:
                m = ac.read_meta(v, self.paths.fg_root, self.aircraft_roots)
            except Exception:  # fichier corrompu : on affiche au moins l'identifiant
                m = ac.AircraftMeta(v.id, "", "", "", "")
            self._meta_cache[v.key] = m
        return m

    def cached_meta(self, v: ac.AircraftVariant) -> Optional[ac.AircraftMeta]:
        return self._meta_cache.get(v.key)

    def variant_label(self, v: ac.AircraftVariant) -> str:
        m = self._meta_cache.get(v.key)
        return f"{v.id} — {m.description}" if m and m.description and m.description != v.id else v.id

    def aircraft_input(self, v: ac.AircraftVariant) -> ac.AircraftInput:
        ai = self._ai_cache.get(v.key)
        if ai is None:
            ai = ac.load_aircraft_input(v, self.paths.fg_root, self.aircraft_roots)
            self._ai_cache[v.key] = ai
        return ai

    def keyboard(self, ctx: Context) -> KeyboardConfig:
        if ctx.is_global or ctx.set_file is None:
            return self.global_kb
        v = self.variant(ctx.set_file)
        if v is None:
            return self.global_kb
        return self.aircraft_input(v).keyboard

    def context_label(self, ctx: Context) -> str:
        if ctx.is_global:
            return "FlightGear (global)"
        v = self.variant(ctx.set_file) if ctx.set_file else None
        if v is None:
            return str(ctx.set_file)
        return f"{self.meta(v).description} ({v.id})"

    def aircraft_specific_slots(self, v: ac.AircraftVariant) -> list[tuple[Slot, Optional[Slot], str]]:
        """Slots propres à l'avion : (slot avion, slot global, statut)."""
        ai = self.aircraft_input(v)
        out = []
        for s in ai.keyboard.slots():
            if s.origin in ("global", "none"):
                continue
            g = self.global_kb.slot(s.code, s.mask)
            if s.origin == "disabled":
                status = "désactivé"
            elif g is None or not g.is_bound:
                status = "ajout"
            elif bindings_equal([b.node for b in s.press], [b.node for b in g.press]) and bindings_equal(
                    [b.node for b in s.release], [b.node for b in g.release]):
                status = "identique"
            else:
                status = "remplace"
            out.append((s, g, status))
        return out

    # ------------------------------------------------------------------
    # Écriture clavier
    # ------------------------------------------------------------------
    def target_description(self, ctx: Context, code: int) -> str:
        if ctx.is_global:
            return str(self.paths.fg_root / "keyboard.xml") if self.paths.fg_root else "?"
        v = self.variant(ctx.set_file)
        if v is None:
            return "?"
        src = self.aircraft_input(v).target_for_key(code)
        return str(src.path) if src else "(aucun fichier modifiable)"

    def write_slot(self, ctx: Context, change: xmledit.SlotChange) -> Path:
        if self.paths.fg_root is None:
            raise xmledit.EditError("Dossier de données de FlightGear (FG_ROOT) introuvable.")
        if not change.key_name:
            change.key_name = combo_label(change.code, 0)
        if ctx.is_global:
            target = self.paths.fg_root / "keyboard.xml"
            tree = xmledit.load_for_edit(target)
            xmledit.write_key_slot(tree, (), change, None)
            self._save(tree, target)
            self._journal_record(change)
            self.refresh_global()
            return target
        v = self.variant(ctx.set_file)
        if v is None:
            raise xmledit.EditError("Aéronef introuvable.")
        ai = self.aircraft_input(v)
        src = ai.target_for_key(change.code)
        if src is None:
            raise xmledit.EditError(
                "Aucun fichier de cet aéronef ne peut recevoir la configuration clavier "
                "(le dossier de l'avion est peut-être en lecture seule).")
        code_s = str(change.code)

        def skip(path: Path, el: etree._Element, cpath: tuple[str, ...]) -> bool:
            return (path == src.path and cpath == ("input", "keyboard", "key")
                    and (el.get("n") or "").strip() == code_s)

        base_ai = ac.load_aircraft_input(v, self.paths.fg_root, self.aircraft_roots, skip=skip)
        base = xmledit.BaseSlotInfo.from_keyboard(base_ai.keyboard, change.code, change.mask)
        tree = xmledit.load_for_edit(src.path)
        xmledit.write_key_slot(tree, src.container, change, base)
        self._save(tree, src.path)
        PropertyLoader.clear_cache()
        self._ai_cache.clear()
        return src.path

    def clear_slot(self, ctx: Context, code: int, mask: int) -> Path:
        return self.write_slot(ctx, xmledit.SlotChange(code=code, mask=mask, press=[], release=[]))

    def restore_slot_to_global(self, ctx: Context, code: int, mask: int) -> Path:
        """Pour un avion : retire la surcharge (le binding global reprend effet)."""
        if ctx.is_global:
            raise xmledit.EditError("Déjà dans le contexte global.")
        v = self.variant(ctx.set_file)
        ai = self.aircraft_input(v)
        written = None
        for src in ai.sources:
            if not src.editable:
                continue
            tree = xmledit.load_for_edit(src.path)
            root = tree.getroot()
            cont = root
            for tag in src.container:
                cont = cont.find(tag) if cont is not None else None
            if cont is None:
                continue
            changed = False
            for ke in xmledit.find_key_elements(cont, code):
                for path, node in xmledit.mod_nodes(ke):
                    if path_mask(path) in (mask, mask | MOD_RELEASED):
                        if xmledit.remove_children(node, "binding"):
                            changed = True
                xmledit.prune_empty(ke, {t for t, _ in MOD_TAGS})
                if not list(ke.iter("binding")):
                    xmledit.remove_child(ke)
            if changed:
                self._save(tree, src.path)
                written = src.path
        PropertyLoader.clear_cache()
        self._ai_cache.clear()
        if written is None:
            raise xmledit.EditError("Cette combinaison n'est pas surchargée par un fichier modifiable de l'avion.")
        return written

    def apply_entries(self, ctx: Context, entries: Iterable[SlotEntry]) -> list[Path]:
        written: list[Path] = []
        for e in entries:
            p = self.write_slot(ctx, xmledit.SlotChange(
                code=e.code, mask=e.mask, press=list(e.press), release=list(e.release), desc=e.desc,
                repeatable=e.repeatable))
            if p not in written:
                written.append(p)
        return written

    def entries_for(self, ctx: Context, only_specific: bool) -> list[SlotEntry]:
        kb = self.keyboard(ctx)
        if only_specific and not ctx.is_global:
            v = self.variant(ctx.set_file)
            return [slot_entry(s, kb) for s, _, st in self.aircraft_specific_slots(v) if st != "identique"]
        return [slot_entry(s, kb) for s in kb.slots() if s.is_bound]

    # ------------------------------------------------------------------
    # Journal des modifications globales
    # ------------------------------------------------------------------
    def _journal(self) -> dict[str, dict]:
        try:
            return json.loads(journal_path().read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def _journal_record(self, ch: xmledit.SlotChange) -> None:
        j = self._journal()
        j[f"{ch.code}:{ch.mask}"] = SlotEntry(
            code=ch.code, mask=ch.mask, press=list(ch.press), release=list(ch.release), desc=ch.desc,
            repeatable=bool(ch.repeatable), label=combo_label(ch.code, ch.mask)).to_json()
        try:
            journal_path().write_text(json.dumps(j, ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError:
            pass

    def journal_entries(self) -> list[SlotEntry]:
        return [SlotEntry.from_json(v) for v in self._journal().values()]

    def journal_mismatches(self) -> list[SlotEntry]:
        """Modifications globales enregistrées qui ne sont plus présentes (mise à jour de FG ?)."""
        out = []
        for e in self.journal_entries():
            s = self.global_kb.slot(e.code, e.mask)
            cur_p = [b.node for b in s.press] if s else []
            cur_r = [b.node for b in s.release] if s else []
            if not (bindings_equal(cur_p, e.press_nodes()) and bindings_equal(cur_r, e.release_nodes())):
                out.append(e)
        return out

    def clear_journal(self) -> None:
        try:
            journal_path().unlink()
        except OSError:
            pass

    # ------------------------------------------------------------------
    # Sauvegardes
    # ------------------------------------------------------------------
    def _registry_path(self) -> Path:
        return app_dir() / "modified-files.json"

    def modified_files(self) -> list[Path]:
        try:
            data = json.loads(self._registry_path().read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []
        return [Path(p) for p in data if Path(p).exists() or xmledit.backup_path(Path(p)).exists()]

    def _save(self, tree: etree._ElementTree, path: Path, backup: bool = True) -> None:
        xmledit.save(tree, path, backup=backup)
        files = [str(p) for p in self.modified_files()]
        if str(path) not in files:
            files.append(str(path))
        try:
            self._registry_path().write_text(json.dumps(files, ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError:
            pass

    def restore_file(self, path: Path) -> bool:
        b = xmledit.backup_path(path)
        if b.exists():
            shutil.copy2(b, path)
            if self.paths.fg_root and path == self.paths.fg_root / "keyboard.xml":
                self.clear_journal()
            ok = True
        elif path.exists():
            # fichier créé par FGKeybinds (copie de joystick) : suppression
            path.unlink()
            ok = True
        else:
            ok = False
        PropertyLoader.clear_cache()
        self._ai_cache.clear()
        return ok

    # ------------------------------------------------------------------
    # Joysticks
    # ------------------------------------------------------------------
    def active_joysticks(self) -> list[ActiveJoystick]:
        out = []
        for d in self.devices:
            cfg, mode = self.joy_lib.match(d.name)
            out.append(ActiveJoystick(d, cfg, mode if cfg else "none"))
        return out

    def joystick_configs_for_bindings(self) -> list[joystick.JoystickConfig]:
        """Configurations réellement utilisées (périphériques branchés)."""
        cfgs = []
        for aj in self.active_joysticks():
            if aj.config is not None and aj.mode in ("exact", "default") and aj.config not in cfgs:
                cfgs.append(aj.config)
        return cfgs

    def user_joystick_dir(self) -> Path:
        return self.paths.fg_home / "Input" / "Joysticks" / "FGKeybinds"

    def joystick_user_copy(self, cfg: joystick.JoystickConfig, names: Optional[list[str]] = None) -> Path:
        """Copie une configuration dans $FG_HOME (prioritaire sur FG_ROOT) si nécessaire."""
        if cfg.origin == "home" and names is None:
            return cfg.path
        dest_dir = self.user_joystick_dir()
        dest_dir.mkdir(parents=True, exist_ok=True)
        title = names[0] if names else cfg.title
        dest = dest_dir / (xmledit.sanitize_filename(title) + ".xml")
        n = 2
        while dest.exists() and dest != cfg.path:
            dest = dest_dir / (xmledit.sanitize_filename(title) + f"-{n}.xml")
            n += 1
        tree = xmledit.load_for_edit(cfg.path)
        root = tree.getroot()
        resolver = IncludeResolver(self.paths.fg_root)
        for el in root.iter():
            if not isinstance(el.tag, str):
                continue
            inc = el.get("include")
            if inc:
                target = resolver.resolve(inc, cfg.path.parent)
                if target is not None and self.paths.fg_root is not None:
                    try:
                        el.set("include", target.resolve().relative_to(self.paths.fg_root.resolve()).as_posix())
                    except ValueError:
                        el.set("include", str(target))
        if names is not None:
            xmledit.set_joystick_names(root, names)
        root.addprevious(xmledit.safe_comment(
            f" Copie créée par FGKeybinds depuis {cfg.path} — elle est prioritaire sur l'original. "))
        self._save(tree, dest, backup=False)
        self.reload_joysticks()
        return dest

    def joystick_for_device(self, device_name: str) -> Path:
        """Fichier modifiable pour un périphérique (création si besoin)."""
        cfg, mode = self.joy_lib.match(device_name)
        if cfg is not None and mode == "exact":
            return self.joystick_user_copy(cfg)
        if cfg is not None and mode == "approx":
            names = list(dict.fromkeys(cfg.names + [device_name]))
            return self.joystick_user_copy(cfg, names=names)
        base = self.joy_lib.default
        if base is not None:
            return self.joystick_user_copy(base, names=[device_name])
        dest = self.user_joystick_dir() / (xmledit.sanitize_filename(device_name) + ".xml")
        tree = xmledit.new_document(comment=" Configuration créée par FGKeybinds ")
        xmledit.insert_child(tree.getroot(), xmledit.sub("name", device_name))
        self._save(tree, dest, backup=False)
        self.reload_joysticks()
        return dest

    def editable_joystick_path(self, cfg: joystick.JoystickConfig, device_name: Optional[str]) -> Path:
        if device_name:
            return self.joystick_for_device(device_name)
        return self.joystick_user_copy(cfg)

    def write_joystick_button(self, path: Path, index: int, desc: Optional[str], press: list[str],
                              release: list[str], repeatable: bool,
                              virtual: Optional[tuple[int, str]] = None) -> None:
        tree = xmledit.load_for_edit(path)
        xmledit.write_button(tree.getroot(), index, desc, press, release, repeatable, virtual)
        self._save(tree, path)
        self.reload_joysticks()

    def clear_joystick_control(self, path: Path, tag: str, index: int) -> None:
        tree = xmledit.load_for_edit(path)
        xmledit.clear_control(tree.getroot(), tag, index)
        self._save(tree, path)
        self.reload_joysticks()

    def write_joystick_axis(self, path: Path, index: int, desc: Optional[str], bindings: list[str],
                            dead_band: Optional[float] = None) -> None:
        tree = xmledit.load_for_edit(path)
        el = xmledit.write_axis(tree.getroot(), index, desc, bindings)
        if dead_band is not None:
            c = curves.read_curve(el)
            curves.apply_curve(el, dead_band, c.expo, c.invert)
        self._save(tree, path)
        self.reload_joysticks()

    def read_axis_curve(self, path: Path, index: int) -> curves.AxisCurve:
        tree = xmledit.load_for_edit(path)
        els = xmledit.find_control_elements(tree.getroot(), "axis", index)
        if not els:
            return curves.AxisCurve()
        return curves.read_curve(els[-1])

    def write_axis_curve(self, path: Path, index: int, dead_band: float, expo: float, invert: bool) -> None:
        tree = xmledit.load_for_edit(path)
        els = xmledit.find_control_elements(tree.getroot(), "axis", index)
        if not els:
            raise xmledit.EditError(f"L'axe {index} n'est pas défini dans {path}.")
        curves.apply_curve(els[-1], dead_band, expo, invert)
        self._save(tree, path)
        self.reload_joysticks()

    def config_by_path(self, path: Path) -> Optional[joystick.JoystickConfig]:
        for c in self.joy_lib.configs:
            if c.path == path:
                return c
        return None

    # ------------------------------------------------------------------
    # Actions non assignées
    # ------------------------------------------------------------------
    def bound_action_ids(self, ctx: Context, include_joysticks: bool = True) -> set[str]:
        kb = self.keyboard(ctx)
        lists = []
        for s in kb.slots():
            lists.append([b.node for b in s.press])
            lists.append([b.node for b in s.release])
        if include_joysticks:
            for cfg in self.joystick_configs_for_bindings():
                for a in cfg.axes.values():
                    if a.index >= joystick.MAX_AXES:
                        continue
                    lists.append(a.bindings)
                    for vb in (a.low, a.high):
                        if vb is not None:
                            lists.append(vb.press)
                for b in cfg.buttons.values():
                    if b.index >= joystick.MAX_BUTTONS:
                        continue
                    lists.append(b.press)
                    lists.append(b.release)
        return self.catalog.bound_ids(lists)

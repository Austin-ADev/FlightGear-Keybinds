"""Configurations de joysticks FlightGear et détection des périphériques Windows.

FlightGear (sous Windows) lit les joysticks via l'API ``winmm`` (bibliothèque
PLIB) : jusqu'à 16 périphériques, 8 axes (X, Y, Z, R, U, V, puis le chapeau
chinois en axes 6/7) et 32 boutons.  Le nom du périphérique est lu dans le
registre (``OEMName``) ; FlightGear cherche ensuite un fichier XML dont une
balise ``<name>`` correspond exactement, d'abord dans ``$FG_HOME/Input/Joysticks``
puis dans ``$FG_ROOT/Input/Joysticks``, et à défaut utilise la configuration
``default``.
"""

from __future__ import annotations

import ctypes
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from .bindings import MOD_RELEASED, MOD_TAGS, describe_bindings, is_null
from .props import IncludeResolver, PNode, PropertyLoader

PLATFORM = "windows"
AXIS_NAMES_WIN = ["X", "Y", "Z", "R (Rz)", "U", "V", "Chapeau X", "Chapeau Y"]
MAX_AXES = 8
MAX_BUTTONS = 32


# ---------------------------------------------------------------------------
# Modèle
# ---------------------------------------------------------------------------

@dataclass
class ButtonDef:
    index: int
    desc: str
    repeatable: bool
    press: list[PNode] = field(default_factory=list)
    release: list[PNode] = field(default_factory=list)
    modded: dict[int, list[PNode]] = field(default_factory=dict)  # masque -> bindings
    node: Optional[PNode] = None

    @property
    def is_bound(self) -> bool:
        return any(not is_null(b) for b in self.press + self.release) or any(
            not is_null(b) for bl in self.modded.values() for b in bl)

    def description(self) -> str:
        return describe_bindings(self.press, self.desc) or (
            ("Au relâchement : " + describe_bindings(self.release)) if self.release else "")


@dataclass
class AxisDef:
    index: int
    desc: str
    dead_band: float
    tolerance: float
    bindings: list[PNode] = field(default_factory=list)
    low: Optional[ButtonDef] = None
    high: Optional[ButtonDef] = None
    low_threshold: float = -0.9
    high_threshold: float = 0.9
    node: Optional[PNode] = None

    @property
    def is_bound(self) -> bool:
        return any(not is_null(b) for b in self.bindings) or bool(
            (self.low and self.low.is_bound) or (self.high and self.high.is_bound))

    @property
    def is_virtual_buttons(self) -> bool:
        return not any(not is_null(b) for b in self.bindings) and bool(self.low or self.high)

    def description(self) -> str:
        if self.bindings and any(not is_null(b) for b in self.bindings):
            return describe_bindings(self.bindings, self.desc)
        if self.desc and self.is_virtual_buttons:
            return self.desc + "  (boutons virtuels − / +)"
        parts = []
        if self.low and self.low.is_bound:
            parts.append("− : " + self.low.description())
        if self.high and self.high.is_bound:
            parts.append("+ : " + self.high.description())
        if parts:
            return (self.desc + " — " if self.desc else "") + " | ".join(parts)
        return self.desc


@dataclass
class JoystickConfig:
    path: Path
    names: list[str]
    origin: str  # "home" (dossier utilisateur) | "root" (FG_ROOT) | "new"
    axes: dict[int, AxisDef] = field(default_factory=dict)
    buttons: dict[int, ButtonDef] = field(default_factory=dict)
    tree: Optional[PNode] = None
    errors: list[str] = field(default_factory=list)

    @property
    def title(self) -> str:
        for n in self.names:
            if n.strip() and n.strip().lower() != "default":
                return n.strip()
        if self.is_default:
            return f"Configuration par défaut ({self.path.stem})"
        return self.path.stem

    @property
    def is_default(self) -> bool:
        return any(n.strip().lower() == "default" for n in self.names)


def _read_button(node: PNode, index: int) -> ButtonDef:
    bd = ButtonDef(index=index, desc=node.text("desc"), repeatable=node.get_bool("repeatable"), node=node)

    def rec(n: PNode, mask: int) -> None:
        bl = n.children("binding")
        if mask == 0:
            bd.press.extend(bl)
        elif mask == MOD_RELEASED:
            bd.release.extend(bl)
        elif bl:
            bd.modded.setdefault(mask, []).extend(bl)
        for tag, bit in MOD_TAGS:
            c = n.child(tag)
            if c is not None:
                rec(c, mask | bit)

    rec(node, 0)
    return bd


def _platform_index(node: PNode) -> Optional[int]:
    num = node.child("number")
    if num is None:
        return node.index
    v = num.child(PLATFORM)
    if v is None or v.value is None or not v.value.strip():
        return None  # axe ignoré sur cette plateforme
    try:
        return int(float(v.value.strip()))
    except ValueError:
        return None


def parse_config(path: Path, fg_root: Optional[Path], origin: str) -> JoystickConfig:
    loader = PropertyLoader(IncludeResolver(fg_root), phase="joystick")
    tree = loader.load(path)
    cfg = JoystickConfig(path=path, names=[(n.value or "").strip() for n in tree.children("name")],
                         origin=origin, tree=tree, errors=loader.errors)
    for a in tree.children("axis"):
        idx = _platform_index(a)
        if idx is None:
            continue
        ad = AxisDef(
            index=idx,
            desc=a.text("desc"),
            dead_band=a.get_float("dead-band", 0.0),
            tolerance=a.get_float("tolerance", 0.002),
            bindings=a.children("binding"),
            low_threshold=a.get_float("low-threshold", -0.9),
            high_threshold=a.get_float("high-threshold", 0.9),
            node=a,
        )
        low = a.child("low")
        high = a.child("high")
        if low is not None:
            ad.low = _read_button(low, idx)
        if high is not None:
            ad.high = _read_button(high, idx)
        cfg.axes[idx] = ad
    for b in tree.children("button"):
        idx = _platform_index(b)
        if idx is None:
            continue
        cfg.buttons[idx] = _read_button(b, idx)
    return cfg


# ---------------------------------------------------------------------------
# Bibliothèque de configurations
# ---------------------------------------------------------------------------

@dataclass
class JoystickLibrary:
    configs: list[JoystickConfig]
    by_name: dict[str, JoystickConfig]  # premier trouvé gagne (FG_HOME avant FG_ROOT)
    default: Optional[JoystickConfig]

    def match(self, name: str) -> tuple[Optional[JoystickConfig], str]:
        """Configuration utilisée par FlightGear pour un nom de périphérique.

        Retourne (config, mode) avec mode = "exact", "approx" (correspondance
        insensible à la casse/aux espaces, que FlightGear n'appliquera PAS) ou
        "default".
        """
        if name in self.by_name:
            return self.by_name[name], "exact"
        low = " ".join(name.split()).lower()
        for n, c in self.by_name.items():
            if " ".join(n.split()).lower() == low:
                return c, "approx"
        return self.default, "default"


def _quick_names(path: Path) -> list[str]:
    root = PropertyLoader.parse(path)
    if root is None:
        return []
    return [(e.text or "").strip() for e in root.findall("name")]


def load_library(fg_root: Optional[Path], fg_home: Optional[Path]) -> JoystickLibrary:
    configs: list[JoystickConfig] = []
    by_name: dict[str, JoystickConfig] = {}
    dirs: list[tuple[Path, str]] = []
    if fg_home is not None:
        dirs.append((fg_home / "Input" / "Joysticks", "home"))
    if fg_root is not None:
        dirs.append((fg_root / "Input" / "Joysticks", "root"))
    for d, origin in dirs:
        if not d.is_dir():
            continue
        for f in sorted(d.rglob("*.xml")):
            if f.name == "template.xml":
                continue
            names = _quick_names(f)
            if not names:
                continue
            cfg = _LazyConfig(f, names, origin, fg_root)
            configs.append(cfg)  # type: ignore[arg-type]
            for n in names:
                by_name.setdefault(n, cfg)  # type: ignore[arg-type]
    default = by_name.get("default")
    return JoystickLibrary(configs, by_name, default)  # type: ignore[arg-type]


class _LazyConfig(JoystickConfig):
    """Configuration dont les axes/boutons ne sont lus qu'au premier accès."""

    def __init__(self, path: Path, names: list[str], origin: str, fg_root: Optional[Path]):
        object.__setattr__(self, "_fg_root", fg_root)
        object.__setattr__(self, "_loaded", False)
        super().__init__(path=path, names=names, origin=origin)

    def _ensure(self) -> None:
        if object.__getattribute__(self, "_loaded"):
            return
        object.__setattr__(self, "_loaded", True)
        full = parse_config(self.path, object.__getattribute__(self, "_fg_root"), self.origin)
        object.__setattr__(self, "axes", full.axes)
        object.__setattr__(self, "buttons", full.buttons)
        object.__setattr__(self, "tree", full.tree)
        object.__setattr__(self, "errors", full.errors)

    def __getattribute__(self, item):
        if item in ("axes", "buttons", "tree", "errors"):
            object.__getattribute__(self, "_ensure")()
        return object.__getattribute__(self, item)


# ---------------------------------------------------------------------------
# Détection des périphériques (winmm)
# ---------------------------------------------------------------------------

class JOYCAPSW(ctypes.Structure):
    _fields_ = [
        ("wMid", ctypes.c_ushort), ("wPid", ctypes.c_ushort), ("szPname", ctypes.c_wchar * 32),
        ("wXmin", ctypes.c_uint), ("wXmax", ctypes.c_uint), ("wYmin", ctypes.c_uint), ("wYmax", ctypes.c_uint),
        ("wZmin", ctypes.c_uint), ("wZmax", ctypes.c_uint), ("wNumButtons", ctypes.c_uint),
        ("wPeriodMin", ctypes.c_uint), ("wPeriodMax", ctypes.c_uint), ("wRmin", ctypes.c_uint),
        ("wRmax", ctypes.c_uint), ("wUmin", ctypes.c_uint), ("wUmax", ctypes.c_uint), ("wVmin", ctypes.c_uint),
        ("wVmax", ctypes.c_uint), ("wCaps", ctypes.c_uint), ("wMaxAxes", ctypes.c_uint),
        ("wNumAxes", ctypes.c_uint), ("wMaxButtons", ctypes.c_uint), ("szRegKey", ctypes.c_wchar * 32),
        ("szOEMVxD", ctypes.c_wchar * 260),
    ]


class JOYINFOEX(ctypes.Structure):
    _fields_ = [
        ("dwSize", ctypes.c_uint32), ("dwFlags", ctypes.c_uint32), ("dwXpos", ctypes.c_uint32),
        ("dwYpos", ctypes.c_uint32), ("dwZpos", ctypes.c_uint32), ("dwRpos", ctypes.c_uint32),
        ("dwUpos", ctypes.c_uint32), ("dwVpos", ctypes.c_uint32), ("dwButtons", ctypes.c_uint32),
        ("dwButtonNumber", ctypes.c_uint32), ("dwPOV", ctypes.c_uint32), ("dwReserved1", ctypes.c_uint32),
        ("dwReserved2", ctypes.c_uint32),
    ]


JOY_RETURNALL = 0xFF
JOYCAPS_HASPOV = 0x10
JOY_POVCENTERED = 0xFFFF


@dataclass
class DeviceState:
    axes: list[float]
    buttons: int  # masque de bits

    def pressed(self, i: int) -> bool:
        return bool(self.buttons & (1 << i))


@dataclass
class Device:
    id: int  # identifiant winmm (= numéro js[n] dans FlightGear)
    name: str  # nom vu par FlightGear
    product: str  # nom du pilote (szPname)
    vid: int
    pid: int
    num_axes: int
    num_buttons: int
    has_pov: bool
    ranges: list[tuple[int, int]] = field(default_factory=list)

    def poll(self) -> Optional[DeviceState]:
        return poll_device(self)


def _winmm():
    if sys.platform != "win32":
        return None
    try:
        return ctypes.windll.winmm
    except OSError:
        return None


def _oem_name(joy_id: int, reg_key: str) -> Optional[str]:
    """Nom OEM lu dans le registre, comme le fait PLIB (getOEMProductName)."""
    try:
        import winreg
    except ImportError:
        return None
    cfg_path = rf"System\CurrentControlSet\Control\MediaResources\Joystick\{reg_key}\CurrentJoystickSettings"
    oem_key = None
    for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
        try:
            with winreg.OpenKey(hive, cfg_path) as k:
                oem_key, _ = winreg.QueryValueEx(k, f"Joystick{joy_id + 1}OEMName")
                break
        except OSError:
            continue
    if not oem_key:
        return None
    oem_path = rf"System\CurrentControlSet\Control\MediaProperties\PrivateProperties\Joystick\OEM\{oem_key}"
    for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
        try:
            with winreg.OpenKey(hive, oem_path) as k:
                name, _ = winreg.QueryValueEx(k, "OEMName")
                if name:
                    return str(name)
        except OSError:
            continue
    return None


def list_devices() -> list[Device]:
    mm = _winmm()
    if mm is None:
        return []
    out: list[Device] = []
    try:
        n = mm.joyGetNumDevs()
    except Exception:
        return []
    for i in range(min(n, 16)):
        caps = JOYCAPSW()
        if mm.joyGetDevCapsW(i, ctypes.byref(caps), ctypes.sizeof(caps)) != 0:
            continue
        info = JOYINFOEX()
        info.dwSize = ctypes.sizeof(info)
        info.dwFlags = JOY_RETURNALL
        if mm.joyGetPosEx(i, ctypes.byref(info)) != 0:
            continue  # non branché
        name = _oem_name(i, caps.szRegKey) or caps.szPname
        has_pov = bool(caps.wCaps & JOYCAPS_HASPOV)
        ranges = [(caps.wXmin, caps.wXmax), (caps.wYmin, caps.wYmax), (caps.wZmin, caps.wZmax),
                  (caps.wRmin, caps.wRmax), (caps.wUmin, caps.wUmax), (caps.wVmin, caps.wVmax)]
        out.append(Device(
            id=i, name=name, product=caps.szPname, vid=caps.wMid, pid=caps.wPid,
            num_axes=8 if has_pov else 6, num_buttons=min(caps.wNumButtons, MAX_BUTTONS),
            has_pov=has_pov, ranges=ranges,
        ))
    return out


def poll_device(dev: Device) -> Optional[DeviceState]:
    mm = _winmm()
    if mm is None:
        return None
    info = JOYINFOEX()
    info.dwSize = ctypes.sizeof(info)
    info.dwFlags = JOY_RETURNALL
    if mm.joyGetPosEx(dev.id, ctypes.byref(info)) != 0:
        return None
    raw = [info.dwXpos, info.dwYpos, info.dwZpos, info.dwRpos, info.dwUpos, info.dwVpos]
    axes = []
    for v, (lo, hi) in zip(raw, dev.ranges):
        if hi <= lo:
            axes.append(0.0)
            continue
        c = (lo + hi) / 2.0
        axes.append(max(-1.0, min(1.0, (v - c) / ((hi - lo) / 2.0))))
    if dev.has_pov:
        import math

        if info.dwPOV == JOY_POVCENTERED or info.dwPOV > 36000:
            axes += [0.0, 0.0]
        else:
            ang = math.radians(info.dwPOV / 100.0)
            s, c = math.sin(ang), math.cos(ang)
            axes += [0.0 if abs(s) < 0.1 else (1.0 if s > 0 else -1.0),
                     0.0 if abs(c) < 0.1 else (1.0 if c > 0 else -1.0)]
    return DeviceState(axes, info.dwButtons)


# ---------------------------------------------------------------------------
# Type de périphérique (pour l'illustration)
# ---------------------------------------------------------------------------

def guess_kind(name: str, cfg: Optional[JoystickConfig] = None) -> str:
    n = name.lower()
    if any(w in n for w in ("pedal", "rudder", "pédal", "palonnier", "t-rudder", "tpr", "crosswind")):
        return "pedals"
    if any(w in n for w in ("throttle", "quadrant", "twcs", "tq", "tca q", "manette", "bravo")):
        return "throttle"
    if "yoke" in n or "alpha" in n or "manche" in n:
        return "yoke"
    if any(w in n for w in ("gamepad", "xbox", "controller", "pad", "dualshock", "dualsense")):
        return "gamepad"
    if cfg is not None:
        descs = " ".join(a.desc.lower() for a in cfg.axes.values())
        if "brake" in descs and "rudder" in descs and "aileron" not in descs:
            return "pedals"
        if "throttle" in descs and "aileron" not in descs:
            return "throttle"
    return "stick"


KIND_LABELS = {
    "stick": "Manche / joystick",
    "throttle": "Manette des gaz",
    "yoke": "Yoke (volant)",
    "pedals": "Palonnier",
    "gamepad": "Manette de jeu",
}

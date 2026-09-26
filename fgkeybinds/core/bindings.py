"""Modificateurs, représentation et description lisible des bindings FlightGear."""

from __future__ import annotations

import re
from typing import Iterable, Optional

from lxml import etree

from .props import PNode, element_to_pnode

# Masques de modificateurs de FlightGear (FGCommonInput / KEYMOD_*)
MOD_NONE = 0
MOD_SHIFT = 1
MOD_CTRL = 2
MOD_ALT = 4
MOD_META = 8
MOD_SUPER = 16
MOD_HYPER = 32
MOD_RELEASED = 64

# Ordre de lecture de FGCommonInput::read_bindings
MOD_TAGS: list[tuple[str, int]] = [
    ("mod-up", MOD_RELEASED),
    ("mod-shift", MOD_SHIFT),
    ("mod-ctrl", MOD_CTRL),
    ("mod-alt", MOD_ALT),
    ("mod-meta", MOD_META),
    ("mod-super", MOD_SUPER),
    ("mod-hyper", MOD_HYPER),
]
MOD_TAG_BY_BIT = {bit: tag for tag, bit in MOD_TAGS}

# Ordre canonique utilisé pour écrire un masque sous forme de chemin
CANONICAL_ORDER = [MOD_SHIFT, MOD_CTRL, MOD_ALT, MOD_META, MOD_SUPER, MOD_HYPER]

_MOD_LABELS = [
    (MOD_CTRL, "Ctrl"),
    (MOD_ALT, "Alt"),
    (MOD_SHIFT, "Maj"),
    (MOD_META, "Meta"),
    (MOD_SUPER, "Super"),
    (MOD_HYPER, "Hyper"),
]


def mask_prefix(mask: int) -> str:
    """``Ctrl+Maj+`` pour un masque donné (sans le bit de relâchement)."""
    if mask & (MOD_CTRL | MOD_ALT) == (MOD_CTRL | MOD_ALT):
        # AltGr sous Windows = Ctrl+Alt
        rest = mask & ~(MOD_CTRL | MOD_ALT)
        return "AltGr+" + "".join(lbl + "+" for bit, lbl in _MOD_LABELS if rest & bit)
    return "".join(lbl + "+" for bit, lbl in _MOD_LABELS if mask & bit)


def mask_path(mask: int) -> tuple[str, ...]:
    """Chemin d'éléments canonique pour un masque (le relâchement en dernier)."""
    path = [MOD_TAG_BY_BIT[b] for b in CANONICAL_ORDER if mask & b]
    if mask & MOD_RELEASED:
        path.append("mod-up")
    return tuple(path)


def path_mask(path: Iterable[str]) -> int:
    m = 0
    for tag in path:
        for t, bit in MOD_TAGS:
            if t == tag:
                m |= bit
    return m


# ---------------------------------------------------------------------------
# Bindings
# ---------------------------------------------------------------------------

def is_null(b: PNode) -> bool:
    return b.text("command") in ("null", "")


def binding_from_xml(xml: str) -> PNode:
    el = etree.fromstring(xml.strip().encode("utf-8"))
    if el.tag != "binding":
        raise ValueError("L'élément racine doit être <binding>")
    return element_to_pnode(el, "binding")


# Paramètres propres à chaque commande connue : les autres enfants d'un binding
# fusionné sont des reliquats du fichier global (ignorés par FlightGear).
_CMD_PARAMS = {
    "nasal": {"script", "module"},
    "property-toggle": {"property"},
    "property-assign": {"property", "value"},
    "property-adjust": {"property", "step", "offset", "factor", "min", "max", "wrap", "mask", "setting"},
    "property-multiply": {"property", "factor", "min", "max", "wrap", "mask", "setting"},
    "property-scale": {"property", "offset", "factor", "squared", "power", "setting"},
    "property-cycle": {"property", "value", "wrap"},
    "property-swap": {"property"},
    "property-randomize": {"property", "min", "max"},
    "dialog-show": {"dialog-name"},
    "dialog-close": {"dialog-name"},
    "null": set(),
}
_ALWAYS = {"command", "condition"}


def clean_binding(b: PNode) -> PNode:
    """Copie du binding sans les paramètres étrangers à sa commande."""
    allowed = _CMD_PARAMS.get(b.text("command"))
    c = b.copy()
    if allowed is None:
        return c
    for child in list(c.children()):
        if child.name not in allowed and child.name not in _ALWAYS:
            c.remove_child(child)
    return c


def binding_to_xml(b: PNode, pretty: bool = True, clean: bool = True) -> str:
    el = (clean_binding(b) if clean else b).to_element("binding")
    if pretty:
        etree.indent(el, space="  ")
    return etree.tostring(el, encoding="unicode")


def _norm_prop(p: str) -> str:
    return p.strip().lstrip("/")


def _norm_script(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


FGKB_SCALE_RE = re.compile(
    r"#\s*FGKB-SCALE\s+property=\"(?P<prop>[^\"]*)\"\s+offset=(?P<offset>\S+)\s+factor=(?P<factor>\S+)\s+power=(?P<power>\S+)"
)
FGKB_CURVE_RE = re.compile(r"#\s*FGKB-CURVE\s+expo=(?P<expo>[-0-9.eE]+)")


def canonical(b: PNode) -> str:
    """Texte normalisé d'un binding, utilisé pour la recherche et le catalogue.

    Une ligne par paramètre : ``cmd=...``, ``prop=...``, ``value=...``,
    ``step=...``, ``script=...``, ``dialog=...``.
    """
    cmd = b.text("command")
    lines = []
    script = b.text("script")
    m = FGKB_SCALE_RE.search(script) if cmd == "nasal" else None
    if m:
        # binding property-scale converti par FGKeybinds pour gérer l'expo
        lines.append("cmd=property-scale")
        lines.append("prop=" + _norm_prop(m.group("prop")))
        lines.append("offset=" + m.group("offset"))
        lines.append("factor=" + m.group("factor"))
        return "\n".join(lines)
    lines.append("cmd=" + cmd)
    for c in b.children():
        v = (c.value or "").strip()
        if c.name == "command":
            continue
        if c.name == "property":
            lines.append("prop=" + _norm_prop(v))
        elif c.name == "script":
            lines.append("script=" + _norm_script(v))
        elif c.name == "dialog-name":
            lines.append("dialog=" + v)
        elif c.name == "condition":
            lines.append("condition=yes")
        elif c.children():
            continue
        else:
            lines.append(f"{c.name}={v}")
    return "\n".join(lines)


_DIALOG_FR = {
    "map": "carte",
    "autopilot": "pilote automatique",
    "radios": "radios",
    "exit": "quitter",
    "replay": "rejeu",
    "chat-menu": "menu du chat",
    "flight-recorder-load": "chargement d'enregistrement",
    "flight-recorder-save": "sauvegarde d'enregistrement",
}

_CMD_FR = {
    "pause": "Pause / reprise de la simulation",
    "screen-capture": "Capture d'écran",
    "toggle-fullscreen": "Plein écran",
    "reset": "Réinitialiser le vol",
    "replay": "Rejeu",
    "cycle-mouse-mode": "Changer le mode de la souris",
    "ATC-dialog": "Dialogue ATC",
    "panel-load": "Recharger le panneau",
    "exit": "Quitter FlightGear",
    "null": "(désactivé)",
}


def summarize(b: PNode, max_len: int = 90) -> str:
    """Description courte et lisible d'un binding, en français."""
    cmd = b.text("command")
    props = [_norm_prop(c.value or "") for c in b.children("property")]
    p0 = "/" + props[0] if props else ""
    if cmd == "property-toggle":
        s = f"Basculer {p0}"
    elif cmd == "property-assign":
        if len(props) > 1:
            s = f"{p0} ← /{props[1]}"
        else:
            s = f"{p0} = {b.text('value')}"
    elif cmd == "property-adjust":
        step = b.text("step") or b.text("offset") or "?"
        if step and not step.startswith("-"):
            step = "+" + step
        s = f"{p0} {step}"
    elif cmd == "property-scale":
        s = f"Axe → {p0}"
        f = b.text("factor")
        if f.startswith("-"):
            s += " (inversé)"
    elif cmd == "property-cycle":
        vals = [(c.value or "").strip() for c in b.children("value")]
        s = f"Cycle {p0} : " + ", ".join(v for v in vals if v)
    elif cmd == "property-swap":
        s = "Échanger " + " ↔ ".join("/" + p for p in props)
    elif cmd == "property-multiply":
        s = f"{p0} × {b.text('factor')}"
    elif cmd == "property-interpolate":
        s = f"Interpoler {p0}"
    elif cmd == "dialog-show":
        d = b.text("dialog-name")
        s = f"Ouvrir la fenêtre « {_DIALOG_FR.get(d, d)} »"
    elif cmd == "nasal":
        script = b.text("script")
        m = FGKB_SCALE_RE.search(script)
        if m:
            s = f"Axe → {m.group('prop')}"
            if m.group("factor").startswith("-"):
                s += " (inversé)"
            ce = FGKB_CURVE_RE.search(script)
            if ce:
                s += f" · expo {float(ce.group('expo')):.2f}"
        else:
            body = _strip_fgkb(script)
            s = _norm_script(body) or "(script Nasal vide)"
            ce = FGKB_CURVE_RE.search(script)
            if ce:
                s += f" · expo {float(ce.group('expo')):.2f}"
    elif cmd in _CMD_FR:
        s = _CMD_FR[cmd]
    elif cmd == "show-message":
        s = "Message : " + (b.text("label") or b.text("id"))
    else:
        s = cmd or "(binding sans commande)"
        if props:
            s += " " + p0
    if b.node("condition") is not None:
        s += " [cond.]"
    if len(s) > max_len:
        s = s[: max_len - 1] + "…"
    return s


def _strip_fgkb(script: str) -> str:
    """Retire le bloc de courbe ajouté par FGKeybinds d'un script Nasal."""
    return re.sub(r"#\s*FGKB-CURVE.*?#\s*FGKB-END[^\n]*\n?", "", script, flags=re.S)


def describe_bindings(bindings: list[PNode], desc: Optional[str] = None) -> str:
    live = [b for b in bindings if not is_null(b)]
    if desc and desc.strip():
        return desc.strip()
    if not live:
        return ""
    return " ; ".join(summarize(b, 60) for b in live[:3])


def bindings_equal(a: list[PNode], b: list[PNode]) -> bool:
    ca = [canonical(x) for x in a if not is_null(x)]
    cb = [canonical(x) for x in b if not is_null(x)]
    return ca == cb

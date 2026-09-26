"""Courbes de sensibilité des axes : zone morte et exponentielle.

* La **zone morte** utilise le paramètre natif ``<dead-band>`` de l'axe.  PLIB
  supprime le signal sous le seuil puis redimensionne le reste de la course
  pour qu'il n'y ait pas de saut : ``y = signe(x)·(|x| − z)/(1 − z)``.
* FlightGear n'a pas d'« expo » natif (``power`` n'accepte que des entiers).
  FGKeybinds l'implémente en Nasal, au début du binding de l'axe, en modifiant
  la valeur ``setting`` transmise au reste du binding :
  ``y = (1 − e)·x + e·x³``.  Un binding ``property-scale`` est converti en
  script Nasal équivalent, ses paramètres d'origine étant conservés dans un
  commentaire ``# FGKB-SCALE`` pour pouvoir le restaurer.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Optional

from lxml import etree

from .bindings import FGKB_CURVE_RE, FGKB_SCALE_RE
from . import xmledit

CURVE_BLOCK_RE = re.compile(r"[ \t]*#\s*FGKB-CURVE.*?#\s*FGKB-END[^\n]*\n?", re.S)
SCALE_BLOCK_RE = re.compile(r"[ \t]*#\s*FGKB-SCALE.*?#\s*FGKB-SCALE-END[^\n]*\n?", re.S)
INVERT_RE = re.compile(r"invert=(?P<inv>[01])")


@dataclass
class AxisCurve:
    dead_band: float = 0.0
    expo: float = 0.0
    invert: bool = False  # sens inversé (facteur négatif pour property-scale)
    # paramètres property-scale (natifs ou conservés dans FGKB-SCALE)
    kind: str = "none"  # "scale" | "nasal" | "none"
    prop: str = ""
    offset: float = 0.0
    factor: float = 1.0
    power: int = 1

    def shaped(self, x: float) -> float:
        """Valeur normalisée transmise après zone morte, inversion, expo et puissance."""
        y = apply_dead_band(x, self.dead_band)
        if self.invert:
            y = -y
        y = apply_expo(y, self.expo)
        if self.kind == "scale" and self.power > 1:
            y = math.copysign(abs(y) ** self.power, y)
        return y

    def output(self, x: float) -> float:
        """Valeur écrite dans la propriété (pour property-scale)."""
        y = self.shaped(x)
        if self.kind == "scale":
            return (y + self.offset) * abs(self.factor)
        return y


def apply_dead_band(x: float, db: float) -> float:
    db = max(0.0, min(0.95, db))
    if abs(x) <= db:
        return 0.0
    return math.copysign((abs(x) - db) / (1.0 - db), x)


def apply_expo(x: float, e: float) -> float:
    e = max(0.0, min(1.0, e))
    return (1.0 - e) * x + e * x * x * x


def _num(s: Optional[str], default: float) -> float:
    if s is None:
        return default
    s = s.strip().lower()
    if s in ("true", "false"):
        return 1.0 if s == "true" else 0.0
    try:
        return float(s)
    except ValueError:
        return default


def _fmt(v: float) -> str:
    s = f"{v:.4f}".rstrip("0").rstrip(".")
    return s if s not in ("", "-0") else "0"


# ---------------------------------------------------------------------------
# Lecture de la courbe depuis un élément <axis>
# ---------------------------------------------------------------------------

def _curve_bindings(axis_el: etree._Element) -> list[etree._Element]:
    """Bindings de l'axe concernés par la courbe (hors boutons virtuels low/high)."""
    out = []
    for b in axis_el.iter("binding"):
        anc = b.getparent()
        skip = False
        while anc is not None and anc is not axis_el:
            if anc.tag in ("low", "high"):
                skip = True
            anc = anc.getparent()
        if not skip:
            out.append(b)
    return out


def read_curve(axis_el: etree._Element) -> AxisCurve:
    c = AxisCurve()
    db = axis_el.find("dead-band")
    c.dead_band = _num(db.text if db is not None else None, 0.0)
    bl = _curve_bindings(axis_el)
    if not bl:
        return c
    b = bl[0]
    cmd = (b.findtext("command") or "").strip()
    if cmd == "property-scale":
        c.kind = "scale"
        c.prop = (b.findtext("property") or "").strip()
        c.offset = _num(b.findtext("offset"), 0.0)
        c.factor = _num(b.findtext("factor"), 1.0)
        squared = (b.findtext("squared") or "").strip().lower() in ("true", "1")
        c.power = int(_num(b.findtext("power"), 2.0 if squared else 1.0))
        c.invert = c.factor < 0
    elif cmd == "nasal":
        script = b.findtext("script") or ""
        m = FGKB_SCALE_RE.search(script)
        if m:
            c.kind = "scale"
            c.prop = m.group("prop")
            c.offset = _num(m.group("offset"), 0.0)
            c.factor = _num(m.group("factor"), 1.0)
            c.power = int(_num(m.group("power"), 1.0))
            c.invert = c.factor < 0
        else:
            c.kind = "nasal"
            c.invert = read_invert(script)
        mc = FGKB_CURVE_RE.search(script)
        if mc:
            c.expo = _num(mc.group("expo"), 0.0)
    return c


def curve_from_pnode_axis(axis) -> AxisCurve:
    """Même chose à partir d'un AxisDef (arbre PNode) pour l'affichage."""
    el = axis.node.to_element("axis") if axis.node is not None else etree.Element("axis")
    c = read_curve(el)
    c.dead_band = axis.dead_band
    return c


# ---------------------------------------------------------------------------
# Écriture
# ---------------------------------------------------------------------------

def _curve_block(expo: float, invert: bool) -> str:
    e = _fmt(expo)
    lines = [f"# FGKB-CURVE expo={e} invert={1 if invert else 0} (courbe gérée par FGKeybinds)",
             "var fgkb_s = cmdarg().getNode(\"setting\");",
             "var fgkb_x = fgkb_s.getValue();"]
    if invert:
        lines.append("fgkb_x = -fgkb_x;")
    if expo > 0:
        lines.append(f"fgkb_x = (1 - {e}) * fgkb_x + {e} * fgkb_x * fgkb_x * fgkb_x;")
    lines.append("fgkb_s.setDoubleValue(fgkb_x);")
    lines.append("# FGKB-END")
    return "\n".join(lines) + "\n"


def _scale_block(prop: str, offset: float, factor: float, power: int) -> str:
    lines = [f'# FGKB-SCALE property="{prop}" offset={_fmt(offset)} factor={_fmt(factor)} power={power}',
             "var fgkb_v = cmdarg().getNode(\"setting\").getValue();"]
    if power > 1:
        prod = " * ".join(["fgkb_a"] * power)
        lines.append("var fgkb_a = fgkb_v < 0 ? -fgkb_v : fgkb_v;")
        lines.append(f"fgkb_v = (fgkb_v < 0 ? -1 : 1) * {prod};")
    expr = "fgkb_v"
    if offset:
        expr = f"({expr} + {_fmt(offset)})"
    if factor != 1.0:
        expr = f"{expr} * {_fmt(factor)}"
    lines.append(f'setprop("{prop}", {expr});')
    lines.append("# FGKB-SCALE-END")
    return "\n".join(lines) + "\n"


def _set_script(b: etree._Element, script: str) -> None:
    s = b.find("script")
    if s is None:
        s = xmledit.insert_child(b, xmledit.sub("script"))
    s.text = etree.CDATA("\n" + script.strip("\n") + "\n" + xmledit.indent_of(s))


def _set_command(b: etree._Element, cmd: str) -> None:
    c = b.find("command")
    if c is None:
        xmledit.insert_child(b, xmledit.sub("command", cmd), 0)
    else:
        c.text = cmd


def apply_curve(axis_el: etree._Element, dead_band: float, expo: float, invert: bool) -> None:
    """Applique zone morte / expo / inversion à un élément ``<axis>``."""
    # zone morte native (doit précéder le binding)
    for d in axis_el.findall("dead-band"):
        xmledit.remove_child(d)
    if dead_band > 0:
        kids = [c for c in axis_el if isinstance(c.tag, str)]
        pos = next((i for i, c in enumerate(kids) if c.tag == "binding"), len(kids))
        xmledit.insert_child(axis_el, xmledit.sub("dead-band", _fmt(dead_band), {"type": "double"}), pos)

    for b in _curve_bindings(axis_el):
        cmd = (b.findtext("command") or "").strip()
        if cmd == "property-scale":
            prop = (b.findtext("property") or "").strip()
            offset = _num(b.findtext("offset"), 0.0)
            factor = _num(b.findtext("factor"), 1.0)
            squared = (b.findtext("squared") or "").strip().lower() in ("true", "1")
            power = int(_num(b.findtext("power"), 2.0 if squared else 1.0))
            if (factor < 0) != invert:
                # inversion native : on change le signe du facteur
                factor = -factor
                _set_scale_param(b, "factor", factor, 1.0)
            if expo <= 0:
                continue
            for tag in ("property", "offset", "factor", "squared", "power", "setting"):
                for e in b.findall(tag):
                    xmledit.remove_child(e)
            _set_command(b, "nasal")
            _set_script(b, _curve_block(expo, False) + _scale_block(prop, offset, factor, power))
        elif cmd == "nasal":
            script = b.findtext("script") or ""
            m = FGKB_SCALE_RE.search(script)
            if m:
                prop = m.group("prop")
                offset = _num(m.group("offset"), 0.0)
                factor = _num(m.group("factor"), 1.0)
                power = int(_num(m.group("power"), 1.0))
                if (factor < 0) != invert:
                    factor = -factor
                if expo <= 0:
                    # retour au property-scale d'origine
                    for e in b.findall("script"):
                        xmledit.remove_child(e)
                    _set_command(b, "property-scale")
                    xmledit.insert_child(b, xmledit.sub("property", prop))
                    if offset:
                        xmledit.insert_child(b, xmledit.sub("offset", _fmt(offset), {"type": "double"}))
                    if factor != 1.0:
                        xmledit.insert_child(b, xmledit.sub("factor", _fmt(factor), {"type": "double"}))
                    if power > 1:
                        xmledit.insert_child(b, xmledit.sub("power", str(power), {"type": "int"}))
                else:
                    _set_script(b, _curve_block(expo, False) + _scale_block(prop, offset, factor, power))
            else:
                body = CURVE_BLOCK_RE.sub("", script).strip("\n")
                if expo <= 0 and not invert:
                    _set_script(b, body)
                else:
                    _set_script(b, _curve_block(expo, invert) + body.strip() + "\n")


def read_invert(script: str) -> bool:
    mc = FGKB_CURVE_RE.search(script)
    if not mc:
        return False
    mi = INVERT_RE.search(script[mc.start(): mc.start() + 120])
    return bool(mi and mi.group("inv") == "1")


def _set_scale_param(b: etree._Element, tag: str, value: float, default: float) -> None:
    els = b.findall(tag)
    if abs(value - default) < 1e-12:
        for e in els:
            xmledit.remove_child(e)
        return
    if els:
        els[-1].text = _fmt(value)
    else:
        xmledit.insert_child(b, xmledit.sub(tag, _fmt(value), {"type": "double"}))

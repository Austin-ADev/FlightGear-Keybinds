from pathlib import Path

import pytest
from lxml import etree

from fgkeybinds.core import aircraft as ac
from fgkeybinds.core import curves, xmledit
from fgkeybinds.core.bindings import MOD_ALT, MOD_CTRL, MOD_RELEASED, MOD_SHIFT, canonical, summarize
from fgkeybinds.core.catalog import Catalog
from fgkeybinds.core.keyboard import KeyboardConfig, combo_label
from fgkeybinds.core.layouts import builtin_layouts
from fgkeybinds.core.profiles import Profile, keyboard_xml, load_profile, profile_from_keyboard_xml, save_profile
from fgkeybinds.core.props import PNode, PropertyLoader
from fgkeybinds.core.search import parse_combo
from fgkeybinds.core.workspace import GLOBAL, Context


# ---------------------------------------------------------------------------
# Lecture des PropertyList
# ---------------------------------------------------------------------------

def test_merge_semantics(tmp_path: Path):
    a = tmp_path / "a.xml"
    b = tmp_path / "b.xml"
    a.write_text("<PropertyList><x><y>1</y><y>2</y></x><z n='3'>c</z></PropertyList>")
    b.write_text("<PropertyList include='a.xml'><x><y>10</y></x><z>0</z><z>1</z><z>2</z><z>3</z></PropertyList>")
    root = PropertyLoader().load(b)
    ys = root.node("x").children("y")
    assert [y.value for y in ys] == ["10", "2"]  # fusion par index
    assert root.get("z[3]") == "3"
    assert len(root.children("z")) == 4


def test_omit_node_and_missing_include(tmp_path: Path):
    (tmp_path / "part.xml").write_text("<PropertyList><k>v</k></PropertyList>")
    f = tmp_path / "main.xml"
    f.write_text("<PropertyList><a><b include='part.xml' omit-node='y'/><c include='nope.xml'/></a></PropertyList>")
    loader = PropertyLoader()
    root = loader.load(f)
    assert root.get("a/k") == "v"
    assert any("nope.xml" in e for e in loader.errors)


# ---------------------------------------------------------------------------
# Clavier
# ---------------------------------------------------------------------------

def test_keyboard_resolution(fgroot):
    kb = ac.load_global_keyboard(fgroot)
    # Ctrl+A → code 1 (le Ctrl est inclus dans le code de contrôle : pas un repli)
    r = kb.resolve(1, MOD_CTRL)
    assert r.is_bound and not r.fallback and r.used_mask == 0
    # Maj+G → G (majuscule) : repli sans Maj
    r = kb.resolve(71, MOD_SHIFT)
    assert r.is_bound and r.used_mask == 0
    # Maj+1 (AZERTY : Maj+&) → binding mod-shift de la touche 49
    r = kb.resolve(49, MOD_SHIFT)
    assert r.used_mask == MOD_SHIFT and "Look back left" in r.slot.description()
    # AltGr+( → '[' avec Ctrl+Alt : repli sur '['
    r = kb.resolve(91, MOD_CTRL | MOD_ALT)
    assert r.is_bound and r.used_mask == 0 and r.fallback
    # Maj+G : la majuscule n'est pas un repli
    assert not kb.resolve(71, MOD_SHIFT).fallback
    # la touche G possède un binding au relâchement
    s = kb.slot(71, 0)
    assert len(s.release) == 1
    assert kb.repeatable(49)


def test_layout_codes():
    lay = {l.id: l for l in builtin_layouts()}
    az = lay["azerty_fr"]
    k1 = az.key("E01")  # touche « & / 1 »
    assert k1.input_for("none").code == ord("&")
    assert k1.input_for("shift").code == ord("1")
    ka = az.key("D00")
    assert ka.input_for("none").code == ord("a")
    assert ka.input_for("ctrl").code == 1
    k5 = az.key("E05")
    assert k5.input_for("altgr").code == ord("[")
    us = lay["qwerty_us"]
    assert us.key("E01").input_for("none").code == ord("1")
    for l in lay.values():
        ids = [k.id for k in l.keys]
        assert len(ids) == len(set(ids))
        assert abs(l.width - 23.0) < 0.01


def test_combo_labels():
    assert combo_label(1, 0) == "Ctrl+A"
    assert combo_label(71, 0) == "Maj+G"
    assert combo_label(103, 0) == "G"
    assert combo_label(257, MOD_SHIFT) == "Maj+F1"
    assert parse_combo("ctrl+a") == (1, MOD_CTRL)
    assert parse_combo("Maj+F1") == (257, MOD_SHIFT)
    assert parse_combo("+") == (43, 0)
    assert parse_combo("alt++") == (43, MOD_ALT)
    assert parse_combo("foo+a") is None


# ---------------------------------------------------------------------------
# Écriture
# ---------------------------------------------------------------------------

GEAR_TOGGLE = "<binding><command>nasal</command><script>controls.gearToggle()</script></binding>"


def test_global_write_roundtrip(workspace, fgroot):
    before = (fgroot / "keyboard.xml").read_text(encoding="utf-8")
    ch = xmledit.SlotChange(code=102, mask=0, press=[GEAR_TOGGLE], desc="Train bascule")
    workspace.write_slot(GLOBAL, ch)
    after = (fgroot / "keyboard.xml").read_text(encoding="utf-8")
    assert "<!-- clavier de test -->" in after  # commentaires préservés
    assert (fgroot / "keyboard.xml.fgkb-backup").read_text(encoding="utf-8") == before
    s = workspace.global_kb.slot(102, 0)
    assert s.is_bound and s.description() == "Train bascule"
    # modifier un slot existant avec modificateur
    workspace.write_slot(GLOBAL, xmledit.SlotChange(code=49, mask=MOD_SHIFT, press=[GEAR_TOGGLE]))
    s = workspace.global_kb.slot(49, MOD_SHIFT)
    assert [canonical(b.node) for b in s.press] == ["cmd=nasal\nscript=controls.gearToggle()"]
    assert workspace.global_kb.slot(49, 0).is_bound  # le slot sans modificateur est intact
    # effacer
    workspace.clear_slot(GLOBAL, 102, 0)
    assert workspace.global_kb.slot(102, 0) is None
    etree.parse(str(fgroot / "keyboard.xml"))  # XML toujours valide
    # journal
    assert {(e.code, e.mask) for e in workspace.journal_entries()} == {(102, 0), (49, MOD_SHIFT)}
    assert workspace.journal_mismatches() == []


def test_aircraft_override_neutralizes_inherited(workspace, fgroot):
    v = workspace.variant(fgroot / "Aircraft" / "test" / "test-set.xml")
    assert v is not None
    ctx = Context("aircraft", v.set_file)
    kb = workspace.keyboard(ctx)
    assert kb.slot(71, 0).origin == "aircraft"
    # surcharger Tab (binding global avec <condition>) dans l'avion
    path = workspace.write_slot(ctx, xmledit.SlotChange(code=9, mask=0, press=[GEAR_TOGGLE]))
    assert path.name == "test-keyboard.xml"
    kb = workspace.keyboard(ctx)
    s = kb.slot(9, 0)
    live = s.live_press
    assert len(live) == 1
    assert canonical(live[0].node) == "cmd=nasal\nscript=controls.gearToggle()"  # pas de <condition> héritée
    assert len(s.press) == 2  # un binding null neutralise l'original
    # le global n'est pas modifié
    assert workspace.global_kb.slot(9, 0).live_press[0].node.text("command") == "cycle-mouse-mode"
    # réécrire le même slot ne doit pas empiler les neutralisations
    workspace.write_slot(ctx, xmledit.SlotChange(code=9, mask=0, press=[GEAR_TOGGLE, GEAR_TOGGLE]))
    s = workspace.keyboard(ctx).slot(9, 0)
    assert len(s.press) == 3 and len(s.live_press) == 2
    # désactiver une touche globale dans l'avion
    workspace.write_slot(ctx, xmledit.SlotChange(code=112, mask=0))
    s = workspace.keyboard(ctx).slot(112, 0)
    assert s.is_disabled and s.origin == "disabled"
    # rétablir le comportement global
    workspace.restore_slot_to_global(ctx, 9, 0)
    s = workspace.keyboard(ctx).slot(9, 0)
    assert s.origin == "global"
    txt = (fgroot / "Aircraft" / "test" / "test-keyboard.xml").read_text(encoding="utf-8")
    assert "<!-- licence : GPL -->" in txt and "<!-- surcharge du train -->" in txt


def test_aircraft_override_of_release(workspace, fgroot):
    v = workspace.variant(fgroot / "Aircraft" / "test" / "test-set.xml")
    ctx = Context("aircraft", v.set_file)
    # g (103) est global ; l'avion le remplace par un binding avec relâchement
    rel = "<binding><command>nasal</command><script>controls.gearDown(0)</script></binding>"
    workspace.write_slot(ctx, xmledit.SlotChange(code=103, mask=0, press=[GEAR_TOGGLE], release=[rel]))
    s = workspace.keyboard(ctx).slot(103, 0)
    assert [canonical(b.node) for b in s.live_press] == ["cmd=nasal\nscript=controls.gearToggle()"]
    assert len(s.live_release) == 1


def test_aircraft_without_keyboard_file(workspace, fgroot, tmp_path):
    d = fgroot / "Aircraft" / "bare"
    d.mkdir()
    (d / "bare-set.xml").write_text("<?xml version='1.0'?>\n<PropertyList>\n  <sim>\n    <description>Nu</description>\n  </sim>\n</PropertyList>\n")
    workspace.reload()
    v = workspace.variant(d / "bare-set.xml")
    ctx = Context("aircraft", v.set_file)
    p = workspace.write_slot(ctx, xmledit.SlotChange(code=120, mask=MOD_ALT, press=[GEAR_TOGGLE], desc="Test"))
    assert p == d / "bare-set.xml"
    s = workspace.keyboard(ctx).slot(120, MOD_ALT)
    assert s.is_bound and s.description() == "Test"


# ---------------------------------------------------------------------------
# Joysticks et courbes
# ---------------------------------------------------------------------------

def test_joystick_library_and_copy(workspace, fghome):
    lib = workspace.joy_lib
    cfg, mode = lib.match("Saitek X52")
    assert mode == "exact"
    assert set(cfg.axes) == {0, 3}  # l'axe « unix only » est ignoré sous Windows
    cfg2, mode2 = lib.match("saitek  x52")
    assert mode2 == "approx"
    d, m = lib.match("Inconnu")
    assert m == "default" and d.is_default
    # création d'une config pour un périphérique inconnu (copie du défaut)
    p = workspace.joystick_for_device("Mon Palonnier")
    assert p.parent == fghome / "Input" / "Joysticks" / "FGKeybinds"
    c, m = workspace.joy_lib.match("Mon Palonnier")
    assert m == "exact" and c.origin == "home" and 0 in c.axes
    workspace.write_joystick_button(p, 5, "Train", [GEAR_TOGGLE], [], False)
    c, _ = workspace.joy_lib.match("Mon Palonnier")
    assert c.buttons[5].desc == "Train"


def test_curves_roundtrip(workspace):
    p = workspace.joystick_for_device("Stick")
    workspace.write_axis_curve(p, 0, 0.1, 0.4, False)
    c = workspace.read_axis_curve(p, 0)
    assert c.kind == "scale" and abs(c.expo - 0.4) < 1e-9 and abs(c.dead_band - 0.1) < 1e-9
    assert c.power == 2 and c.prop == "/controls/flight/aileron"
    cfg, _ = workspace.joy_lib.match("Stick")
    b = cfg.axes[0].bindings[0]
    assert b.text("command") == "nasal"
    assert canonical(b).startswith("cmd=property-scale")  # reconnu comme axe d'aileron
    assert "expo 0.40" in summarize(b)
    # inversion puis retour à un property-scale natif
    workspace.write_axis_curve(p, 0, 0.0, 0.0, True)
    c = workspace.read_axis_curve(p, 0)
    assert c.kind == "scale" and c.invert and c.expo == 0 and c.dead_band == 0
    cfg, _ = workspace.joy_lib.match("Stick")
    b = cfg.axes[0].bindings[0]
    assert b.text("command") == "property-scale" and b.text("factor") == "-1"
    # axe Nasal (gaz) : bloc ajouté puis retiré
    workspace.write_axis_curve(p, 2, 0.05, 0.3, True)
    c = workspace.read_axis_curve(p, 2)
    assert c.kind == "nasal" and c.invert and abs(c.expo - 0.3) < 1e-9
    cfg, _ = workspace.joy_lib.match("Stick")
    assert "controls.throttleAxis()" in cfg.axes[2].bindings[0].text("script")
    workspace.write_axis_curve(p, 2, 0.0, 0.0, False)
    cfg, _ = workspace.joy_lib.match("Stick")
    assert cfg.axes[2].bindings[0].text("script") == "controls.throttleAxis()"


def test_curve_math():
    c = curves.AxisCurve(dead_band=0.2, expo=0.5)
    assert c.shaped(0.1) == 0.0
    assert abs(c.shaped(1.0) - 1.0) < 1e-9
    assert abs(c.shaped(-1.0) + 1.0) < 1e-9
    assert 0 < c.shaped(0.6) < 0.5  # l'expo adoucit le centre


# ---------------------------------------------------------------------------
# Catalogue et profils
# ---------------------------------------------------------------------------

def test_catalog_matches(workspace):
    cat = Catalog.load()
    ids = workspace.bound_action_ids(GLOBAL, include_joysticks=False)
    assert "gear.down" in ids and "gear.up" in ids and "sim.pause" in ids and "flaps.up" in ids
    assert "flaps.down" not in ids
    assert len(cat.categories()) >= 8


def test_profiles_roundtrip(workspace, tmp_path, fgroot):
    v = workspace.variant(fgroot / "Aircraft" / "test" / "test-set.xml")
    ctx = Context("aircraft", v.set_file)
    entries = workspace.entries_for(ctx, only_specific=True)
    assert {(e.code, e.mask) for e in entries} == {(71, 0), (102, 0)}
    prof = Profile(name="test", keyboard=entries)
    f = tmp_path / "p.fgkb"
    save_profile(prof, f)
    back = load_profile(f)
    assert [(e.code, e.mask, e.press) for e in back.keyboard] == [(e.code, e.mask, e.press) for e in entries]
    x = tmp_path / "k.xml"
    x.write_text(keyboard_xml(entries, "export"), encoding="utf-8")
    back2 = profile_from_keyboard_xml(x)
    assert {(e.code, e.mask) for e in back2.keyboard} == {(71, 0), (102, 0)}
    g = [e for e in back2.keyboard if e.code == 71][0]
    assert g.desc == "Gear down (avion)"
    # appliquer le profil au clavier global
    workspace.apply_entries(GLOBAL, back.keyboard)
    assert workspace.global_kb.slot(102, 0).is_bound


def test_clean_binding_removes_merge_leftovers(workspace, fgroot):
    from fgkeybinds.core.bindings import binding_to_xml

    v = workspace.variant(fgroot / "Aircraft" / "test" / "test-set.xml")
    kb = workspace.keyboard(Context("aircraft", v.set_file))
    b = kb.slot(71, 0).live_press[0].node
    assert b.text("script")  # reliquat du binding global fusionné
    xml = binding_to_xml(b)
    assert "script" not in xml and "gear-down" in xml


def test_scancodes_follow_physical_position():
    from fgkeybinds.core.layouts import live_layer, scancode_map

    lay = {l.id: l for l in builtin_layouts()}
    az, us, uk = scancode_map(lay["azerty_fr"]), scancode_map(lay["qwerty_us"]), scancode_map(lay["qwerty_uk"])
    # même position physique (0x10), caractère différent selon la disposition
    assert lay["azerty_fr"].key(az[0x10]).base == "a"
    assert lay["qwerty_us"].key(us[0x10]).base == "q"
    # touches propres à l'ISO / à l'ANSI
    assert lay["azerty_fr"].key(az[0x56]).base == "<"
    assert lay["qwerty_us"].key(us[0x2B]).base == "\\"
    assert lay["qwerty_uk"].key(uk[0x2B]).base == "#"
    # pavé numérique (non étendu) ≠ bloc de navigation (étendu)
    assert az[0x47] == "KP7" and az[0x147] == "HOME"
    assert az[0x11C] == "KPENT" and az[0x1C] == "ENTER"
    # toutes les touches du dessin ont un code de balayage
    for l in lay.values():
        m = scancode_map(l)
        missing = {k.id for k in l.keys} - set(m.values())
        assert not missing, (l.id, missing)
    # couche affichée selon les modificateurs tenus
    assert live_layer({"LSHIFT"}, True) == "shift"
    assert live_layer({"LCTRL", "RALT"}, True) == "altgr"  # AltGr = faux Ctrl + Alt droit
    assert live_layer({"RALT"}, False) == "alt"  # pas d'AltGr en QWERTY US
    assert live_layer({"LCTRL", "RSHIFT"}, True) == "ctrl+shift"
    assert live_layer(set(), True) is None

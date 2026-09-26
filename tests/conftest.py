import sys
import textwrap
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

GLOBAL_KB = """<?xml version="1.0"?>
<!-- clavier de test -->
<PropertyList>
 <key n="1">
  <name>Ctrl-A</name>
  <desc>Toggle altitude</desc>
  <binding>
   <command>property-toggle</command>
   <property>/autopilot/alt</property>
  </binding>
 </key>
 <key n="9">
  <name>Tab</name>
  <desc>Cycle mouse mode</desc>
  <binding>
   <condition><not><property>/devices/status/keyboard/alt</property></not></condition>
   <command>cycle-mouse-mode</command>
  </binding>
 </key>
 <key n="49">
  <name>1</name>
  <desc>Elevator trim down</desc>
  <repeatable type="bool">true</repeatable>
  <binding>
   <command>property-adjust</command>
   <property>/controls/flight/elevator-trim</property>
   <step type="double">-0.001</step>
  </binding>
  <mod-shift>
   <desc>Look back left</desc>
   <binding>
    <command>property-assign</command>
    <property>/sim/current-view/goal-heading-offset-deg</property>
    <property>/sim/view/config/back-left-direction-deg</property>
   </binding>
  </mod-shift>
 </key>
 <key n="71">
  <name>G</name>
  <desc>Gear down</desc>
  <binding>
   <command>nasal</command>
   <script>controls.gearDown(1)</script>
  </binding>
  <mod-up>
   <binding>
    <command>nasal</command>
    <script>controls.gearDown(0)</script>
   </binding>
  </mod-up>
 </key>
 <key n="91">
  <name>[</name>
  <desc>Decrease flaps</desc>
  <binding>
   <command>nasal</command>
   <script>controls.flapsDown(-1)</script>
  </binding>
 </key>
 <key n="103">
  <name>g</name>
  <desc>Gear up</desc>
  <binding>
   <command>nasal</command>
   <script>controls.gearDown(-1)</script>
  </binding>
 </key>
 <key n="112">
  <name>p</name>
  <desc>Pause</desc>
  <binding>
   <command>pause</command>
  </binding>
 </key>
</PropertyList>
"""

DEFAULT_JS = """<?xml version="1.0"?>
<PropertyList>
 <name>default</name>
 <axis n="0">
  <desc>Aileron</desc>
  <binding>
   <command>property-scale</command>
   <property>/controls/flight/aileron</property>
   <squared type="bool">true</squared>
  </binding>
 </axis>
 <axis n="2">
  <desc>Throttle</desc>
  <binding>
   <command>nasal</command>
   <script>controls.throttleAxis()</script>
  </binding>
 </axis>
 <button n="0">
  <desc>Brakes</desc>
  <binding>
   <command>nasal</command>
   <script>controls.applyBrakes(1)</script>
  </binding>
  <mod-up>
   <binding>
    <command>nasal</command>
    <script>controls.applyBrakes(0)</script>
   </binding>
  </mod-up>
 </button>
</PropertyList>
"""

X52_JS = """<?xml version="1.0"?>
<PropertyList>
 <name>Saitek X52</name>
 <axis>
  <desc>Aileron</desc>
  <number><unix>0</unix><windows>0</windows></number>
  <binding><command>property-scale</command><property>/controls/flight/aileron</property></binding>
 </axis>
 <axis>
  <desc>Rudder</desc>
  <number><unix>5</unix><windows>3</windows></number>
  <binding><command>property-scale</command><property>/controls/flight/rudder</property></binding>
 </axis>
 <axis>
  <desc>Unix only</desc>
  <number><unix>9</unix></number>
  <binding><command>property-scale</command><property>/foo</property></binding>
 </axis>
</PropertyList>
"""

AIRCRAFT_SET = """<?xml version="1.0"?>
<PropertyList include="test-main.xml">
 <sim>
  <description>Avion de test</description>
 </sim>
</PropertyList>
"""

AIRCRAFT_MAIN = """<?xml version="1.0"?>
<PropertyList>
 <sim><author>Moi</author></sim>
 <input>
  <keyboard include="test-keyboard.xml"/>
 </input>
</PropertyList>
"""

AIRCRAFT_KB = """<?xml version="1.0" encoding="UTF-8"?>
<!-- licence : GPL -->
<PropertyList>
    <!-- surcharge du train -->
    <key n="71">
        <name>G</name>
        <desc>Gear down (avion)</desc>
        <binding>
            <command>property-assign</command>
            <property>/controls/gear/gear-down</property>
            <value>true</value>
        </binding>
    </key>
    <key n="102">
        <name>f</name>
        <desc>Flashlight</desc>
        <binding>
            <command>property-toggle</command>
            <property>/sim/rendering/flashlight</property>
        </binding>
    </key>
</PropertyList>
"""


def _w(p: Path, s: str) -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(textwrap.dedent(s), encoding="utf-8")
    return p


@pytest.fixture
def fgroot(tmp_path: Path) -> Path:
    root = tmp_path / "fgdata"
    _w(root / "keyboard.xml", GLOBAL_KB)
    _w(root / "Input" / "Joysticks" / "Default" / "joystick.xml", DEFAULT_JS)
    _w(root / "Input" / "Joysticks" / "Saitek" / "X52.xml", X52_JS)
    _w(root / "Aircraft" / "test" / "test-set.xml", AIRCRAFT_SET)
    _w(root / "Aircraft" / "test" / "test-main.xml", AIRCRAFT_MAIN)
    _w(root / "Aircraft" / "test" / "test-keyboard.xml", AIRCRAFT_KB)
    (root / "version").write_text("2024.1.1")
    return root


@pytest.fixture
def fghome(tmp_path: Path) -> Path:
    h = tmp_path / "fghome"
    h.mkdir()
    return h


@pytest.fixture
def workspace(fgroot, fghome, tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    from fgkeybinds.core.settings import Settings
    from fgkeybinds.core.workspace import Workspace

    s = Settings(fg_root=str(fgroot), fg_home=str(fghome))
    return Workspace(s)

"""probe20: subtitle / UI watcher (read-only).

Run while playing. Goal: see exactly what appears - screen-stack entries,
newly created UI objects, watched-class hits - when a subtitle or audio log
plays and when a tutorial banner shows. This is how we pin down a
"subtitle active" signal (or confirm that no UI object is created and the
subtitle shader must be separated via ShaderToggler instead).

Logs (timestamped, via hud_dynamic's log()):
  - 'ui watch: new <label> ii=... obj=...'   watched UI class created
  - 'screen stack changed: n=... [ii=.../tag]'
  - a heartbeat line every 30 s

Usage: run it from the Win64 folder next to hud_dynamic.py:
    python probe20_subwatch.py
"""
import os
import sys
import time

GAME_DIR = r"D:\SteamLibrary\steamapps\common\Returnal\Returnal\Binaries\Win64"
for p in (os.getcwd(), os.path.dirname(os.path.abspath(__file__)), GAME_DIR):
    if p and p not in sys.path:
        sys.path.insert(0, p)

import hud_dynamic as h

pid = h.find_process_id(h.GAME_EXE)
mods = h.module_bases(pid, {h.GAME_DLL.lower(), h.HMQ_DLL.lower()})
gb = mods[h.GAME_DLL.lower()]
hb = mods.get(h.HMQ_DLL.lower(), 0)
mem = h.ProcessMem(pid, read_only=True)

tr = h.PlayerTracker(mem, gb, hb)
tr.tail_every = 1
tr._refresh_class_ptrs()
h.log("watcher up: pid=%d game=0x%X hmq=0x%X" % (pid, gb, hb))
h.log("watched labels: %s" % sorted(set(tr.watch.values())))
h.log("waiting for play: trigger an audio log (subtitle) and a tutorial banner")

last_hb = 0.0
while mem.alive():
    s = tr.sample(time.time())
    if time.time() - last_hb >= 30:
        last_hb = time.time()
        if s.get("ok"):
            h.log("hb: menus=%d layer=%s aim=%s ui=%d hp=%s ammo=%s/%s" % (
                int(bool(s.get("menu_open"))), s.get("stack_layer"),
                int(bool(s.get("aim"))), int(bool(s.get("ui_event"))),
                s.get("hp"), s.get("clip"), s.get("clip2")))
        elif s.get("note"):
            h.log("hb: waiting: %s" % s["note"])
    time.sleep(0.5)

h.log("game process exited; watcher done")
mem.close()

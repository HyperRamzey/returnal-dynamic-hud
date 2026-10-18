"""probe19: live verification of v1.3.0 stack classification (read-only)."""
import sys
import time

sys.path.insert(0, ".")
import hud_dynamic as h

pid = h.find_process_id(h.GAME_EXE)
mods = h.module_bases(pid, {h.GAME_DLL.lower(), h.HMQ_DLL.lower()})
gb = mods[h.GAME_DLL.lower()]
hb = mods.get(h.HMQ_DLL.lower(), 0)
mem = h.ProcessMem(pid, read_only=True)

t0 = time.time()
tr = h.PlayerTracker(mem, gb, hb)
tr.tail_every = 5
s = tr.sample(time.time())
print("sample ok=%s note=%r menus=%s layer=%s ui=%s" % (
    s["ok"], s.get("note"), s.get("menu_open"), s.get("stack_layer"),
    s.get("ui_event")))
print("pc=0x%X mgr=0x%X hud=0x%X pawn=0x%X" % (tr.pc, tr.mgr, tr.hud, tr.pawn))
print("cls pause=0x%X tutpanel=0x%X" % (
    tr.cls.get("pause", 0), tr.cls.get("tutpanel", 0)))

st = tr._stack()
if st is None:
    print("stack None")
else:
    n, entries = st
    print("stack n=%d" % n)
    for e in entries:
        ii, o, isp, isb, aux = e
        chain = []
        if o:
            try:
                chain = tr._chain(mem.u64(o + h.UOBJECT_CLASS))
            except OSError:
                pass
        print("  ii=%d aux=%d obj=0x%X pause=%s benign=%s chain=%s" % (
            ii, aux, o, isp, isb, [hex(x) for x in chain[:8]]))

s2 = tr.sample(time.time() + 0.5)
print("second sample: layer=%s menu=%s ui=%s" % (
    s2.get("stack_layer"), s2.get("menu_open"), s2.get("ui_event")))
print("elapsed %.2fs" % (time.time() - t0))
print("DONE", flush=True)
mem.close()

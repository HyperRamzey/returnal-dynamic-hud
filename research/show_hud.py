"""show_hud: restore the ShaderToggler group to byte 0 (HUD visible)."""
import sys

sys.path.insert(0, ".")
import hud_dynamic as h

pid = h.find_process_id(h.GAME_EXE)
mods = h.module_bases(pid, {h.ADDON_DLL.lower()})
base = mods.get(h.ADDON_DLL.lower(), 0)
print("pid=%d addon_base=0x%X" % (pid, base))
if base:
    mem = h.ProcessMem(pid, read_only=False)
    ga = h.GroupAccess(mem, base, 0)
    print("mode=%s rec0=0x%X state=%s" % (ga.mode, ga.rec0, ga.read_state()))
    print("enforce(0) ->", ga.enforce(0))
    print("state now:", ga.read_state())
    mem.close()
else:
    print("addon module not found")

"""probe57_inputmap.py - dump the live UInputSettings action mappings.

Finds the InputSettings object (CDO preferred) and scans its memory for
the ActionMappings TArray (FInputActionKeyMapping: FName action, bit flags,
FKey key). Prints every action -> key binding so we do not have to guess
the alt-fire / interact / melee keys.
"""
import struct
import time

import probe_lib as P

P.set_log(r"C:\Users\admin\AppData\Local\Temp\opencode\probe57.out")
P.say("=== probe57 input map %s ===" % time.strftime("%H:%M:%S"))
P.init()
P.build_names()
NCAP = len(P.IDS) + 1000

cdo = 0
other = 0
for obj, nm, cn, c in P.iter_objects():
    if nm == "Default__InputSettings":
        cdo = obj
    elif "InputSettings" in (cn or "") and not nm.startswith("Default__"):
        other = obj
P.say("InputSettings CDO=0x%X other=0x%X" % (cdo, other))
target = cdo or other
if not target:
    P.say("no InputSettings object found")
    raise SystemExit

data = P.rpm(target, 0x600)
found = 0
for off in range(0x28, 0x500, 4):
    ptr, num, mx = struct.unpack_from("<QII", data, off)
    if not (P.okp(ptr) and 10 <= num <= 2000 and num <= mx <= 4000):
        continue
    try:
        raw = P.rpm(ptr, num * 0x18 + 0x20)
    except OSError:
        continue
    ai, an = struct.unpack_from("<II", raw, 0)
    if an == 0 or ai >= NCAP:
        continue
    lines = []
    ok = True
    for stride in (0x14, 0x18):
        lines = []
        ok = True
        for i in range(num):
            base = i * stride
            ai, an = struct.unpack_from("<II", raw, base)
            if an == 0 or ai >= NCAP:
                ok = False
                break
            name = P.IDS.get(ai, "?")
            bits = raw[base + 8]
            ki, kn = struct.unpack_from("<II", raw, base + 12)
            key = P.IDS.get(ki, "?") if kn else "None"
            flags = []
            if bits & 1:
                flags.append("shift")
            if bits & 2:
                flags.append("ctrl")
            if bits & 4:
                flags.append("alt")
            if bits & 8:
                flags.append("cmd")
            lines.append("%-28s key=%-20s %s"
                         % (name, key, "+".join(flags) if flags else ""))
        if ok:
            break
    if not ok:
        continue
    found += 1
    P.say("ACTION MAP @+0x%X ptr=0x%X num=%d (stride 0x%X)"
          % (off, ptr, num, stride))
    for line in lines:
        P.say("  " + line)
P.say("found %d candidate arrays" % found)
P.say("done")

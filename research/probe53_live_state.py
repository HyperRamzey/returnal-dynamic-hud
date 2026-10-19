"""probe53_live_state.py - live trigger-signal survey.

- live player pawns (non-Default __*PlayerCharacter_C)
- objects whose Outer == chosen live pawn (component inventory)
- keyword props of the pawn class chain (weapon/gun/health/ammo/shield/...)
- BPC_PlayerAltFire_C instances: full known-field dump + hex window
- InteractionManagerComponent: class prop list, live instances + focus/selected
"""
import struct
import time

import probe_lib as P

P.set_log(r"C:\Users\admin\AppData\Local\Temp\opencode\probe53.out")
P.say("=== probe53 %s ===" % time.strftime("%Y-%m-%d %H:%M:%S"))
P.init()
P.build_names()

pawns = []
afacts = []
imcs = []
imc_cls = None
for obj, nm, cn, c in P.iter_objects():
    ch = P.chain_names(c)
    if "BPC_PlayerAltFire_C" in ch:
        afacts.append((obj, nm, cn))
    elif "InteractionManagerComponent" in ch and not nm.startswith("Default__"):
        imcs.append((obj, nm, cn))
    if nm == "InteractionManagerComponent" and cn == "Class":
        imc_cls = obj
    if cn.endswith("PlayerCharacter_C") and not nm.startswith("Default__"):
        pawns.append((obj, nm, cn))

P.say("pawns=%d afacts=%d imcs=%d imc_cls=0x%X"
      % (len(pawns), len(afacts), len(imcs), imc_cls or 0))
for obj, nm, cn in pawns[:14]:
    P.say("  PAWN 0x%X %s (%s)" % (obj, nm, cn))

KW = ("weapon", "gun", "health", "hp", "ammo", "shield", "integrity",
      "armor", "life", "altfire", "clip", "mag")
live = [p for p in pawns if p[2] == "BP_FirstPersonPlayerCharacter_C"] or pawns
if live:
    pawn, pnm, pcn = live[0]
    P.say("LIVE PAWN 0x%X %s (%s)" % (pawn, pnm, pcn))
    kids = []
    for obj, nm, cn, c in P.iter_objects():
        try:
            if P.u64(obj + 0x20) == pawn:
                kids.append((obj, nm, cn))
        except OSError:
            pass
    P.say("outer==pawn: %d" % len(kids))
    for obj, nm, cn in kids[:36]:
        P.say("    child 0x%X %s (%s)" % (obj, nm, cn))
    seen = set()
    for n, o, c in P.class_props(P.u64(pawn + 0x10)):
        low = n.lower()
        if not any(k in low for k in KW) or (n, o) in seen:
            continue
        seen.add((n, o))
        v = P.val8(pawn, o)
        if v is None:
            continue
        q, i, f, b = v
        tgt = ""
        if P.okp(q) and (q & 0xFFFF) == 0:
            tgt = " -> " + P.oname(q)
        P.say("    %s@%X Q=%X I=%d F=%.3f B=%d%s" % (n, o, q, i, f, b, tgt))

for obj, nm, cn in afacts:
    P.say("AF 0x%X %s (%s)" % (obj, nm, cn))
    try:
        outer = P.u64(obj + 0x20)
        owner = P.u64(obj + 0x130)
        P.say("    outer=0x%X(%s) +130=0x%X(%s) OwnerPlayer@280=0x%X(%s)"
              % (outer, P.oname(outer), owner, P.oname(owner),
                 P.u64(obj + 0x280), P.oname(P.u64(obj + 0x280))))
    except OSError:
        pass
    named = [(0x270, "bWants@270"), (0x271, "bModeActive@271"),
             (0x272, "bFiring@272"), (0x273, "bShotFired@273"),
             (0x274, "CurrentFuel@274"), (0x278, "CurrentAmmo@278"),
             (0x27C, "FuelState@27C"), (0x290, "CurSettings@290")]
    for off, label in named:
        v = P.val8(obj, off)
        if v is None:
            continue
        q, i, f, b = v
        P.say("    %s Q=%X I=%d F=%.4f B=%d" % (label, q, i, f, b))
    raw = [(0x320, "cooldownMode"), (0x324, "?"), (0x328, "fuelMax?"),
           (0x32C, "refillRate?"), (0x330, "?330"), (0x334, "?"),
           (0x338, "val338"), (0x33C, "val33C"), (0x340, "timerHandle"),
           (0x348, "readyFlag"), (0x34C, "?"), (0x368, "?"),
           (0x370, "?"), (0x378, "GEhandle?"), (0x3A0, "b3A0"),
           (0x3AE, "b3AE"), (0x3B0, "b3B0"), (0x3B4, "?")]
    for off, label in raw:
        v = P.val8(obj, off)
        if v is None:
            continue
        q, i, f, b = v
        P.say("    %s@%X Q=%X I=%d F=%.4f B=%d" % (label, off, q, i, f, b))
    try:
        d = P.rpm(obj + 0x2E0, 0x100)
        for i in range(0, 0x100, 16):
            P.say("      +%03X  %s" % (0x2E0 + i,
                                        " ".join("%02X" % x for x in d[i:i + 16])))
    except OSError as e:
        P.say("    hex fail %s" % e)

if imc_cls:
    pl = P.class_props(imc_cls)
    P.say("IMC props(%d): %s" % (len(pl),
          " ".join("%s@%X" % (n, o) for n, o, _ in pl)))

for obj, nm, cn in imcs:
    try:
        outer = P.u64(obj + 0x20)
    except OSError:
        continue
    P.say("IMC 0x%X %s (%s) outer=0x%X(%s)"
          % (obj, nm, cn, outer, P.oname(outer)))
    for n, o, c in P.class_props(P.u64(obj + 0x10)):
        low = n.lower()
        if not any(k in low for k in ("select", "focus", "mode", "interact",
                                      "radius", "current")):
            continue
        v = P.val8(obj, o)
        if v is None:
            continue
        q, i, f, b = v
        tgt = ""
        if P.okp(q) and (q & 0xFFFF) == 0 and q > 0x10000:
            tgt = " -> " + P.oname(q)
        P.say("    %s@%X Q=%X I=%d F=%.3f B=%d%s" % (n, o, q, i, f, b, tgt))
P.say("done")

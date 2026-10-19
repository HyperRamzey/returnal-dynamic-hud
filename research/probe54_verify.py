"""probe54_verify.py - verify class-global RVAs + pawn member offsets live.

  - hud_dynamic RVA_CLASS_* slots: read game+rva -> UClass* -> name
  - new slots: SayManagerComponent 0xF68F80, InteractionManagerComponent 0xF60D58
  - live pawn: find IMC + alt-fire component pointers and their pawn offsets
  - live SayManager instance via GObjects (class chain contains SayManager UClass)
  - gun slots -> clip/altfire chains + altfire-ready flag live value
"""
import struct
import time

import probe_lib as P

P.set_log(r"C:\Users\admin\AppData\Local\Temp\opencode\probe54.out")
P.say("=== probe54 %s ===" % time.strftime("%Y-%m-%d %H:%M:%S"))
P.init()
P.build_names()
game = P.GAME

SLOTS = [
    ("TOURISTPC", 0xF6F168), ("HEALTHCOMP", 0xF5FAF8),
    ("FOCUSCOMP", 0xF5EBE0), ("GUNBASE", 0xF5F330),
    ("WEAPONCLIP", 0xF679A8), ("ALTFIRE_tool", 0xF57B90),
    ("ALTFIRE_ida", 0xF57B98), ("TOURISTHUD", 0xF6EB10),
    ("SCREENMGR", 0xF6FED8), ("PAUSEMENU", 0xF64B88),
    ("SAYMANAGER", 0xF68F80), ("INTERACTCOMP", 0xF60D58),
]
cls_by_name = {}
for name, rva in SLOTS:
    try:
        ptr = P.u64(game + rva)
        nm = P.oname(ptr) if ptr else ""
        cls_by_name[name] = ptr
        P.say("SLOT %-14s @%X -> 0x%X %s" % (name, rva, ptr, nm))
    except OSError as e:
        P.say("SLOT %-14s @%X read fail %s" % (name, rva, e))

# ---- pawn ----
pawn = 0x13FF10000
try:
    if P.oname(P.u64(pawn + 0x10)) != "BP_PlayerCharacter_C":
        pawn = 0
except OSError:
    pawn = 0
if not pawn:
    for obj, nm, cn, c in P.iter_objects():
        if cn == "BP_PlayerCharacter_C" and not nm.startswith("Default__"):
            pawn = obj
            break
P.say("pawn=0x%X" % pawn)

if pawn:
    try:
        data = P.rpm(pawn, 0x2800)
    except OSError as e:
        data = None
        P.say("pawn read fail %s" % e)
    if data:
        for label, t in (("IMC", 0x15C8DF100), ("AF_live", 0x3C8CC5B50),
                         ("GUN1?", 0), ("HEALTH?", 0x1325EF020)):
            if not t:
                continue
            hits = [i for i in range(0, len(data) - 7, 8)
                    if struct.unpack_from("<Q", data, i)[0] == t]
            P.say("  pawn qword %-8s 0x%X at %s" % (label, t,
                                                    [hex(x) for x in hits]))
    for off in (0x1028, 0x1040):
        try:
            p = P.u64(pawn + off)
            P.say("  pawn+%X -> 0x%X %s" % (off, p, P.oname(p) if p else ""))
            if p:
                af = P.u64(p + 0xC80)
                cl = P.u64(p + 0x908)
                P.say("     gun+0xC80 -> 0x%X %s" % (af, P.oname(af) if af else ""))
                P.say("     gun+0x908 -> 0x%X %s" % (cl, P.oname(cl) if cl else ""))
                if af:
                    v = P.val8(af, 0x348)
                    P.say("     altfire+0x348 = %s ; +271=%s +272=%s +27C=%s"
                          % (v, P.val8(af, 0x271), P.val8(af, 0x272),
                             P.val8(af, 0x27C)))
        except OSError as e:
            P.say("  pawn+%X fail %s" % (off, e))

# ---- SayManager instance ----
saycls = cls_by_name.get("SAYMANAGER", 0)
if saycls:
    found = 0
    for obj, nm, cn, c in P.iter_objects():
        try:
            if any(x[0] == saycls for x in P.chain(c)):
                found += 1
                num = P.u32(obj + 0x1C8)
                mx = P.u32(obj + 0x1CC)
                P.say("SAY 0x%X %s (%s) outer=0x%X(%s) num=%d max=%d"
                      % (obj, nm, cn, P.u64(obj + 0x20),
                         P.oname(P.u64(obj + 0x20)), num, mx))
                if found > 3:
                    break
        except OSError:
            pass
    if not found:
        P.say("SAY: no instance found")
P.say("done")

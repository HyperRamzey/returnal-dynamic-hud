# Process journal — how this tool was built

A record of the reverse-engineering and engineering process, so the findings
can be re-derived and extended. Everything here was done on the live
shipping game with **read-only** memory probes first; the only writer in the
project is `hud_dynamic.py` itself (one ShaderToggler toggle byte).

## Tooling

- Python 3 (stdlib only — `ctypes` ReadProcessMemory) for live probing.
- IDA Pro for static analysis and class-name recovery.
- `hud_dynamic.py --selftest` (61 offline checks) as the regression gate.
- `--dry-run` / `--calibrate` modes for live validation without any writes.

## The probe series

Each probe is a small read-only script answering one question. The ones
worth keeping are shipped in `research/` (index in `research/README.md`).

| probe | question | outcome |
|---|---|---|
| probe1–6 | where is the object array / can classes be resolved / enemy states | GUObjectArray via game DLL IAT `0x8A15B0`; class chains; enemy aggression states |
| probe7–8 | can FName be decoded? | no reliable pool anchor; abandoned (class chains suffice) |
| probe9–10 | player member chain | PC -> pawn -> health/focus/guns -> clip |
| probe11 | live watcher, session A (menus/aim) | signal table for aim/menus; screen stack first observed (persistent `UTouristTutorialPanel` entry) |
| probe12 | live watcher, session B (firing) | ammo float 12->0, reload byte, refill ramp |
| probe13 | stack entry + live instance inventory | entry+16 = object InternalIndex; UPauseMenu entries confirmed |
| probe14–15 | module scan for class-global slots | UMG / CoreUObject / HMQ class globals found + live-validated |
| probe16–18 | tutorial-banner class hunt + raw entry dump | entries are `{pad, pad, u32 main@16, u32 aux@20}`; banner entry object = `UOverlaySlot` instance; UMG class names recovered via IDA |
| probe19 | v1.3.0 stack classification live check | pause entry classified correctly; no false layers while in menus |

## Engineering milestones

1. **Actuation** — ShaderToggler addon reversed in IDA: records vector +
   toggle byte. Direct byte writes replaced any key simulation; "no keyboard
   injection" became a hard design rule.
2. **Detection** — `CombatDetector` (enemy states) + `PlayerTracker` (hp,
   ammo, reload, aim, alt-fire, menus, UI events) with guarded reads; an
   unknown state holds the previous decision instead of guessing.
3. **Hold windows** — every trigger keeps the HUD up for its window,
   refreshed on each change (a burst of fire keeps it up); combat leaves
   after `--exit-delay` seconds of no aggression.
4. **Menu safety (top requirement)** — menu-open count (`HUD+0x4BC`) plus
   UPauseMenu stack entries force the HUD visible and disable hiding
   completely, in both directions, `--invert` included.
5. **UI events** — a tail scan of the GUObjectArray for newly created
   watched UI objects (tutorial/notification/subtitle classes) plus screen
   stack changes raise a 6 s window (best effort).
6. **v1.3.0 — sustained screen layers** — the 2026-10-18 regression analysis
   (below) showed the tutorial banner living ~30 s: the 6 s window expired
   while the banner was still up, so the HUD hid mid-banner and left
   "backgrounds" (shaders outside the toggled set). Fix: classify screen
   stack entries (pause / tutorial-panel shell / anything else = "layer")
   and hold the HUD visible *while a layer is present*, with no window
   expiry. The tutorial-panel shell is deliberately classified benign so
   hiding keeps working in tutorial zones where the stack always carries it.
   `--no-stack-layers` opts out.

## The 2026-10-18 regression analysis (tutorial banner + subtitles)

**Symptom 1: "tutorials leave backgrounds."** Log evidence from the live
run: a stack entry appeared 21:53:12; the HUD hid at 21:53:20 while the
banner was still up. The banner text is drawn with a shader inside Group0
(blocked) while its background uses other shaders (not blocked) — leftover
boxes. The stack entry itself resolved to a `UOverlaySlot` instance (the
prompt animates via its slot), which is exactly the "layer" case.
Fix (v1.3.0): sustained layer visibility — no window expiry while the layer
is present. Live-verified: pause entries classify as menu, no false layers.

**Symptom 2: "subtitles disappear when the HUD is hidden (they appear if I
zoom in)."** Zoom = HUD visible, so subtitle text uses a shader that Group0
blocks. The desired end state — subtitles appear by themselves, *only* the
subtitles — requires the subtitle shader hash to be removed from Group0 in
`ShaderToggler.ini`: a one-time in-game shader hunt (procedure in
`docs/SHADERTOGGLER.md`). If the subtitle shader turns out to be the shared
"all HUD text" hash, shader-level separation is impossible and the fallback
is a UI-event trigger (whole HUD shows while a subtitle line is up).
Open item — needs one play session with the watcher running.

## Verification gates

| gate | what it proves |
|---|---|
| `--selftest` | pure logic + fake-memory discovery paths (61 checks, no game needed) |
| `--dry-run` live session | detection correct, nothing written |
| `--calibrate` live session | field-level signal dump against player actions |
| live acceptance runs | user plays; logs + user report confirm behavior |
| read-only probes (`probe*`) | every offset claim re-checked live |
| single-writer discipline | exactly one tool instance writes the toggle byte at a time |

## Lessons learned

- Module RVAs are stable; the heap is per-launch. Never cache heap pointers.
- The GUObjectArray item has no class field — read the class from the object
  (`+0x10`). A whole probe round was lost to reading item+16 instead.
- InternalIndex is never reused: a resolvable index pointing at a destroyed
  slot just means the object was garbage-collected.
- The screen stack is the game's UI-layer list, not a widget inventory;
  entries can be widgets *or* slots (slot-animated prompts!).
- The tool cannot change *which* pixels are blocked: that is fully determined
  by the ShaderToggler ini group composition. All partial-hiding artifacts
  (leftover backgrounds, surviving crosshair) are ini-scope issues.
- UI frameworks on this build: widget classes live in the UMG module, game
  UI subclasses in HMQScreen (`UHMQUserWidget` -> `UHMQScreenWidget`), and
  game screens on top of those. Names were only recoverable through IDA
  xrefs of `Z_Construct_UClass_*` referencing the `.data` slots.

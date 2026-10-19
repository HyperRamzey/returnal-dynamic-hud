# Research probes

Read-only scripts used to reverse-engineer and verify every offset in
`docs/FINDINGS.md`. They are kept for reproducibility: each one ran against
the live game process and printed the evidence that is quoted in the docs.

| file | purpose |
|---|---|
| `probe1.py` .. `probe6.py` | early discovery rounds: object array, class resolution, enemy-manager state machine |
| `probe7.py` / `probe8.py` | FName pool attempts (dead end — class chains made it unnecessary) |
| `probe9.py` / `probe10.py` | player member-chain discovery (PC -> pawn -> components) |
| `probe11_livespy.py` + `probe11.out` | live watcher session A: signal table vs user actions (menus/aim) |
| `probe12_livespy.py` + `probe12.out` | live watcher session B: firing; ammo/reload correlation |
| `probe13_findings.py` | screen-stack entry decode + live class inventory |
| `probe14_findglobals.py` | module scan for class-global slots |
| `probe15_modscan.py` | UMG/CoreUObject/HMQ class-global resolution |
| `probe16_banner.py` | tutorial-banner class hunt (contains a known item-offset bug; superseded by probe18) |
| `probe17_stack.py` | raw stack dump attempt (same bug; superseded) |
| `probe18_stack.py` | definitive raw stack entry dump: entry = {pad, pad, u32 main@16, u32 aux@20} |
| `probe19_live_stack.py` | v1.3.0 stack classification live verification |
| `probe20_subwatch.py` | subtitle/UI watcher: run while playing to pin a "subtitle active" signal |
| `probe50_saywatch.py` + `probe50.out` | subtitle cue chain: `SayManager` queue (`+0x1C8`), live SayHUD row walk, inter-line gaps |
| `probe51_classdump.py` + `probe51.out` | class-global dump: `USayManagerComponent` / `UInteractionManagerComponent` slots |
| `probe52_playercomps.py` + `probe52.out` | pawn component sweep: IMC at `pawn+0x820` |
| `probe53_live_state.py` + `probe53.out` | combined live state dump of the v1.4 signals |
| `probe54_verify.py` + `probe54.out` | v1.4 offset verification pass (fresh launch) |
| `probe56_signalwatch.py` + `probe56.out` | windowed signal watcher; G-key alt-fire discovery |
| `probe57_inputmap.py` + `probe57.out` | alt-fire input-map scan (dead end - no candidate arrays) |
| `ahk_key.ahk` / `ahk_mouse.ahk` / `ahk_click.ahk` | AutoHotkey v2 input helpers used to drive the live verification |
| `live_run4.out` | v1.4.0 acceptance-run log (subtitle / interaction / alt-ready session, 2026-10-19) |
| `show_hud.py` | one-shot: force the HUD visible again (restores group byte 0) |
| `live_run1.out` / `live_run2.out` / `live_run3.out` | acceptance-run logs (user sessions; v1.1 / v1.2 / v1.3) |
| `probe_sessions.py` / `probeproof_run.py` | earlier session/proof harness scripts |

Notes:

- All probes are **read-only**; none of them write process memory. The only
  writer in this project is `hud_dynamic.py` itself (one addon toggle byte).
- Probe scripts import `hud_dynamic` from the game directory (`sys.path`
  tweak at the top) so they share the live-verified offsets/readers.
- The `.out` files are raw session logs, kept as the original evidence for
  the signal tables in `docs/FINDINGS.md`.

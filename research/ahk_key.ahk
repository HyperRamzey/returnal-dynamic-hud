#Requires AutoHotkey v2.0
; ahk_key.ahk KEY (tap|down|up) [hold_ms]
; Sends to the foreground window (SendInput semantics).
key := A_Args[1]
mode := A_Args.Length >= 2 ? A_Args[2] : "tap"
if (mode = "down") {
    Send("{" key " down}")
} else if (mode = "up") {
    Send("{" key " up}")
} else {
    hold := A_Args.Length >= 3 ? Integer(A_Args[3]) : 60
    Send("{" key " down}")
    Sleep hold
    Send("{" key " up}")
}

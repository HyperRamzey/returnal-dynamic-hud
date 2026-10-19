#Requires AutoHotkey v2.0
; ahk_mouse.ahk move DX DY | hold L|R|M [ms] | click L|R|M
; Relative mouse move for in-game camera steering + button holds.
mode := A_Args[1]
if (mode = "move") {
    MouseMove(Integer(A_Args[2]), Integer(A_Args[3]), 0, "R")
} else if (mode = "hold") {
    btn := A_Args[2]
    Send("{" btn "Button down}")
    Sleep Integer(A_Args[3])
    Send("{" btn "Button up}")
} else if (mode = "click") {
    Send("{" A_Args[2] "Button}")
}

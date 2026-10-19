#Requires AutoHotkey v2.0
; ahk_click.ahk X Y [L|R|M] - move the cursor to screen X,Y then click.
x := Integer(A_Args[1])
y := Integer(A_Args[2])
btn := A_Args.Length >= 3 ? A_Args[3] : "L"
MouseMove(x, y, 0)
Sleep 120
Send("{" btn "Button}")

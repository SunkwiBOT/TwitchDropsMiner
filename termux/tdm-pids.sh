#!/system/bin/sh
# Shared PID discovery for the TwitchDropsMiner service.
# Reads /proc cmdlines instead of grepping `ps`, and never matches this script
# itself (only supervise.sh and the exact $APP/run.py are candidates).
our_pids() {
    for d in /proc/[0-9]*; do
        pid=${d#/proc/}
        [ -r "$d/cmdline" ] || continue
        cmd=$(tr '\0' ' ' < "$d/cmdline" 2>/dev/null) || continue
        case "$cmd" in
            *"$APP/termux/supervise.sh"*|*"$APP/run.py"*) echo "$pid" ;;
        esac
    done
}

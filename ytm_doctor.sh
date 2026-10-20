#!/usr/bin/env bash
# Diagnóstico de yt/ytm en Termux (Android)
# Uso: bash ytm_doctor.sh
set +e

YT_BIN="$HOME/.local/bin/yt"
YTM_BIN="$HOME/.local/bin/ytm"

echo "══════════════════════════════════════════"
echo "  DIAGNÓSTICO yt/ytm — Termux"
echo "══════════════════════════════════════════"

echo ""
echo "── Entorno ──"
echo "HOME: $HOME"
echo "PATH: $PATH"
echo "TERM: ${TERM:-?}"
echo "Termux: ${TERMUX_VERSION:-no detectado}"
echo "TTY stdin:  $([[ -t 0 ]] && echo sí || echo NO)"
echo "TTY stdout: $([[ -t 1 ]] && echo sí || echo NO)"

echo ""
echo "── Dependencias ──"
for dep in bash python3 yt-dlp fzf mpv jq md5sum stat find seq timeout node; do
    if command -v "$dep" >/dev/null 2>&1; then
        printf "  [OK]    %-8s %s\n" "$dep" "$(command -v "$dep")"
    else
        printf "  [FALTA] %s\n" "$dep"
    fi
done

echo ""
echo "── Versiones ──"
yt-dlp --version 2>&1 | head -1
mpv --version 2>&1 | head -1
fzf --version 2>&1 | head -1
jq --version 2>&1 | head -1
python3 --version 2>&1

echo ""
echo "── Scripts instalados ──"
for f in yt ytm yt_control.py ytm_control.py mpv_client.py exit_codes.py ytm_mcp.py; do
    if [[ -e "$HOME/.local/bin/$f" ]]; then
        ls -l "$HOME/.local/bin/$f"
    else
        echo "  [FALTA] $HOME/.local/bin/$f"
    fi
done

echo ""
echo "── Prueba yt-dlp (15 s) ──"
timeout 15 yt-dlp --flat-playlist --dump-json --ignore-errors "ytsearch1:test" 2>&1 | head -3

echo ""
echo "── Prueba ytm -l (sin TTY, 40 s) ──"
timeout 40 "$YTM_BIN" -l -n 3 "test" </dev/null 2>&1 | head -20

echo ""
echo "── Última canción / logs ──"
echo "[last_song]"
cat "$HOME/.cache/ytm/last_song" 2>/dev/null || echo "(sin last_song)"
echo "[events.log]"
tail -15 "$HOME/.cache/ytm/events.log" 2>/dev/null || echo "(sin events.log)"

echo ""
echo "── Recomendaciones ──"
command -v fzf     >/dev/null || echo "  pkg install fzf"
command -v mpv     >/dev/null || echo "  pkg install mpv"
command -v jq      >/dev/null || echo "  pkg install jq"
command -v yt-dlp  >/dev/null || echo "  pkg install yt-dlp"
command -v node    >/dev/null || echo "  (opcional) pkg install nodejs   # extracción más fiable"
command -v md5sum  >/dev/null || echo "  pkg install coreutils"
command -v find    >/dev/null || echo "  pkg install findutils"
if [[ ! -x "$YTM_BIN" ]]; then
    echo "  chmod +x $YTM_BIN $YT_BIN"
fi
if [[ ! -t 0 || ! -t 1 ]]; then
    echo "  Ejecuta ytm en una sesión interactiva de Termux (fzf necesita TTY)"
fi
echo ""
echo "══════════════════════════════════════════"

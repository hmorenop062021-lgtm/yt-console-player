#!/usr/bin/env bash
# ══════════════════════════════════════════════════════════════════════
#  BATERÍA DE PRUEBAS QA — yt / ytm (YouTube Console Player)
#  Ejecutar: bash yt_qa_battery.sh
#  Requiere: yt-dlp, fzf, mpv, jq, python3, bc en PATH
# ══════════════════════════════════════════════════════════════════════
BIN="$HOME/.local/bin"
PASS=0; FAIL=0; WARN=0

ok()   { PASS=$((PASS+1)); echo "  [PASS] $1"; }
fail() { FAIL=$((FAIL+1)); echo "  [FAIL] $1"; }
warn() { WARN=$((WARN+1));  echo "  [WARN ] $1"; }

echo "══════════════════════════════════════════════════════════════════════"
echo "  BATERÍA QA yt/ytm"
echo "══════════════════════════════════════════════════════════════════════"
echo ""

# ═════════════════════════════════════════════════════════════════════
# 1. SINTAXIS ESTÁTICA
# ══════════════════════════════════════════════════════════════════════
echo "━━━ 1. SINTAXIS ESTÁTICA ━━━"
for f in "$BIN/yt" "$BIN/ytm"; do
    if bash -n "$f" 2>/dev/null; then ok "bash -n $(basename "$f")"; else fail "bash -n $(basename "$f")"; fi
done
for f in "$BIN/yt_control.py" "$BIN/ytm_control.py" "$BIN/mpv_client.py"; do
    if python3 -m py_compile "$f" 2>/dev/null; then ok "py_compile $(basename "$f")"; else fail "py_compile $(basename "$f")"; fi
done
echo ""

# ═════════════════════════════════════════════════════════════════════
# 2. CLI NO INTERACTIVA (no requiere TTY)
# ══════════════════════════════════════════════════════════════════════
echo "━━━ 2. CLI NO INTERACTIVA ━━━"

# 2.1 --help
out=$(timeout 15 "$BIN/yt" --help 2>&1); rc=$?
if [[ $rc -eq 0 && "$out" == *"Uso:"* ]]; then ok "yt --help (rc=0)"; else fail "yt --help (rc=$rc)"; fi
out=$(timeout 15 "$BIN/ytm" --help 2>&1); rc=$?
if [[ $rc -eq 0 && "$out" == *"USO:"* ]]; then ok "ytm --help (rc=0)"; else fail "ytm --help (rc=$rc)"; fi

# 2.2 -l (listar) canciones
out=$(timeout 25 "$BIN/ytm" -l metallica </dev/null 2>&1); rc=$?
if [[ $rc -eq 0 && "$out" == *"Resultados: metallica"* ]]; then ok "ytm -l metallica (rc=0, lista canciones)"; else fail "ytm -l metallica (rc=$rc)"; fi

# 2.3 -l -a (listar álbumes)
out=$(timeout 30 "$BIN/ytm" -l -a metallica </dev/null 2>&1); rc=$?
if [[ $rc -eq 0 && "$out" == *"Resultados: metallica"* ]]; then ok "ytm -l -a metallica (rc=0, lista álbumes)"; else fail "ytm -l -a metallica (rc=$rc)"; fi

# 2.4 -l -p (listar playlists)
out=$(timeout 30 "$BIN/ytm" -l -p metallica </dev/null 2>&1); rc=$?
if [[ $rc -eq 0 && "$out" == *"Resultados: metallica"* ]]; then ok "ytm -l -p metallica (rc=0, lista playlists)"; else fail "ytm -l -p metallica (rc=$rc)"; fi

# 2.5 -n sin argumento → error limpio, no crash
out=$(timeout 10 "$BIN/ytm" -n 2>&1); rc=$?
if [[ $rc -ne 0 && "$out" == *"requiere un número"* ]]; then ok "ytm -n sin arg (error limpio rc=$rc)"; else fail "ytm -n sin arg (rc=$rc, out=$out)"; fi

# 2.6 -c con valor no numérico → error limpio
out=$(timeout 10 "$BIN/ytm" -c abc 2>&1); rc=$?
if [[ $rc -ne 0 && "$out" == *"requiere un número"* ]]; then ok "ytm -c abc (error limpio rc=$rc)"; else fail "ytm -c abc (rc=$rc)"; fi

# 2.7 yt -n sin argumento → error limpio
out=$(timeout 10 "$BIN/yt" -n 2>&1); rc=$?
if [[ $rc -ne 0 && "$out" == *"requiere un número"* ]]; then ok "yt -n sin arg (error limpio rc=$rc)"; else fail "yt -n sin arg (rc=$rc)"; fi

# 2.8 yt --list-formats con URL inválida → error controlado
out=$(timeout 20 "$BIN/yt" -F "https://youtube.com/watch?v=invalido123" 2>&1); rc=$?
if [[ $rc -ne 0 ]]; then ok "yt -F URL inválida (rc=$rc, sin crash)"; else warn "yt -F URL inválida (rc=$rc, revisar)"; fi
echo ""

# ══════════════════════════════════════════════════════════════════════
# 3. PRUEBAS DE UNIDAD DE FUNCIONES BASH (extraídas del fuente)
# ══════════════════════════════════════════════════════════════════════
echo "━━━ 3. UNIT TESTS FUNCIONES BASH ━━━"
T=/tmp/yt_qa_tmp; rm -rf "$T"; mkdir -p "$T"

# 3.1 get_cached_file sin caché → rc 1
bash -c "source <(sed -n '/^get_cached_file()/,/^}/p' $BIN/yt); CACHE_MEDIA_DIR=/nonexistent get_cached_file 'https://youtube.com/watch?v=abcdefghijk'; echo \$?" > "$T/gcf.out" 2>&1
if [[ "$(cat "$T/gcf.out")" == "1" ]]; then ok "get_cached_file vacío → rc 1"; else fail "get_cached_file vacío (out=$(cat $T/gcf.out))"; fi

# 3.2 prune_cache: 60 archivos, 5 vencidos → quedan 50, vencidos borrados, sin stderr
for i in $(seq 1 60); do touch "$T/f$i.webm"; done
touch -d "3 days ago" "$T"/f[1-5].webm
export CACHE_MEDIA_DIR="$T" CACHE_TTL=86400
stderr=$(bash -c "source <(sed -n '/^prune_cache()/,/^}/p' $BIN/ytm); prune_cache" 2>&1 >/dev/null)
remaining=$(ls "$T" | wc -l)
old_remaining=$(ls "$T" | grep -c -E 'f[1-5]\.webm' || true)
if [[ "$remaining" -eq 50 && "$old_remaining" -eq 0 && -z "$stderr" ]]; then
    ok "prune_cache: 60→50, vencidos borrados, sin stderr"
else
    fail "prune_cache: quedan=$remaining vencidos=$old_remaining stderr=[$stderr]"
fi

# 3.3 PLAY_COUNT truncación (0 = ilimitado, >0 recorta)
bash -c 'urls=(a b c d e); start_idx=1; PLAY_COUNT=2;
if [[ "${PLAY_COUNT:-0}" -gt 0 && "${#urls[@]}" -gt $(( start_idx + PLAY_COUNT )) ]]; then
    urls=("${urls[@]:0:$(( start_idx + PLAY_COUNT ))}");
fi
echo "${urls[*]}"' > "$T/pc.out"
if [[ "$(cat "$T/pc.out")" == "a b c" ]]; then ok "PLAY_COUNT=2 desde índice 1 → a b c"; else fail "PLAY_COUNT truncación (out=$(cat $T/pc.out))"; fi

# 3.4 PLAY_COUNT=0 no trunca
bash -c 'urls=(a b c); start_idx=0; PLAY_COUNT=0;
if [[ "${PLAY_COUNT:-0}" -gt 0 && "${#urls[@]}" -gt $(( start_idx + PLAY_COUNT )) ]]; then
    urls=("${urls[@]:0:$(( start_idx + PLAY_COUNT ))}");
fi
echo "${urls[*]}"' > "$T/pc2.out"
if [[ "$(cat "$T/pc2.out")" == "a b c" ]]; then ok "PLAY_COUNT=0 → sin truncar (a b c)"; else fail "PLAY_COUNT=0 (out=$(cat $T/pc2.out))"; fi
echo ""

# ══════════════════════════════════════════════════════════════════════
# 4. CONTROLADORES PYTHON (sin mpv → no deben crashear, rc esperados)
# ══════════════════════════════════════════════════════════════════════
echo "━━━ 4. CONTROLADORES (sin mpv / socket inexistente) ━━━"

# 4.1 ytm_control.py sin socket → debe salir rc=1 (error conexión), no traceback
timeout 12 python3 "$BIN/ytm_control.py" /tmp/yt_qa_noexiste.sock 424242 </dev/null > "$T/ytmc.out" 2>&1; rc=$?
if [[ $rc -eq 1 && ! "$(cat "$T/ytmc.out")" == *"Traceback"* ]]; then
    ok "ytm_control.py socket inexistente → rc=1 (error conexión), sin traceback"
else
    fail "ytm_control.py socket inexistente → rc=$rc out=$(head -3 $T/ytmc.out)"
fi

# 4.2 yt_control.py con pid muerto → debe salir rc=1 (error conexión), no traceback
timeout 8 python3 "$BIN/yt_control.py" /tmp/yt_qa_noexiste.sock 999999 </dev/null > "$T/ytc.out" 2>&1; rc=$?
if [[ $rc -eq 1 && ! "$(cat "$T/ytc.out")" == *"Traceback"* ]]; then
    ok "yt_control.py pid muerto → rc=1 (error conexión), sin traceback"
else
    fail "yt_control.py pid muerto → rc=$rc out=$(head -3 $T/ytc.out)"
fi

# 4.2b yt_control.py con pid VIVO pero socket inexistente → rc=1 (no bucle 100% CPU)
timeout 12 python3 "$BIN/yt_control.py" /tmp/yt_qa_noexiste2.sock $$ </dev/null > "$T/ytc2.out" 2>&1; rc=$?
if [[ $rc -eq 1 && ! "$(cat "$T/ytc2.out")" == *"Traceback"* ]]; then
    ok "yt_control.py pid vivo + socket ausente → rc=1 (sin bucle)"
else
    fail "yt_control.py pid vivo + socket ausente → rc=$rc (posible bucle)"
fi

# 4.3 los controladores registran en LOG_FILE (versión + motivo del fallo)
TL=$(mktemp)
LOG_FILE="$TL" timeout 8 python3 "$BIN/ytm_control.py" /tmp/yt_qa_noexiste.sock 424242 </dev/null >/dev/null 2>&1
if grep -q 'connection failed' "$TL" && grep -q 'v1\.0\.0' "$TL"; then ok "ytm_control registra versión+fallo en LOG_FILE"; else fail "ytm_control no registra en LOG_FILE"; fi
rm -f "$TL"
rm -rf "$T"
echo ""

# ══════════════════════════════════════════════════════════════════════
# 5. TABLA DE TECLAS (verificación estática de bindings)
# ══════════════════════════════════════════════════════════════════════
echo "━━━ 5. TABLA DE TECLAS (bindings estáticos) ━━━"

# Escape debe salir rc=0 (volver al menú), no rc=1
grep -E 'key in \(\s*"q",\s*"Q",\s*"\\x1b"\s*\)' "$BIN/ytm_control.py" >/dev/null && ok "ytm_control: Esc/q → salida rc=0 (menú)" || fail "ytm_control: Esc/q no mapeado a rc=0"
grep -E 'key in \(\s*"q",\s*"Q",\s*"\\x1b"\s*\)' "$BIN/yt_control.py" >/dev/null && ok "yt_control: Esc/q → salida rc=0 (menú)" || fail "yt_control: Esc/q no mapeado a rc=0"

# s/m/a/l deben devolver códigos de nueva búsqueda (10-13)
grep -Eq 'sys\.exit\((10|EXIT_SEARCH_SONGS)\)' "$BIN/ytm_control.py" >/dev/null && ok "ytm_control: 's' → exit 10 (canciones)" || fail "ytm_control: 's' no mapeado a 10"
grep -Eq 'sys\.exit\((12|EXIT_SEARCH_ALBUMS)\)' "$BIN/ytm_control.py" >/dev/null && ok "ytm_control: 'a' → exit 12 (álbumes)" || fail "ytm_control: 'a' no mapeado a 12"
grep -Eq 'sys\.exit\((13|EXIT_SEARCH_PLAYLISTS)\)' "$BIN/ytm_control.py" >/dev/null && ok "ytm_control: 'l' → exit 13 (playlists)" || fail "ytm_control: 'l' no mapeado a 13"

# n/b deben enviar playlist-next / playlist-prev
grep -q 'playlist-next' "$BIN/ytm_control.py" && ok "ytm_control: 'n' usa playlist-next" || fail "ytm_control: 'n' no usa playlist-next"
grep -q 'playlist-prev' "$BIN/ytm_control.py" && ok "ytm_control: 'b' usa playlist-prev" || fail "ytm_control: 'b' no usa playlist-prev"

# 'l' NO debe aparecer en binding de flecha derecha (conflicto histórico resuelto)
if grep -E 'key in \(\s*"\\x1b\[C",\s*"l"' "$BIN/ytm_control.py" >/dev/null; then
    fail "ytm_control: 'l' aún conflictúa con flecha derecha"
else
    ok "ytm_control: 'l' liberado para playlists (sin conflicto con flecha derecha)"
fi
echo ""

# Limpieza temporal
rm -rf "$T" 2>/dev/null || true
unset CACHE_MEDIA_DIR CACHE_TTL

# ══════════════════════════════════════════════════════════════════════
# 6. FUNCIONES BASH (source selectivo de yt/ytm)
# ══════════════════════════════════════════════════════════════════════
echo "━━━ 6. FUNCIONES BASH (source selectivo) ━━━"

# 6.1 resolve_format (yt)
_rf() { bash -c "source <(sed -n '/^resolve_format()/,/^}/p' '$BIN/yt'); resolve_format \"$1\""; }
[[ "$(_rf best)"  == "bestvideo+bestaudio/best" ]] && ok "resolve_format best" || fail "resolve_format best → $(_rf best)"
[[ "$(_rf audio)" == "bestaudio/best" ]] && ok "resolve_format audio" || fail "resolve_format audio → $(_rf audio)"
[[ "$(_rf mp3)"   == "bestaudio/best" ]] && ok "resolve_format mp3 → audio" || fail "resolve_format mp3"
[[ "$(_rf 720)"   == *"height<=720"* ]] && ok "resolve_format 720" || fail "resolve_format 720 → $(_rf 720)"
[[ "$(_rf 720p)"  == *"height<=720"* ]] && ok "resolve_format 720p" || fail "resolve_format 720p"
[[ "$(_rf 4k)"    == *"height<=2160"* ]] && ok "resolve_format 4k" || fail "resolve_format 4k"
[[ "$(_rf mp4)"   == *"ext=mp4"* ]] && ok "resolve_format mp4" || fail "resolve_format mp4"
[[ "$(_rf raro)"  == "raro" ]] && ok "resolve_format desconocido → passthrough" || fail "resolve_format passthrough → $(_rf raro)"

# 6.2 resolve_eq (yt)
_rq() { bash -c "source <(sed -n '/^declare -A EQ_PRESETS/,/^}/p' '$BIN/yt'); resolve_eq \"$1\""; }
[[ -z "$(_rq flat)" ]] && ok "resolve_eq flat → sin filtro" || fail "resolve_eq flat → $(_rq flat)"
[[ "$(_rq bass)" == --af=equalizer=* ]] && ok "resolve_eq bass → --af=..." || fail "resolve_eq bass → $(_rq bass)"
[[ -z "$(_rq nope 2>/dev/null)" ]] && ok "resolve_eq desconocido → stdout vacío" || fail "resolve_eq desconocido stdout"
{ _rq nope 2>&1 >/dev/null; } | grep -q "desconocido" && ok "resolve_eq desconocido → aviso stderr" || warn "resolve_eq desconocido sin aviso stderr"

# 6.3 get_cached_file (ytm): id plano, URLs, vencido, .part
GC=$(mktemp -d)
_gcf() { bash -c "CACHE_MEDIA_DIR='$GC' CACHE_TTL=86400; source <(sed -n '/^get_cached_file()/,/^}/p' '$BIN/ytm'); get_cached_file \"$1\""; }
touch "$GC/abc123.webm"
[[ "$(_gcf abc123)" == "$GC/abc123.webm" ]] && ok "get_cached_file id plano → ruta" || fail "get_cached_file id plano"
[[ "$(_gcf 'https://youtu.be/abc123')" == "$GC/abc123.webm" ]] && ok "get_cached_file youtu.be/ID" || fail "get_cached_file youtu.be/ID"
[[ "$(_gcf 'https://www.youtube.com/watch?v=abc123')" == "$GC/abc123.webm" ]] && ok "get_cached_file watch?v=ID" || fail "get_cached_file watch?v=ID"
touch "$GC/viejo1.mp4"; touch -d "3 days ago" "$GC/viejo1.mp4"
_gcf viejo1 >/dev/null && fail "get_cached_file debe descartar archivo vencido" || ok "get_cached_file archivo vencido → rc!=0"
touch "$GC/par1.webm.part"
_gcf par1 >/dev/null && fail "get_cached_file debe ignorar .part" || ok "get_cached_file ignora .part"
rm -rf "$GC"

# 6.4 prune_cache: carpeta vacía no falla ni emite stderr
GE=$(mktemp -d)
outp=$(bash -c "CACHE_MEDIA_DIR='$GE' source <(sed -n '/^prune_cache()/,/^}/p' '$BIN/ytm'); prune_cache" 2>&1); rcp=$?
[[ $rcp -eq 0 && -z "$outp" ]] && ok "prune_cache carpeta vacía → rc=0 sin error" || fail "prune_cache vacía rc=$rcp [$outp]"
rm -rf "$GE"

# 6.5 Sin drift: funciones compartidas idénticas en yt y ytm
for fn in get_cached_file prune_cache; do
    a=$(sed -n "/^$fn()/,/^}/p" "$BIN/yt"); b=$(sed -n "/^$fn()/,/^}/p" "$BIN/ytm")
    [[ "$a" == "$b" ]] && ok "$fn idéntica en yt y ytm" || warn "$fn difiere entre yt y ytm (drift)"
done
echo ""

# ══════════════════════════════════════════════════════════════════════
# 7. CLI: errores de argumentos y salidas tempranas
# ══════════════════════════════════════════════════════════════════════
echo "━━━ 7. CLI OPCIONES (argumentos/errores) ━━━"
_chk_err() {
    local desc="$1" pat="$2"; shift 2
    local out; out=$(timeout 10 "$@" </dev/null 2>&1); local rc=$?
    if [[ $rc -eq 1 && "$out" == *"$pat"* ]]; then ok "$desc → rc=1 con aviso"
    else fail "$desc → rc=$rc out=$(printf '%s' "$out" | head -1)"; fi
}
_chk_err "yt -f sin arg"         "requiere formato"    "$BIN/yt"  -f
_chk_err "yt -s sin arg"         "requiere código"     "$BIN/yt"  -s
_chk_err "yt -S sin arg"         "requiere un factor"  "$BIN/yt"  -S
_chk_err "yt -e sin preset"      "Ecualizadores"       "$BIN/yt"  -e
_chk_err "ytm -f sin arg"        "requiere formato"    "$BIN/ytm" -f
_chk_err "ytm -S sin arg"        "requiere un factor"  "$BIN/ytm" -S
_chk_err "ytm -c sin arg"        "requiere un número"  "$BIN/ytm" -c
_chk_err "ytm -e sin preset"     "Disponibles"         "$BIN/ytm" -e
_chk_err "ytm opción desconocida" "Opción desconocida" "$BIN/ytm" -Z
out=$(timeout 10 "$BIN/yt" --manual </dev/null 2>&1); rc=$?
[[ $rc -eq 0 ]] && ok "yt --manual → rc=0" || fail "yt --manual → rc=$rc"
out=$(timeout 10 "$BIN/yt" --version </dev/null 2>&1); rc=$?
[[ $rc -eq 0 && "$out" == yt\ v* ]] && ok "yt --version → rc=0 ($out)" || fail "yt --version → rc=$rc [$out]"
out=$(timeout 10 "$BIN/ytm" --version </dev/null 2>&1); rc=$?
[[ $rc -eq 0 && "$out" == ytm\ v* ]] && ok "ytm --version → rc=0 ($out)" || fail "ytm --version → rc=$rc [$out]"
echo ""

# ══════════════════════════════════════════════════════════════════════
# 8. mpv_client.py — integración con socket Unix real (sin mpv)
# ══════════════════════════════════════════════════════════════════════
echo "━━━ 8. mpv_client.py (integración socket real) ━━━"
MVD=$(mktemp -d)
cat > "$MVD/test_mpv.py" <<'PYEOF'
import os, sys, json, socket, threading, time, tempfile
sys.path.insert(0, os.environ["BIN"])
import mpv_client

d = tempfile.mkdtemp()
spath = os.path.join(d, "mpv.sock")
srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
srv.bind(spath); srv.listen(1)
received = []

def server():
    conn, _ = srv.accept(); conn.settimeout(3.0); buf = b""
    try:
        while True:
            chunk = conn.recv(4096)
            if not chunk: break
            buf += chunk
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                if not line.strip(): continue
                received.append(line.decode())
                try: req = json.loads(line)
                except Exception: continue
                cmd = req.get("command", [])
                if cmd and cmd[0] == "quit": return
                if "request_id" in req:
                    prop = cmd[1] if len(cmd) > 1 else None
                    val = {"media-title": "Cancion X", "time-pos": 12.5, "duration": 200.0}.get(prop)
                    conn.sendall((json.dumps({"request_id": req["request_id"], "data": val}) + "\n").encode())
    except Exception: pass
    finally:
        try: conn.close()
        except Exception: pass

threading.Thread(target=server, daemon=True).start()

c0 = mpv_client.MpvClient(os.path.join(d, "nope.sock"))
assert c0.connect() is False, "connect socket inexistente debe ser False"
assert c0.is_connected() is False
assert c0.get_properties(["media-title"]) == {}
assert c0.send_command(["quit"]) is False
c0.close()

c = mpv_client.MpvClient(spath)
assert c.connect() is True, "connect debe ser True"
assert c.is_connected() is True
props = {}
for _ in range(60):
    props.update(c.get_properties(["media-title", "time-pos", "duration"]))
    if props.get("media-title") and props.get("time-pos") is not None and props.get("duration") is not None:
        break
    time.sleep(0.05)
assert props.get("media-title") == "Cancion X", f"media-title={props}"
assert props.get("time-pos") == 12.5, f"time-pos={props}"
assert props.get("duration") == 200.0, f"duration={props}"

s0 = c.seconds_since_ok(); time.sleep(0.05)
assert c.seconds_since_ok() >= s0, "seconds_since_ok debe crecer"
assert c.send_command(["quit"]) is True, "send_command quit"
time.sleep(0.2)
assert any('"quit"' in r for r in received), f"servidor no recibió quit: {received}"

c._close_socket(); c._close_socket()
assert c.is_connected() is False
c.close(); c.close()
print("MPV_CLIENT_OK")
PYEOF
out=$(BIN="$BIN" timeout 20 python3 "$MVD/test_mpv.py" </dev/null 2>&1); rc=$?
if [[ $rc -eq 0 && "$out" == *"MPV_CLIENT_OK"* ]]; then ok "mpv_client: connect/send/get_properties/close (socket real)"
else fail "mpv_client integración → rc=$rc $(printf '%s' "$out" | tail -2)"; fi
rm -rf "$MVD"
echo ""

# ══════════════════════════════════════════════════════════════════════
# 9. CONTROLADORES: lógica de navegación n/b (estático)
# ══════════════════════════════════════════════════════════════════════
echo "━━━ 9. CONTROLADORES: navegación n/b ━━━"
grep -q 'playlist-next", "force"' "$BIN/yt_control.py"  && ok "yt_control 'n' → playlist-next force"  || fail "yt_control 'n' sin playlist-next force"
grep -q 'playlist-prev", "force"' "$BIN/yt_control.py"  && ok "yt_control 'b' → playlist-prev force"  || fail "yt_control 'b' sin playlist-prev force"
grep -q 'playlist-next", "force"' "$BIN/ytm_control.py" && ok "ytm_control 'n' → playlist-next force" || fail "ytm_control 'n' sin playlist-next force"
grep -q 'playlist-prev", "force"' "$BIN/ytm_control.py" && ok "ytm_control 'b' → playlist-prev force" || fail "ytm_control 'b' sin playlist-prev force"
awk '/key in \("n", "N"\)/,/break/' "$BIN/yt_control.py" | grep -q 'else:' && ok "yt_control 'n' tiene fallback else (conteo desconocido)" || fail "yt_control 'n' sin fallback else"
awk '/key in \("n", "N"\)/,/key in \("d", "D"\)/' "$BIN/ytm_control.py" | grep -q 'else:' && ok "ytm_control 'n' tiene fallback else (conteo desconocido)" || fail "ytm_control 'n' sin fallback else"
grep -q 'seek", 0, "absolute"' "$BIN/yt_control.py"  && ok "yt_control 'b' → seek 0 si no hay anterior"  || fail "yt_control 'b' sin seek 0"
grep -q 'seek", 0, "absolute"' "$BIN/ytm_control.py" && ok "ytm_control 'b' → seek 0 si no hay anterior" || fail "ytm_control 'b' sin seek 0"
grep -q 'PLAYLIST_LABEL' "$BIN/ytm" && ok "ytm exporta PLAYLIST_LABEL (nombre de álbum)" || fail "ytm sin PLAYLIST_LABEL"
grep -q 'PLAYLIST_LABEL' "$BIN/yt"  && ok "yt exporta PLAYLIST_LABEL (nombre de lista)" || fail "yt sin PLAYLIST_LABEL"
grep -q 'key == "D"' "$BIN/ytm_control.py" && ok "ytm_control 'D' → descargar álbum" || fail "ytm_control sin 'D' álbum"
grep -q 'key == "D"' "$BIN/yt_control.py"  && ok "yt_control 'D' → descargar álbum"  || fail "yt_control sin 'D' álbum"
grep -q 'prompt_for_type' "$BIN/ytm" && ok "ytm maneja rc de búsqueda m/a/l (prompt_for_type)" || fail "ytm sin manejo rc búsqueda"
grep -q 'had_errexit' "$BIN/ytm" && ok "ytm no reactiva errexit tras el control (rc 10-13 no aborta)" || fail "ytm reactiva errexit tras control"
grep -q 'had_errexit' "$BIN/yt"  && ok "yt no reactiva errexit tras el control (rc 10-13 no aborta)"  || fail "yt reactiva errexit tras control"
if grep -q 'trap cleanup EXIT' "$BIN/ytm" && sed -n '/^cleanup()/,/^}/p' "$BIN/ytm" | grep -q 'stop_inhibit'; then ok "ytm: cleanup EXIT limpia inhibidor (sin fugas)"; else fail "ytm: trap EXIT no limpia inhibidor"; fi
if grep -q 'trap cleanup EXIT' "$BIN/yt" && sed -n '/^cleanup()/,/^}/p' "$BIN/yt" | grep -q 'stop_inhibit'; then ok "yt: cleanup EXIT limpia inhibidor (sin fugas)"; else fail "yt: trap EXIT no limpia inhibidor"; fi
echo ""

# ══════════════════════════════════════════════════════════════════════
# 10. ytm: elegir 1 pista carga el álbum completo (estático)
# ══════════════════════════════════════════════════════════════════════
echo "━━━ 10. ytm: álbum completo desde 1 pista ━━━"
grep -q 'start_idx=\$((line_num - 1))' "$BIN/ytm" && ok "ytm: start_idx según pista elegida" || fail "ytm: sin start_idx"
grep -q 'all_tracks=$(cat "$fzf_data")' "$BIN/ytm" && ok "ytm: carga álbum completo (all_tracks)" || fail "ytm: sin carga completa"
grep -q 'process_selection "$all_tracks" "$start_idx"' "$BIN/ytm" && ok "ytm: process_selection(álbum, start_idx)" || fail "ytm: process_selection sin start_idx"
grep -q 'result_count' "$BIN/ytm" && ok "ytm: cuenta total de pistas del álbum" || fail "ytm: sin result_count"
echo ""

# ══════════════════════════════════════════════════════════════════════
# 11. INSTALACIÓN / PERMISOS
# ══════════════════════════════════════════════════════════════════════
echo "━━━ 11. INSTALACIÓN ━━━"
for f in yt ytm; do
    [[ -x "$BIN/$f" ]] && ok "$f ejecutable" || fail "$f no ejecutable"
    head -1 "$BIN/$f" | grep -q '^#!' && ok "$f tiene shebang" || fail "$f sin shebang"
done
for f in yt_control.py ytm_control.py mpv_client.py; do
    [[ -f "$BIN/$f" ]] && ok "$f presente" || fail "$f ausente"
done
echo ""

# ══════════════════════════════════════════════════════════════════════
# 12. INTEGRACIÓN REAL n/b (mpv + control bajo PTY)
# ══════════════════════════════════════════════════════════════════════
echo "━━━ 12. Integración real n/b (PTY + mpv) ━━━"
if ! command -v mpv >/dev/null 2>&1; then
    warn "mpv ausente: se omite integración PTY n/b"
elif ! python3 -c 'import pty' >/dev/null 2>&1; then
    warn "python3 sin módulo pty: se omite integración PTY n/b"
else
    NEXTRACT=$(mktemp /tmp/yt_qa_nextrack.XXXXXX.py)
    cat > "$NEXTRACT" <<'PYEOF'
import os, sys, time, socket, json, wave, tempfile, subprocess, pty, fcntl, termios, struct, threading, select

CTRL = sys.argv[1]
d = tempfile.mkdtemp()
LOG = os.path.join(d, "ctrl.log")

def make_wav(path, seconds=20):
    with wave.open(path, "w") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(8000)
        w.writeframes(b"\x00\x00" * 8000 * seconds)

files = [os.path.join(d, f"t{i}.wav") for i in range(3)]
for p in files:
    make_wav(p)

sock = os.path.join(d, "mpv.sock")
mpv = subprocess.Popen(["mpv", f"--input-ipc-server={sock}", "--no-video",
                        "--keep-open=yes", "--really-quiet", "--no-terminal"] + files,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

def mpv_get(props):
    try:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM); s.settimeout(2); s.connect(sock)
    except Exception:
        return {}
    idmap = {}
    for i, p in enumerate(props, 1):
        idmap[i] = p
        s.sendall((json.dumps({"command": ["get_property", p], "request_id": i}) + "\n").encode())
    time.sleep(0.35)
    data = b""; s.settimeout(0.4)
    try:
        while True:
            c = s.recv(65536)
            if not c:
                break
            data += c
    except Exception:
        pass
    s.close()
    out = {}
    for line in data.split(b"\n"):
        line = line.strip()
        if not line:
            continue
        try:
            dat = json.loads(line)
        except Exception:
            continue
        rid = dat.get("request_id")
        if rid in idmap:
            out[idmap[rid]] = dat.get("data")
    return out

for _ in range(120):
    if os.path.exists(sock):
        break
    time.sleep(0.1)
for _ in range(60):
    r = mpv_get(["playlist-count", "playlist-pos"])
    if (r.get("playlist-count") or 0) >= 3:
        break
    time.sleep(0.2)

master, slave = pty.openpty()
fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 40, 120, 0, 0))
dl = os.path.join(d, "dl")
env = dict(os.environ, LOG_FILE=LOG, CACHE_MEDIA_DIR=d, VERSION="test",
           DOWNLOAD_DIR=dl, PLAYLIST_LABEL="testalbum")
ctrl = subprocess.Popen(["python3", CTRL, sock, str(mpv.pid)],
                        stdin=slave, stdout=slave, stderr=subprocess.DEVNULL, env=env)
os.close(slave)

stop = False
def drain():
    while not stop:
        try:
            r, _, _ = select.select([master], [], [], 0.2)
            if r:
                os.read(master, 4096)
        except OSError:
            break
threading.Thread(target=drain, daemon=True).start()

def send(k):
    os.write(master, k)

time.sleep(2.5)
pos0 = mpv_get(["playlist-pos"]).get("playlist-pos")
# 'b' en la primera pista NO debe matar mpv (regresión corregida)
send(b"b"); time.sleep(1.2)
pos_b0 = mpv_get(["playlist-pos"]).get("playlist-pos")
send(b"n"); time.sleep(1.2)
pos1 = mpv_get(["playlist-pos"]).get("playlist-pos")
send(b"n"); time.sleep(1.2)
pos2 = mpv_get(["playlist-pos"]).get("playlist-pos")
send(b"b"); time.sleep(1.2)
pos3 = mpv_get(["playlist-pos"]).get("playlist-pos")
# 'D' descarga el álbum/playlist completo (aquí: copia local sin red)
send(b"D"); time.sleep(1.5)
album_dir = os.path.join(dl, "testalbum")
album_files = sorted(os.listdir(album_dir)) if os.path.isdir(album_dir) else []
alive_mpv = mpv.poll() is None
alive_ctrl = ctrl.poll() is None

stop = True
for p in (ctrl, mpv):
    try:
        p.terminate()
    except Exception:
        pass

ok = (pos0 == 0 and pos_b0 == 0 and pos1 == 1 and pos2 == 2 and pos3 == 1
      and len(album_files) == 3 and alive_mpv and alive_ctrl)
print(f"pos0={pos0} b_en_0={pos_b0} next1={pos1} next2={pos2} prev={pos3} "
      f"album={len(album_files)} mpv_vivo={alive_mpv} ctrl_vivo={alive_ctrl}")
sys.exit(0 if ok else 1)
PYEOF
    for ctrl in yt_control.py ytm_control.py; do
        if out=$(timeout 60 python3 "$NEXTRACT" "$BIN/$ctrl" 2>&1); then
            ok "$ctrl: teclas n/b reales ($out)"
        else
            fail "$ctrl: teclas n/b reales ($out)"
        fi
    done
    rm -f "$NEXTRACT"
fi
echo ""

# ══════════════════════════════════════════════════════════════════════
# 13. CACHÉ DE BÚSQUEDA (24 h + --refresh, sin red)
# ══════════════════════════════════════════════════════════════════════
echo "━━━ 13. CACHÉ DE BÚSQUEDA (fake yt-dlp) ━━━"
grep -q 'SEARCH_CACHE_TTL:-86400' "$BIN/ytm" && ok "ytm TTL búsqueda 24 h" || fail "ytm TTL búsqueda != 24 h"
grep -q 'SEARCH_CACHE_TTL:-86400' "$BIN/yt"  && ok "yt TTL búsqueda 24 h"  || fail "yt TTL búsqueda != 24 h"
grep -q 'PLAYLIST_CACHE_TTL' "$BIN/ytm" && ok "ytm caché de álbumes" || fail "ytm sin caché de álbumes"
grep -q 'PLAYLIST_CACHE_TTL' "$BIN/yt"  && ok "yt caché de álbumes"  || fail "yt sin caché de álbumes"
grep -q -- '--refresh' "$BIN/ytm" && ok "ytm --refresh" || fail "ytm sin --refresh"
grep -q -- '--refresh' "$BIN/yt"  && ok "yt --refresh"  || fail "yt sin --refresh"

TMPC=$(mktemp -d)
mkdir -p "$TMPC/bin" "$TMPC/cache" "$TMPC/cfg" "$TMPC/data"
cat > "$TMPC/bin/fake-ytdlp" <<'FAKE'
#!/usr/bin/env bash
echo call >> "$FAKE_MARKER"
echo '{"id":"FAKEID12345","title":"FAKE FROM NETWORK","channel":"Fake","duration":123}'
FAKE
chmod +x "$TMPC/bin/fake-ytdlp"
count_lines() { [[ -f "$1" ]] && wc -l < "$1" || echo 0; }

run_cache() {
    local bin="$1" marker="$2"; shift 2
    env XDG_CACHE_HOME="$TMPC/cache" XDG_CONFIG_HOME="$TMPC/cfg" XDG_DATA_HOME="$TMPC/data" \
        HOME="$HOME" YT_DLP="$TMPC/bin/fake-ytdlp" FAKE_MARKER="$marker" \
        timeout 45 "$bin" "$@" </dev/null 2>&1
}

for spec in "ytm|$TMPC/ytm.calls|-l -s qa-cache" "yt|$TMPC/yt.calls|-l -m qa-cache"; do
    IFS='|' read -r name marker args <<< "$spec"
    rm -f "$marker"
    o1=$(run_cache "$BIN/$name" "$marker" $args); c1=$(count_lines "$marker")
    o2=$(run_cache "$BIN/$name" "$marker" $args); c2=$(count_lines "$marker")
    o3=$(run_cache "$BIN/$name" "$marker" $args -R); c3=$(count_lines "$marker")
    if [[ "$c1" -eq 1 && "$o1" != *"Caché de búsqueda"* ]]; then ok "$name 1ª búsqueda → red (1 llamada)"; else fail "$name 1ª búsqueda (llamadas=$c1)"; fi
    if [[ "$c2" -eq 1 && "$o2" == *"Caché de búsqueda"* && "$o2" == *"FAKE FROM NETWORK"* ]]; then ok "$name 2ª búsqueda → caché (sin red)"; else fail "$name 2ª búsqueda (llamadas=$c2)"; fi
    if [[ "$c3" -eq 2 && "$o3" != *"Caché de búsqueda"* ]]; then ok "$name -R → ignora caché (2 llamadas)"; else fail "$name -R (llamadas=$c3)"; fi
done
oC=$(run_cache "$BIN/ytm" "$TMPC/ytm.calls" --clear-cache -l -s qa-cache)
[[ "$oC" == *"Caché de búsquedas/álbumes borrada"* ]] && ok "ytm --clear-cache borra caché" || fail "ytm --clear-cache"
rm -rf "$TMPC"
echo ""

# ══════════════════════════════════════════════════════════════════════
# 14. FAVORITOS (track_id + toggle)
# ══════════════════════════════════════════════════════════════════════
echo "━━━ 14. FAVORITOS ━━━"
grep -q 'show_favorites' "$BIN/ytm" && ok "ytm tiene modo Favoritos" || fail "ytm sin modo Favoritos"
grep -q 'show_favorites' "$BIN/yt"  && ok "yt tiene modo Favoritos"  || fail "yt sin modo Favoritos"
grep -q 'toggle_favorite' "$BIN/ytm_control.py" && ok "ytm_control tecla f (toggle)" || fail "ytm_control sin toggle"
grep -q 'toggle_favorite' "$BIN/yt_control.py"  && ok "yt_control tecla f (toggle)"  || fail "yt_control sin toggle"
if out=$(timeout 30 python3 - "$BIN" <<'PYFAV' 2>&1
import sys, tempfile, os
sys.path.insert(0, sys.argv[1])
import ytm_control as Y
import yt_control as T
cases = [
    ("https://www.youtube.com/watch?v=dQw4w9WgXcQ", "dQw4w9WgXcQ"),
    ("https://youtu.be/dQw4w9WgXcQ", "dQw4w9WgXcQ"),
    ("/home/u/.cache/ytm/media/dQw4w9WgXcQ.webm", "dQw4w9WgXcQ"),
    ("", ""),
]
ok = True
for mod in (Y, T):
    d = tempfile.mkdtemp(); fav = os.path.join(d, "favorites")
    for inp, exp in cases:
        if mod.track_id(inp) != exp:
            ok = False; print(f"track_id {mod.__name__} {inp!r}")
    r1 = mod.toggle_favorite(fav, "dQw4w9WgXcQ", "Titulo\tcon tab")
    r2 = mod.toggle_favorite(fav, "dQw4w9WgXcQ", "Titulo")
    r3 = mod.toggle_favorite(fav, "abcDEF12345", "Otra")
    lines = open(fav, encoding="utf-8").read().splitlines()
    if (r1, r2, r3) != (True, False, True):
        ok = False; print(f"toggle {mod.__name__}: {r1},{r2},{r3}")
    if len(lines) != 1 or not lines[0].startswith("abcDEF12345\t") or lines[0].count("\t") != 1:
        ok = False; print(f"contenido {mod.__name__}: {lines}")
print("FAVORITES_OK" if ok else "FAVORITES_FAIL")
PYFAV
); then
    [[ "$out" == *"FAVORITES_OK"* ]] && ok "track_id + toggle añadir/quitar (ambos controles)" || fail "favoritos: $out"
else
    fail "favoritos: $out"
fi
echo ""

# ══════════════════════════════════════════════════════════════════════
# 15. REGRESIONES DE ROBUSTEZ (P0/P1)
# ══════════════════════════════════════════════════════════════════════
echo "━━━ 15. ROBUSTEZ P0/P1 ━━━"

# 15.1 Contrato de exit codes
if python3 - "$BIN" <<'PYEX' >/dev/null 2>&1
import sys
sys.path.insert(0, sys.argv[1])
import exit_codes as E
assert (E.EXIT_OK, E.EXIT_ERROR) == (0, 1)
assert (E.EXIT_SEARCH_SONGS, E.EXIT_SEARCH_MUSIC, E.EXIT_SEARCH_ALBUMS, E.EXIT_SEARCH_PLAYLISTS) == (10, 11, 12, 13)
assert set(E.SEARCH_CODES) == {10, 11, 12, 13}
PYEX
then ok "exit_codes.py (0/1 y 10-13)"; else fail "exit_codes.py"; fi
grep -q 'from exit_codes import' "$BIN/ytm_control.py" && grep -q 'from exit_codes import' "$BIN/yt_control.py" && ok "controles usan exit_codes" || fail "controles no usan exit_codes"
grep -q 'EXIT_SEARCH_SONGS=10' "$BIN/ytm" && grep -q 'EXIT_SEARCH_SONGS=10' "$BIN/yt" && ok "constantes de exit codes en bash" || fail "faltan constantes bash"

# 15.2 Un único trap EXIT y cleanup con registro de temporales
for f in yt ytm; do
    n=$(grep -c 'trap .*EXIT' "$BIN/$f")
    if [[ "$n" -eq 1 ]] && grep -q 'trap cleanup EXIT' "$BIN/$f"; then ok "$f: un solo trap EXIT (cleanup)"; else fail "$f: $n traps EXIT"; fi
    grep -q '^_TMP_FILES=()' "$BIN/$f" && grep -q '^reg_tmp()' "$BIN/$f" && ok "$f: registro _TMP_FILES/reg_tmp" || fail "$f: sin registro de temporales"
    if grep -q "trap 'rm -f" "$BIN/$f"; then fail "$f: trap de función residual"; else ok "$f: sin traps de función"; fi
done
TP=$(mktemp); echo x > "$TP"
out=$(TP="$TP" bash -c '
set -euo pipefail
_TMP_FILES=(); reg_tmp(){ _TMP_FILES+=("$1"); }
stop_inhibit(){ :; }; _kill_mpv(){ :; }
cleanup() {
    local f
    if (( ${#_TMP_FILES[@]} > 0 )); then
        for f in "${_TMP_FILES[@]}"; do [[ -n "$f" ]] && rm -f "$f"; done
    fi
    stop_inhibit; _kill_mpv /tmp/x 2>/dev/null || true
}
t="$TP"; reg_tmp "$t"; trap cleanup EXIT
echo CLEANUP_OK
' 2>&1); rc=$?
if [[ "$out" == *"CLEANUP_OK"* && ! -e "$TP" ]]; then ok "cleanup con set -u + temporales"; else fail "cleanup: $out (rc=$rc)"; fi
rm -f "$TP"

# 15.3 Poda JSON por edad/tipo y tope
TMPP=$(mktemp -d); W="$TMPP/work"; mkdir -p "$W"
echo '[]' > "$W/search_old.json";  touch -d '2 days ago' "$W/search_old.json"
echo '[]' > "$W/search_new.json"
echo '[]' > "$W/playlist_old.json"; touch -d '2 days ago' "$W/playlist_old.json"
eval "$(sed -n '/^prune_search_cache()/,/^}/p' "$BIN/ytm")"
SEARCH_CACHE_TTL=86400 PLAYLIST_CACHE_TTL=259200 CACHE_MAX_MB=0 prune_search_cache "$W"
[[ ! -e "$W/search_old.json" && -e "$W/search_new.json" && -e "$W/playlist_old.json" ]] && ok "poda respeta TTL por tipo" || fail "poda por tipo"
head -c 700000 /dev/zero | tr '\0' 'x' > "$W/a.json"
head -c 700000 /dev/zero | tr '\0' 'x' > "$W/b.json"
touch -d '1 hour ago' "$W/a.json"; touch -d '2 hours ago' "$W/b.json"
CACHE_MAX_MB=1 prune_search_cache "$W"
total_kb=$(du -sk "$W" | awk '{print $1}')
[[ "$total_kb" -le 1024 ]] && ok "tope CACHE_MAX_MB evicta por antigüedad" || fail "tope caché: ${total_kb}KB"
rm -rf "$TMPP"

# 15.4 Rotación de mpv.log
TMPL=$(mktemp -d)
eval "$(sed -n '/^rotate_mpv_log()/,/^}/p' "$BIN/ytm")"
MPV_LOG="$TMPL/mpv.log"; MPV_LOG_MAX_BYTES=1048576
head -c 3000000 /dev/zero | tr '\0' 'x' > "$MPV_LOG"
rotate_mpv_log
sz=$(stat -c %s "$MPV_LOG")
[[ "$sz" -eq 1048576 ]] && ok "mpv.log recortado a 1 MB" || fail "mpv.log tamaño=$sz"
rm -rf "$TMPL"

# 15.5 Caché mpv configurable
grep -q 'MPV_CACHE_MB:-20' "$BIN/ytm" && grep -q 'MPV_CACHE_MB:-20' "$BIN/yt" && ok "MPV_CACHE_MB=30 configurable" || fail "MPV_CACHE_MB"
grep -q 'demuxer-max-bytes=${MPV_CACHE_MB}M' "$BIN/ytm" && grep -q 'demuxer-max-bytes=${MPV_CACHE_MB}M' "$BIN/yt" && ok "flags mpv usan MPV_CACHE_MB" || fail "flags mpv"
grep -q 'stream-buffer-size=${MPV_STREAM_BUFFER_MB}M' "$BIN/ytm" && grep -q 'stream-buffer-size=${MPV_STREAM_BUFFER_MB}M' "$BIN/yt" && ok "stream buffer configurable" || fail "stream buffer"

# 15.6 mpv_client buffer bytearray con tope
grep -q '_buf = bytearray()' "$BIN/mpv_client.py" && grep -Eq '1_048_576|1048576' "$BIN/mpv_client.py" && ok "mpv_client buffer bytearray + tope" || fail "mpv_client buffer"

# 15.7 Descargas acotadas + favoritos atómicos
if out=$(timeout 30 env LOG_FILE=/dev/null python3 - "$BIN" <<'PYP0' 2>&1
import sys, os, tempfile
sys.path.insert(0, sys.argv[1])
import ytm_control as Y, yt_control as T
ok = True
for mod in (Y, T):
    src = open(mod.__file__, encoding="utf-8").read()
    for needle in ("_DOWNLOADS", "_reap_downloads", "MAX_DOWNLOADS", "os.replace", "fcntl.flock", "os.fsync"):
        if needle not in src:
            ok = False; print("missing", mod.__name__, needle)
d = tempfile.mkdtemp()
fake = os.path.join(d, "fake-dl")
with open(fake, "w") as fh:
    fh.write("#!/usr/bin/env bash\nsleep 5\n")
os.chmod(fake, 0o755)
os.environ["YT_DLP"] = fake; os.environ["MAX_DOWNLOADS"] = "1"; os.environ["LOG_FILE"] = "/dev/null"
r1 = Y.spawn_ytdlp(["u1"], d, "best")
r2 = Y.spawn_ytdlp(["u2"], d, "best")
for p in Y._DOWNLOADS: p.terminate()
if (r1, r2) != (True, False): ok = False; print("download limit", r1, r2)
os.environ["FAVORITES_MAX"] = "2"
fav = os.path.join(d, "favorites")
Y.toggle_favorite(fav, "a", "A"); Y.toggle_favorite(fav, "b", "B"); Y.toggle_favorite(fav, "c", "C")
lines = open(fav, encoding="utf-8").read().splitlines()
if len(lines) != 2 or not lines[-1].startswith("c\t"): ok = False; print("fav cap", lines)
if not os.path.exists(fav + ".lock"): ok = False; print("no lock")
if any(n.startswith("favorites.tmp.") for n in os.listdir(d)): ok = False; print("tmp residual")
print("P0_OK" if ok else "P0_FAIL")
PYP0
); then
    [[ "$out" == *"P0_OK"* ]] && ok "descargas acotadas + favoritos atómicos con cota" || fail "P0: $out"
else
    fail "P0: $out"
fi
echo ""

# ══════════════════════════════════════════════════════════════════════
# 16. NUEVOS MENÚS DE UI (álbumes, relacionados, radio)
# ══════════════════════════════════════════════════════════════════════
echo "━━━ 16. NUEVOS MENÚS DE UI ━━━"
grep -q 'save_last_song()' "$BIN/ytm" && ok "ytm tiene save_last_song()" || fail "ytm sin save_last_song()"
grep -q 'show_albums_for_song()' "$BIN/ytm" && ok "ytm tiene show_albums_for_song()" || fail "ytm sin show_albums_for_song()"
grep -q 'show_related_songs()' "$BIN/ytm" && ok "ytm tiene show_related_songs()" || fail "ytm sin show_related_songs()"
grep -q 'show_radio_menu()' "$BIN/ytm" && ok "ytm tiene show_radio_menu()" || fail "ytm sin show_radio_menu()"
grep -q 'LAST_SONG_FILE=' "$BIN/ytm" && ok "ytm define LAST_SONG_FILE" || fail "ytm sin LAST_SONG_FILE"
grep -q 'RADIO_MODE=0' "$BIN/ytm" && ok "ytm define RADIO_MODE=0" || fail "ytm sin RADIO_MODE"
grep -q '8.*💿  Álbumes de…' "$BIN/ytm" && ok "ytm menú opción 8 álbumes" || fail "ytm sin opción 8 menú"
grep -q '9.*🔀  Relacionados' "$BIN/ytm" && ok "ytm menú opción 9 relacionados" || fail "ytm sin opción 9 menú"
grep -q '10.*📻  Radio…' "$BIN/ytm" && ok "ytm menú opción 10 radio" || fail "ytm sin opción 10 menú"
grep -q 'show_albums_for_song && break' "$BIN/ytm" && ok "ytm case opción 8 conectado" || fail "ytm case 8 no conectado"
grep -q 'show_related_songs && break' "$BIN/ytm" && ok "ytm case opción 9 conectado" || fail "ytm case 9 no conectado"
grep -q 'show_radio_menu && break' "$BIN/ytm" && ok "ytm case opción 10 conectado" || fail "ytm case 10 no conectado"
grep -q 'if \[\[ "$RADIO_MODE" == "1" && "$rc" -eq 0 \]\]; then' "$BIN/ytm" && ok "ytm radio continua repite búsqueda" || fail "ytm radio sin repetición"
echo ""

# ══════════════════════════════════════════════════════════════════════
# RESUMEN
# ══════════════════════════════════════════════════════════════════════
echo "══════════════════════════════════════════════════════════════════════"
echo "  RESUMEN: $PASS pasadas, $FAIL falladas, $WARN advertencias"
echo "══════════════════════════════════════════════════════════════════════"
[[ $FAIL -eq 0 ]] && exit 0 || exit 1

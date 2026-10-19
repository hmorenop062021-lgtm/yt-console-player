#!/usr/bin/env python3
"""
yt_control.py - Control interactivo para reproducción de YouTube / YouTube Music con mpv
Usa mpv_client.py compartido para comunicación con mpv.
"""
import sys
import os
import time
import select
import tty
import termios
import signal
import shutil
import subprocess
import re
import traceback
import mpv_client
from exit_codes import (
    EXIT_OK, EXIT_ERROR, EXIT_SEARCH_SONGS, EXIT_SEARCH_MUSIC,
    EXIT_SEARCH_ALBUMS, EXIT_SEARCH_PLAYLISTS,
)


VERSION = "1.0.0"


def _log(msg):
    """Registra eventos del controlador en el log compartido (LOG_FILE)."""
    try:
        path = os.environ.get("LOG_FILE") or os.path.expanduser("~/.cache/yt/events.log")
        with open(path, "a") as f:
            f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} [CTRL] | {msg}\n")
    except Exception:
        pass


def format_time(seconds):
    if seconds is None:
        return "--:--"
    seconds = int(seconds)
    minutes = seconds // 60
    seconds = seconds % 60
    hours = minutes // 60
    minutes = minutes % 60
    if hours > 0:
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
    return f"{minutes:02d}:{seconds:02d}"


_SAVED_TERMIOS = None


def enter_raw_mode():
    """Pone la terminal en modo raw una sola vez para toda la sesión."""
    global _SAVED_TERMIOS
    try:
        fd = sys.stdin.fileno()
        _SAVED_TERMIOS = termios.tcgetattr(fd)
        tty.setraw(fd)
    except Exception:
        _SAVED_TERMIOS = None


def get_key():
    fd = sys.stdin.fileno()
    try:
        rlist, _, _ = select.select([fd], [], [], 0.05)
        if rlist:
            data = os.read(fd, 8)
            key = data.decode("utf-8", errors="ignore")
            if key == "\x1b":
                rlist2, _, _ = select.select([fd], [], [], 0.1)
                if rlist2:
                    data2 = os.read(fd, 7)
                    key += data2.decode("utf-8", errors="ignore")
            return key
    except (OSError, IOError):
        pass
    return None


def flush_stdin():
    """Limpia caracteres pendientes en stdin para no contaminar el siguiente prompt."""
    try:
        fd = sys.stdin.fileno()
        while True:
            rlist, _, _ = select.select([fd], [], [], 0.0)
            if not rlist:
                break
            if not os.read(fd, 1024):
                break
    except Exception:
        pass


def check_process_alive(pid):
    if pid is None:
        return True
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def safe_name(name):
    """Nombre de archivo seguro (sin separadores ni caracteres reservados)."""
    return "".join(c for c in (name or "") if c not in r'/\:*?"<>|').strip()


_DOWNLOADS = []


def _reap_downloads():
    """Elimina de la lista los procesos yt-dlp ya terminados."""
    global _DOWNLOADS
    _DOWNLOADS = [p for p in _DOWNLOADS if p.poll() is None]


def spawn_ytdlp(urls, dest, fmt):
    """Lanza yt-dlp en segundo plano (máx. MAX_DOWNLOADS activos)."""
    if not urls:
        return False
    _reap_downloads()
    try:
        limit = int(os.environ.get("MAX_DOWNLOADS", "2"))
    except ValueError:
        limit = 2
    if limit > 0 and len(_DOWNLOADS) >= limit:
        _log(f"DOWNLOAD rejected: {len(_DOWNLOADS)} activos (límite {limit})")
        return False
    cmd = [os.environ.get("YT_DLP", "yt-dlp"),
           "--js-runtimes", "node", "--remote-components", "ejs:github",
           "-f", fmt, "--embed-thumbnail", "--add-metadata",
           "-o", os.path.join(dest, "%(title)s.%(ext)s")] + list(urls)
    try:
        p = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        _DOWNLOADS.append(p)
        _log(f"DOWNLOAD started pid={p.pid} urls={len(urls)} dest={dest}")
        return True
    except OSError:
        return False

def track_id(path):
    """Extrae el ID de YouTube de una URL o de un archivo en caché."""
    if not path:
        return ""
    m = re.search(r'(?:v=|youtu\.be/)([\w-]{11})', path)
    if m:
        return m.group(1)
    m = re.match(r'([\w-]{11})\.', os.path.basename(path))
    return m.group(1) if m else ""


def toggle_favorite(fav_file, vid, title):
    """Añade/quita una pista de favoritos (escritura atómica + lock). True si la añadió."""
    title = (title or vid).replace("\t", " ").replace("\n", " ").strip()
    try:
        d = os.path.dirname(fav_file)
        if d:
            os.makedirs(d, exist_ok=True)
        lock_path = fav_file + ".lock"
        with open(lock_path, "a", encoding="utf-8") as lock:
            try:
                import fcntl
                fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            except (ImportError, OSError):
                pass
            kept, found = [], False
            if os.path.isfile(fav_file):
                with open(fav_file, "r", encoding="utf-8") as f:
                    for ln in f:
                        if ln.startswith(vid + "\t"):
                            found = True
                            continue
                        kept.append(ln)
            if not found:
                kept.append(f"{vid}\t{title}\n")
            try:
                max_n = int(os.environ.get("FAVORITES_MAX", "500"))
            except ValueError:
                max_n = 500
            if max_n > 0 and len(kept) > max_n:
                kept = kept[-max_n:]
            tmp = f"{fav_file}.tmp.{os.getpid()}"
            with open(tmp, "w", encoding="utf-8") as f:
                f.writelines(kept)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, fav_file)
        return not found
    except OSError:
        return None

def restore_terminal():
    try:
        sys.stdout.write("\033[?25h\033[0m")  # Mostrar cursor y resetear colores
        sys.stdout.flush()
    except Exception:
        pass
    flush_stdin()
    if _SAVED_TERMIOS is not None:
        try:
            termios.tcsetattr(sys.stdin.fileno(), termios.TCSADRAIN, _SAVED_TERMIOS)
        except Exception:
            pass


def main():
    if len(sys.argv) < 2:
        print("Uso: yt_control.py <socket_path> [pid]")
        sys.exit(EXIT_ERROR)

    socket_path = sys.argv[1]
    mpv_pid = int(sys.argv[2]) if len(sys.argv) > 2 else None

    # Ignore SIGINT in python so exit is handled via quit key or loop
    def sig_handler(sig, frame):
        restore_terminal()
        sys.exit(EXIT_OK)
    try:
        signal.signal(signal.SIGINT, sig_handler)
        signal.signal(signal.SIGTERM, sig_handler)
    except Exception:
        pass

    _log(f"yt_control v{VERSION} start | socket={socket_path} pid={mpv_pid}")
    client = mpv_client.MpvClient(socket_path)

    # Esperar hasta 5 segundos a que mpv cree el socket e inicialice
    connected = False
    for _ in range(50):
        if not check_process_alive(mpv_pid):
            _log("mpv process is dead before connect")
            break
        if client.connect():
            connected = True
            break
        time.sleep(0.1)

    if not connected:
        _log("connection failed (mpv dead or socket missing) -> rc=1")
        restore_terminal()
        # Sin conexión al socket no se puede operar: error, nunca entrar al bucle
        sys.exit(EXIT_ERROR)
    _log("connected to mpv")

    # Ocultar cursor durante el panel interactivo
    sys.stdout.write("\033[?25l\033[H\033[2J")
    sys.stdout.flush()

    # Estado previo cacheado
    last_title = "Cargando..."
    last_duration = None
    last_pos = None
    last_paused = False
    last_volume = 100.0
    last_speed = 1.0
    last_playlist_pos = 0
    last_playlist_count = 0
    feedback_msg = ""
    feedback_time = 0
    last_active_time = time.time()

    props_to_query = [
        "media-title",
        "time-pos",
        "duration",
        "pause",
        "volume",
        "speed",
        "playlist-pos",
        "playlist-count",
        "path"
    ]

    exit_code = EXIT_OK
    enter_raw_mode()
    try:
        while True:
            # Comprobar si mpv sigue vivo
            if not check_process_alive(mpv_pid):
                break

            now = time.time()
            # Consultar propiedades a mpv
            props = client.get_properties(props_to_query)
            if props:
                last_active_time = now
                if props.get("media-title"):
                    last_title = props["media-title"]
                if props.get("duration") is not None:
                    last_duration = props["duration"]
                if props.get("time-pos") is not None:
                    last_pos = props["time-pos"]
                if props.get("pause") is not None:
                    last_paused = bool(props["pause"])
                if props.get("volume") is not None:
                    last_volume = props["volume"]
                if props.get("speed") is not None:
                    last_speed = props["speed"]
                if props.get("playlist-pos") is not None and props["playlist-pos"] >= 0:
                    last_playlist_pos = props["playlist-pos"]
                if props.get("playlist-count") is not None and props["playlist-count"] > 0:
                    last_playlist_count = props["playlist-count"]
            else:
                if now - last_active_time > 8.0:
                    break


            # Mensaje de feedback temporal (desaparece tras 2s)
            if feedback_msg and (now - feedback_time > 2.0):
                feedback_msg = ""

            # Formatear datos para la interfaz
            title_display = last_title[:75] + ("..." if len(last_title) > 75 else "")
            
            percent = 0
            bar_str = "────────────"
            if last_duration and last_pos and last_duration > 0:
                percent = int((last_pos / last_duration) * 100)
                dot_pos = int((last_pos / last_duration) * 12)
                dot_pos = min(max(dot_pos, 0), 12)
                bar_str = "━" * dot_pos + "●" + "─" * (12 - dot_pos)

            time_str = f"{format_time(last_pos)} / {format_time(last_duration)}"
            percent_str = f"({percent}%)" if percent > 0 else ""
            status_str = "\033[1;93m⏸ PAUSADO\033[0m" if last_paused else "\033[1;92m▶ REPRODUCIENDO\033[0m"
            track_str = f"[{last_playlist_pos + 1}/{last_playlist_count}]"

            # Renderizar interfaz
            sys.stdout.write("\033[H")
            sys.stdout.write(f"\033[1;36m🎵 {title_display}\033[K\033[0m\n")
            sys.stdout.write(f"⏱  {time_str} {percent_str}  [{bar_str}]\033[K\n")
            sys.stdout.write(f"🎚  Vel: {last_speed:.2f}x  |  Vol: {int(last_volume)}%  |  {status_str}  |  Pista: \033[1;95m{track_str}\033[0m\033[K\n")

            if feedback_msg:
                sys.stdout.write(f"\033[1;33m💡 {feedback_msg}\033[K\033[0m\n")
            else:
                sys.stdout.write("\033[K\n")

            sys.stdout.write("─────────────────────────────────────────────────────────────────────────────\033[K\n")
            sys.stdout.write("\033[1mControles:\033[0m\033[K\n")
            sys.stdout.write("  \033[1;32m[Espacio/p]\033[0m Pausar/Reanudar    \033[1;32m[◀ / ▶]\033[0m -/+ 10s       \033[1;32m[Shift+◀/▶]\033[0m -/+ 60s\033[K\n")
            sys.stdout.write("  \033[1;32m[▲ / ▼]\033[0m     Vol +/- 5%         \033[1;33m[n]\033[0m Siguiente pista  \033[1;33m[b]\033[0m Pista anterior\033[K\n")
            sys.stdout.write("  \033[1;36m[s]\033[0m         Buscar YouTube     \033[1;35m[m]\033[0m Canciones Music  \033[1;33m[f]\033[0m Favorito\033[K\n")
            sys.stdout.write("  \033[1;34m[a]\033[0m         Álbumes            \033[1;34m[l]\033[0m Listas           \033[1;32m[d]\033[0m Canción  \033[1;32m[D]\033[0m Álbum/lista  \033[1;31m[q/Esc]\033[0m Salir\033[K\n")
            sys.stdout.flush()

            # Escuchar teclado
            start_wait = time.time()
            exit_requested = False
            while time.time() - start_wait < 0.25:
                key = get_key()
                if key:
                    _log(f"key={key!r} pos={last_playlist_pos}/{last_playlist_count}")
                    if key in (" ", "p", "P"):
                        client.send_command(["cycle", "pause"])
                        last_paused = not last_paused
                        break
                    elif key in ("\x1b[C", "."):  # Right arrow
                        client.send_command(["seek", 10, "relative"])
                        break
                    elif key in ("\x1b[D", "h", ","):  # Left arrow
                        client.send_command(["seek", -10, "relative"])
                        break
                    elif key in ("\x1b[1;2C", "L", ">"):  # Shift + Right
                        client.send_command(["seek", 60, "relative"])
                        break
                    elif key in ("\x1b[1;2D", "H", "<"):  # Shift + Left
                        client.send_command(["seek", -60, "relative"])
                        break
                    elif key in ("\x1b[A", "k", "K", "+"):  # Up arrow
                        client.send_command(["add", "volume", 5])
                        break
                    elif key in ("\x1b[B", "j", "J", "-"):  # Down arrow
                        client.send_command(["add", "volume", -5])
                        break
                    elif key in ("n", "N"):  # Next song
                        if last_playlist_count > 1 and last_playlist_pos < last_playlist_count - 1:
                            client.send_command(["playlist-next", "force"])
                            feedback_msg = "⏭️ Cambiando a siguiente pista..."
                            feedback_time = time.time()
                        elif last_playlist_count > 1:
                            feedback_msg = "ℹ️ Ya estás en la última pista de la lista."
                            feedback_time = time.time()
                        elif last_playlist_count == 1:
                            feedback_msg = "ℹ️ Pista única. Presiona [s] o [m] para buscar más canciones."
                            feedback_time = time.time()
                        else:
                            # conteo aún no leído por mpv: intentar navegación igual
                            client.send_command(["playlist-next", "force"])
                            feedback_msg = "⏭️ Cambiando a siguiente pista..."
                            feedback_time = time.time()
                        break
                    elif key in ("b", "B"):  # Previous song
                        if last_playlist_count > 1 and last_playlist_pos > 0:
                            client.send_command(["playlist-prev", "force"])
                            feedback_msg = "⏮️ Cambiando a pista anterior..."
                            feedback_time = time.time()
                        elif last_playlist_count > 1:
                            client.send_command(["seek", 0, "absolute"])
                            feedback_msg = "⏮️ Reiniciando pista actual..."
                            feedback_time = time.time()
                        else:
                            client.send_command(["seek", 0, "absolute"])
                            feedback_msg = "⏮️ Reiniciando pista..."
                            feedback_time = time.time()
                        break
                    elif key in ("d", "D"):  # Descargar canción o álbum/playlist
                        download_dir = os.environ.get("DOWNLOAD_DIR", os.path.expanduser("~/Downloads"))
                        try:
                            os.makedirs(download_dir, exist_ok=True)
                        except OSError:
                            download_dir = os.path.expanduser("~/Downloads")

                        if key == "D":
                            # ── Descargar el álbum/playlist completo ──
                            fmt = os.environ.get("FORMAT", "best")
                            label = safe_name(os.environ.get("PLAYLIST_LABEL", ""))
                            if not label:
                                label = time.strftime("playlist_%Y%m%d_%H%M%S")
                            dest = os.path.join(download_dir, label)
                            try:
                                os.makedirs(dest, exist_ok=True)
                            except OSError:
                                feedback_msg = "❌ No se pudo crear la carpeta"
                                feedback_time = time.time()
                            else:
                                playlist = client.get_properties(["playlist"]).get("playlist") or []
                                urls, copied = [], 0
                                for entry in playlist:
                                    fn = entry.get("filename") or ""
                                    if not fn:
                                        continue
                                    title = safe_name(entry.get("title")
                                                      or os.path.splitext(os.path.basename(fn))[0]) or "track"
                                    if os.path.isfile(fn):
                                        ext = os.path.splitext(fn)[1] or ".webm"
                                        try:
                                            shutil.copyfile(fn, os.path.join(dest, title + ext))
                                            copied += 1
                                        except OSError:
                                            pass
                                    elif fn.startswith(("http://", "https://")):
                                        urls.append(fn)
                                total = len(playlist)
                                if urls and spawn_ytdlp(urls, dest, fmt):
                                    feedback_msg = f"⏬ Álbum/lista ({total}): {len(urls)} en descarga → {dest}"
                                elif copied:
                                    feedback_msg = f"✅ Copiadas {copied} pistas → {dest}"
                                else:
                                    feedback_msg = "⚠️ No hay pistas descargables"
                                feedback_time = time.time()
                                _log(f"DOWNLOAD_ALBUM total={total} urls={len(urls)} copied={copied} dest={dest}")
                        else:
                            # ── Descargar la canción actual ──
                            cache_dir = os.environ.get("CACHE_MEDIA_DIR", os.path.expanduser("~/.cache/yt/media"))
                            curr_path = props.get("path") or ""
                            base = safe_name(last_title) or "track"
                            saved = False

                            # 1. Si mpv reproduce un archivo local (caché), copiarlo
                            if curr_path and os.path.isfile(curr_path):
                                ext = os.path.splitext(curr_path)[1] or ".webm"
                                dst = os.path.join(download_dir, f"{base}{ext}")
                                try:
                                    shutil.copyfile(curr_path, dst)
                                    feedback_msg = f"⚡ Guardado al instante desde caché en {os.path.basename(dst)}"
                                    feedback_time = time.time()
                                    saved = True
                                except OSError:
                                    pass

                            # 2. Si no, buscar en la carpeta de caché por ID o URL
                            if not saved and curr_path and os.path.exists(cache_dir):
                                vid_match = re.search(r'(?:v=|youtu\.be/)([\w-]{11})', curr_path)
                                if vid_match:
                                    vid = vid_match.group(1)
                                    for cand in os.listdir(cache_dir):
                                        if cand.startswith(vid) and not cand.endswith(('.part', '.ytdl', '.temp')):
                                            src = os.path.join(cache_dir, cand)
                                            ext = os.path.splitext(cand)[1]
                                            dst = os.path.join(download_dir, f"{base}{ext}")
                                            try:
                                                shutil.copyfile(src, dst)
                                                feedback_msg = f"⚡ Guardado al instante desde caché en {os.path.basename(dst)}"
                                                feedback_time = time.time()
                                                saved = True
                                                break
                                            except OSError:
                                                pass

                            # 3. Si mpv reproduce una URL, lanzar descarga en background con yt-dlp
                            if not saved and curr_path.startswith(("http://", "https://")):
                                fmt = os.environ.get("FORMAT", "bestaudio/best" if os.environ.get("AUDIO_ONLY") == "1" else "best")
                                if spawn_ytdlp([curr_path], download_dir, fmt):
                                    feedback_msg = f"⏬ Descargando en segundo plano a {download_dir}..."
                                else:
                                    feedback_msg = "❌ Error al iniciar descarga"
                                feedback_time = time.time()
                            elif not saved:
                                feedback_msg = "⚠️ No se pudo determinar la fuente para descargar."
                                feedback_time = time.time()
                        break
                    elif key in ("f", "F"):  # Favorito
                        fav_file = os.environ.get("FAVORITES_FILE", "")
                        vid = track_id(props.get("path") or "")
                        if not fav_file or not vid:
                            feedback_msg = "⚠️ No se pudo identificar la pista"
                        else:
                            res = toggle_favorite(fav_file, vid, last_title)
                            if res is True:
                                feedback_msg = "⭐ Añadido a favoritos"
                            elif res is False:
                                feedback_msg = "☆ Quitado de favoritos"
                            else:
                                feedback_msg = "❌ Error de favoritos"
                            _log(f"FAVORITE vid={vid} added={res}")
                        feedback_time = time.time()
                        break
                    elif key in ("]",):
                        client.send_command(["multiply", "speed", 1.1])
                        break
                    elif key in ("[",):
                        client.send_command(["multiply", "speed", 0.9])
                        break
                    elif key in ("0", "\x08", "\x7f"):
                        client.send_command(["set", "speed", 1.0])
                        break
                    elif key in ("s", "S", "/"):  # Buscar YouTube
                        exit_code = EXIT_SEARCH_SONGS
                        exit_requested = True
                        break
                    elif key in ("m", "M"):  # Buscar YouTube Music - Canciones
                        exit_code = EXIT_SEARCH_MUSIC
                        exit_requested = True
                        break
                    elif key in ("a", "A"):  # Buscar Álbumes
                        exit_code = EXIT_SEARCH_ALBUMS
                        exit_requested = True
                        break
                    elif key in ("l", "L"):  # Buscar Listas
                        exit_code = EXIT_SEARCH_PLAYLISTS
                        exit_requested = True
                        break
                    elif key in ("q", "Q", "\x1b"):  # Salir
                        exit_code = EXIT_OK
                        exit_requested = True
                        break
                time.sleep(0.02)

            if exit_requested:
                break

    except KeyboardInterrupt:
        _log("interrupted by user (KeyboardInterrupt)")
        exit_code = EXIT_OK
    except Exception:
        _log("EXCEPTION: " + traceback.format_exc().replace("\n", " | "))
        exit_code = EXIT_ERROR
    finally:
        client.close()
        restore_terminal()

    _log(f"yt_control exit rc={exit_code}")
    if exit_code == EXIT_OK:
        sys.stdout.write("\033[H\033[2J✨ Reproducción detenida.\n")
        sys.stdout.flush()

    sys.exit(exit_code)


if __name__ == "__main__":
    main()


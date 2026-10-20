#!/usr/bin/env python3
"""
ytm_control.py - Panel de control de reproducción responsive para YouTube Music
Usa mpv_client.py compartido para comunicación con mpv.
"""
import sys
import os
import time
import select
import tty
import termios
import shutil
import re
import subprocess
import unicodedata
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
        path = os.environ.get("LOG_FILE") or os.path.expanduser("~/.cache/ytm/events.log")
        with open(path, "a") as f:
            f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} [CTRL] | {msg}\n")
    except Exception:
        pass


# ── Colores ANSI ────────────────────────────────────────────────
class C:
    RST  = "\033[0m"
    BOLD = "\033[1m"
    DIM  = "\033[2m"
    RED  = "\033[31m";  GRN  = "\033[32m";  YLW  = "\033[33m"
    BLU  = "\033[34m";  MAG  = "\033[35m";  CYN  = "\033[36m";  WHT  = "\033[37m"
    BRED = "\033[1;31m"; BGRN = "\033[1;32m"; BYLW = "\033[1;33m"
    BBLU = "\033[1;34m"; BMAG = "\033[1;35m"; BCYN = "\033[1;36m"; BWHT = "\033[1;37m"
    HIDE = "\033[?25l";  SHOW = "\033[?25h"
    CLR  = "\033[2J";    HOME = "\033[H"


# ── Visual length ──────────────────────────────────────────────
def vis_len(s):
    w = 0
    for ch in s:
        eaw = unicodedata.east_asian_width(ch)
        w += 2 if eaw in ('W', 'F') else 1
    return w

def strip_ansi(s):
    return re.sub(r'\033\[[0-9;]*m', '', s)

def get_cols():
    try: return shutil.get_terminal_size().columns
    except Exception: return 80


# ── Box drawing ────────────────────────────────────────────────
def box_top(w):    return f"{C.BCYN}╭{'─' * (w - 2)}╮{C.RST}"
def box_mid(w):    return f"{C.BCYN}├{'─' * (w - 2)}┤{C.RST}"
def box_bot(w):    return f"{C.BCYN}╰{'─' * (w - 2)}╯{C.RST}"

def box_center(text, w, bc=C.BCYN):
    vl = vis_len(strip_ansi(text))
    inner = w - 2
    pad_l = max(0, (inner - vl) // 2)
    pad_r = max(0, inner - vl - pad_l)
    return f"{bc}│{C.RST}{' ' * pad_l}{text}{' ' * pad_r}{bc}│{C.RST}"

def box_blank(w, bc=C.BCYN):
    return f"{bc}│{C.RST}{' ' * (w - 2)}{bc}│{C.RST}"


# ── Utility functions ──────────────────────────────────────────
def fmt_time(seconds):
    if seconds is None: return "──:──"
    s = int(seconds)
    h, m, sec = s // 3600, (s % 3600) // 60, s % 60
    return f"{h:02d}:{m:02d}:{sec:02d}" if h > 0 else f"{m:02d}:{sec:02d}"


def progress_bar(pos, dur, w=30):
    if not dur or dur <= 0:
        return f"{C.DIM}{'░' * w}{C.RST}"
    pct = max(0.0, min(1.0, (pos or 0) / dur))
    n = int(pct * w)
    color = C.BCYN if pct < 0.3 else (C.BGRN if pct < 0.7 else C.BYLW)
    if n > 0:
        return f"{color}{'━' * (n-1)}◉{C.DIM}{'─' * (w - n)}{C.RST}"
    return f"{C.DIM}{'─' * w}{C.RST}"


def vol_str(vol, w=12):
    n = int((vol / 100) * w)
    color = C.BRED if vol > 80 else (C.BYLW if vol > 50 else C.BGRN)
    speaker = "🔊" if vol > 60 else ("🔉" if vol > 20 else ("🔈" if vol > 0 else "🔇"))
    return f"{speaker} {color}{'▮' * n}{C.DIM}{'▯' * (w - n)}{C.RST} {int(vol)}%"


def speed_str(speed):
    if speed == 1.0: return f"{C.BGRN}▶ 1.00x{C.RST}"
    if speed > 1.0:  return f"{C.BYLW}⏩ {speed:.2f}x{C.RST}"
    return f"{C.BCYN}⏪ {speed:.2f}x{C.RST}"


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
                r2, _, _ = select.select([fd], [], [], 0.1)
                if r2:
                    key += os.read(fd, 7).decode("utf-8", errors="ignore")
            return key
    except (OSError, IOError):
        pass
    return None


def flush_stdin():
    try:
        fd = sys.stdin.fileno()
        while True:
            rlist, _, _ = select.select([fd], [], [], 0.0)
            if not rlist: break
            if not os.read(fd, 1024): break
    except Exception: pass


def check_alive(pid):
    if pid is None: return True
    try: os.kill(pid, 0); return True
    except OSError: return False


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
        sys.stdout.write(f"{C.SHOW}{C.RST}\r\033[2K")
        sys.stdout.flush()
        flush_stdin()
    except Exception: pass
    if _SAVED_TERMIOS is not None:
        try:
            termios.tcsetattr(sys.stdin.fileno(), termios.TCSADRAIN, _SAVED_TERMIOS)
        except Exception:
            pass


# ── Main TUI ──────────────────────────────────────────────────
def main():
    if len(sys.argv) < 2:
        print(f"Uso: {sys.argv[0]} <socket_path> [mpv_pid]")
        sys.exit(EXIT_ERROR)

    socket_path = sys.argv[1]
    mpv_pid = int(sys.argv[2]) if len(sys.argv) > 2 else None
    _log(f"ytm_control v{VERSION} start | socket={socket_path} pid={mpv_pid}")

    client = mpv_client.MpvClient(socket_path)

    # Wait for mpv socket (up to 10s)
    connected = False
    for _ in range(100):
        if not check_alive(mpv_pid):
            _log("mpv process is dead before connect")
            break
        if client.connect():
            connected = True
            break
        time.sleep(0.1)

    if not connected:
        _log("connection failed (mpv dead or socket missing) -> rc=1")
        restore_terminal()
        # mpv no pudo iniciar o no creó el socket — error de conexión, no salida de usuario
        sys.exit(EXIT_ERROR)
    _log("connected to mpv")

    # Hide cursor, clear
    try:
        sys.stdout.write(f"{C.HOME}{C.CLR}{C.HIDE}")
        sys.stdout.flush()
    except Exception:
        pass

    # State
    st = {
        "title": "Cargando...", "duration": None, "pos": None,
        "paused": False, "volume": 100.0, "speed": 1.0,
        "t_pos": 0, "t_count": 1,
        "fb": "", "fb_t": 0,
    }

    props_q = ["media-title", "time-pos", "duration", "pause",
               "volume", "speed", "playlist-pos", "playlist-count", "path"]

    keys = [
        ("Espacio", "Pausar"),     ("◀▶", "-/+ 10s"),
        ("▲▼", "Volumen"),         ("n/b", "Sig/Ant"),
        ("d", "Descargar"),        ("D", "Álbum"),
        ("f", "Favorito"),
        ("s", "YouTube"),
        ("m/a/l", "Music/Á/Lista"), ("q/Esc", "Salir"),
    ]

    last_props_time = time.time()  # heartbeat tracker
    exit_code = EXIT_OK  # 0=user quit, 1=mpv error/connection lost

    enter_raw_mode()
    try:
        while True:
            # ── Heartbeat: detect mpv death ────────────────────
            now = time.time()
            if not check_alive(mpv_pid):
                exit_code = EXIT_ERROR
                break
            # If no successful IPC for 5s, try reconnect
            if client.seconds_since_ok() > 5.0:
                if not client.connect():
                    # Give it a few more seconds
                    if client.seconds_since_ok() > 8.0:
                        exit_code = EXIT_ERROR
                        break
                    time.sleep(0.1)
                    continue

            # ── Query mpv ──────────────────────────────────────
            props = {}
            try:
                props = client.get_properties(props_q)
            except Exception:
                props = {}

            if props:
                last_props_time = now
                if props.get("media-title"):     st["title"] = props["media-title"]
                if props.get("duration") is not None:    st["duration"] = props["duration"]
                if props.get("time-pos") is not None:    st["pos"] = props["time-pos"]
                if props.get("pause") is not None:       st["paused"] = bool(props["pause"])
                if props.get("volume") is not None:      st["volume"] = props["volume"]
                if props.get("speed") is not None:       st["speed"] = props["speed"]
                if props.get("playlist-pos") is not None and props["playlist-pos"] >= 0:
                    st["t_pos"] = props["playlist-pos"]
                if props.get("playlist-count") is not None and props["playlist-count"] > 0:
                    st["t_count"] = props["playlist-count"]
            else:
                # No response from mpv — if too long, consider dead
                if now - last_props_time > 8.0:
                    exit_code = EXIT_ERROR
                    break

            # Expire feedback
            if st["fb"] and (now - st["fb_t"] > 2.5):
                st["fb"] = ""

            # ── Render ─────────────────────────────────────────
            W = get_cols()
            lines = []

            lines.append(box_top(W))
            lines.append(box_center(f"{C.BMAG}{C.BOLD}♪  YouTube Music  ♪{C.RST}", W))
            lines.append(box_mid(W))
            lines.append(box_center(f"{C.BCYN}{C.BOLD}♫ Now Playing{C.RST}", W))
            lines.append(box_center(f"{C.DIM}[{st['t_pos'] + 1}/{st['t_count']}]{C.RST}", W))

            # Title (truncate by display width)
            title = st["title"]
            title_max_w = W - 6
            if vis_len(title) > title_max_w:
                truncated = ""
                cur_w = 0
                for ch in title:
                    cw = 2 if unicodedata.east_asian_width(ch) in ('W', 'F') else 1
                    if cur_w + cw + 3 > title_max_w:
                        truncated += "..."
                        break
                    truncated += ch
                    cur_w += cw
                title = truncated
            lines.append(box_center(f"{C.BWHT}{C.BOLD}{title}{C.RST}", W))
            lines.append(box_blank(W))

            # Progress
            pct = 0
            if st["duration"] and st["pos"] and st["duration"] > 0:
                pct = int((st["pos"] / st["duration"]) * 100)
            time_s = f"{fmt_time(st['pos'])} / {fmt_time(st['duration'])}"
            pct_s = f" {pct}%" if pct > 0 else ""
            bar_w = max(10, min(40, W - 30))
            bar = progress_bar(st["pos"], st["duration"], bar_w)
            lines.append(box_center(f"  {C.DIM}{time_s}{C.RST}  {bar}{C.DIM}{pct_s}{C.RST}", W))

            # Status
            status = f"{C.BGRN}▶ PLAY{C.RST}" if not st["paused"] else f"{C.BYLW}⏸ PAUSE{C.RST}"
            vol_s = vol_str(st["volume"], max(8, min(15, W // 8)))
            spd_s = speed_str(st["speed"])
            lines.append(box_center(f"{status}  {C.DIM}│{C.RST}  {vol_s}  {C.DIM}│{C.RST}  {spd_s}", W))
            lines.append(box_blank(W))
            lines.append(box_mid(W))

            # Key hints / feedback
            if st["fb"]:
                lines.append(box_center(f"{C.BYLW}⚡ {st['fb']}{C.RST}", W))
            else:
                mid = len(keys) // 2
                left_keys = keys[:mid]
                right_keys = keys[mid:]
                col_w = (W - 6) // 2
                for i in range(max(len(left_keys), len(right_keys))):
                    lp = ""
                    rp = ""
                    if i < len(left_keys):
                        k, v = left_keys[i]
                        lp = f"{C.BMAG}[{k}]{C.RST} {C.DIM}{v}{C.RST}"
                    if i < len(right_keys):
                        k, v = right_keys[i]
                        rp = f"{C.BMAG}[{k}]{C.RST} {C.DIM}{v}{C.RST}"
                    if lp and rp:
                        combined = f"  {lp}{' ' * max(1, col_w - vis_len(strip_ansi(lp)))}{rp}"
                    elif lp:
                        combined = f"  {lp}"
                    else:
                        combined = f"  {rp}"
                    lines.append(box_center(combined, W))

            lines.append(box_bot(W))

            # Flush
            try:
                output = C.HOME
                for ln in lines:
                    output += f"\033[2K{ln}\n"
                for _ in range(3):
                    output += "\033[2K\n"
                sys.stdout.write(output)
                sys.stdout.flush()
            except (OSError, IOError):
                pass

            # ── Keyboard ───────────────────────────────────────
            t0 = time.time()
            while time.time() - t0 < 0.25:
                key = get_key()
                if not key:
                    continue

                _log(f"key={key!r} t_pos={st['t_pos']} t_count={st['t_count']}")

                handled = True

                if key in (" ", "p", "P"):
                    client.send_command(["cycle", "pause"])
                    st["paused"] = not st["paused"]

                elif key in ("\x1b[C", "."):
                    client.send_command(["seek", 10, "relative"])

                elif key in ("\x1b[D", "h", ","):
                    client.send_command(["seek", -10, "relative"])

                elif key in ("\x1b[1;2C", "L", ">"):
                    client.send_command(["seek", 60, "relative"])
                    st["fb"] = "⏩ +60s"; st["fb_t"] = time.time()

                elif key in ("\x1b[1;2D", "H", "<"):
                    client.send_command(["seek", -60, "relative"])
                    st["fb"] = "⏪ -60s"; st["fb_t"] = time.time()

                elif key in ("\x1b[A", "k", "K", "+"):
                    client.send_command(["add", "volume", 5])
                    st["fb"] = f"🔊 Vol: {min(100, int(st['volume'] + 5))}%"
                    st["fb_t"] = time.time()

                elif key in ("\x1b[B", "j", "J", "-"):
                    client.send_command(["add", "volume", -5])
                    st["fb"] = f"🔉 Vol: {max(0, int(st['volume'] - 5))}%"
                    st["fb_t"] = time.time()

                elif key in ("n", "N"):
                    if st["t_count"] > 1 and st["t_pos"] < st["t_count"] - 1:
                        client.send_command(["playlist-next", "force"])
                        st["fb"] = "⏭ Siguiente pista"
                    elif st["t_count"] > 1:
                        st["fb"] = "ℹ Última pista"
                    elif st["t_count"] == 1:
                        st["fb"] = "ℹ Pista única"
                    else:
                        # conteo aún no leído por mpv: intentar navegación igual
                        client.send_command(["playlist-next", "force"])
                        st["fb"] = "⏭ Siguiente pista"
                    st["fb_t"] = time.time()

                elif key in ("b", "B"):
                    # En la primera pista, "playlist-prev force" hace que mpv
                    # detenga la reproducción y salga; reiniciar la pista.
                    if st["t_count"] > 1 and st["t_pos"] > 0:
                        client.send_command(["playlist-prev", "force"])
                        st["fb"] = "⏮ Pista anterior"
                    else:
                        client.send_command(["seek", 0, "absolute"])
                        st["fb"] = "⏮ Reiniciando pista"
                    st["fb_t"] = time.time()

                elif key in ("d", "D"):
                    download_dir = os.environ.get("DOWNLOAD_DIR", os.path.expanduser("~/Downloads"))
                    try:
                        os.makedirs(download_dir, exist_ok=True)
                    except OSError:
                        download_dir = os.path.expanduser("~/Downloads")

                    if key == "D":
                        # ── Descargar el álbum/playlist completo ──
                        fmt = os.environ.get("FORMAT", "bestaudio/best")
                        label = safe_name(os.environ.get("PLAYLIST_LABEL", ""))
                        if not label:
                            label = time.strftime("album_%Y%m%d_%H%M%S")
                        dest = os.path.join(download_dir, label)
                        try:
                            os.makedirs(dest, exist_ok=True)
                        except OSError:
                            st["fb"] = "❌ No se pudo crear la carpeta"
                            st["fb_t"] = time.time()
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
                                st["fb"] = f"⏬ Álbum ({total} pistas): {len(urls)} en descarga"
                            elif copied:
                                st["fb"] = f"✅ Álbum copiado: {copied} pistas"
                            else:
                                st["fb"] = "⚠️ No hay pistas descargables"
                            st["fb_t"] = time.time()
                            _log(f"DOWNLOAD_ALBUM total={total} urls={len(urls)} copied={copied} dest={dest}")
                    else:
                        # ── Descargar la canción actual ──
                        cache_dir = os.environ.get("CACHE_MEDIA_DIR", os.path.expanduser("~/.cache/ytm/media"))
                        curr_path = props.get("path") or ""
                        base = safe_name(st["title"]) or "track"
                        saved = False

                        # 1. Si mpv reproduce un archivo local (caché), copiarlo
                        if curr_path and os.path.isfile(curr_path):
                            ext = os.path.splitext(curr_path)[1] or ".webm"
                            dst = os.path.join(download_dir, f"{base}{ext}")
                            try:
                                shutil.copyfile(curr_path, dst)
                                st["fb"] = f"⚡ Guardado de caché: {os.path.basename(dst)[:20]}..."
                                st["fb_t"] = time.time()
                                saved = True
                            except OSError:
                                pass

                        # 2. Si no, buscar en la carpeta de caché por ID o URL
                        if not saved and curr_path and os.path.exists(cache_dir):
                            vid_match = re.search(r'(?:v=|youtu\.be/)([\w-]{11})', curr_path)
                            if vid_match:
                                vid = vid_match.group(1)
                                for cand in sorted(os.listdir(cache_dir)):
                                    if cand.startswith(vid) and not cand.endswith(('.part', '.ytdl', '.temp')):
                                        src = os.path.join(cache_dir, cand)
                                        ext = os.path.splitext(cand)[1]
                                        dst = os.path.join(download_dir, f"{base}{ext}")
                                        try:
                                            shutil.copyfile(src, dst)
                                            st["fb"] = f"⚡ Guardado de caché: {os.path.basename(dst)[:20]}..."
                                            st["fb_t"] = time.time()
                                            saved = True
                                            break
                                        except OSError:
                                            pass

                        # 3. Si mpv reproduce una URL, lanzar descarga en background con yt-dlp
                        if not saved and curr_path.startswith(("http://", "https://")):
                            fmt = os.environ.get("FORMAT", "bestaudio/best")
                            if spawn_ytdlp([curr_path], download_dir, fmt):
                                st["fb"] = "⏬ Descargando en segundo plano..."
                            else:
                                st["fb"] = "❌ Error en descarga"
                            st["fb_t"] = time.time()
                        elif not saved:
                            st["fb"] = "⚠️ Fuente desconocida"
                            st["fb_t"] = time.time()

                elif key in ("f", "F"):
                    fav_file = os.environ.get("FAVORITES_FILE", "")
                    vid = track_id(props.get("path") or "")
                    if not fav_file or not vid:
                        st["fb"] = "⚠️ No se pudo identificar la pista"
                    else:
                        res = toggle_favorite(fav_file, vid, st["title"])
                        if res is True:
                            st["fb"] = "⭐ Añadido a favoritos"
                        elif res is False:
                            st["fb"] = "☆ Quitado de favoritos"
                        else:
                            st["fb"] = "❌ Error de favoritos"
                        _log(f"FAVORITE vid={vid} added={res}")
                    st["fb_t"] = time.time()

                elif key == "]":
                    client.send_command(["multiply", "speed", 1.1])

                elif key == "[":
                    client.send_command(["multiply", "speed", 0.9])

                elif key in ("0", "\x08", "\x7f"):
                    client.send_command(["set", "speed", 1.0])
                    st["fb"] = "▶ Vel: 1.00x"; st["fb_t"] = time.time()

                elif key in ("r", "R"):
                    # Relacionados (r) / Radio continua (R) de la última canción
                    try:
                        action = "radio" if key == "R" else "related"
                        with open(os.path.expanduser("~/.cache/ytm/action"), "w") as f:
                            f.write(action)
                    except OSError:
                        pass
                    try:
                        client.send_command(["quit"])
                    except Exception:
                        pass
                    client._close_socket()
                    restore_terminal()
                    sys.exit(EXIT_SEARCH_SONGS)

                elif key in ("s", "S", "/"):
                    # Search YouTube - asegurar limpieza de mpv
                    try:
                        client.send_command(["quit"])
                    except Exception:
                        pass
                    client._close_socket()
                    restore_terminal()
                    sys.exit(EXIT_SEARCH_SONGS)

                elif key in ("m", "M"):
                    # Search Music (songs) - asegurar limpieza de mpv
                    try:
                        client.send_command(["quit"])
                    except Exception:
                        pass
                    client._close_socket()
                    restore_terminal()
                    sys.exit(EXIT_SEARCH_MUSIC)

                elif key in ("a", "A"):
                    # Search Albums - asegurar limpieza completa de mpv
                    try:
                        client.send_command(["quit"])
                    except Exception:
                        pass
                    client._close_socket()
                    restore_terminal()
                    sys.exit(EXIT_SEARCH_ALBUMS)

                elif key in ("l", "L"):
                    # Search Playlists - asegurar limpieza de mpv
                    try:
                        client.send_command(["quit"])
                    except Exception:
                        pass
                    client._close_socket()
                    restore_terminal()
                    sys.exit(EXIT_SEARCH_PLAYLISTS)

                elif key in ("q", "Q", "\x1b"):
                    # Quit
                    client.close()
                    try:
                        sys.stdout.write(f"{C.HOME}{C.CLR}✨ Música detenida.\n")
                        sys.stdout.flush()
                    except Exception: pass
                    sys.exit(EXIT_OK)

                else:
                    handled = False

                if handled:
                    break
                time.sleep(0.02)

    except KeyboardInterrupt:
        _log("interrupted by user (KeyboardInterrupt)")
    except Exception:
        _log("EXCEPTION: " + traceback.format_exc().replace("\n", " | "))
        exit_code = EXIT_ERROR
    finally:
        try: client._close_socket()
        except Exception: pass
        restore_terminal()

    # Normal end (mpv finished or heartbeat timeout)
    _log(f"ytm_control exit rc={exit_code}")
    try:
        if exit_code == EXIT_OK:
            sys.stdout.write(f"{C.HOME}{C.CLR}✨ Reproducción finalizada.\n")
        else:
            sys.stdout.write(f"{C.HOME}{C.CLR}⚠️  mpv cerró inesperadamente (código {exit_code}).\n")
        sys.stdout.flush()
    except Exception: pass
    sys.exit(exit_code)


if __name__ == "__main__":
    main()

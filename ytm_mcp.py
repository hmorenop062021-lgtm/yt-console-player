#!/usr/bin/env python3
"""
Servidor MCP (Model Context Protocol) para controlar yt/ytm
YouTube & YouTube Music Console Player desde un agente de IA.

Se comunica vía stdio (JSON-RPC línea por línea). Un cliente MCP
puede conectarse y usar las herramientas expuestas.
"""

import json
import sys
import os
import socket
import subprocess

# ── Rutas ────────────────────────────────────────────────────────
HOME = os.path.expanduser("~")
YTM_BIN = os.path.join(HOME, ".local/bin/ytm")
YT_BIN = os.path.join(HOME, ".local/bin/yt")
SOCKET_PATH = "/tmp/mpv-ytm.sock"
CACHE_DIR = os.path.join(HOME, ".cache/ytm")
LAST_SONG_FILE = os.path.join(CACHE_DIR, "last_song")
ACTION_FILE = os.path.join(CACHE_DIR, "action")


def mcp_response(result=None, error=None, rpc_id=None):
    resp = {"jsonrpc": "2.0"}
    if rpc_id is not None:
        resp["id"] = rpc_id
    if error is not None:
        resp["error"] = error
    else:
        resp["result"] = result or {}
    sys.stdout.write(json.dumps(resp, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def mpv_command(cmd, timeout=2.0):
    """Envía un comando al socket IPC de mpv y devuelve la respuesta."""
    if not os.path.exists(SOCKET_PATH):
        return {"error": "mpv socket not found"}
    try:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(timeout)
        s.connect(SOCKET_PATH)
        msg = json.dumps({"command": cmd}) + "\n"
        s.sendall(msg.encode("utf-8"))
        data = b""
        while True:
            chunk = s.recv(4096)
            if not chunk:
                break
            data += chunk
            if b"\n" in data:
                break
        s.close()
        if data:
            return json.loads(data.decode("utf-8").strip())
    except Exception as e:
        return {"error": str(e)}
    return {"error": "no response from mpv"}


def run_cmd(args, timeout=30):
    """Ejecuta un comando externo y devuelve salida/código."""
    try:
        proc = subprocess.run(
            args, capture_output=True, text=True, timeout=timeout
        )
        return {
            "stdout": proc.stdout,
            "stderr": proc.stderr,
            "rc": proc.returncode,
        }
    except subprocess.TimeoutExpired:
        return {"error": f"command timed out after {timeout}s"}
    except FileNotFoundError:
        return {"error": f"binary not found: {args[0]}"}
    except Exception as e:
        return {"error": str(e)}


def read_last_song():
    """Lee la última canción reproducida."""
    if not os.path.isfile(LAST_SONG_FILE):
        return None
    try:
        with open(LAST_SONG_FILE, "r", encoding="utf-8") as f:
            line = f.readline().strip()
        if not line:
            return None
        parts = line.split("\t")
        if len(parts) >= 3:
            return {"id": parts[0], "title": parts[1], "channel": parts[2]}
        return {"id": parts[0], "title": parts[1] if len(parts) > 1 else "", "channel": ""}
    except Exception:
        return None


# ── Definición de herramientas MCP ──────────────────────────────
TOOLS = [
    {
        "name": "search",
        "description": "Buscar canciones, álbumes o playlists en YouTube Music",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Término de búsqueda"},
                "type": {
                    "type": "string",
                    "enum": ["songs", "albums", "playlists"],
                    "default": "songs",
                    "description": "Tipo de búsqueda",
                },
                "limit": {"type": "integer", "default": 20, "description": "N° de resultados"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "play",
        "description": "Reproducir una búsqueda en ytm (lanza el reproductor)",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Término de búsqueda"},
                "type": {
                    "type": "string",
                    "enum": ["songs", "albums", "playlists"],
                    "default": "songs",
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "play_last",
        "description": "Reproducir la última canción",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "related",
        "description": "Buscar canciones similares (mismo canal/artista) de la última canción",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "radio",
        "description": "Iniciar radio continua de canciones relacionadas a la última",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "control",
        "description": "Controlar mpv (pause, next, prev, volume, seek, speed)",
        "inputSchema": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["pause", "next", "prev", "volume_up", "volume_down",
                             "seek_forward", "seek_backward", "speed_up", "speed_down",
                             "stop", "status"],
                    "description": "Acción a ejecutar",
                },
                "value": {
                    "type": "integer",
                    "default": 10,
                    "description": "Valor para seek (segundos) o volumen",
                },
            },
            "required": ["action"],
        },
    },
    {
        "name": "status",
        "description": "Obtener estado actual de reproducción de mpv",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "favorites_list",
        "description": "Listar canciones favoritas",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "favorites_toggle",
        "description": "Agregar o quitar la última canción de favoritos",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "last_song",
        "description": "Obtener información de la última canción reproducida",
        "inputSchema": {"type": "object", "properties": {}},
    },
]


# ── Handlers ────────────────────────────────────────────────────

def handle_search(args):
    query = args.get("query", "")
    search_type = args.get("type", "songs")
    limit = args.get("limit", 20)
    # No podemos interactuar con fzf desde MCP sin TTY, así que devolvemos
    # los resultados crudos de yt-dlp para que el IA los muestre.
    cmd = [YTM_BIN, "-l"]
    if search_type == "albums":
        cmd.append("-a")
    elif search_type == "playlists":
        cmd.append("-p")
    cmd.append("-n")
    cmd.append(str(limit))
    cmd.append(query)
    return run_cmd(cmd, timeout=60)


def handle_play(args):
    query = args.get("query", "")
    search_type = args.get("type", "songs")
    # Lanzar ytm en segundo plano (necesita TTY para fzf, pero el usuario
    # puede completarlo desde su terminal).
    cmd = [YTM_BIN]
    if search_type == "albums":
        cmd.append("-a")
    elif search_type == "playlists":
        cmd.append("-p")
    cmd.append(query)
    # Lanzar detached para no bloquear el servidor MCP
    subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return {"ok": True, "message": f"ytm lanzado: {query}"}


def handle_play_last(args):
    song = read_last_song()
    if not song:
        return {"error": "no hay última canción registrada"}
    subprocess.Popen(
        [YTM_BIN, f"{song['channel']} {song['title']}"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    return {"ok": True, "song": song}


def handle_related(args):
    song = read_last_song()
    if not song:
        return {"error": "no hay última canción registrada"}
    query = f"{song['channel']} {song['title']}"
    subprocess.Popen(
        [YTM_BIN, query],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    return {"ok": True, "query": query, "song": song}


def handle_radio(args):
    song = read_last_song()
    if not song:
        return {"error": "no hay última canción registrada"}
    # Escribir marker para activar RADIO_MODE en ytm
    os.makedirs(CACHE_DIR, exist_ok=True)
    with open(ACTION_FILE, "w", encoding="utf-8") as f:
        f.write("radio")
    query = f"{song['channel']} {song['title']}"
    subprocess.Popen(
        [YTM_BIN, query],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    return {"ok": True, "query": query, "song": song, "radio": True}


def handle_control(args):
    action = args.get("action", "")
    value = args.get("value", 10)

    mpv_map = {
        "pause": ["cycle", "pause"],
        "next": ["playlist-next", "force"],
        "prev": ["playlist-prev", "force"],
        "stop": ["quit"],
        "volume_up": ["add", "volume", value],
        "volume_down": ["add", "volume", -value],
        "seek_forward": ["seek", value, "relative"],
        "seek_backward": ["seek", -value, "relative"],
        "speed_up": ["multiply", "speed", 1.1],
        "speed_down": ["multiply", "speed", 0.9],
    }

    if action == "status":
        return handle_status({})

    if action not in mpv_map:
        return {"error": f"acción desconocida: {action}"}

    return mpv_command(mpv_map[action])


def handle_status(args):
    props = ["filename", "title", "artist", "album", "duration",
             "time-pos", "pause", "speed", "volume", "playlist-count",
             "playlist-pos"]
    result = {}
    for prop in props:
        result[prop] = mpv_command(["get_property", prop])
    return result


def handle_favorites_list(args):
    fav_file = os.path.join(HOME, ".config/ytm/favorites")
    if not os.path.isfile(fav_file):
        return {"favorites": []}
    favs = []
    try:
        with open(fav_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                parts = line.split("\t", 1)
                if len(parts) == 2:
                    favs.append({"id": parts[0], "title": parts[1]})
                else:
                    favs.append({"id": parts[0], "title": parts[0]})
    except Exception:
        pass
    return {"favorites": favs}


def handle_favorites_toggle(args):
    song = read_last_song()
    if not song:
        return {"error": "no hay última canción registrada"}
    # Usar yt_control.py toggle_favorite vía Python import
    sys.path.insert(0, os.path.dirname(YTM_BIN))
    try:
        import yt_control as YT
        import ytm_control as YTM
    except Exception as e:
        return {"error": f"no se pudo importar controles: {e}"}

    fav_file = os.path.join(HOME, ".config/ytm/favorites")
    added = YTM.toggle_favorite(fav_file, song["id"], song["title"])
    if added is None:
        return {"error": "error escribiendo favoritos"}
    return {"ok": True, "added": added, "song": song}


def handle_last_song(args):
    song = read_last_song()
    if not song:
        return {"error": "no hay última canción registrada"}
    return {"song": song}


HANDLERS = {
    "search": handle_search,
    "play": handle_play,
    "play_last": handle_play_last,
    "related": handle_related,
    "radio": handle_radio,
    "control": handle_control,
    "status": handle_status,
    "favorites_list": handle_favorites_list,
    "favorites_toggle": handle_favorites_toggle,
    "last_song": handle_last_song,
}


# ── Bucle MCP ───────────────────────────────────────────────────
def main():
    # Mensaje de bienvenida / capabilities
    while True:
        line = sys.stdin.readline()
        if not line:
            break
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            mcp_response(error={"code": -32700, "message": "Parse error"})
            continue

        rpc_id = msg.get("id")
        method = msg.get("method", "")
        params = msg.get("params", {})

        if method == "initialize":
            mcp_response(
                result={
                    "protocolVersion": "1.0.0",
                    "serverInfo": {"name": "ytm-mcp", "version": "1.0.0"},
                    "capabilities": {"tools": {}},
                },
                rpc_id=rpc_id,
            )
        elif method == "initialized":
            # Notificación, no respuesta
            pass
        elif method == "tools/list":
            mcp_response(result={"tools": TOOLS}, rpc_id=rpc_id)
        elif method == "tools/call":
            tool_name = params.get("name", "")
            tool_args = params.get("arguments", {})
            if tool_name not in HANDLERS:
                mcp_response(
                    error={"code": -32601, "message": f"Tool not found: {tool_name}"},
                    rpc_id=rpc_id,
                )
            else:
                try:
                    result = HANDLERS[tool_name](tool_args)
                    mcp_response(result=result, rpc_id=rpc_id)
                except Exception as e:
                    mcp_response(
                        error={"code": -32603, "message": str(e)},
                        rpc_id=rpc_id,
                    )
        elif method == "ping":
            mcp_response(result={}, rpc_id=rpc_id)
        else:
            mcp_response(
                error={"code": -32601, "message": f"Method not found: {method}"},
                rpc_id=rpc_id,
            )


if __name__ == "__main__":
    main()

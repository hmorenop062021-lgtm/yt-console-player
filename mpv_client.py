#!/usr/bin/env python3
"""
mpv_client.py - Shared MPV IPC client module

Provides a robust MPV Unix socket client for sending commands and retrieving properties.
Used by both yt_control.py and ytm_control.py to avoid code duplication.

Features:
- Automatic reconnection
- Non-blocking socket I/O
- Property querying with response parsing
- Command sending with error handling
- Heartbeat/last-ok tracking for connection health
"""

import socket
import json
import select
import time
import os


VERSION = "1.0.0"


class MpvClient:
    """
    MPV JSON-RPC client via Unix domain socket.
    
    Handles connection management, command sending, and property retrieval.
    Designed to be robust against network glitches and mpv crashes.
    """

    def __init__(self, socket_path):
        self.socket_path = socket_path
        self.sock = None
        self._buf = bytearray()
        self.req_counter = 0
        self._last_ok = time.time()

    def connect(self):
        """Connect to the MPV socket. Returns True on success."""
        self._close_socket()
        if not os.path.exists(self.socket_path):
            return False
        try:
            self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            self.sock.settimeout(0.5)
            self.sock.connect(self.socket_path)
            self.sock.setblocking(False)
            self._buf = bytearray()
            self._last_ok = time.time()
            return True
        except Exception:
            self._close_socket()
            return False

    def _close_socket(self):
        if self.sock:
            try:
                self.sock.close()
            except Exception:
                pass
            self.sock = None

    def is_connected(self):
        """Check if currently connected to MPV."""
        return self.sock is not None

    def seconds_since_ok(self):
        """Seconds elapsed since the last successful IPC interaction."""
        return time.time() - self._last_ok

    def send_command(self, cmd):
        """
        Send a command to MPV.
        
        Args:
            cmd: List of command elements (e.g., ["seek", 10, "relative"])
            
        Returns:
            True on success, False on failure
        """
        if not self.sock:
            if not self.connect():
                return False
        try:
            msg = json.dumps({"command": cmd}) + "\n"
            self.sock.sendall(msg.encode("utf-8"))
            self._last_ok = time.time()
            return True
        except OSError:
            self._close_socket()
            return False

    def get_properties(self, props):
        """
        Query multiple properties from MPV.

        Args:
            props: List of property names (e.g., ["media-title", "time-pos"])

        Returns:
            Dict of property name -> value
        """
        if not self.sock:
            if not self.connect():
                return {}

        wanted = {}
        for prop in props:
            self.req_counter += 1
            req_id = self.req_counter
            wanted[req_id] = prop
            try:
                msg = json.dumps({"command": ["get_property", prop], "request_id": req_id}) + "\n"
                self.sock.sendall(msg.encode("utf-8"))
            except OSError:
                self._close_socket()
                return {}

        results = {}
        deadline = time.time() + 0.3
        while wanted and time.time() < deadline:
            try:
                rlist, _, _ = select.select([self.sock], [], [], 0.05)
            except (OSError, ValueError):
                self._close_socket()
                return results
            if rlist:
                try:
                    chunk = self.sock.recv(65536)
                    if not chunk:
                        self._close_socket()
                        return results
                    self._buf.extend(chunk)
                except BlockingIOError:
                    pass
                except (OSError, socket.error):
                    self._close_socket()
                    return results
            # Parse every complete line available, resolving matching request ids
            while True:
                idx = self._buf.find(b"\n")
                if idx < 0:
                    break
                raw = bytes(self._buf[:idx])
                del self._buf[:idx + 1]
                line = raw.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                except (json.JSONDecodeError, ValueError):
                    continue
                rid = data.get("request_id")
                if rid in wanted:
                    results[wanted.pop(rid)] = data.get("data")
            # Tope defensivo: una línea incompleta gigante no debe crecer sin control
            if len(self._buf) > 1_048_576:
                self._buf.clear()

        if results:
            self._last_ok = time.time()
        return results

    def close(self):
        """Gracefully quit MPV and close the socket."""
        try:
            self.send_command(["quit"])
        except Exception:
            pass
        self._close_socket()
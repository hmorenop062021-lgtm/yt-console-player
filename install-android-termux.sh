#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════════════
#  Instalador de yt/ytm para Android (Termux)
#  Ejecutar dentro de Termux:
#    curl -sSL https://raw.githubusercontent.com/<usuario>/<repo>/main/install-android-termux.sh | bash
#  o copiar este archivo al dispositivo y correr: bash install-android-termux.sh
# ═══════════════════════════════════════════════════════════════════════════
set -euo pipefail

BIN_DIR="$HOME/.local/bin"
CACHE_YT="$HOME/.cache/yt"
CACHE_YTM="$HOME/.cache/ytm"
CFG_YT="$HOME/.config/yt"
CFG_YTM="$HOME/.config/ytm"

echo "[termux/android] actualizando índices de paquetes..."
pkg update -y

echo "[termux/android] instalando dependencias (mpv, yt-dlp, fzf, jq, python)..."
pkg install -y mpv yt-dlp fzf jq python

echo "[termux/android] concediendo acceso al almacenamiento interno (Descargas)..."
termux-setup-storage >/dev/null 2>&1 || true

echo "[termux/android] creando directorios..."
mkdir -p "$BIN_DIR" "$CACHE_YT" "$CACHE_YTM" "$CFG_YT" "$CFG_YTM" "$HOME/Downloads"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"

echo "[termux/android] desplegando yt ytm en $BIN_DIR..."
cp "$SCRIPT_DIR/yt" "$SCRIPT_DIR/ytm" "$BIN_DIR/"
chmod +x "$BIN_DIR/yt" "$BIN_DIR/ytm"

if ! grep -q '\.local/bin' "$HOME/.bashrc" 2>/dev/null; then
  echo 'export PATH="$HOME/.local/bin:$PATH"' >> "$HOME/.bashrc"
fi

export PATH="$BIN_DIR:$PATH"

echo ""
echo "[termux/android] instalado. Reinicia la sesión de Termux o ejecuta:"
echo "  export PATH=\"$BIN_DIR:\$PATH\""
echo ""
echo "Pruebas rápidas:"
echo "  yt -l metallica          # listar canciones (sin TTY interactiva)"
echo "  ytm -n 20 <búsqueda>     # reproductor con interfaz"
echo ""
echo "Nota: usa -k/--keep-awake solo si necesitas que la pantalla no se apague;"
echo "por defecto el inhibidor de sueño está desactivado para ahorrar RAM."

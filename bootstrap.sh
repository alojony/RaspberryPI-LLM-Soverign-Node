#!/bin/bash
# Pi Sovereign Node — Bootstrap Script
# Run once on a fresh Raspberry Pi OS Lite 64-bit install.
# Usage: bash bootstrap.sh

set -e

REPO_URL="https://github.com/jonpaper/pi-node.git"  # ← update this
INSTALL_DIR="$HOME/pi-node"
COMPOSE_VERSION="v2.24.0"

echo "==> Pi Sovereign Node Bootstrap"
echo ""

# ── Docker ────────────────────────────────────────────────────
if ! command -v docker &>/dev/null; then
  echo "==> Installing Docker..."
  curl -fsSL https://get.docker.com | sh
  sudo usermod -aG docker "$USER"
  echo ""
  echo "    Docker installed. You will need to log out and back in for group"
  echo "    membership to take effect. Re-run this script after relogging."
  echo ""
  exit 0
else
  echo "==> Docker already installed: $(docker --version)"
fi

# ── Docker Compose v2 plugin ──────────────────────────────────
if ! docker compose version &>/dev/null; then
  echo "==> Installing Docker Compose v2 plugin (aarch64)..."
  mkdir -p ~/.docker/cli-plugins
  curl -SL "https://github.com/docker/compose/releases/download/${COMPOSE_VERSION}/docker-compose-linux-aarch64" \
    -o ~/.docker/cli-plugins/docker-compose
  chmod +x ~/.docker/cli-plugins/docker-compose
  echo "    Compose installed: $(docker compose version)"
else
  echo "==> Docker Compose already installed: $(docker compose version)"
fi

# ── Clone repo ────────────────────────────────────────────────
if [ ! -d "$INSTALL_DIR" ]; then
  echo "==> Cloning repo to $INSTALL_DIR..."
  git clone "$REPO_URL" "$INSTALL_DIR"
else
  echo "==> Repo already at $INSTALL_DIR — pulling latest..."
  git -C "$INSTALL_DIR" pull
fi

# ── Data directories ──────────────────────────────────────────
echo "==> Creating data directories..."
mkdir -p "$INSTALL_DIR/data/models"
mkdir -p "$INSTALL_DIR/data/db"
mkdir -p "$INSTALL_DIR/data/qdrant"
touch "$INSTALL_DIR/data/db/.gitkeep"
touch "$INSTALL_DIR/data/qdrant/.gitkeep"
touch "$INSTALL_DIR/data/models/.gitkeep"

# ── .env ─────────────────────────────────────────────────────
if [ ! -f "$INSTALL_DIR/.env" ]; then
  echo ""
  echo "==> No .env found. Copying from .env.example..."
  cp "$INSTALL_DIR/.env.example" "$INSTALL_DIR/.env"
  echo ""
  echo "    !! Edit $INSTALL_DIR/.env before starting the stack."
  echo "    !! Key values to set:"
  echo "       MODEL_PATH   — path to your .gguf file inside the container"
  echo "       VAULT_HOST_PATH — path to your Obsidian vault on this machine"
  echo "       SEARCH_API_KEY  — Brave Search API key"
  echo "       TZ              — your timezone (e.g. America/Los_Angeles)"
else
  echo "==> .env already exists — skipping."
fi

# ── Model check ───────────────────────────────────────────────
echo ""
MODEL_COUNT=$(find "$INSTALL_DIR/data/models" -name "*.gguf" | wc -l)
if [ "$MODEL_COUNT" -eq 0 ]; then
  echo "==> No model found. Download Qwen2.5-7B Q4_K_M:"
  echo ""
  echo "    wget -P $INSTALL_DIR/data/models \\"
  echo "      https://huggingface.co/Qwen/Qwen2.5-7B-Instruct-GGUF/resolve/main/qwen2.5-7b-instruct-q4_k_m-00001-of-00002.gguf"
  echo ""
  echo "    wget -P $INSTALL_DIR/data/models \\"
  echo "      https://huggingface.co/Qwen/Qwen2.5-7B-Instruct-GGUF/resolve/main/qwen2.5-7b-instruct-q4_k_m-00002-of-00002.gguf"
  echo ""
else
  echo "==> Model files found:"
  find "$INSTALL_DIR/data/models" -name "*.gguf" -exec echo "      {}" \;
fi

# ── Done ─────────────────────────────────────────────────────
echo ""
echo "==> Bootstrap complete."
echo ""
echo "    Next steps:"
echo "    1. Edit .env:          nano $INSTALL_DIR/.env"
echo "    2. Download model      (if not already done, see above)"
echo "    3. Start the stack:    cd $INSTALL_DIR && docker compose up -d"
echo "    4. Open the UI:        http://$(hostname -I | awk '{print $1}'):8000/ui"
echo "    5. Ingest your vault:  curl -X POST http://localhost:8000/ingest"
echo ""

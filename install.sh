#!/bin/sh
# Install agent-sandbox from a GitHub release.
#
#   curl -fsSL https://raw.githubusercontent.com/superintelligenceco/agent-sandbox/main/install.sh | sh
#
# By default the script downloads the standalone `agent-sandbox` executable for
# your OS and CPU, checks it against the release's SHA256SUMS, and installs it
# into AGENT_SANDBOX_BIN_DIR. Run `agent-sandbox serve` to start the server.
#
# With AGENT_SANDBOX_INSTALL=compose, the script instead downloads the release's
# Docker Compose file into AGENT_SANDBOX_DIR, writes an API key to a .env file
# next to it (unless one exists), and runs `docker compose up -d --wait`. Run it
# again to upgrade: it keeps the key.
#
# Environment variables:
#   AGENT_SANDBOX_VERSION   release tag to install, for example v0.2.0 (default: latest)
#   AGENT_SANDBOX_INSTALL   `binary` (default) or `compose`
#   AGENT_SANDBOX_BIN_DIR   binary mode: install directory (default: $HOME/.local/bin)
#   AGENT_SANDBOX_DIR       compose mode: install directory (default: $HOME/.agent-sandbox)
#   AGENT_SANDBOX_API_KEY   compose mode: API key to use (default: a new random key)
#   AGENT_SANDBOX_PORT      compose mode: host port (default: 8080)
#   AGENT_SANDBOX_NO_START  compose mode: set to 1 to configure without starting

set -eu

REPO="superintelligenceco/agent-sandbox"
VERSION="${AGENT_SANDBOX_VERSION:-latest}"
MODE="${AGENT_SANDBOX_INSTALL:-binary}"

say() { printf 'agent-sandbox: %s\n' "$*"; }
die() { printf 'agent-sandbox: error: %s\n' "$*" >&2; exit 1; }

if command -v curl > /dev/null 2>&1; then
  fetch() { curl -fsSL -o "$2" "$1"; }
elif command -v wget > /dev/null 2>&1; then
  fetch() { wget -q -O "$2" "$1"; }
else
  die "install curl or wget"
fi

sha256() {
  if command -v sha256sum > /dev/null 2>&1; then
    sha256sum "$1" | awk '{ print $1 }'
  else
    shasum -a 256 "$1" | awk '{ print $1 }'
  fi
}

if [ "$VERSION" = latest ]; then
  url="https://github.com/$REPO/releases/latest/download"
else
  url="https://github.com/$REPO/releases/download/$VERSION"
fi

# download ASSET DEST: fetch a release file and check it against SHA256SUMS.
download() {
  fetch "$url/$1" "$2" || die "download failed: $url/$1"
  fetch "$url/SHA256SUMS" "$2.sums" || die "download failed: $url/SHA256SUMS"
  expected=$(awk -v f="$1" '$2 == f || $2 == "*" f { print $1 }' "$2.sums")
  rm -f "$2.sums"
  actual=$(sha256 "$2")
  if [ -z "$expected" ] || [ "$expected" != "$actual" ]; then
    rm -f "$2"
    die "checksum mismatch for $1"
  fi
}

install_binary() {
  case "$(uname -s)" in
    Linux) os=linux ;;
    Darwin) os=macos ;;
    *) die "unsupported OS $(uname -s); download a release file by hand from https://github.com/$REPO/releases" ;;
  esac
  case "$(uname -m)" in
    x86_64 | amd64) arch=x86_64 ;;
    aarch64 | arm64) arch=aarch64 ;;
    *) die "unsupported CPU $(uname -m)" ;;
  esac
  if [ "$os" = macos ]; then
    [ "$arch" = aarch64 ] || die "the macOS executable is built for Apple silicon only; use pip install sic-agent-sandbox[server]"
    arch=arm64
  fi
  asset="agent-sandbox-$os-$arch"
  bin_dir="${AGENT_SANDBOX_BIN_DIR:-$HOME/.local/bin}"
  mkdir -p "$bin_dir"
  say "downloading $asset ($VERSION) into $bin_dir"
  download "$asset" "$bin_dir/agent-sandbox.new"
  chmod 0755 "$bin_dir/agent-sandbox.new"
  mv "$bin_dir/agent-sandbox.new" "$bin_dir/agent-sandbox"
  say "installed $("$bin_dir/agent-sandbox" --version)"
  case ":$PATH:" in
    *":$bin_dir:"*) ;;
    *) say "add $bin_dir to your PATH to run agent-sandbox from anywhere" ;;
  esac
  say "start the server with: AGENT_SANDBOX_API_KEYS=\$(openssl rand -hex 24) agent-sandbox serve"
}

install_compose() {
  case "$(uname -s)" in
    Linux) ;;
    Darwin) say "macOS works through Docker Desktop, but the server is tested on Linux only" ;;
    *) die "unsupported OS $(uname -s); the server needs a Linux Docker host" ;;
  esac
  case "$(uname -m)" in
    x86_64 | amd64 | aarch64 | arm64) ;;
    *) die "unsupported CPU $(uname -m); the image is built for amd64 and arm64" ;;
  esac
  command -v docker > /dev/null 2>&1 || die "docker is not installed: https://docs.docker.com/engine/install/"
  docker compose version > /dev/null 2>&1 || die "the Docker Compose plugin is missing: https://docs.docker.com/compose/install/"
  docker info > /dev/null 2>&1 || die "can't reach the Docker daemon; start it or add your user to the docker group"

  dir="${AGENT_SANDBOX_DIR:-$HOME/.agent-sandbox}"
  mkdir -p "$dir"
  cd "$dir"
  say "downloading the Compose file ($VERSION) into $dir"
  download docker-compose.yml docker-compose.yml.new
  mv docker-compose.yml.new docker-compose.yml

  if [ ! -f .env ]; then
    key="${AGENT_SANDBOX_API_KEY:-}"
    if [ -z "$key" ]; then
      key=$(od -An -N24 -tx1 /dev/urandom | tr -d ' \n')
    fi
    umask 077
    {
      echo "AGENT_SANDBOX_API_KEY=$key"
      echo "AGENT_SANDBOX_PORT=${AGENT_SANDBOX_PORT:-8080}"
    } > .env
    say "wrote a new API key to $dir/.env"
  fi

  if [ "${AGENT_SANDBOX_NO_START:-0}" = 1 ]; then
    say "configured; start the server with: cd $dir && docker compose up -d"
    return 0
  fi

  say "starting the server"
  docker compose pull --quiet
  docker compose up -d --wait
  port=$(awk -F= '$1 == "AGENT_SANDBOX_PORT" { print $2 }' .env)
  say "the API listens on http://localhost:${port:-8080}"
  say "your API key is in $dir/.env; stop the server with: cd $dir && docker compose down"
}

case "$MODE" in
  binary) install_binary ;;
  compose) install_compose ;;
  *) die "AGENT_SANDBOX_INSTALL must be binary or compose, got $MODE" ;;
esac

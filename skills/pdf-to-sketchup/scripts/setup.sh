#!/bin/sh
# Bootstrap without requiring Python, Homebrew, or administrator access.
set -eu

skill_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
runtime_root=${PDF2SKP_RUNTIME_DIR:-"$HOME/.local/share/pdf2skp-skill"}
mkdir -p "$runtime_root/tools"

uv_path="$runtime_root/tools/uv"
if [ ! -x "$uv_path" ]; then
    if command -v uv >/dev/null 2>&1; then
        uv_path=$(command -v uv)
    else
        installer=$(mktemp "$runtime_root/tools/uv-install.XXXXXX")
        trap 'rm -f "$installer"' EXIT HUP INT TERM
        curl --proto '=https' --tlsv1.2 -fLsS https://astral.sh/uv/install.sh -o "$installer"
        UV_UNMANAGED_INSTALL="$runtime_root/tools" sh "$installer"
        rm -f "$installer"
        trap - EXIT HUP INT TERM
    fi
fi

export UV_CACHE_DIR="$runtime_root/cache"
export UV_PYTHON_CACHE_DIR="$runtime_root/python-cache"
export UV_PYTHON_INSTALL_DIR="$runtime_root/python"
export PYTHONDONTWRITEBYTECODE=1
export PYTHONUTF8=1
python_path="$runtime_root/.venv/bin/python"
if [ ! -x "$python_path" ]; then
    if [ -e "$runtime_root/.venv" ]; then
        echo "Existing runtime is incomplete: $runtime_root/.venv" >&2
        exit 1
    fi
    "$uv_path" --no-config venv --python "${PDF2SKP_PYTHON:-3.12}" "$runtime_root/.venv"
fi
"$uv_path" --no-config pip install --python "$python_path" -r "$skill_root/requirements.txt"
exec "$python_path" "$skill_root/scripts/check_runtime.py" --runtime-root "$runtime_root" "$@"

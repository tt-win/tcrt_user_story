#!/usr/bin/env bash
set -euo pipefail

# Test Case Repository Web Tool - dependency installer
# - Creates a Python virtualenv and installs requirements
# - Optionally installs JS libraries (Bootstrap 5, Font Awesome) via npm
# - Copies JS/CSS assets into app/static/vendor for offline/local serving

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENVDIR="${PROJECT_ROOT}/.venv"
REQ_FILE="${PROJECT_ROOT}/requirements.txt"
VENDOR_DIR="${PROJECT_ROOT}/app/static/vendor"
USE_LOCAL_JS=false

function usage() {
  cat << USAGE
Usage: $(basename "$0") [--local-js]

Options:
  --local-js   Install JS libs locally (Bootstrap 5, Font Awesome) and copy to app/static/vendor

By default, only Python dependencies are installed (CDN is used for JS in templates).
USAGE
}

if [[ ${#} -gt 0 ]]; then
  case "${1:-}" in
    --local-js) USE_LOCAL_JS=true ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $1"; usage; exit 2 ;;
  esac
fi

echo "==> Python: creating virtual environment at ${VENVDIR}"
PYTHON_BIN="${PYTHON_BIN:-python3}"
if ! command -v "${PYTHON_BIN}" >/dev/null 2>&1; then
  echo "Error: python3 not found. Please install Python 3.10+ and retry." >&2
  exit 1
fi

"${PYTHON_BIN}" -m venv "${VENVDIR}"
source "${VENVDIR}/bin/activate"
python -m pip install --upgrade pip wheel

if [[ ! -f "${REQ_FILE}" ]]; then
  echo "Error: requirements.txt not found at ${REQ_FILE}" >&2
  exit 1
fi

echo "==> Installing Python dependencies from requirements.txt"
pip install -r "${REQ_FILE}"

echo "==> Python dependencies installed successfully"

if [[ "${USE_LOCAL_JS}" == "true" ]]; then
  echo "==> Installing JS libraries locally (Bootstrap 5, Font Awesome)"
  if ! command -v npm >/dev/null 2>&1; then
    echo "Error: npm is required for --local-js but was not found. Install Node.js (v18+) and retry." >&2
    exit 1
  fi

  pushd "${PROJECT_ROOT}" >/dev/null
  # Use a dedicated prefix to avoid polluting project root
  WEB_PREFIX_DIR="${PROJECT_ROOT}/.web_vendor"
  mkdir -p "${WEB_PREFIX_DIR}"

  # Initialize a minimal package.json if absent
  if [[ ! -f "${WEB_PREFIX_DIR}/package.json" ]]; then
    echo "{}" > "${WEB_PREFIX_DIR}/package.json"
  fi

  echo "==> npm installing bootstrap@5 @fortawesome/fontawesome-free"
  npm --prefix "${WEB_PREFIX_DIR}" install bootstrap@5 @fortawesome/fontawesome-free@6 >/dev/null

  echo "==> Copying assets into ${VENDOR_DIR}"
  # Bootstrap
  mkdir -p "${VENDOR_DIR}/bootstrap/css" "${VENDOR_DIR}/bootstrap/js"
  cp "${WEB_PREFIX_DIR}/node_modules/bootstrap/dist/css/bootstrap.min.css" "${VENDOR_DIR}/bootstrap/css/" || true
  cp "${WEB_PREFIX_DIR}/node_modules/bootstrap/dist/js/bootstrap.bundle.min.js" "${VENDOR_DIR}/bootstrap/js/" || true

  # Font Awesome
  mkdir -p "${VENDOR_DIR}/fontawesome/css" "${VENDOR_DIR}/fontawesome/webfonts"
  cp "${WEB_PREFIX_DIR}/node_modules/@fortawesome/fontawesome-free/css/all.min.css" "${VENDOR_DIR}/fontawesome/css/" || true
  cp -R "${WEB_PREFIX_DIR}/node_modules/@fortawesome/fontawesome-free/webfonts/." "${VENDOR_DIR}/fontawesome/webfonts/" || true

  popd >/dev/null

  echo "==> Local JS installation complete"
  echo "Note: Templates currently use CDN. To use local assets, update <link>/<script> tags to point to /static/vendor/..."
fi

echo "\nAll done. Activate the venv with:"
echo "  source ${VENVDIR}/bin/activate"
echo "Then run the app as you usually do."


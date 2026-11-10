# Shared paths for the macOS scripts. Sourcing this file does not start anything.

macos_package_root() {
  local dir
  dir="$(cd "$(dirname "${BASH_SOURCE[1]}")" && pwd)"
  cd "$dir/../.." && pwd
}

macos_python() {
  local venv="${HOME}/Library/Application Support/ProtonMailMCP/runtimes/venv/bin/python3"
  if [[ -n "${PYTHON_EXE:-}" ]]; then
    if [[ "${PYTHON_EXE}" != /* || ! -x "${PYTHON_EXE}" ]]; then
      echo "PYTHON_EXE must be a full path to python" >&2
      return 1
    fi
    printf '%s\n' "${PYTHON_EXE}"
    return 0
  fi
  if [[ ! -x "${venv}" ]]; then
    echo "Python runtime was not found. Run scripts/macos/install.sh first." >&2
    return 1
  fi
  printf '%s\n' "${venv}"
}

macos_refuse_xtrace() {
  case $- in
    *x*)
      echo "Refusing to run with shell tracing." >&2
      exit 2
      ;;
  esac
}

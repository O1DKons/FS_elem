#!/bin/zsh
set -u
cd -- "${0:A:h}" || exit 1

fs_elem_pause() {
  if [[ -t 0 ]]; then
    printf '\nНажмите Enter, чтобы закрыть окно. '
    read -r
  fi
}

fs_elem_node=".runtime/bin/node"
if [[ ! -x "$fs_elem_node" ]]; then
  fs_elem_node="$(command -v node 2>/dev/null || true)"
fi
if [[ -z "$fs_elem_node" ]]; then
  printf 'FS_elem: нужен Node.js 24. Установите его и выполните первоначальную настройку.\nИнструкция: docs/release/installation.md\n'
  fs_elem_pause
  exit 1
fi
fs_elem_major="$("$fs_elem_node" -p 'process.versions.node.split(".")[0]' 2>/dev/null || true)"
if [[ "$fs_elem_major" != 24 ]]; then
  printf 'FS_elem: нужен Node.js 24, найдено: %s.\nИнструкция: docs/release/installation.md\n' "${fs_elem_major:-неизвестно}"
  fs_elem_pause
  exit 1
fi

"$fs_elem_node" scripts/start-release.mjs --open "$@"
fs_elem_status=$?
if (( fs_elem_status != 0 )); then
  printf '\nFS_elem не запущен. Сохраните сообщение выше; настройка описана в docs/release/installation.md.\n'
  fs_elem_pause
fi
exit "$fs_elem_status"

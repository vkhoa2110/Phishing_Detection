#!/usr/bin/env bash
cd -- "$(dirname -- "${BASH_SOURCE[0]}")" || exit 1
if [[ ! -x .venv/bin/python ]]; then
  echo "Chưa có môi trường .venv. Hãy làm theo README.md."
  read -r -p "Nhấn Enter để đóng…"
  exit 1
fi
.venv/bin/python launch.py "$@"
result=$?
if [[ $result -ne 0 && -t 0 ]]; then read -r -p "Nhấn Enter để đóng…"; fi
exit "$result"

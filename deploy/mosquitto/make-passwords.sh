#!/usr/bin/env bash
# Creates deploy/mosquitto/passwd for the users in the ACL file.
# Usage: ./make-passwords.sh <backend-pw> <device-m01-pw> <simulator-pw>
set -euo pipefail
[ $# -eq 3 ] || { echo "usage: $0 <backend-pw> <device-m01-pw> <simulator-pw>"; exit 1; }
cd "$(dirname "$0")"
rm -f passwd
for pair in "backend:$1" "device-m01:$2" "simulator:$3"; do
  user="${pair%%:*}"; pw="${pair#*:}"
  if [ -f passwd ]; then flag="-b"; else flag="-c -b"; fi
  docker run --rm -v "$PWD:/work" eclipse-mosquitto:2 mosquitto_passwd $flag /work/passwd "$user" "$pw"
done
# mosquitto_passwd writes the file 0600 as root, but the broker runs as an
# unprivileged user inside the container and must be able to read it.
chmod 0644 passwd
echo "Created $(pwd)/passwd"

#!/usr/bin/env bash
# Download a complete, checksummed release. Run as root, or through sudo bash.
set -Eeuo pipefail
umask 077
REPO=DKardash/aegis-redirection
if [[ ${EUID} -ne 0 ]]; then
  echo 'Запустите из root-shell (sudo -i) либо скачайте скрипт и выполните sudo bash update.sh.' >&2
  exit 1
fi
for cmd in curl python3; do command -v "$cmd" >/dev/null || { echo "Нужен $cmd" >&2; exit 1; }; done
TEMP_DIR=$(mktemp -d /tmp/aegis-download.XXXXXXXX)
trap 'rm -rf -- "$TEMP_DIR"' EXIT
VERSION=latest
if [[ ${1:-} == --version ]]; then VERSION=${2:?Укажите v1.0.0}; shift 2; fi
if [[ "$VERSION" == latest ]]; then
  URL="https://github.com/$REPO/releases/latest/download"
elif [[ "$VERSION" =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
  URL="https://github.com/$REPO/releases/download/$VERSION"
else
  echo 'Неверная версия: ожидается v1.0.0' >&2; exit 1
fi
for file in aegis-redirection.tar.gz SHA256SUMS; do
  curl --fail --silent --show-error --location --proto '=https' --tlsv1.2 \
    --retry 3 --connect-timeout 15 --max-time 300 "$URL/$file" -o "$TEMP_DIR/$file"
done
# Validate before extracting or executing downloaded Python code. Reject links,
# devices, traversal and duplicate archive names; do not trust tar metadata.
python3 - "$TEMP_DIR" <<'PY'
import hashlib, pathlib, sys, tarfile
root = pathlib.Path(sys.argv[1])
archive = root / 'aegis-redirection.tar.gz'
lines = (root / 'SHA256SUMS').read_text().splitlines()
matches = [line.split()[0] for line in lines if len(line.split()) == 2 and line.split()[1] == 'aegis-redirection.tar.gz']
if len(matches) != 1 or hashlib.sha256(archive.read_bytes()).hexdigest() != matches[0]:
    raise SystemExit('Контрольная сумма релиза не совпадает')
seen = set()
with tarfile.open(archive) as tf:
    members = tf.getmembers()
    if sum(m.size for m in members) > 50 * 1024 * 1024:
        raise SystemExit('Архив слишком большой')
    for m in members:
        p = pathlib.PurePosixPath(m.name)
        if p.is_absolute() or '..' in p.parts or '\\' in m.name or m.name in seen or not (m.isfile() or m.isdir()):
            raise SystemExit('Недопустимая запись архива')
        seen.add(m.name)
        out = root / 'release' / p
        if m.isdir():
            out.mkdir(parents=True, exist_ok=True)
        else:
            out.parent.mkdir(parents=True, exist_ok=True)
            with tf.extractfile(m) as src, out.open('wb') as dst:
                dst.write(src.read())
PY
python3 "$TEMP_DIR/release/scripts/updater.py" "$@"

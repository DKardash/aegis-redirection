"""Build from an explicit allowlist; never package VM state or address lists."""
import hashlib
import io
import re
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def build():
    version = (ROOT / 'VERSION').read_text().strip()
    if not re.fullmatch(r'\d+\.\d+\.\d+', version):
        raise ValueError('Invalid VERSION')
    out = ROOT / 'dist'
    out.mkdir(exist_ok=True)
    archive = out / 'aegis-redirection.tar.gz'
    files = [ROOT / name for name in ('VERSION', 'requirements.txt', 'update.sh', 'README.md')]
    for folder, suffixes in [('app', {'.py'}), ('web', {'.html', '.js', '.css'}), ('scripts', {'.py'})]:
        files.extend(p for p in (ROOT / folder).rglob('*') if p.is_file() and p.suffix in suffixes and '__pycache__' not in p.parts)
    with tarfile.open(archive, 'w:gz') as tf:
        for path in sorted(files):
            info = tarfile.TarInfo(path.relative_to(ROOT).as_posix())
            data = path.read_bytes().replace(b'\r\n', b'\n')
            info.size, info.mode, info.mtime = len(data), 0o644, 0
            tf.addfile(info, io.BytesIO(data))
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    (out / 'SHA256SUMS').write_text(digest + '  ' + archive.name + '\n', encoding='ascii')
    print(f'Built v{version}: {archive.name}, {archive.stat().st_size} bytes')


if __name__ == '__main__':
    build()

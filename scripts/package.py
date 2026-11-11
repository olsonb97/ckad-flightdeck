"""Build the source-only coworker ZIP from an explicit distribution allowlist."""
import argparse
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parents[1]
FILES = (
    '.dockerignore', '.env.example', 'Dockerfile', 'LICENSE', 'README.md',
    'compose.yaml', 'requirements.txt', 'start.cmd', 'start.ps1', 'start.sh',
    'app/shellrc', 'docs/QUESTION_CATALOG.md', 'docs/SOURCES.md',
    'scripts/package.py', 'scripts/migrate-identities.ps1', 'scripts/migrate-identities.sh',
    'scripts/diagnostics.sh', 'scripts/browser_smoke.py', 'scripts/tutor_browser_smoke.py',
)
PATTERNS = ('app/*.py', 'app/static/*.js', 'app/static/*.css', 'app/static/*.html',
            'app/static/vendor/*.js', 'app/static/vendor/*.css', 'app/static/vendor/*.txt', 'tests/test_*.py')


def package(output):
    paths = {ROOT/name for name in FILES}
    for pattern in PATTERNS:
        paths.update(ROOT.glob(pattern))
    for path in paths:
        if not path.is_file() or path.is_symlink():
            raise ValueError('Missing or non-regular distribution file: '+str(path))
    output = Path(output).resolve()
    if output in paths:
        raise ValueError('The archive cannot replace a source file.')
    with zipfile.ZipFile(output, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(paths):
            name = 'ckad-flightdeck/'+path.relative_to(ROOT).as_posix()
            info = zipfile.ZipInfo(name)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 3
            info.external_attr = (0o100755 if path.suffix == '.sh' else 0o100644) << 16
            archive.writestr(info, path.read_bytes())
    return len(paths)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT/'ckad-flightdeck-share.zip')
    args = parser.parse_args()
    print(f'Packaged {package(args.output)} source files: {args.output.resolve()}')

"""One explicit repository base; strict POSIX paths for all active references."""
from pathlib import Path, PurePosixPath, PureWindowsPath


def repository(root=None):
    return Path(root).resolve() if root is not None else Path(__file__).resolve().parents[3]


def resolve(root, value):
    if not isinstance(value, str) or not value or '\\' in value or ':' in value:
        raise ValueError('repository-relative POSIX path required')
    p = PurePosixPath(value)
    if p.is_absolute() or PureWindowsPath(value).is_absolute() or any(
            x in ('', '.', '..') for x in value.split('/')):
        raise ValueError('unsafe relative path')
    base = repository(root)
    target = base.joinpath(*p.parts)
    if not target.resolve().is_relative_to(base):
        raise ValueError('path escapes repository through link')
    for parent in (target, *target.parents):
        if parent == base:
            break
        if parent.is_symlink() or (hasattr(parent, 'is_junction') and parent.is_junction()):
            raise ValueError('redirected path')
    return target


def relative(root, path):
    value = Path(path).resolve().relative_to(repository(root)).as_posix()
    resolve(root, value)
    return value

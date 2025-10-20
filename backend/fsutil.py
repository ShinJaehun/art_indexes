import os, io, tempfile


def _fsync_dir(dir_path: str) -> None:
    try:
        dfd = os.open(dir_path, os.O_RDONLY)
        try:
            os.fsync(dfd)
        finally:
            os.close(dfd)
    except OSError:
        pass


def _inherit_mode(src_path: str, tmp_path: str) -> None:
    try:
        st = os.stat(src_path)
        os.chmod(tmp_path, st.st_mode & 0o777)
    except FileNotFoundError:
        pass


def _atomic_replace(src_tmp: str, dst_path: str) -> None:
    dst_dir = os.path.dirname(os.path.abspath(dst_path)) or "."
    os.replace(src_tmp, dst_path)
    _fsync_dir(dst_dir)


def atomic_write_bytes(
    dst_path: str, data: bytes, *, inherit_mode: bool = True
) -> None:
    dst_path = os.path.abspath(dst_path)
    dst_dir = os.path.dirname(dst_path) or "."
    os.makedirs(dst_dir, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(prefix=".tmp-", dir=dst_dir)
    try:
        with os.fdopen(fd, "wb", closefd=True) as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        if inherit_mode:
            _inherit_mode(dst_path, tmp_path)
        _atomic_replace(tmp_path, dst_path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def atomic_write_text(
    dst_path: str,
    text: str,
    *,
    encoding="utf-8",
    newline="\n",
    inherit_mode: bool = True
) -> None:
    import io as _io, tempfile as _tempfile

    dst_path = os.path.abspath(dst_path)
    dst_dir = os.path.dirname(dst_path) or "."
    os.makedirs(dst_dir, exist_ok=True)
    fd, tmp_path = _tempfile.mkstemp(prefix=".tmp-", dir=dst_dir)
    try:
        with _io.open(fd, "w", encoding=encoding, newline=newline, closefd=True) as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        if inherit_mode:
            _inherit_mode(dst_path, tmp_path)
        _atomic_replace(tmp_path, dst_path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise

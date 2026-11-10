"""Apply a unified diff. Enough for this repo's patches, with no ``patch`` binary."""
from __future__ import annotations

import re
from pathlib import Path

_HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")


class UnifiedDiffError(ValueError):
    pass


class _Line:
    def __init__(self, kind: str, text: str, newline: bool = True) -> None:
        self.kind = kind
        self.text = text
        self.newline = newline


class _File:
    def __init__(self, path: str) -> None:
        self.path = path
        self.hunks: list[tuple[int, list[_Line]]] = []


class _FileLines:
    def __init__(self, lines: list[tuple[str, bool]]) -> None:
        self.lines = lines

    def match(self, start: int, old: list[_Line]) -> bool:
        if start < 0 or start + len(old) > len(self.lines):
            return False
        for offset, wanted in enumerate(old):
            text, newline = self.lines[start + offset]
            if text != wanted.text or newline != wanted.newline:
                return False
        return True

    def apply(self, start: int, old: list[_Line], new: list[_Line]) -> None:
        replacement = [(line.text, line.newline) for line in new]
        self.lines[start : start + len(old)] = replacement

    def render(self) -> str:
        return "".join(text + ("\n" if newline else "") for text, newline in self.lines)


def apply_unified_diff(root: Path, diff_text: str) -> None:
    """Apply ``diff_text`` under ``root``. Raises if context does not match."""
    for parsed in _parse(diff_text):
        if parsed.path.startswith("/") or ".." in Path(parsed.path).parts:
            raise UnifiedDiffError("patch path is not inside the tree")
        destination = root / parsed.path
        _apply_file(destination, parsed)


def _parse(diff_text: str) -> list[_File]:
    lines = diff_text.splitlines(keepends=True)
    start = 0
    for index, line in enumerate(lines):
        if line.startswith("diff ") or line.startswith("--- "):
            start = index
            break
    else:
        raise UnifiedDiffError("patch has no diff")
    files: list[_File] = []
    current: _File | None = None
    hunk_lines: list[_Line] | None = None
    hunk_start = 0
    index = start
    while index < len(lines):
        line = lines[index]
        if line.startswith("diff "):
            _finish_hunk(current, hunk_start, hunk_lines)
            hunk_lines = None
            index += 1
            continue
        if (
            line.startswith("--- ")
            and index + 1 < len(lines)
            and lines[index + 1].startswith("+++ ")
        ):
            _finish_hunk(current, hunk_start, hunk_lines)
            hunk_lines = None
            path = _header_path(lines[index + 1])
            current = _File(path)
            files.append(current)
            index += 2
            continue
        if line.startswith("@@"):
            _finish_hunk(current, hunk_start, hunk_lines)
            match = _HUNK.match(line)
            if match is None or current is None:
                raise UnifiedDiffError("patch hunk could not be read")
            hunk_start = int(match.group(1))
            hunk_lines = []
            index += 1
            continue
        if hunk_lines is None:
            if line.startswith("index ") or line.startswith("new file") or line.startswith("deleted file"):
                index += 1
                continue
            if line.strip() == "":
                index += 1
                continue
            raise UnifiedDiffError("patch hunk could not be read")
        if line.startswith("\\"):
            if not hunk_lines:
                raise UnifiedDiffError("patch hunk could not be read")
            hunk_lines[-1].newline = False
            index += 1
            continue
        kind = line[0]
        if kind not in " +-":
            raise UnifiedDiffError("patch hunk could not be read")
        text = line[1:]
        newline = True
        if text.endswith("\n"):
            text = text[:-1]
            if text.endswith("\r"):
                text = text[:-1]
        else:
            newline = False
        hunk_lines.append(_Line(kind, text, newline))
        index += 1
    _finish_hunk(current, hunk_start, hunk_lines)
    if not files:
        raise UnifiedDiffError("patch has no diff")
    return files


def _finish_hunk(current: _File | None, start: int, hunk_lines: list[_Line] | None) -> None:
    if hunk_lines is None:
        return
    if current is None:
        raise UnifiedDiffError("patch hunk could not be read")
    current.hunks.append((start, hunk_lines))


def _header_path(line: str) -> str:
    text = line[4:].strip()
    if "\t" in text:
        text = text.split("\t", 1)[0].strip()
    if text == "/dev/null":
        raise UnifiedDiffError("patch creates or deletes a file")
    if text.startswith("b/") or text.startswith("a/"):
        text = text[2:]
    if not text or text.startswith("/") or ".." in Path(text).parts:
        raise UnifiedDiffError("patch path is not inside the tree")
    return text


def _apply_file(destination: Path, parsed: _File) -> None:
    if destination.is_file():
        raw = destination.read_text(encoding="utf-8")
        pieces = raw.splitlines(keepends=True)
        lines = []
        for piece in pieces:
            newline = piece.endswith("\n")
            text = piece[:-1] if newline else piece
            if text.endswith("\r"):
                text = text[:-1]
            lines.append((text, newline))
    else:
        raise UnifiedDiffError("patch target was not found")
    document = _FileLines(lines)
    for start, hunk_lines in parsed.hunks:
        old = [line for line in hunk_lines if line.kind in " -"]
        new = [line for line in hunk_lines if line.kind in " +"]
        index = _locate(document, old, start)
        document.apply(index, old, new)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(document.render(), encoding="utf-8")


def _locate(document: _FileLines, old: list[_Line], start: int) -> int:
    hint = 0 if start == 0 else start - 1
    if document.match(hint, old):
        return hint
    found = [index for index in range(len(document.lines) - len(old) + 1) if document.match(index, old)]
    if len(found) == 1:
        return found[0]
    raise UnifiedDiffError("patch context did not match")

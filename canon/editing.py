"""Changing a value in a stored file without disturbing the rest of it.

A file's frontmatter is read the way YAML reads it, as nodes that know where
in the text they sit, and only the characters of the one value are replaced.
Comments, quoting elsewhere, the order of fields and line endings are kept.
The nodes are composed, never built into values, so an alias in a file costs
nothing here. plotcanon checks the World again after any change.

plotcanon owns the file format; setting a field in a file is a candidate for
it to offer (#23), and this module should go when it does.
"""

import re

import yaml

FRONTMATTER = re.compile(r"\A﻿?---\r?\n(.*?)\r?\n---", re.S)


class CannotEdit(Exception):
    """The value could not be found or changed. `str()` says which."""


def frontmatter(text):
    """The root node of a file's frontmatter, and where the frontmatter
    starts in the text. `(None, None)` if there is none or it cannot be read."""
    block = FRONTMATTER.match(text)
    if block is None:
        return None, None
    try:
        root = yaml.compose(block.group(1), Loader=yaml.SafeLoader)
    except Exception:  # noqa: BLE001 - unreadable frontmatter is plotcanon's to report
        return None, None
    return root, block.start(1)


def fields(node):
    """A mapping node's entries as `{name: value node}`. Where a name appears
    twice, the last counts, as it does in YAML."""
    if not isinstance(node, yaml.MappingNode):
        return {}
    return {key.value: value for key, value in node.value if isinstance(key, yaml.ScalarNode)}


def find(text, path):
    """The node at `path` in a file's frontmatter, and the frontmatter's start.
    `path` is a list of field names and list positions, such as
    `["canon_changes", 2, "decision"]`. Raises `CannotEdit` if it is not there."""
    node, offset = frontmatter(text)
    if node is None:
        raise CannotEdit("the file has no frontmatter that can be read")
    for step in path:
        if isinstance(step, int):
            if not isinstance(node, yaml.SequenceNode) or step >= len(node.value):
                raise CannotEdit(f"there is no item {step} at `{'.'.join(map(str, path))}`")
            node = node.value[step]
        else:
            node = fields(node).get(step)
            if node is None:
                raise CannotEdit(f"there is no `{'.'.join(map(str, path))}`")
    return node, offset


def replace(text, path, new):
    """The file with the value at `path` replaced by `new`, which is written
    into the YAML as it stands, so it must already be YAML."""
    node, offset = find(text, path)
    start, end = offset + node.start_mark.index, offset + node.end_mark.index
    if start == end:
        # An empty value. Keep a space after the colon.
        new = " " + new
    # A list or mapping written down the page ends where the next field
    # begins, so its span takes in the line break and spaces before it. Those
    # belong to the layout, not the value, and are kept.
    old = text[start:end]
    return text[:start] + new + old[len(old.rstrip()):] + text[end:]


def set_field(text, field, new):
    """The file with a top-level field set to `new`, which must already be
    YAML. A field that is not there is added at the end of the frontmatter,
    with the file's own line ending."""
    try:
        return replace(text, [field], new)
    except CannotEdit:
        block = FRONTMATTER.match(text)
        if block is None:
            raise
        ending = "\r\n" if "\r\n" in block.group(0) else "\n"
        return text[:block.end(1)] + f"{ending}{field}: {new}" + text[block.end(1):]


def flow_list(items):
    """A list of ids written as YAML on one line."""
    return "[" + ", ".join(items) + "]"

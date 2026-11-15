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


def set_key(text, path, key, new, after):
    """The file with `key` in the mapping at `path` set to `new`, which must
    already be YAML. A key that is not there is added just after the key
    `after`, written the way the mapping already is: on one line, or down the
    page. Raises `CannotEdit` if `path` is not a mapping holding `after`."""
    try:
        return replace(text, [*path, key], new)
    except CannotEdit:
        pass
    node, offset = find(text, path)
    entries = {k.value: (k, v) for k, v in node.value if isinstance(k, yaml.ScalarNode)} \
        if isinstance(node, yaml.MappingNode) else {}
    if after not in entries:
        raise CannotEdit(f"there is no `{'.'.join(map(str, [*path, after]))}`")
    name, value = entries[after]
    end = offset + value.end_mark.index
    if node.flow_style:
        return text[:end] + f", {key}: {new}" + text[end:]
    # Down the page: a new line after the line `after` ends on, so that a
    # comment on that line stays with it, indented as `after` is.
    newline = text.find("\n", end)
    if newline == -1:
        newline = len(text)
    ending = "\r\n" if text[newline - 1:newline] == "\r" else "\n"
    at = newline - 1 if ending == "\r\n" else newline
    indent = " " * name.start_mark.column
    return text[:at] + f"{ending}{indent}{key}: {new}" + text[at:]


def remove_key(text, path, key):
    """The file without `key` in the mapping at `path`, or as it was if the
    key is not there."""
    node, offset = find(text, path)
    if not isinstance(node, yaml.MappingNode):
        raise CannotEdit(f"`{'.'.join(map(str, path))}` is not a mapping")
    pairs = [(k, v) for k, v in node.value if isinstance(k, yaml.ScalarNode)]
    at = next((i for i, (k, _v) in enumerate(pairs) if k.value == key), None)
    if at is None:
        return text
    name, value = pairs[at]
    end = offset + value.end_mark.index
    if node.flow_style:
        # Take the comma before it, or after it if it is first.
        if at > 0:
            start = offset + pairs[at - 1][1].end_mark.index
        else:
            start = offset + name.start_mark.index
            if at + 1 < len(pairs):
                end = offset + pairs[at + 1][0].start_mark.index
        return text[:start] + text[end:]
    if at == 0:
        raise CannotEdit(f"`{key}` begins its mapping and cannot be taken out")
    # Down the page: its whole line or lines, from the end of the line before.
    start = text.rfind("\n", 0, offset + name.start_mark.index)
    newline = text.find("\n", offset + value.end_mark.index - 1)
    if newline == -1:
        newline = len(text)
    if text[newline - 1:newline] == "\r":
        newline -= 1
    start -= 1 if text[start - 1:start] == "\r" else 0
    return text[:start] + text[newline:]


def quoted(words):
    """Text written as one YAML scalar, in double quotes, on one line."""
    return yaml.safe_dump(words, default_style='"', allow_unicode=True,
                          width=float("inf")).rstrip("\n").removesuffix("\n...")


def add_to_list(text, field, item):
    """The file with `item`, which must already be YAML, added at the end of
    the list in a top-level field, written the way the list already is: on one
    line, or down the page. A field that is not there, or is empty, becomes a
    list of the one item. Raises `CannotEdit` if the field holds something
    other than a list."""
    try:
        node, offset = find(text, [field])
    except CannotEdit:
        return set_field(text, field, flow_list([item]))
    if isinstance(node, yaml.ScalarNode) and node.tag == "tag:yaml.org,2002:null":
        return replace(text, [field], flow_list([item]))
    if not isinstance(node, yaml.SequenceNode):
        raise CannotEdit(f"`{field}` is not a list")
    if node.flow_style:
        if not node.value:
            # Just inside the closing bracket.
            at = offset + node.end_mark.index - 1
            return text[:at] + item + text[at:]
        at = offset + node.value[-1].end_mark.index
        return text[:at] + ", " + item + text[at:]
    # Down the page: a new line after the last item's line, so that a comment
    # on that line stays with it, indented as the other items are.
    after = offset + node.value[-1].end_mark.index
    newline = text.find("\n", after)
    if newline == -1:
        newline = len(text)
    ending = "\r\n" if text[newline - 1:newline] == "\r" else "\n"
    at = newline - 1 if ending == "\r\n" else newline
    indent = " " * node.start_mark.column
    return text[:at] + f"{ending}{indent}- {item}" + text[at:]


def flow_list(items):
    """A list of ids written as YAML on one line."""
    return "[" + ", ".join(items) + "]"

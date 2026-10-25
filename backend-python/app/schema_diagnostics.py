"""Bounded diagnostics drawn from trusted outgoing schema names, never output values."""
import re

TECHNICAL_PARTS = frozenset({'response_format', 'json_schema', 'schema', 'properties',
    'required', 'additionalProperties', 'anyOf', 'oneOf', 'enum', 'const', 'type',
    'items', '$ref', '$defs'})
NAME = re.compile(r'[$A-Za-z_][$A-Za-z_0-9]{0,63}\Z')


def schema_names(schema):
    """Read only schema structure. Never inspect descriptions, enums or defaults."""
    names, definitions = set(), set()
    pending = [schema]
    visited = 0
    while pending:
        node = pending.pop()
        visited += 1
        if visited > 2048:
            return frozenset(), frozenset()
        if type(node) is not dict:
            continue
        for key, target in (('properties', names), ('$defs', definitions)):
            children = node.get(key)
            if type(children) is dict:
                for name, child in children.items():
                    if type(name) is str and NAME.fullmatch(name):
                        target.add(name)
                    pending.append(child)
        for key in ('items', 'additionalProperties'):
            if type(node.get(key)) is dict:
                pending.append(node[key])
        for key in ('anyOf', 'oneOf', 'allOf'):
            if type(node.get(key)) is list:
                pending.extend(node[key])
        if len(names) + len(definitions) > 256 or len(pending) > 2048:
            return frozenset(), frozenset()
    return frozenset(names), frozenset(definitions)


def missing_properties(message, names):
    """Extract quoted identifiers only beside explicit missing/required markers.

    A name is evidence that the provider mentioned that schema property, not proof
    that the model actually omitted it. Unknown names and all values are discarded.
    """
    if type(message) is not str or len(message) > 8192:
        return []
    candidates = []
    for match in re.finditer(r'(?i)\bmissing\s+(?:required\s+)?propert(?:y|ies)\s*:\s*([^\n;]{0,512})', message):
        # Stop at the first non-list token; never scan an entire failed output.
        tail = match.group(1).lstrip(' [')
        for _ in range(16):
            item = re.match(r"(['\"])([$A-Za-z_][$A-Za-z_0-9]{0,63})\1", tail)
            if not item:
                break
            candidates.append(item.group(2))
            tail = tail[item.end():].lstrip()
            if not tail.startswith(','):
                break
            tail = tail[1:].lstrip()
    for match in re.finditer(r"(['\"])([$A-Za-z_][$A-Za-z_0-9]{0,63})\1\s+is\s+(?:a\s+)?required\s+property\b", message, re.I):
        candidates.append(match.group(2))
    result = []
    for name in candidates:
        if name in names and name not in result:
            result.append(name)
        if len(result) == 8:
            break
    return result

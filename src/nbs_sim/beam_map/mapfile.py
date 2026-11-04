"""
Load and validate a beamline map file.

The map file is TOML. ``[map]`` names the map and the PV prefix for the node
status PVs, ``[beam]`` optionally gives the global beam condition, and each
``[nodes.<name>]`` table gives a node, the node directly upstream of it, and
the conditions under which it blocks the beam or is selected. ``[status]``
optionally names PVs, such as the ring mode, that clients read directly to
report the beamline's state; the IOC does not watch them. Each entry is a
table with ``pv`` and an optional ``desc``, or just the PV name::

    [status.ring_status]
    pv = "SR-OPS{}Mode-Sts"
    desc = "Beam operation status"

A condition is a table with ``pv`` and exactly one comparison::

    { pv = "NBS_SIM:fe_shutter:Pos-Sts", eq = 1 }
    { pv = "XF:07IDA-OP{Mir:M1-Ax:X}Mtr_MON", between = [10, 20] }

``between`` is inclusive and takes its bounds in either order.
"""

import operator
from dataclasses import dataclass, field

try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib


class MapError(ValueError):
    """The map file is not valid."""


_OPS = {
    "eq": operator.eq,
    "ne": operator.ne,
    "lt": operator.lt,
    "le": operator.le,
    "gt": operator.gt,
    "ge": operator.ge,
}
_SYMBOLS = {"eq": "=", "ne": "!=", "lt": "<", "le": "<=", "gt": ">", "ge": ">="}

_MAP_KEYS = {"name", "prefix", "desc"}
_BEAM_KEYS = {"on_when"}
_NODE_KEYS = {"upstream", "desc", "blocked_when", "selected_when"}
_TOP_KEYS = {"map", "beam", "nodes", "status"}
_STATUS_KEYS = {"pv", "desc"}


@dataclass(frozen=True)
class Condition:
    pv: str
    op: str
    value: object

    def holds(self, x):
        if self.op == "between":
            lo, hi = sorted(self.value)
            return lo <= x <= hi
        return _OPS[self.op](x, self.value)

    def text(self, x):
        """Describe the condition's PV and its current value."""
        return f"{self.pv} = {x:g}"

    def describe(self):
        """Describe the condition itself, for logs."""
        if self.op == "between":
            lo, hi = sorted(self.value)
            return f"{self.pv} between {lo:g} and {hi:g}"
        return f"{self.pv} {_SYMBOLS[self.op]} {self.value:g}"


@dataclass
class Node:
    name: str
    upstream: object = None
    desc: str = ""
    blocked_when: list = field(default_factory=list)
    selected_when: list = field(default_factory=list)


@dataclass
class BeamMap:
    name: str
    prefix: str
    beam_on: list
    nodes: dict
    status: dict = field(default_factory=dict)

    def children(self, name):
        return [n for n, node in self.nodes.items() if node.upstream == name]

    def ancestors(self, name):
        """Nodes upstream of ``name``, nearest first."""
        out = []
        up = self.nodes[name].upstream
        while up is not None:
            out.append(up)
            up = self.nodes[up].upstream
        return out

    def input_pvs(self):
        conds = list(self.beam_on)
        for node in self.nodes.values():
            conds += node.blocked_when + node.selected_when
        return {c.pv for c in conds}


def _check_keys(table, allowed, where):
    unknown = set(table) - allowed
    if unknown:
        raise MapError(f"{where}: unknown key(s) {', '.join(sorted(unknown))}")


def _number(x, where):
    if isinstance(x, bool) or not isinstance(x, (int, float)):
        raise MapError(f"{where}: expected a number, got {x!r}")
    return x


def _condition(spec, where):
    if not isinstance(spec, dict):
        raise MapError(f"{where}: a condition must be a table, got {spec!r}")
    if "pv" not in spec or not isinstance(spec["pv"], str):
        raise MapError(f"{where}: a condition needs a pv name")
    ops = [k for k in spec if k != "pv"]
    _check_keys({k: 1 for k in ops}, set(_OPS) | {"between"}, where)
    if len(ops) != 1:
        raise MapError(f"{where}: a condition needs exactly one comparison, got {ops}")
    op = ops[0]
    value = spec[op]
    if op == "between":
        if not isinstance(value, list) or len(value) != 2:
            raise MapError(f"{where}: between needs [low, high], got {value!r}")
        value = tuple(_number(v, where) for v in value)
    else:
        value = _number(value, where)
    return Condition(spec["pv"], op, value)


def _conditions(spec, where):
    if spec is None:
        return []
    specs = spec if isinstance(spec, list) else [spec]
    return [_condition(s, where) for s in specs]


def parse_map(data):
    """Build a BeamMap from the parsed TOML of a map file."""
    _check_keys(data, _TOP_KEYS, "map file")
    meta = data.get("map", {})
    _check_keys(meta, _MAP_KEYS, "[map]")
    beam = data.get("beam", {})
    _check_keys(beam, _BEAM_KEYS, "[beam]")
    status = {}
    specs = data.get("status", {})
    if not isinstance(specs, dict):
        raise MapError("[status]: must be a table")
    for name, spec in specs.items():
        where = f"[status.{name}]"
        if isinstance(spec, str):
            spec = {"pv": spec}
        if not isinstance(spec, dict):
            raise MapError(f"{where}: expected a table with pv, got {spec!r}")
        _check_keys(spec, _STATUS_KEYS, where)
        if not isinstance(spec.get("pv"), str):
            raise MapError(f"{where}: needs a pv name")
        status[name] = {"pv": spec["pv"], "desc": str(spec.get("desc", ""))}

    nodes = {}
    for name, spec in data.get("nodes", {}).items():
        where = f"node {name}"
        if not isinstance(spec, dict):
            raise MapError(f"{where}: must be a table")
        _check_keys(spec, _NODE_KEYS, where)
        nodes[name] = Node(
            name=name,
            upstream=spec.get("upstream"),
            desc=spec.get("desc", ""),
            blocked_when=_conditions(spec.get("blocked_when"), f"{where} blocked_when"),
            selected_when=_conditions(
                spec.get("selected_when"), f"{where} selected_when"
            ),
        )

    for name, node in nodes.items():
        if node.upstream is not None and node.upstream not in nodes:
            raise MapError(f"node {name}: upstream {node.upstream!r} is not a node")
    for name in nodes:
        seen = {name}
        up = nodes[name].upstream
        while up is not None:
            if up in seen:
                raise MapError(f"node {name}: upstream chain has a cycle")
            seen.add(up)
            up = nodes[up].upstream

    return BeamMap(
        name=meta.get("name", ""),
        prefix=meta.get("prefix", ""),
        beam_on=_conditions(beam.get("on_when"), "[beam] on_when"),
        nodes=nodes,
        status=status,
    )


def load_map(path):
    """Read and validate the map file at ``path``."""
    with open(path, "rb") as f:
        data = tomllib.load(f)
    try:
        return parse_map(data)
    except MapError as e:
        raise MapError(f"{path}: {e}") from None

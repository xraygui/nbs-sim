# Beamline map IOC: design

Date: 2026-10-27. Status: draft for review.

## Intent

The beamline map describes how beam flows through the beamline: which node
sits downstream of which, what blocks each node, and which branch of a split
gets beam. An earlier attempt (nbs-bl branch `beamline_map`) put that logic in
nbs-bl, with devices declaring `_blocks` and `_selects`, so nbs-bl had to watch
the raw shutter and motor PVs and work out beam status itself.

This design moves the monitoring and logic into a caproto IOC instead. The IOC
reads a map file, watches the raw PVs, and serves a small set of read-only
status PVs for every node. nbs-bl reads the same map file only to learn the
node structure, and subscribes to the status PVs, never to the raw PVs. An IOC
is a better home for always-on monitoring: it runs whether or not a bluesky
session is open, every client sees the same answer, and the logic lives in one
place.

This is a mock-up of the concept, built alongside the earlier attempt, which
stays untouched.

## Goals

- A map file format that holds the node graph, the blocking and selection
  conditions, and the global beam condition, and names no device classes.
- A caproto IOC (`nbs-map-ioc`) that serves four status PVs per node and can
  be started on its own, without the full nbs-sim beamline.
- A claude-pods setup that runs the IOC against the sim, with a fake global
  beam PV.
- An nbs-bl reader that builds the node tree from the file and exposes the
  status PVs as read-only signals.

## Non-goals

- nbs-sim using the map for its physics (e.g. no i0 when the beam is blocked).
  Jamie wants this eventually; it is a later step.
- Placing devices on nodes (`_node`), or any GUI.
- Controlling anything. The IOC only reports; it never writes to the raw PVs
  and its status PVs are read-only.
- Replacing or merging with the `beamline_map` branch.

## Anti-goals

- nbs-bl subscribing to the raw blocking or selection PVs, or repeating any of
  the status logic. If nbs-bl needs to know something, the IOC should serve it.
- The two halves disagreeing about the node graph. Both read the same file.

## The map file

TOML. Jamie's original sketch, in plain English, was:

```
[front_end]  blocked by NBS_SIM:fe_shutter:Pos-Sts = 1
[m1]         downstream from front_end
[branch1]    downstream from m1, selected when M1 X between 10 and 20
[branch2]    downstream from m1, selected when M1 X between -10 and -20
```

The concrete format (Jamie agreed to this shape):

```toml
[map]
name = "claude"
prefix = "NBS_MAP:"            # prefix for every status PV the IOC serves

[beam]
on_when = { pv = "NBS_SIM:beam_available", eq = 1 }

[nodes.front_end]
desc = "Front-end shutter"
blocked_when = { pv = "NBS_SIM:fe_shutter:Pos-Sts", eq = 1 }

[nodes.m1]
upstream = "front_end"

[nodes.branch1]
upstream = "m1"
selected_when = { pv = "XF:07IDA-OP{Mir:M1-Ax:X}Mtr_MON", between = [10, 20] }

[nodes.branch2]
upstream = "m1"
selected_when = { pv = "XF:07IDA-OP{Mir:M1-Ax:X}Mtr_MON", between = [-20, -10] }
```

Rules:

- A node with no `upstream` is a root. Several roots are allowed; the graph
  must be a forest (no cycles, every `upstream` names a known node).
- A condition is a table with `pv` and exactly one comparison: `eq`, `ne`,
  `lt`, `le`, `gt`, `ge`, or `between = [lo, hi]` (inclusive, order of lo/hi
  does not matter). *My call.*
- `blocked_when` may also be a list of conditions; the node blocks when any of
  them holds (a node with a valve and a shutter). `selected_when` and
  `on_when` may be lists too, and then all must hold. *My call.*
- `[beam]` is optional. Without it, global beam is always on.
- Unknown keys are an error, so typos fail loudly. `desc` is free text.
- The file is validated once at load by a single shared loader, and a bad
  file stops the IOC with a clear message naming the node and key.

## Node status

Each node gets four PVs, named `{prefix}{node}:{status}`:

| PV | Type | Meaning |
|---|---|---|
| `Blocking` | bool | This node itself stops the beam. True when any `blocked_when` holds, or when the node has a `selected_when` that does not hold. |
| `PathClear` | bool | Beam can reach this node: no node upstream of it is blocking. Does not include the node's own blocking. Roots are always path clear. |
| `BeamExpected` | bool | `PathClear`, not `Blocking`, and global beam on. |
| `Reason` | string | Empty when beam is expected. Otherwise why not: the closest blocking node on the path to this node, this node included. Jamie chose closest over most upstream so that every blocker is visible at a glance across the nodes, e.g. while everything except the front-end shutter is opened up in preparation. If nothing blocks, it is the global beam reason. |

A blocking node stops beam for everything below it, whatever the reason it
blocks. A branch that is not selected therefore makes all of its descendants
PathClear=0, so the logic works the same at any depth of branching.

Worked example: front-end shutter closed (`Pos-Sts = 1`).
`front_end`: Blocking=1, PathClear=1, BeamExpected=0, Reason
"front_end blocked: NBS_SIM:fe_shutter:Pos-Sts = 1". `m1`, `branch1`,
`branch2`: PathClear=0, BeamExpected=0. `m1` and `branch1` give
front_end's reason; with M1 X = 15, `branch2` gives its own closer reason,
"branch2 not selected: ...".

Worked example: shutter open, M1 X = 15. `branch1`: Blocking=0,
PathClear=1, BeamExpected=1, Reason "". `branch2`: Blocking=1, PathClear=1,
BeamExpected=0, Reason "branch2 not selected: XF:07IDA-OP{Mir:M1-Ax:X}Mtr_MON
= 15".

Reason text forms (*my call*, the builder may refine wording):

- `<node> blocked: <pv> = <value>`
- `<node> not selected: <pv> = <value>`
- `<node>: <pv> disconnected`
- `beam off: <pv> = <value>`

Disconnected input PVs fail safe (*my call*): a `blocked_when` PV that is
disconnected counts as blocking, a `selected_when` PV that is disconnected
counts as not selected, and a disconnected beam PV counts as beam off. The
reason says which PV is disconnected.

**Sim mode** (Jamie's request). Simulations often cover only part of the
node map, so the IOC has a sim mode in which a disconnected PV is ignored:
its condition is treated as non-blocking. A disconnected `blocked_when` PV
does not block, a disconnected `selected_when` PV counts as selected, and a
disconnected beam PV counts as beam on. It is turned on with
`nbs-map-ioc --sim`, or when `NBS_SIM_MODE=1` is set (claude-pods already
sets it for the sim). The IOC logs each PV it is ignoring once at startup
and again if it later connects. Side effect: if every branch of a split keys
off unsimulated PVs, all of them read as selected. That is accepted for
testing (*my call*). Outside sim mode the fail-safe rules above apply.

At startup the IOC serves its PVs at once, and nodes whose inputs have not
connected yet show the disconnected reason until they do (*my call*). This
keeps start order between the sim and the IOC unimportant.

`Reason` needs more than the 40 characters of a DBR_STRING, so serve it as a
char waveform reported as a string (e.g. `max_length=256`,
`report_as_string=True`).

## How it is built

### nbs-sim: the IOC

Jamie's direction: reuse nbs-sim's caproto machinery, keep it startable
without the whole sim, and expect nbs-sim to use the map later.

- New module `nbs_sim/beam_map/` with the file loader and validator, the
  status logic as plain functions over the node graph and a dict of current
  input values (easy to unit test with no EPICS), and the IOC.
- The IOC is a caproto `PVGroup` whose pvproperties are created from the
  loaded map at startup. It monitors every input PV with the caproto asyncio
  client and recomputes all node statuses on any update (the graph is tiny),
  writing only the PVs whose values change.
- New console script `nbs-map-ioc`, using caproto's `template_arg_parser` and
  `run` as `nbs-sim` does, plus `--map <path>`. The prefix comes from the
  file; a `--prefix` flag may override it.
- Branch `map_ioc`, from `per-sample-spectra` (the branch claude-pods runs
  today), in worktree `nbs-sim-map-ioc`.
- Add a fake global beam PV to the sim beamline, `NBS_SIM:beam_available`,
  default 1, writable so tests and operators can drop the beam.

### claude-pods: the map and the container

- The map file lives in claude-pods for now, in `startup/`. The current
  working tree already has an untracked `startup/beamline_map.toml` from the
  earlier attempt, so the new file gets a distinct name such as
  `startup/beam_map.toml` (*my call*).
- A new compose service that runs `nbs-map-ioc --map ...` from the same image
  as the sim, following the sim service's mounts and environment, and a pods
  preset entry so it starts with the sim.
- The claude-pods changes go on a branch in a claude-pods worktree, so the
  uncommitted earlier-attempt files in the main checkout stay as they are.
- The map uses PVs the claude sim actually serves. `XF:07IDA-OP{Mir:M1-Ax:X}Mtr_MON`
  exists (mir1 prefix plus the FMB axis names in `nbs_sim/devices/mirrors.py`).
  The map may be changed freely to match what the sim serves; Jamie's PV
  names were illustrative. The selection ranges should be chosen so the sim's
  default M1 position selects one branch.
- Getting the new code into the pods: in `--dev` mode the containers install
  local packages from `NBS_COLLECTION_PACKAGES` (the xraygui directory), which
  holds the main nbs-sim checkout, not this worktree. The map IOC service can
  mount and install the `nbs-sim-map-ioc` worktree directly. The fake beam PV
  lives in the sim, so testing the beam-off case needs the sim running the
  `map_ioc` code too; until then the map can omit `[beam]` (beam always on).
  Restarting the sim needs coordinating, since another thread owns pods
  start/stop.

### nbs-bl: the reader

- New module `nbs_bl/beam_map.py` on a new branch from `develop` (separate
  from `beamline_map`, and named differently to avoid confusion).
- Loads the same file with the same rules (the loader is small; nbs-bl can
  copy the validator or depend on nbs-sim's, builder's choice, but nbs-bl
  must not need the IOC code).
- Builds `Node` objects (name, desc, upstream, children) and, for each, four
  `EpicsSignalRO` signals for the status PVs. Publishes the tree as
  `BEAM_MAP` and offers small helpers: the status of a node, and the reason
  there is no beam at a node.
- Reads only the status PVs. It never sees the conditions' PVs except as text.

## Testing

- Unit tests for the loader (good file, each kind of bad file) and the status
  logic (the worked examples above, disconnected inputs, multiple roots).
- An integration test that starts a tiny caproto IOC serving the input PVs
  and the map IOC, flips the inputs, and checks the status PVs.
- nbs-bl tests that build the tree from a file and read status through the
  signals (against the test IOC, or with mocked signals).
- A run in claude-pods: start the IOC, close the sim front-end shutter and
  move M1, and watch the statuses. Take the pods lock first.

## Left to the builder

Module layout inside nbs-sim and nbs-bl, the exact Reason wording, whether
to debounce updates, the compose details, and how nbs-bl finds the map file. The
`beamline_map` branch (`nbs_bl/beamline_map.py`, `beamline.py`) shows one
way; copy only the file loading and publishing, none of the `_node` or
device-config handling.

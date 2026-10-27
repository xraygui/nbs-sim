# Beamline Map IOC Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A caproto IOC that reads a beamline map file and serves four read-only status PVs per node, plus an nbs-bl reader that builds the node tree from the same file and subscribes only to those PVs.

**Architecture:** Pure loader and status functions in `nbs_sim.beam_map` (no EPICS), wrapped by a caproto IOC that monitors the input PVs with the caproto asyncio client and recomputes all statuses on any update. nbs-bl parses only the structural part of the file and makes `EpicsSignalRO`s for the status PVs. claude-pods holds the map and runs the IOC as its own container.

**Tech Stack:** Python 3, caproto (server and asyncio/threading clients), ophyd, tomllib, pytest.

**Spec:** `docs/superpowers/specs/2026-10-27-beamline-map-ioc-design.md` (same worktree).

## Global Constraints

- Repos and worktrees (never touch the main checkouts' working trees):
  - nbs-sim: `/home/jamie/work/xraygui/nbs-sim-map-ioc`, branch `map_ioc` (from `per-sample-spectra`).
  - nbs-bl: create `/home/jamie/work/xraygui/nbs-bl-beam-map`, branch `beam_map` from `develop`.
  - claude-pods: create `/home/jamie/work/xraygui/claude-pods-beam-map`, branch `beam_map` from `master`.
- Status PV names: `{prefix}{node}:Blocking`, `:PathClear`, `:BeamExpected`, `:Reason`. Booleans for the first three; `Reason` is a char waveform, `max_length=256`, reported as a string.
- Conditions: `pv` plus exactly one of `eq ne lt le gt ge between`; `between = [lo, hi]` inclusive, either order. `blocked_when` list = any; `selected_when` / `on_when` list = all.
- Unknown keys are errors. `[beam]` optional (absent = beam always on). Graph must be a forest.
- Fail safe outside sim mode: disconnected `blocked_when` PV blocks, `selected_when` PV counts as not selected, beam PV counts as beam off. Sim mode (`--sim` or `NBS_SIM_MODE=1`): disconnected conditions are ignored (non-blocking, selected, beam on).
- Reason forms: `<node> blocked: <pv> = <value>`, `<node> not selected: <pv> = <value>`, `<node>: <pv> disconnected`, `beam off: <pv> = <value>` (and `beam off: <pv> disconnected`).
- The IOC never writes to input PVs. nbs-bl never subscribes to input PVs.
- Python for tests: `PY=/home/jamie/work/xraygui/claude-pods/.pixi/envs/gui/bin/python` (has caproto, ophyd, pytest; no pytest-asyncio, so tests use sync code and subprocesses). Run from the repo root with `PYTHONPATH=src`. Do not install into that env.
- Commits end with `Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>`. No model names elsewhere.

## Review Focus

1. Input PV is an int/enum (sim `Pos-Sts` is `dtype=int`): compare numerically; request enums as their integer index, never as strings.
2. One input PV used by several nodes (M1 X selects both branches): one subscription, every dependent node updates.
3. Input IOC restarts: PV goes disconnected then reconnects; statuses go fail-safe and then recover without restarting the map IOC.
4. Value exactly on a `between` bound, and reversed bounds (`[-10, -20]`): both inclusive and order-free.
5. Node names that aren't Python identifiers (`pipe-m1`): PV names keep the name verbatim; only internal attribute names are sanitized.

---

### Task 1: Map file loader (nbs-sim)

**Files:**
- Create: `src/nbs_sim/beam_map/__init__.py` (re-exports), `src/nbs_sim/beam_map/mapfile.py`
- Test: `tests/beam_map/test_mapfile.py`, fixture `tests/beam_map/example_map.toml` (the spec's example file)

**Interfaces:**
- Produces:
  - `class MapError(ValueError)`
  - `@dataclass(frozen=True) Condition(pv: str, op: str, value: float | tuple[float, float])`, method `holds(x: float) -> bool`, method `text(x) -> str` giving `"<pv> = <x>"`
  - `@dataclass Node(name: str, upstream: str | None, desc: str, blocked_when: list[Condition], selected_when: list[Condition])`
  - `@dataclass BeamMap(name: str, prefix: str, beam_on: list[Condition], nodes: dict[str, Node])`, methods `children(name) -> list[str]`, `ancestors(name) -> list[str]` (nearest first), `input_pvs() -> set[str]`
  - `load_map(path: str) -> BeamMap`, `parse_map(data: dict) -> BeamMap`

- [ ] **Step 1: Write failing tests**: `test_load_example` (4 nodes, `branch1.upstream == "m1"`, `prefix == "NBS_MAP:"`, `input_pvs()` has 3 PVs); `test_between_inclusive_and_unordered` (`between=[-10,-20]` holds at -10, -20, -15, not at -21); `test_ops` (each of eq/ne/lt/le/gt/ge at a boundary); `test_blocked_when_list`; and `MapError` with node and key in the message for: unknown upstream, cycle, unknown node key, condition with two ops, condition with no op, `between` not length 2.
- [ ] **Step 2: Run** `PYTHONPATH=src $PY -m pytest tests/beam_map/test_mapfile.py -v`. Expected: FAIL (import error).
- [ ] **Step 3: Implement** `mapfile.py` with `tomllib`; a single dict may be given where a list is allowed.
- [ ] **Step 4: Run** same command. Expected: PASS.
- [ ] **Step 5: Commit** `Add the beam map file loader`.

### Task 2: Status logic (nbs-sim)

**Files:**
- Create: `src/nbs_sim/beam_map/status.py`
- Test: `tests/beam_map/test_status.py`

**Interfaces:**
- Consumes: `BeamMap`, `Condition` from Task 1.
- Produces:
  - `@dataclass(frozen=True) NodeStatus(blocking: bool, path_clear: bool, beam_expected: bool, reason: str)`
  - `compute_status(bmap: BeamMap, values: dict[str, float | None], sim: bool = False) -> dict[str, NodeStatus]`. A PV missing from `values` or mapped to `None` is disconnected.

- [ ] **Step 1: Write failing tests** using the example map:
  - `test_shutter_closed`: `{fe: 1, m1x: 15, beam: 1}` → front_end `(True, True, False, "front_end blocked: NBS_SIM:fe_shutter:Pos-Sts = 1")`; m1, branch1, branch2 `path_clear False`, same reason.
  - `test_branch_selection`: `{fe: 0, m1x: 15, beam: 1}` → branch1 `(False, True, True, "")`; branch2 `(True, True, False, "branch2 not selected: XF:07IDA-OP{Mir:M1-Ax:X}Mtr_MON = 15")`.
  - `test_beam_off`: `{fe: 0, m1x: 15, beam: 0}` → branch1 `beam_expected False`, reason `"beam off: NBS_SIM:beam_available = 0"`.
  - `test_unselected_blocks_descendants`: add `branch2_child` under branch2 → `path_clear False`, reason names branch2.
  - `test_disconnected_fail_safe`: `{m1x: 15, beam: 1}` → front_end blocking, reason `"front_end: NBS_SIM:fe_shutter:Pos-Sts disconnected"`.
  - `test_sim_mode_ignores_disconnected`: `values={}` with `sim=True` → every node `beam_expected True` (both branches selected).
  - `test_no_beam_section` and `test_multiple_roots`.
  - Format numbers with `f"{x:g}"`.
- [ ] **Step 2: Run** `PYTHONPATH=src $PY -m pytest tests/beam_map/test_status.py -v`. Expected: FAIL.
- [ ] **Step 3: Implement** `compute_status`: per node, own blocking plus own reason; walk nodes in topological order for `path_clear`; reason = nearest blocking node in `[node] + ancestors(node)`, else beam reason, else `""`.
- [ ] **Step 4: Run.** Expected: PASS.
- [ ] **Step 5: Commit** `Compute beam map node status`.

### Task 3: The IOC and `nbs-map-ioc` (nbs-sim)

**Files:**
- Create: `src/nbs_sim/beam_map/ioc.py`
- Modify: `pyproject.toml` `[project.scripts]` and `src/setup.py` `entry_points`: add `nbs-map-ioc = nbs_sim.beam_map.ioc:main`
- Test: `tests/beam_map/test_ioc.py`, helper `tests/beam_map/fake_inputs.py` (a tiny caproto IOC serving the example's three input PVs, writable)

**Interfaces:**
- Consumes: `load_map`, `compute_status`.
- Produces: `make_ioc(bmap: BeamMap, prefix: str | None = None, sim: bool = False) -> PVGroup`; `main(argv=None)`; CLI `nbs-map-ioc --map PATH [--sim] [--prefix P]` plus caproto's `template_arg_parser` options. `sim` is also on when env `NBS_SIM_MODE=1`.

- [ ] **Step 1: Write failing tests** (sync, `caproto.threading.client`; start `fake_inputs.py` and `python -m nbs_sim.beam_map.ioc` as subprocesses on localhost with `EPICS_CA_AUTO_ADDR_LIST=NO`, `EPICS_CA_ADDR_LIST=127.255.255.255` or `127.0.0.1`, kill in a fixture):
  - `test_status_follows_inputs`: write fe=1 → `NBS_MAP:front_end:Blocking` reads 1 and `NBS_MAP:m1:Reason` contains "front_end blocked" within 3 s; write fe=0, m1x=-15 → `branch2:BeamExpected` 1, `branch1:BeamExpected` 0.
  - `test_shared_pv_updates_both_branches` (Review Focus 2).
  - `test_input_ioc_restart`: kill fake inputs → front_end Reason ends "disconnected"; restart → recovers (Review Focus 3).
  - `test_sim_mode_no_inputs`: map IOC with `--sim`, no fake inputs → `branch1:BeamExpected` 1.
  - `test_reason_longer_than_40_chars` reads back intact.
- [ ] **Step 2: Run** `PYTHONPATH=src $PY -m pytest tests/beam_map/test_ioc.py -v`. Expected: FAIL.
- [ ] **Step 3: Implement.** Build the PVGroup subclass with `type()`: per node four `pvproperty(name=f"{node}:{Status}", read_only=True, ...)` under sanitized attribute names, plus `MapName` (string). A `MapName.startup` hook creates a `caproto.asyncio.client.Context`, subscribes once per input PV (request numeric type; enums as int index), tracks connection state via the connection callback (disconnect → `None`), and on any change calls `compute_status` and writes only changed values. Log ignored PVs once in sim mode.
- [ ] **Step 4: Run.** Expected: PASS. Also run the whole `tests/beam_map` suite.
- [ ] **Step 5: Commit** `Add the nbs-map-ioc beam map IOC`.

### Task 4: Fake global beam PV in the sim (nbs-sim)

**Files:**
- Modify: `src/nbs_sim/beamline.py` (`Beamline` class)

- [ ] **Step 1:** Add a writable `beam_available = pvproperty(value=1, dtype=int, name="beam_available")` to `Beamline`.
- [ ] **Step 2: Verify** the full PV name the sim serves. The sim's group prefix defaults to `SIM:` while device prefixes are absolute (`NBS_SIM:fe_shutter:`), so the beam PV may come out as `SIM:beam_available`. Check by running `nbs-sim --startup-dir /home/jamie/work/xraygui/claude-pods/startup --list-pvs` locally (no pods needed) if the env allows, otherwise by reading how pvproperty names compose. Record the real name; Task 6 uses it.
- [ ] **Step 3: Commit** `Add a fake beam_available PV to the sim`.

### Task 5: nbs-bl reader

**Files (in `/home/jamie/work/xraygui/nbs-bl-beam-map`):**
- Create: `src/nbs_bl/beam_map.py`
- Modify: `src/nbs_bl/configuration.py`: add `"beam_map_filename": "beam_map.toml"` to `_default_settings`; add `LoadBeamMapStep` after `SetupSpecialDevicesStep` in `BeamlineInitializer`. Modify `src/nbs_bl/beamline.py`: add `"beam_map"` to the attribute list and a `beam_map = None` default.
- Test: `src/nbs_bl/tests/test_beam_map.py`, fixture copy of the example map.

**Interfaces:**
- Produces:
  - `class MapNode`: `name`, `desc`, `upstream: str | None`, `children: list[str]`, signals `blocking`, `path_clear`, `beam_expected`, `reason` (`EpicsSignalRO`, created lazily or with `auto_monitor=True`), method `status() -> dict` with keys `blocking, path_clear, beam_expected, reason`.
  - `class BeamMap`: `name`, `prefix`, `nodes: dict[str, MapNode]`, `roots() -> list[str]`, `status(node) -> dict`, `why_no_beam(node) -> str` (the Reason PV value).
  - `load_beam_map(path: str, prefix: str | None = None) -> BeamMap`. Parses only `[map]` and each node's `upstream` and `desc`; ignores condition keys; raises `ValueError` on unknown upstream or cycles.

- Follow the old branch's `LoadBeamlineMapStep` pattern (nbs-bl-beamline-map worktree, `configuration.py`): skip quietly if the file is missing, print errors without aborting startup. Do not copy any `_node`, devices or Redis publishing.

- [ ] **Step 1: Write failing tests**: `test_tree` (roots `["front_end"]`, `m1.children == ["branch1","branch2"]`); `test_signal_names` (`nodes["branch2"].reason.pvname == "NBS_MAP:branch2:Reason"`); `test_prefix_override`; `test_rejects_cycle`; `test_ignores_conditions` (no signal anywhere uses an input PV name).
- [ ] **Step 2: Run** `PYTHONPATH=src $PY -m pytest src/nbs_bl/tests/test_beam_map.py -v`. Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run.** Expected: PASS.
- [ ] **Step 5: Live check.** With Task 3's fake inputs and map IOC running locally, `load_beam_map(...).status("branch1")` matches the IOC. Not a committed test.
- [ ] **Step 6: Commit** `Add a beam map reader backed by map IOC status PVs`.

### Task 6: claude-pods map and container

**Files (in `/home/jamie/work/xraygui/claude-pods-beam-map`):**
- Create: `startup/beam_map.toml`, `compose/map-ioc/docker-compose.yml` and `docker-compose.development.yml` (mirror `compose/sim`), `scripts/map-ioc-start.sh`
- Modify: `compose/pods.toml` presets (add `map-ioc` after `sim` in each), `pixi.toml` tasks, `README.md` (one short section)

- [ ] **Step 1:** Write `startup/beam_map.toml` for the claude sim: `front_end` blocked by `NBS_SIM:fe_shutter:Pos-Sts` `ne = 0` (matches the old `_blocks`); `m1`; `mono`; `m3`; endstation branch selected by an M1 X range that contains the sim's default M1 X; `[beam]` on the PV recorded in Task 4. Validate with `PYTHONPATH=/home/jamie/work/xraygui/nbs-sim-map-ioc/src $PY -c "from nbs_sim.beam_map import load_map; load_map('startup/beam_map.toml')"`.
- [ ] **Step 2:** Compose service: same image as sim, same network and EPICS env, mounts the nbs-sim-map-ioc worktree and the startup dir, runs `pip install -e <worktree> && nbs-map-ioc --map .../startup/beam_map.toml` with `NBS_SIM_MODE=1`.
- [ ] **Step 3: Commit** `Add the beam map and a map IOC container`.

### Task 7: Run in claude-pods

- [ ] **Step 1:** Take the pods lock (`mkdir /home/jamie/work/xraygui/claude-pods/.pods-lock`, owner/purpose file inside). If another thread holds it, wait; never break it. Starting or stopping containers belongs to the samples thread, so ask in the thread before starting the map-ioc container or restarting the sim.
- [ ] **Step 2:** Through `podman unshare --rootless-netns`, read every `NBS_MAP:*` PV, close the sim front-end shutter, move M1 X out of range, and check Blocking/PathClear/BeamExpected/Reason against the spec. Restore the shutter and M1.
- [ ] **Step 3:** Release the lock. Report results in the thread.

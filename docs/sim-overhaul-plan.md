# nbs-sim overhaul: plan

Status: draft, 2026-11-06; open questions decided 2026-11-09 (see Decisions).

## Why

- **One process holds everything.** Every simulated device runs in the
  nbs-sim process, and adding richer devices (the PEAK analyzer sim, area
  detectors) makes that process heavier and its failures shared.
- **Too much is SST-specific.** The undulator, the SST1 and HAXPES monos, the
  SST mode selectors and several beamline-only devices (FASSTCAT, the Wiener
  supplies, the flood gun) live in nbs-sim, so nbs-sim has to change whenever
  a beamline does.
- **It is hard to extend.** A device gets its physics by calling methods on
  `parent`, the nbs-sim `Beamline` object: `intensity_func()` (21 call sites),
  `energy.value` (9), `distance_func()` (9), `sample_yield()`,
  `energy_resolution()`, plus the `yspl`/`refspl` splines. A device can only
  be simulated inside that object, so it cannot run anywhere else. Its
  attenuation counts only if it sits in one of the shutter, aperture or
  gate-valve groups, through a `transmission` property that
  `Beamline.configure_*` picks up.
- **The beam map already knows the layout.** `nbs-map-ioc` reads
  `beam_map.toml`, watches real PVs and serves Blocking, PathClear,
  BeamExpected and Reason for each node. It answers "is there beam here?" but
  not "how much beam, at what energy?"

## Goals

1. **Physics PVs.** Photon energy, bandwidth and flux are served as PVs,
   node by node, and are the only way a device learns about the beam.
2. **The beam map computes them.** The map IOC already walks the node tree for
   blocking, so it also multiplies transmissions down the tree and passes the
   energy on from the mono.
3. **Plugin loading.** Sim device classes live with the code they simulate
   (`haxpes.sim`, `sst_base.sim`, `peak_ioc`), and nbs-sim finds them through
   entry points.
4. **Location independence.** A device takes its physics inputs and reports
   its attenuation over Channel Access, so it behaves the same whether it runs
   in the main nbs-sim process, in a second nbs-sim process, or as its own IOC
   in its own container.

## Non-goals

- Turning ophyd classes into simulations automatically (the "simulated mixin"
  idea in `notes_on_ultimate_nbs.md`). Sim classes stay hand-written
  PVGroups.
- Quantitative beamline physics. Flux stays in the current relative units
  (a source `scale` makes nominal photons/s a config change later); the aim is realism of behaviour (i0 normalisation, blocking, energy
  dependence), not of absolute numbers.
- Changing the beam map as nbs-bl and real beamlines see it. The four
  existing status PVs and the map file format stay as they are; everything
  added here is opt-in.

## Target architecture

```
                 beam_map.toml  +  beam_map.sim.toml (sim-only overlay)
                          |
                          v
   +------------------- beam IOC (nbs-map-ioc) --------------------+
   | per node: Blocking PathClear BeamExpected Reason   (as today) |
   |           Transmission Flux Energy Bandwidth       (new, sim) |
   +---------------------------------------------------------------+
        ^ watches over CA                          | serves over CA
        |                                          v
   source and attenuator PVs            physics inputs of each device
   (ring current, shutters, slits,      (detectors, analyzers, cameras)
    undulator match, mono energy,
    sample overlap)
        ^                                          |
        +------ sim devices in any process --------+
           nbs-sim (main)   nbs-sim --process analyzer   peak-sim-ioc
```

Every device talks to the others only through PVs. The beam IOC is the one
place that knows the layout; devices know only the name of their node.

### Physics PVs

For each node `N`, the beam IOC serves, under the map prefix:

| PV | Meaning |
| --- | --- |
| `N:Transmission` | this node's own transmission, 0 to 1 |
| `N:Flux` | flux arriving at `N`: source flux times the transmission of every node upstream of `N` |
| `N:Energy` | photon energy at `N`, eV; NaN upstream of the first node that sets one |
| `N:Bandwidth` | energy FWHM at `N`, eV; 0 where not set |

Plus `Source:Flux` for the beam entering the root node.

- **Flux.** The flux at a node is the flux upstream of its own attenuation.
  A detector reads `Flux` at the node it sits on, and a downstream node sees
  that node's transmission. Units stay relative: source flux is ring current
  (mA) times an optional source factor, so the numbers match today's
  `intensity_func()` and existing detector count rates keep their meaning.
- **Energy is per node, not global.** Setting it at a mono node and passing it
  downstream handles beamlines with more than one mono or branch, such as
  HAXPES's `enpostender` and `enpossoft`.
- **Blocking is transmission 0.** A node that blocks (`blocked_when` holds, or
  not `selected_when`) has transmission 0, so the boolean and continuous
  views always agree.

### Map file: a sim-only overlay

`beam_map.toml` stays the production file. A sim overlay,
`beam_map.sim.toml`, adds the physics inputs and is read only when the IOC
runs in sim mode (`--sim-overlay`, or the file beside the map). The overlay
may only add `[beam] flux` and node `transmission`, `energy` and
`bandwidth`; it is parsed on its own rather than merged, so it can never
change a condition and the status PVs are the same with or without it. (An
earlier draft reused nbs-core's `_deep_merge_dict`; its `_remove` and
replace directives are exactly what the overlay must not be able to do.) A
real beamline never sees PVs that exist only in the sim, so a missing
transmission PV can never fail-safe-block a real map.

An input is `{ pv = ..., scale = ... }` or a fixed `{ value = ... }` (or a
bare number). Disconnected inputs fail safe outside sim mode (transmission
0); in sim mode a disconnected transmission counts as 1. A disconnected
source flux is 0, and a disconnected energy or bandwidth is NaN, in either
mode.

```toml
# beam_map.sim.toml
[beam]
flux = { pv = "NBS_SIM:Real-I", scale = 1.0 }

[nodes.m1]
transmission = { pv = "SIM:m1:transmission" }   # e.g. mirror stripe and pitch

[nodes.mono]
energy = { pv = "XF:07ID6-OP{Mono:DCM1-Ax:ENERGY_MON}" }
bandwidth = { value = 0.25 }                        # fixed until the mono models it

[nodes.exit_slit]
transmission = { pv = "SIM:haxslt:transmission" }

[nodes.sample]
transmission = { pv = "SIM:manip:transmission" } # 1 - overlap, for i1 downstream
```

### Device side: a small SDK in nbs-sim

`nbs_sim.sdk` gives a sim device its inputs and outputs:

- **`BeamInput`** is a helper a device holds. It subscribes with the caproto
  asyncio client to `Flux`, `Energy` and `Bandwidth` at the device's node and
  keeps the latest values. It also gives a time-averaged flux over an
  interval, for exposures and sweeps during which a shutter may close. When
  the inputs are disconnected it falls back to configured defaults and logs
  the fact once, so a device still runs without a beam IOC.
- **Attenuators** serve their own transmission, 0 to 1, on a
  `{prefix}transmission` PV, which the overlay points nodes at. The sim's
  shutters, gate valves and slits already did; the manipulator now does too
  (the fraction of the beam that passes the sample bar). An earlier draft
  had an `Attenuator` mixin and a `Sim:Transmission` name; the existing name
  is kept instead, so no PVs move.
- **Node binding.** devices.toml already places devices with `_node` (nbs-bl
  uses it). `createIOCDevice` sets it on the device as `beam_node`, and the
  `Beamline` holds the map prefix. nbs-sim uses the beam map when the
  startup dir has a `beam_map.sim.toml` overlay (or `--beam-map`;
  `--no-beam-map` turns it off), the same file that turns the map IOC's
  physics on.
- **Samples.** The manipulator sim publishes `Sim:SampleID` and `Sim:Overlap`.
  A sample model file (today's sample map, plus optional per-sample XPS lines
  and other spectra) is loaded by any device that needs it. Devices share the
  file, not Python objects.

Because all of this goes over CA, the same class runs in-process or in
another container. In-process it costs one local CA hop, which is fine at
the 10 to 20 Hz that the sim updates at.

### Plugin loading

Two entry point groups:

- **`nbs_sim.loaders`**: a package returns a translation table from real
  class to sim class, the same thing `[loaders]` in sim_conf.toml holds today.
  For example, haxpes registers
  `PeakAnalyzerIOC -> haxpes.sim.peak:PeakAnalyzerSim` and
  `energypos -> haxpes.sim.energy:HAXEnergy`. nbs-sim merges the tables of
  installed packages, and sim_conf.toml `[loaders]` still overrides them.
- **`nbs_sim.devices`** (optional): short stable names for sim classes, so
  configs need not change when modules move. Dotted paths keep working, since
  `simpleResolver` already imports them.

A package's sim code goes in a `sim` subpackage that imports only caproto,
numpy and nbs-sim's SDK. It must never import ophyd or bluesky, so the sim
process stays light.

That is an import-time guarantee only. sst-base, haxpes and ucal require
bluesky, ophyd and nbs-bl, so installing them for their sim classes still
puts the bluesky stack in the sim image. We accept that for now: it costs
image size, not correctness. If size becomes a problem, a beamline package
can move its bluesky dependencies to an extra or split out a `<pkg>-sim`
package, without changing the entry points. haxpes has no `__init__.py` (it is a namespace package),
so `import haxpes.sim` does not pull in the rest of haxpes.

### Splitting into processes

A sim_conf.toml device can name a process: `_process = "analyzer"`.
`nbs-sim --process analyzer` loads only those devices, and plain `nbs-sim`
loads the rest. Compose runs one service per process from the same image and
config. A plugin that is a full IOC already (peak-ioc) can instead run as its
own service with its own CLI, using the same SDK inputs.

### Where code ends up

| Code | Moves to |
| --- | --- |
| Motors and positioners, generic signals, `RingCurrent` (the flux source), vacuum, slits, generic detectors, SRS570, MCA, PID, manipulator | stays in nbs-sim |
| NSLS-II conventions every pod uses: `SSTShutter` (the EPS `Pos-Sts`/`Cmd:Opn-Cmd` PVs; `InterlockedGateValve` subclasses it), `FakeFMBOMotor`, `FMBOQuadSlits`, `FMBHexapodMirror` | stays in nbs-sim, renamed where the name says SST (`SSTShutter` → `EPSShutter`, with an alias) |
| `SSTEPU`, `SST1Energy`, `sst1_energy.py`, `RSoXSShutter`, `ModeControl` and `EndstationControl` (the SST soft/tender and endstation selectors), `WienerPS` (ucal today; other SST endstations soon), legacy `sim_sst.py` | sst-base `sst_base.sim` |
| `HAXEnergy`, `HAXEnergyFlyer`, `hax_dcm.py`, `HAXFloodgun`, PEAK analyzer sim | haxpes `haxpes.sim` |
| `FasstcatSimDevice` | ucal `ucal.sim` |
| `RBD9103` (ucal and rsoxs), `K2600B` | stays in nbs-sim |
| GreatEyes (`greateyes.py`) | rsoxs `rsoxs.sim` |
| PCO Edge (`pcoedge.py`) | vppem `vppem.sim` |
| `beam_map` (the map IOC and its physics module) | its own package, `nbs-map-ioc` (Phase 1b, deferred); real beamlines run it without nbs-sim (as beamline-onboarding.md already suggests) |

## Phases

Each phase leaves every pod's sim working. The order puts the shared
contracts first, so the device moves later are mechanical.

### Phase 0: agree on the contracts

- Record the decisions below, and the PV names, overlay keys, entry
  point groups and `_process` key in nbs-sim's docs.
- Inventory: for each class in `nbs_sim.devices`, which pods use it (from
  each pod's sim_conf.toml) and its target home.

Done when the contract doc is merged.

### Phase 1: physics in the beam IOC

Status: implemented on nbs-sim branch `sim-physics` (2026-11-09).
Slits and other attenuators feed the overlay once they publish
`transmission` in Phase 2.

- Extend `mapfile.py` with overlay loading (`--sim-overlay` or
  `beam_map.sim.toml` beside the map in sim mode) for `[beam] flux` and node
  `transmission`, `energy` and `bandwidth`.
- Add a `physics.py` module that computes Transmission, Flux, Energy and
  Bandwidth per node. The map IOC loads it, and serves its PVs, only when an
  overlay is given; overlay inputs can be a PV or a fixed `value`.
- Unit tests on small maps (branches, blocking, missing inputs). Integration
  test: map IOC plus a stub IOC on an isolated CA port, the pattern the
  peak-ioc device tests use.

Done when, with claude-pods' map and an overlay, `branch_es:Flux` follows
ring current, shutters and slits, and the four existing PVs are unchanged;
and without an overlay the IOC serves exactly today's PVs.

### Phase 1b: split out nbs-map-ioc

Status: deferred (2026-11-09). Phase 2 went ahead with the map IOC still in
nbs-sim; do the split once the physics PVs have settled.

- Move `nbs_sim.beam_map` (map file parser, status, physics, IOC) into a new
  `nbs-map-ioc` package with its own CLI and tests. nbs-sim depends on it.
- nbs-bl reads the tree through `nbs-map-ioc`'s map file parser instead of
  its own copy in `nbs_bl/beam_map.py`.

Done when a beamline runs the map IOC with only `nbs-map-ioc` installed.

### Phase 2: the SDK, and the old parent API on top of it

Status: implemented on nbs-sim branch `sim-physics` (2026-11-09), tested
with claude-pods, which gains a `startup/beam_map.sim.toml`. As built:

- `nbs_sim.sdk` has `BeamInput` (map PVs at a node, a fallback for anything
  missing or NaN, and `mean_flux` over an interval), `ParentBeam` (the old
  `Beamline` computation) and `FixedBeam`; `beam_for(device)` picks one.
  A BeamInput falls back to ParentBeam, so a pod keeps running if the map
  IOC is down.
- `DetectorKindMixin.kind_signal()` takes flux, energy and bandwidth from
  the beam source. SRS570, RBD9103 and the MCA use it too instead of their
  own copies; their `ref` now gets the mono broadening like the generic
  detector's.
- Not done yet: sc, ref and i1 still take the sample model from the parent
  `Beamline` (`sample_yield`, `distance_func`, the `yspl`/`refspl`
  splines), so they need nbs-sim's main process. Phase 5 added
  `Sim:SampleID` and `Sim:Overlap` for devices elsewhere. HAXPES is not
  checked.

The original task list:

- Add `nbs_sim.sdk` (`BeamInput`, `Attenuator`, sample model reader) and pass
  `_node` and the map prefix through `createIOCDevice`.
- Give shutters, gate valves, slits and the manipulator `Attenuator` outputs.
- Port `DetectorKindMixin` (i0, sc, ref, i1) to `BeamInput`. An i0 reads
  `Flux` at its node. An i1 sits downstream of the sample node, so it no
  longer needs `distance_func(transmission=True)`. An sc needs flux, energy
  and the sample model.
- Keep `Beamline.intensity_func()`, `energy` and friends working for
  unported devices: when the sim config names a beam IOC, they read from
  `BeamInput`s; otherwise they compute as today.

Done when the claude-pods and HAXPES sims run with detectors on `BeamInput`,
and i0, sc and i1 give the same values as before, to within noise.

### Phase 3: plugin loading and processes

Status: implemented (2026-11-09) on nbs-sim branch `sim-physics`, with the
compose pattern in nbs-pods. As built:

- `nbs_sim.plugins` reads both entry point groups. `nbs-sim` passes the
  merged `nbs_sim.loaders` tables, with sim_conf.toml `[loaders]` on top,
  to `generate_device_config`; `createIOCDevice` resolves `_target` through
  `nbs_sim.devices` names before dotted paths. A table that fails to load
  is logged and skipped.
- `nbs-sim --process NAME` loads only the devices with `_process = NAME`;
  plain `nbs-sim` loads those with none. An extra process does not serve
  the beamline's `beam_available` PV, and since it holds only part of the
  beamline, its devices fall back to a FixedBeam rather than a ParentBeam.
- nbs-pods: a `sim-process` compose service (same sim image, `pixi run
  sim-process`, process from `NBS_SIM_PROCESS`, default `analyzer`), and a
  `SIM_EXTRAS` build arg on the sim image for pip-installing beamline
  packages. A pod with more processes copies the service directory.
- Checked with haxpes as the package outside nbs-sim (see Phase 5): its
  entry point maps `PeakAnalyzerIOC` with no `[loaders]` line, and the
  analyzer runs in `--process analyzer` reading the beam IOC.

The original task list:

- `nbs_sim.loaders` and `nbs_sim.devices` entry points, merged under
  sim_conf.toml `[loaders]`.
- `_process` key and `nbs-sim --process`.
- Compose pattern in nbs-pods for an extra sim process, plus a sim image that
  can install beamline packages' `sim` extras.

Done when a test package outside nbs-sim registers a sim class that loads in
a second process and reads physics from the beam IOC.

### Phase 4: move beamline- and facility-specific devices out

Status: deferred (2026-11-09). Phases 3 and 5 do not need it: the classes
stay in nbs-sim and pods keep their `[loaders]` lines until it is done.

- Move the classes per the table into `sst_base.sim`, `haxpes.sim`,
  `ucal.sim`, `rsoxs.sim` and `vppem.sim`, each with an entry point loader
  table. These are pure moves: no behaviour changes in this phase, so any
  regression is a packaging problem.
- Leave re-export shims in `nbs_sim.devices` with a deprecation warning for
  one release, so pod configs can move at their own pace.
- Update each pod's sim_conf.toml to drop the `[loaders]` lines now provided
  by entry points.

Done when nbs-sim imports nothing SST- or beamline-specific outside the shims.

### Phase 5: the PEAK analyzer, as the first external device

Status: implemented (2026-11-09) in peak-ioc, haxpes (branch
`peak-ioc-device`) and nbs-sim (branch `sim-physics`). As built:

- peak-ioc: `SimBackend(lines=..., beam=..., work_function=4.5)`. A `Line`
  has a binding energy (core) or kinetic energy (Auger); widths add
  natural width, 0.2% of pass energy and (core only) mono bandwidth in
  quadrature, keeping the line's area. The beam needs `energy()`,
  `bandwidth()`, `flux()` and optionally `mean_flux(t0, t1)`; a sweep takes
  each channel's flux over its own slice of the acquisition. `load_lines`
  reads `[[line]]` TOML. Defaults (Au 4f at a constant 2090 eV) keep
  `peak-sim-ioc` working on its own.
- nbs-sim: the manipulator serves `{prefix}Sim:SampleID` and
  `{prefix}Sim:Overlap` (fraction of the beam on the bar). `nbs_sim.sdk`
  has `SampleInput` to watch them and `SampleTable` to read per-sample
  columns from the sample CSV.
- haxpes: `haxpes.sim.peak.PeakAnalyzerSim` is peak-ioc's IOC on
  `SimBackend`, with the beam from `start_beam` at its node, counts scaled
  by overlap and the sample's `signal_scale`, and lines from the sample's
  `xps` column (a line file) or `lines_file`. It adds `Sim:Flux`,
  `Sim:PhotonEnergy` and `Sim:Sample` PVs for checking. `haxpes.sim`
  registers it for `PeakAnalyzerIOC` and as `peak-analyzer`; a `sim` extra
  lists nbs-sim and peak-ioc.
- HAXPES (profile_collection_haxpes): `beam_map.sim.toml` feeds the map the
  DCCT ring current, the DCM energy (bandwidth = 1.4e-4 x energy, Si(111))
  and the DM1 and HAXPES slit transmissions. `devices_sim.toml` swaps
  `peak_analyzer` to `PeakAnalyzerIOC` and loads it; sim_conf.toml starts
  DM1 and the nanoBPM filter out of the beam and gives the analyzer the
  manipulator's sample PVs. In that sim, with the slits opened (they start
  closed) and the bar half in the beam: I0 per unit flux stayed at 600 and
  counts per flux at 0.41-0.44 when the HAXPES slits halved the flux,
  Au 4f7/2 sat within 0.2 eV of hv - 88.5 at 1820 and 1850 eV, and closing
  S2 two seconds into a 4.8 s sweep emptied its last third.
- Also checked on a scratch copy of claude-pods' startup, with the analyzer
  in `_process = "analyzer"` and a sample with its own C 1s and C KLL lines.
- Not done: the HAXPES sim environment (its pixi.toml) needs haxpes and
  peak-ioc for the pods to run the analyzer, and peak-ioc has no remote
  yet; a standalone `peak-sim-ioc` that reads the beam map.

The original task list:

- peak-ioc: give `SimBackend` a pluggable beam source (photon energy, flux
  averaged over the acquisition, bandwidth). Add a binding-energy line model:
  core lines at KE = hv − BE − φ, Auger lines at fixed KE, widths combining
  natural width, analyzer resolution and mono bandwidth.
- haxpes: `haxpes.sim.peak` gives the analyzer a beam source built on
  `BeamInput` at its node, registers it for `PeakAnalyzerIOC`, and runs it as
  `_process = "analyzer"` or standalone.
- Optional `xps` column in the sample model for per-sample lines.

Done when, in the HAXPES sim, an XPS scan's counts track i0, lines move with
the DCM energy, and closing a shutter mid-sweep lowers the counts.

### Phase 6: clean up

- Remove the `parent` physics API once nothing uses it, and the shims after
  their release.
- Docs: a "writing a sim device" guide, the map overlay reference, and a
  worked example (the PEAK analyzer).

### Later: undulator and mono behaviour

- The undulator sim (now in `sst_base.sim`) reports a `transmission` for
  gap or harmonic mismatch with the mono energy, and the mono reports its
  bandwidth and harmonic content, replacing the fixed overlay values. Both
  fit the node model without changing the PV contract.

## Decisions

Settled 2026-11-09.

1. **One beam IOC.** The physics runs in the map IOC process, as a separate
   module loaded only with a sim overlay. A second IOC would evaluate the
   same tree from the same inputs and could briefly disagree with the map
   about blocking. Without an overlay the map IOC is exactly today's.
2. **Flux stays relative** (mA × transmissions), with a `scale` on the
   source. Detectors keep their own gain factors; nominal photons/s can come
   later as a config change.
3. **Undulator and mono behaviour wait** until after the moves (see
   "Later"). Phase 4 is pure moves. Until then the mono node gets a fixed
   `bandwidth` in the overlay, which is all the PEAK line model needs.
4. **SST pieces go to sst-base**, in `sst_base.sim`, next to its existing
   `nbs_gui.tabs` entry points. The install weight this brings applies to
   every beamline package alike (see Plugin loading), so it is not a reason
   for a separate `nbs-sim-sst`.
5. **RBD9103 and K2600B stay in nbs-sim** as generic instruments. GreatEyes
   goes to rsoxs and PCO Edge to vppem.
6. **The map IOC becomes its own package** (Phase 1b), but not right after
   Phase 1 as first planned: it is deferred until the physics PVs settle.
   Changing the map file schema and the IOC together is easier in one repo;
   after that, production beamlines should not need nbs-sim.
7. **Phases 3 and 5 before Phase 4.** The device moves are deferred; the
   plugin and process machinery and the PEAK analyzer came first.

## Risks

- **Startup order.** Devices start before the beam IOC is up. `BeamInput`
  defaults cover that, but a device that is still at its defaults should say
  so in its status, or tests will pass on stale physics.
- **Overlay drift.** Sim-only overlays can fall out of step with
  beam_map.toml as nodes are renamed. The map IOC should reject an overlay
  that names a node the map lacks.
- **Two transmission paths during Phase 2.** Until every pod's sim uses the
  beam IOC, there are two ways to compute intensity. Tests should compare
  them.
- **Image and dependency weight.** Plugin sim code must stay free of ophyd
  and bluesky imports; a CI import test per package can enforce it. The
  packages themselves still install the bluesky stack (see Plugin loading).

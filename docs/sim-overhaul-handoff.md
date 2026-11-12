# nbs-sim overhaul and PEAK analyzer: handoff

Context from a Claude Code session (Nov 6-12, 2026) for other agent threads.
The authoritative plan is `nbs-sim/docs/sim-overhaul-plan.md` on nbs-sim
branch `sim-physics`; this summarizes it and the state of every repo.

## Working conventions

- Commit only when asked, and let the user review diffs first. Keep work
  local: nothing is pushed or opened as a PR unless the user says so.
- nbs-pods: work on `develop` or a topic branch from it, never on `build`.
  `build` exists only to trigger the GitHub Actions image builds.
- Leave the user's untracked files alone (`pixi.lock`, `history.sqlite`,
  `notes_on_ultimate_nbs.md`, `device_config.yaml`, `dev-pixi.toml`, ...).
- Never touch the user's running pods. Test with local processes on
  isolated CA ports instead (see Testing).
- Do not delete the old direct-to-PEAK `haxpes.devices.peak_analyzer.PeakAnalyzer`.

## Goal of the overhaul

1. **Physics PVs.** Photon energy, bandwidth and flux are served per beam
   map node and are how a sim device learns about the beam.
2. **The beam map IOC computes them**, walking the same node tree it
   already uses for blocking status.
3. **Plugin loading.** Sim classes live with the code they simulate and
   nbs-sim finds them through entry points.
4. **Location independence.** Devices take physics inputs and report
   attenuation over CA, so they run the same in the main nbs-sim process,
   an extra process, or their own container.

## Decisions (settled 2026-11-09)

- One beam IOC: physics runs in the map IOC, only when a sim overlay is
  given. Without an overlay the map IOC is exactly as before.
- Flux stays relative (mA x transmissions) with a `scale` on the source.
- Undulator and mono behaviour wait until after the device moves.
- SST pieces go to `sst_base.sim` (including WienerPS, since other
  endstations will use it soon). RBD9103 and K2600B stay in nbs-sim.
  GreatEyes goes to `rsoxs.sim`, PCO Edge to `vppem.sim`.
- Phase 1b (map IOC as its own package) deferred until the physics PVs
  settle. Phase 4 (device moves) deferred; Phases 3 and 5 came first.

## Phase status

| Phase | State |
| --- | --- |
| 0: contract doc and per-pod inventory | not done |
| 1: physics PVs in the map IOC | done, committed |
| 1b: split out `nbs-map-ioc` | deferred |
| 2: SDK, devices read the beam from the map | done, committed |
| 3: entry points, `--process`, `sim-process` service | done, committed |
| 4: move beamline-specific devices out | deferred |
| 5: PEAK analyzer as the first external device | done, committed; HAXPES pod run unconfirmed |
| 6: cleanup, docs | not started |
| Later: undulator gap/mono behaviour | not started |

## Repos, branches, commits (all local, nothing pushed unless noted)

| Repo (path) | Branch | Commits |
| --- | --- | --- |
| nbs-sim (`~/work/xraygui/nbs-sim`) | `sim-physics` (from `per-sample-spectra`) | 4bd7c36 plan; efde32b Phase 1; 0013637 Phase 2; c1bcfd0 Phases 3 and 5 |
| claude-pods (`~/work/xraygui/claude-pods`) | `sim-physics` | a07242f beam map sim overlay |
| peak-ioc (`~/work/xraygui/peak-ioc`, no remote yet) | `sim-physics` (from `preposition-pv`) | ce7e9a9 initial IOC; 8d64821 Preposition PV; d107a68 line model and beam source |
| haxpes (`~/work/xraygui/haxpes`) | `peak-ioc-device` | b0018ea, a4109d1 `PeakAnalyzerIOC`; ec0bc2f `haxpes.sim` |
| nbs-pods (`~/work/xraygui/nbs-pods`) | `sim-process` (from `develop` = `master` = 912f94f) | a45bf69 sim-process service |
| profile_collection_haxpes (`~/work/nsls-ii-sst/`) | `beam-map-tender` | bdb44b1 HAXPES sim setup (local only) |

profile_collection_haxpes: `develop` was fast-forwarded to `beam-map-tender`
at bb402d4 and pushed (for the image build); bdb44b1 is not pushed. Its CI
only tags images on push events, and pushes only trigger CI on `main`.
Images are published as `env-<hash>` (`ci/image-tag.sh <rev>`); run a
specific build with `pixi run pods develop --image-tag env-<hash>`.

## How it works

### Map IOC physics (Phase 1, `nbs_sim/beam_map/`)

- Sim overlay `beam_map.sim.toml` beside `beam_map.toml`, read only in sim
  mode (`NBS_SIM_MODE=1` or `--sim-overlay`). It may only set
  `[beam] flux` and node `transmission`, `energy`, `bandwidth`. An input is
  `{ pv = ..., scale = ... }`, `{ value = ... }` or a bare number. Parsed
  separately (not merged), so it can never change a condition.
- Per node: `N:Transmission`, `N:Flux`, `N:Energy`, `N:Bandwidth`, plus
  `Source:Flux`. Blocking node = transmission 0. Flux at a node = source
  flux x transmissions of its ancestors. Energy/bandwidth come from the
  nearest setting node upstream (inclusive); unset energy is NaN, unset
  bandwidth 0. Disconnected transmission counts as 1 in sim mode.

### SDK (`nbs_sim/sdk.py`)

- Beam sources with `flux()`, `energy()`, `bandwidth(energy)`:
  `BeamInput(map_prefix, node, fallback)` (CA subscriptions to the node's
  physics PVs; `mean_flux(t0, t1)` over monotonic time), `ParentBeam`
  (old in-process `Beamline` computation), `FixedBeam`.
- `beam_for(device)` / `start_beam(device)`: BeamInput when the device has
  a `beam_node` (from devices.toml `_node`) and the parent Beamline has a
  beam map; fallback ParentBeam in the main process, FixedBeam in an extra
  process.
- nbs-sim reads the beam from the map when the startup dir has a
  `beam_map.sim.toml` (`--beam-map` / `--no-beam-map` override).
- Attenuators serve `{prefix}transmission`; shutters, gate valves, slits
  already did, and the manipulator now does.
- Samples: the manipulator serves `{prefix}Sim:SampleID` and
  `{prefix}Sim:Overlap` (fraction of beam on the bar). `SampleInput(prefix)`
  watches them; `SampleTable(path)` reads per-sample CSV columns.
- `DetectorKindMixin.kind_signal()` is shared by GenericDetector, SRS570,
  RBD9103 and the MCA.

### Plugins and processes (Phase 3)

- `nbs_sim.plugins`: entry point groups `nbs_sim.loaders` (dict or function
  returning {real class: sim class}, merged in entry point name order,
  sim_conf.toml `[loaders]` wins) and `nbs_sim.devices` (short names usable
  as `_target`).
- sim_conf.toml `_process = "name"`; `nbs-sim --process name` runs only
  those devices, plain `nbs-sim` the rest. Extra processes don't serve
  `beam_available`.
- nbs-pods `sim-process` compose service: same sim image, runs
  `nbs-sim --process "$NBS_SIM_PROCESS"` (default `analyzer`); copy the
  directory for more processes. Sim image `SIM_EXTRAS` build arg
  pip-installs beamline packages.

### PEAK analyzer (Phase 5)

- peak-ioc: caproto IOC (`peak-ioc` real, `peak-sim-ioc` sim), not
  areaDetector. `SimBackend(lines, beam, work_function=4.5)`: core lines at
  KE = hv - BE - phi, Auger lines at fixed KE; widths add natural width,
  0.2% of pass energy and (core only) bandwidth in quadrature, keeping
  area; sweeps take per-channel flux over their slice of the acquisition.
  `load_lines()` reads `[[line]]` TOML. Defaults: Au 4f at 2090 eV.
- haxpes: `haxpes.devices.peak_analyzer_ioc.PeakAnalyzerIOC` (ophyd,
  drop-in for `PeakAnalyzer`). `haxpes.sim.peak.PeakAnalyzerSim` runs
  peak-ioc's IOC inside nbs-sim with beam from `start_beam`, counts scaled
  by overlap and the sample's `signal_scale`, and lines from the sample's
  `xps` column or `lines_file`. `count_rate` default 20 per unit map flux.
  Extra PVs `Sim:Flux`, `Sim:PhotonEnergy`, `Sim:Sample`. Registered via
  `haxpes.sim:LOADERS` for `PeakAnalyzerIOC`; `sim` extra lists nbs-sim
  and peak-ioc.

### HAXPES sim (profile_collection_haxpes, commit bdb44b1)

- `beam_map.sim.toml`: flux from `SR:OPS-BI{DCCT:1}I:Real-I`; DCM energy
  from `XF:07ID6-OP{Mono:DCM1-Ax::ENERGY_MON`, bandwidth = 1.4e-4 x
  energy; transmission for `dm1_slits` and `haxpes_slits`.
- `devices_sim.toml`: `peak_analyzer` -> `PeakAnalyzerIOC` at
  `XF:07ID-ES{PEAK}:`, `_defer_loading = false`, `_remove = ["peak_url"]`.
- `sim_conf.toml`: `dm1 = { value = 60 }`, `nBPM = { value = 16 }` (the
  map blocks below 55 and 15); `peak_analyzer = { sample_prefix =
  "XF:07ID1-BI{HAX-Ax:" }`.
- Dev scripts: sim compose runs `sim-dev`, which installs local nbs-sim,
  haxpes and peak-ioc (`--no-deps`); map-ioc installs local nbs-sim from
  `NBS_MAP_IOC_SRC`; the 10.66.51.255 CA settings in `map-ioc-start.sh`
  apply only outside sim mode (pod network is 10.89.0.0/24). The
  queueserver's `qs-start.sh` already installs local haxpes.
- Both slit sets start closed; open the blades before measuring. Put the
  sample bar in the beam (or drop `sample_prefix`) to get counts.

## Testing

- nbs-sim needs the caproto fork, branch `no_macros` (PV names with `{`
  break stock caproto); local checkout at `~/work/caproto`. Tests:
  `PYTHONPATH=~/work/caproto:src .pixi/envs/test/bin/python -m pytest tests`
  (95 pass). peak-ioc: `pixi run -e test pytest tests` (19 pass). haxpes:
  `tests/test_sim_peak.py` (3 pass, needs peak-ioc and nbs-sim importable).
- Live checks: run nbs-sim, the map IOC and optionally `--process
  analyzer` with `EPICS_CA_SERVER_PORT=26064`, `EPICS_CA_REPEATER_PORT=26065`,
  `EPICS_CA_ADDR_LIST=127.255.255.255`, `EPICS_CA_AUTO_ADDR_LIST=NO`.
- Results in the HAXPES sim: I0 per unit flux constant (~600) and counts
  per flux constant when the slits halved the flux; Au 4f7/2 within 0.2 eV
  of hv - 88.5 at 1820 and 1850 eV; closing S2 mid-sweep emptied the last
  third of the sweep. Same checks passed on claude-pods' map.
- Gotcha: `pkill -f` patterns that also appear in the shell command kill
  the shell; list PIDs and kill them explicitly.

## What's left

- Confirm the HAXPES pod `--dev` run with the analyzer (first real test of
  the bluesky side loading `PeakAnalyzerIOC` and of editable installs in
  containers).
- Phase 2 leftovers: sc, ref and i1 still use the in-process sample model
  (`sample_yield`, `distance_func`, `yspl`/`refspl`), so they can't run in
  an extra process; HAXPES detector values before/after not compared.
- Phase 5 leftovers: HAXPES `pixi.toml` sim env lacks haxpes/peak-ioc (only
  `--dev` works); peak-ioc has no remote; standalone `peak-sim-ioc` can't
  read the beam map; HAXPES `pixi.lock` has nbs-pods 0.2.8 and
  `requires-pixi >= 0.82.1` (user wants 0.2.9 / >= 0.82.3).
- Phase 0: contract doc and inventory of sim classes per pod.
- Phase 1b and Phase 4 (deferred), Phase 6, and the undulator/mono work.
- Risks: devices don't report when on fallback values; no CI check that
  sim plugins avoid ophyd/bluesky imports; no test comparing map flux with
  the in-process calculation.
- profile_collection_haxpes CI: `tag-branch` only runs on push; one-line
  change to also run on `workflow_dispatch` was offered, not made.

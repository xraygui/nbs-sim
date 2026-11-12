# nbs-sim

`nbs-sim` provides a configurable EPICS simulation IOC for NBS beamline environments.
It builds a caproto-based IOC from startup configuration files and simulated device
classes so UIs and orchestration systems can be exercised without hardware.

## Features

- Loads simulated devices from configuration
- Exposes PVs through a caproto IOC.
- Supports startup from a profile startup directory or explicit config file paths.
- Includes simulation device classes for motors, shutters, detectors, optics, and
  beamline-specific components.

## Requirements

- Python `>=3.8`
- Runtime dependencies from `pyproject.toml`:
  - `caproto`
  - `scipy`
  - `numpy`
  - `nbs-bl`
  - `nbs-core`

## Installation

### pip (editable)

```bash
pip install -e .
```

### pixi

If you use pixi in this monorepo:

```bash
pixi install
pixi run python -m pip install -e .
```

## Running the IOC

The CLI entrypoint is `nbs-sim`.

### Option 1: startup directory

Point to a startup directory that contains:

- `devices.toml`
- `sim_conf.toml`

```bash
nbs-sim --startup-dir /path/to/startup --list-pvs
```

### Option 2: explicit file paths

```bash
nbs-sim \
  --device-file /path/to/devices.toml \
  --config-file /path/to/sim_conf.toml \
  --list-pvs
```

If neither `--startup-dir` nor both config file options are provided, startup exits
with a CLI error.

### Sim classes from other packages

A package can ship sim classes for its own devices and register them with
entry points, instead of every pod listing them in sim_conf.toml
`[loaders]`:

```toml
[project.entry-points."nbs_sim.loaders"]
haxpes = "haxpes.sim:LOADERS"   # a dict {real class: sim class}, or a function returning one

[project.entry-points."nbs_sim.devices"]
peak-analyzer = "haxpes.sim.peak:PeakAnalyzerSim"   # a short name usable as _target
```

The installed packages' tables are merged in entry point name order, and
sim_conf.toml `[loaders]` overrides them. Sim code registered this way should
import only caproto, numpy and `nbs_sim.sdk`, never ophyd or bluesky.

### Extra sim processes

A device can run in its own process: give it `_process = "analyzer"` in
sim_conf.toml `[devices]`, and run

```bash
nbs-sim --startup-dir /path/to/startup --process analyzer
```

beside the main `nbs-sim`, which runs every device without a `_process`.
Devices in an extra process get their beam from the beam map IOC
(`nbs_sim.sdk.BeamInput`, so give them a `_node`) and the sample from the
manipulator's `Sim:SampleID` and `Sim:Overlap` PVs (`nbs_sim.sdk.SampleInput`).
Without a beam map they see a fixed beam.

## How it works

- `nbs_sim.beamline:main` parses CLI arguments and loads device configuration.
- `generate_device_config` merges the device and simulation configuration files.
- `loadFromConfig` instantiates devices with `createIOCDevice`.
- The IOC is started with caproto `run(...)`.

## Development

Install development tools:

```bash
pip install -e ".[dev]"
```

Run tests:

```bash
pytest
```

Format and lint:

```bash
black src
flake8 src
```

## Package layout

- `src/nbs_sim/beamline.py`: CLI entrypoint and IOC assembly.
- `src/nbs_sim/load.py`: device factory helper used by autoload.
- `src/nbs_sim/plugins.py`: sim classes from other packages' entry points.
- `src/nbs_sim/sdk.py`: beam and sample inputs for sim devices.
- `src/nbs_sim/devices/`: simulation device implementations.

## Notes

- Project status is currently alpha.
- This package expects configuration files generated or maintained by the broader
  NBS beamline stack.

import numpy as np
import asyncio
from caproto.server import PVGroup, pvproperty
from caproto import ChannelType
from .detectors import DetectorKindMixin
import re

unit_strs = ["nA", "uA", "mA"]
range_strs = ("Auto", "2nA", "20nA", "200nA", "2uA", "20uA", "200uA", "2mA")
mode_strs = ("Single", "Multiple", "Continuous")
sample_strs = ("Idle", "Sampling")
stable_strs = ("Not Stable", "Stable")
in_range_strs = ("OK", "Under", "Over")

# Range limits in nA for each range setting
range_limits = {
    "2nA": 2e-9,
    "20nA": 20e-9,
    "200nA": 200e-9,
    "2uA": 2e-6,
    "20uA": 20e-6,
    "200uA": 200e-6,
    "2mA": 2e-3,
    "Auto": float("inf"),  # Auto range has no upper limit
}


class RBD9103Detector(DetectorKindMixin, PVGroup):
    """
    RBD9103 detector with device-specific simulation.

    This detector simulates the RBD9103 picoammeter with proper sampling
    behavior, range management, and current reading functionality.
    """

    # Current reading PV
    value = pvproperty(
        name="Current_RBV", value=0, dtype=float, read_only=True, doc="Current Value"
    )

    def __init__(
        self, prefix, kind="sc", initial_signal_level=1e-9, parent=None, **kwargs
    ):
        """
        Initialize the RBD9103 detector.

        Parameters
        ----------
        prefix : str
            PV prefix for the detector
        kind : str, optional
            Detector kind (i0, sc, ref, i1), by default "sc"
        initial_signal_level : float, optional
            Initial current level in Amperes, by default 1e-9 (1 nA)
        parent : object, optional
            Parent beamline object, by default None
        """
        super().__init__(prefix, parent=parent)
        self.kind = kind
        self._initial_signal_level = initial_signal_level
        self._current_value = initial_signal_level
        self._sampling_active = False
        self._sampling_task = None
        self._samples_remaining = 0  # For multiple sampling mode
        self._sample_counter = 0  # Track total samples taken

        # Initialize device state

    async def _read(self):
        """
        Read the current value based on detector kind and device state.

        Returns
        -------
        float
            Current value in Amperes
        """
        # Get base intensity from parent beamline
        if self.kind == "i0":
            intensity = self.parent.intensity_func()
        elif self.kind == "sc":
            energy = self.parent.energy.value
            overlap = self.parent.distance_func(transmission=False)
            intensity = self.parent.intensity_func() * self.parent.yspl(energy)
            intensity = intensity * overlap
        elif self.kind == "ref":
            energy = self.parent.energy.value
            intensity = self.parent.intensity_func() * self.parent.refspl(energy)
        elif self.kind == "i1":
            overlap = self.parent.distance_func(transmission=True)
            intensity = self.parent.intensity_func()
            intensity = intensity * overlap
        else:
            intensity = self.parent.intensity_func()

        # Convert intensity to current (assuming some conversion factor)
        # This is a simplified model - in reality this would depend on
        # detector efficiency
        current = intensity * self._initial_signal_level

        # Add some realistic noise1
        # noise = np.random.normal(0, 0.01)  # 0.01 V noise floor
        # current += noise

        # Ensure current is positive
        # current = max(current, 0)

        self._current_value = current
        # print(f"Current value: {current}")
        return current

    def _parse_range_value(self, range_str):
        """
        Convert a range string like '2nA', '20uA', etc. to a float value in Amperes.
        """
        if not range_str:
            return 1e-9  # default to 1 nA if not set
        match = re.match(r"([0-9.]+)\s*([a-zA-Z]+)", range_str)
        if not match:
            return 1e-9
        value, unit = match.groups()
        value = float(value)
        unit_map = {"pA": 1e-12, "nA": 1e-9, "uA": 1e-6, "mA": 1e-3, "A": 1.0}
        mult = unit_map.get(unit, 1.0)
        return value * mult

    async def _update_range_actual(self):
        """Update the actual range based on current value and range control."""
        range_ctrl = self.range_ctrl.value
        if range_ctrl == "Auto":
            # Auto-range logic: select appropriate range based on current
            current_abs = abs(self._current_value)
            if current_abs < 2e-9:
                await self.range_actual.write("2nA")
            elif current_abs < 20e-9:
                await self.range_actual.write("20nA")
            elif current_abs < 200e-9:
                await self.range_actual.write("200nA")
            elif current_abs < 2e-6:
                await self.range_actual.write("2uA")
            elif current_abs < 20e-6:
                await self.range_actual.write("20uA")
            elif current_abs < 200e-6:
                await self.range_actual.write("200uA")
            else:
                await self.range_actual.write("2mA")
        else:
            await self.range_actual.write(range_ctrl)

    async def _update_in_range_status(self):
        """Update the in-range status based on current value and range."""
        range_actual = self.range_actual.value
        if range_actual == "Auto":
            await self.in_range.write("OK")
            return

        current_abs = abs(self._current_value)
        range_limit = range_limits.get(range_actual, float("inf"))

        if current_abs > range_limit:
            await self.in_range.write("Over")
        elif current_abs < range_limit * 0.01:  # Below 1% of range
            await self.in_range.write("Under")
        else:
            await self.in_range.write("OK")

    async def _update_stability(self):
        """Update stability status based on current fluctuations."""
        # Simple stability check: if current is relatively stable
        # In a real implementation, this would track historical values
        if abs(self._current_value) > 1e-12:  # Above noise floor
            await self.stable.write("Stable")
        else:
            await self.stable.write("Not Stable")

    async def _sampling_loop(self):
        """Main sampling loop that updates values based on sampling mode."""
        while self._sampling_active:
            try:
                # Read current value (noiseless)
                current = await self._read()

                # Get the current range value
                range_str = getattr(self, "range_actual", None)
                if range_str is not None:
                    range_value = self._parse_range_value(self.range_actual.value)
                else:
                    range_value = 1e-9  # default 1 nA

                # Cap at range and add noise
                if abs(current) > range_value:
                    capped_current = range_value * (1 if current >= 0 else -1)
                else:
                    noise = np.random.normal(0, 0.01 * range_value)
                    capped_current = current + noise

                # Update the value PV
                await self.value.write(capped_current)

                # Increment sample counter
                self._sample_counter += 1
                await self.sample_counter.write(self._sample_counter)

                # Update device state
                await self._update_range_actual()
                await self._update_in_range_status()
                await self._update_stability()

                # Update sampling rate actual to match control
                await self.sampling_rate.write(self.sampling_rate_ctrl.value)

                # Handle different sampling modes
                sampling_mode = self.sampling_mode.value
                if sampling_mode == "Single":
                    # Single shot - take one reading and stop
                    await self.sample.write("Idle", verify_value=False)
                    self._sampling_active = False
                    break
                elif sampling_mode == "Multiple":
                    # Multiple samples - count down remaining samples
                    self._samples_remaining -= 1
                    if self._samples_remaining <= 0:
                        await self.sample.write("Idle", verify_value=False)
                        self._sampling_active = False
                        break
                # Continuous mode continues indefinitely

                # Determine sampling period based on rate
                rate = self.sampling_rate_ctrl.value
                if rate > 0:
                    period = 1.0 / rate
                else:
                    period = 1.0  # Default 1 Hz

                await asyncio.sleep(period)

            except Exception as e:
                print(f"Error in RBD9103 sampling loop: {e}")
                await asyncio.sleep(1.0)


# Create the main RBD9103 class that combines device functionality
# with detector capability
class RBD9103(RBD9103Detector):
    """
    RBD9103 picoammeter with full device simulation and detector integration.

    This class provides both the device-specific PVs and the detector
    functionality for integration with the nbs_sim beamline.
    """

    # Device-specific PVs
    unit = pvproperty(
        name="CurrentUnits_RBV",
        record="mbbo",
        value="nA",
        enum_strings=unit_strs,
        dtype=ChannelType.ENUM,
    )
    range_ctrl = pvproperty(
        name="Range",
        record="mbbo",
        value="Auto",
        enum_strings=range_strs,
        dtype=ChannelType.ENUM,
        doc="Range control",
    )
    range_actual = pvproperty(
        name="RangeActual_RBV",
        record="mbbo",
        value="Auto",
        enum_strings=range_strs,
        dtype=ChannelType.ENUM,
    )
    sampling_rate_ctrl = pvproperty(name="SamplingRate", value=1.0, dtype=float)
    sampling_rate = pvproperty(
        name="SamplingRateActual_RBV", value=1.0, dtype=float, read_only=True
    )
    sampling_mode = pvproperty(
        name="SamplingMode",
        record="mbbo",
        value="Single",
        enum_strings=mode_strs,
        dtype=ChannelType.ENUM,
    )
    sampling_mode_rbv = pvproperty(
        name="SamplingMode_RBV",
        record="mbbo",
        value="Single",
        enum_strings=mode_strs,
        read_only=True,
        dtype=ChannelType.ENUM,
    )
    sampling_status = pvproperty(
        name="Sample_RBV",
        record="mbbo",
        value="Idle",
        enum_strings=sample_strs,
        dtype=ChannelType.ENUM,
        read_only=True,
    )
    sample = pvproperty(
        name="Sample",
        record="mbbo",
        value="Idle",
        enum_strings=sample_strs,
        dtype=ChannelType.ENUM,
    )
    stable = pvproperty(
        name="Stable_RBV",
        record="mbbo",
        value="Not Stable",
        enum_strings=stable_strs,
        read_only=True,
        dtype=ChannelType.ENUM,
    )
    in_range = pvproperty(
        name="InRange_RBV",
        record="mbbo",
        value="OK",
        enum_strings=in_range_strs,
        read_only=True,
        dtype=ChannelType.ENUM,
    )

    # New PVs for sample counting
    num_samples = pvproperty(
        name="NumSamples",
        value=1,
        dtype=int,
    )
    num_samples_rbv = pvproperty(
        name="NumSamples_RBV",
        value=1,
        dtype=int,
        read_only=True,
    )
    sample_counter = pvproperty(
        name="SampleCounter_RBV",
        value=0,
        dtype=int,
        read_only=True,
    )

    @sample.putter
    async def sample(self, instance, value):
        """Handle sample control changes."""
        print(f"Sample control changed to {value}")
        if value == "Sampling" and not self._sampling_active:
            self._sampling_active = True

            # Reset sample counter for new sampling session
            self._sample_counter = 0
            await self.sample_counter.write(0)

            # Set up sampling based on mode
            sampling_mode = self.sampling_mode.value
            if sampling_mode == "Multiple":
                # Use the configured number of samples
                self._samples_remaining = self.num_samples.value

            self._sampling_task = asyncio.create_task(self._sampling_loop())
            await self.sampling_status.write("Sampling")
        elif value == "Idle" and self._sampling_active:
            self._sampling_active = False
            if self._sampling_task:
                self._sampling_task.cancel()
                self._sampling_task = None
            await self.sampling_status.write("Idle")
        return value

    @range_actual.startup
    async def range_actual(self, instance, async_lib):
        print("RBD9103 range_actual startup called")
        await self._update_range_actual()

    @in_range.startup
    async def in_range(self, instance, async_lib):
        print("RBD9103 in_range startup called")
        await self._update_in_range_status()

    @sampling_rate_ctrl.putter
    async def sampling_rate_ctrl(self, instance, value):
        """Handle sampling rate control changes."""
        # Clamp value to valid range
        if value < 0.1:
            value = 0.1
        elif value > 500:
            value = 500
        return value
        # await instance.write(value)

    @sampling_mode.putter
    async def sampling_mode(self, instance, value):
        """Handle sampling mode control changes."""
        # Update the readback value
        await self.sampling_mode_rbv.write(value)
        return value
        # await instance.write(value)

    @num_samples.putter
    async def num_samples(self, instance, value):
        """Handle number of samples control changes."""
        # Ensure value is positive
        if value < 1:
            value = 1
        # Update the readback value
        await self.num_samples_rbv.write(value)
        return value

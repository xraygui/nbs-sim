import asyncio
from pathlib import Path
from caproto.server import PVGroup, pvproperty, SubGroup, ioc_arg_parser, run
from caproto._data import ChannelType

try:
    import tomllib
except ImportError:
    import tomli as tomllib

# Parse gases.toml for FlowSMSSim
GASES_TOML_PATH = Path(__file__).parent.parent / "gases.toml"
with open(GASES_TOML_PATH, "rb") as f:
    gases_config = tomllib.load(f)


def get_gas_pv_defs():
    pv_defs = {}
    for gas, cfg in gases_config.items():
        flow_range = cfg.get("flow_range", [0.0, 100.0])
        pv_defs[gas] = {
            "low": flow_range[0],
            "high": flow_range[1],
        }
    return pv_defs


GAS_PV_DEFS = get_gas_pv_defs()
print(f"DEBUG: Found {len(GAS_PV_DEFS)} gases: {list(GAS_PV_DEFS.keys())}")


class EurothermSim(PVGroup):
    """
    Simulated Eurotherm temperature controller.

    Attributes
    ----------
    Temp_Setpoint : pvproperty
        Target temperature setpoint (degC).
    Temp_Rate : pvproperty
        Ramp rate (degC/min).
    Temp_Trigger : pvproperty
        Write 1 to start ramping event.
    Temp_Readback : pvproperty
        Simulated current temperature (degC).
    """

    Temp_Setpoint = pvproperty(
        value=22.0, dtype=float, doc="Temperature setpoint (degC)"
    )
    Temp_Rate = pvproperty(value=1.0, dtype=float, doc="Ramp rate (degC/min)")
    Temp_Trigger = pvproperty(value=0, dtype=int, doc="Write 1 to start ramp")
    Temp_Readback = pvproperty(
        value=22.0, dtype=float, read_only=True, doc="Current temperature (degC)"
    )

    async def _ramp_temperature(self, target, rate):
        """
        Simulate temperature ramping.

        Parameters
        ----------
        target : float
            Target temperature (degC).
        rate : float
            Ramp rate (degC/min).
        """
        current = self.Temp_Readback.value
        step = rate / 60.0  # degC per second
        while abs(current - target) > 0.01:
            if current < target:
                current = min(current + step, target)
            else:
                current = max(current - step, target)
            await self.Temp_Readback.write(current)
            await asyncio.sleep(1)
        await self.Temp_Readback.write(target)

    @Temp_Trigger.putter
    async def Temp_Trigger(self, instance, value):
        """
        Start a temperature ramp when set to 1.
        """
        if value == 1:
            target = self.Temp_Setpoint.value
            rate = self.Temp_Rate.value
            self._ramp_task = asyncio.create_task(self._ramp_temperature(target, rate))
        return 0


def create_flowsms_class():
    """
    Dynamically create FlowSMSSim class with gas PVs.

    Returns
    -------
    type
        FlowSMSSim class with all gas PVs defined.
    """
    # Start with the base class attributes
    class_attrs = {
        "__doc__": """
        Simulated FlowSMS gas flow controller.

        PVs are generated dynamically from gases.toml.

        Attributes
        ----------
        Flow_<GAS>_SP : pvproperty
            Setpoint for each gas (sccm).
        Flow_<GAS>_RB : pvproperty
            Readback for each gas (sccm).
        Flow_Apply : pvproperty
            Write 1 to apply all setpoints to readbacks.
        """,
        "Flow_Apply": pvproperty(
            value=0, dtype=int, doc="Apply all setpoints to readbacks"
        ),
    }

    # Add PVs for each gas
    for gas, lims in GAS_PV_DEFS.items():
        sp_name = f"{gas}_SP"
        rb_name = f"{gas}_RB"
        print(f"DEBUG: Adding PVs for gas {gas}: {sp_name}, {rb_name}")

        class_attrs[sp_name] = pvproperty(
            value=0.0,
            dtype=float,
            doc=f"Setpoint for {gas} (sccm)",
            units="sccm",
            lower_ctrl_limit=lims["low"],
            upper_ctrl_limit=lims["high"],
        )

        class_attrs[rb_name] = pvproperty(
            value=0.0,
            dtype=float,
            read_only=True,
            doc=f"Readback for {gas} (sccm)",
            units="sccm",
        )

    # Create the class
    FlowSMSSim = type("FlowSMSSim", (PVGroup,), class_attrs)

    # Add the putter method
    @FlowSMSSim.Flow_Apply.putter
    async def Flow_Apply(self, instance, value):
        """
        Apply all setpoints to readbacks when set to 1.
        """
        if value == 1:
            for gas in GAS_PV_DEFS:
                sp = getattr(self, f"{gas}_SP")
                rb = getattr(self, f"{gas}_RB")
                sp_val = sp.value
                await rb.write(sp_val)
        return 0

    return FlowSMSSim


# Create the FlowSMSSim class dynamically
FlowSMSSim = create_flowsms_class()


class PulseSim(PVGroup):
    """
    Simulated pulse mode controller.

    Attributes
    ----------
    Line_Select : pvproperty
        Enum: ["A", "B"]
    Line_Mode : pvproperty
        Enum: ["continuous", "pulses"]
    Pulse_Count : pvproperty
        Number of pulses.
    Pulse_Time : pvproperty
        Time per pulse (s).
    Pulse_Trigger : pvproperty
        Write 1 to start pulse sequence.
    Pulse_Status : pvproperty
        Enum: ["idle", "running", "done"]
    """

    Line_Select = pvproperty(
        value=0,
        enum_strings=["A", "B"],
        record="mbbo",
        dtype=ChannelType.ENUM,
        doc="Line select",
    )
    Line_Mode = pvproperty(
        value=0,
        enum_strings=["continuous", "pulses"],
        record="mbbo",
        dtype=ChannelType.ENUM,
        doc="Line mode",
    )
    Pulse_Count = pvproperty(value=1, dtype=int, doc="Number of pulses")
    Pulse_Time = pvproperty(value=1.0, dtype=float, doc="Time per pulse (s)")
    Pulse_Trigger = pvproperty(
        value=0, dtype=int, doc="Write 1 to start pulse sequence"
    )
    Pulse_Status = pvproperty(
        value=0,
        enum_strings=["idle", "running", "done"],
        record="mbbo",
        dtype=ChannelType.ENUM,
        read_only=True,
        doc="Pulse status",
    )

    async def _run_pulses(self, count, pulse_time):
        await self.Pulse_Status.write(1)  # running
        await asyncio.sleep(count * pulse_time)
        await self.Pulse_Status.write(2)  # done
        await asyncio.sleep(1)
        await self.Pulse_Status.write(0)  # idle

    @Pulse_Trigger.putter
    async def Pulse_Trigger(self, instance, value):
        """
        Start pulse sequence when set to 1.
        """
        if value == 1:
            count = self.Pulse_Count.value
            pulse_time = self.Pulse_Time.value
            self._pulse_task = asyncio.create_task(self._run_pulses(count, pulse_time))
        return 0


class FasstcatSimDevice(PVGroup):
    """
    Top-level simulated FASSTCAT device.

    Attributes
    ----------
    eurotherm : SubGroup
        Simulated Eurotherm temperature controller.
    flowsms : SubGroup
        Simulated FlowSMS gas flow controller.
    pulse : SubGroup
        Simulated pulse mode controller.
    """

    eurotherm = SubGroup(EurothermSim, prefix="eurotherm}")
    flowsms = SubGroup(FlowSMSSim, prefix="flowsms}")
    pulse = SubGroup(PulseSim, prefix="pulse}")


if __name__ == "__main__":
    ioc_options, run_options = ioc_arg_parser(
        default_prefix="",
        desc="FASSTCAT Simulated IOC",
    )
    ioc = FasstcatSimDevice(**ioc_options)
    run(ioc.pvdb, **run_options)

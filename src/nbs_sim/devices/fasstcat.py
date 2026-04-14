import asyncio
from pathlib import Path
from caproto.server import PVGroup, pvproperty, SubGroup, ioc_arg_parser, run
from caproto._data import ChannelType

try:
    import tomllib
except ImportError:
    import tomli as tomllib

# Parse new_gases.toml for FlowSMSSim
GASES_TOML_PATH = Path(__file__).parent.parent / "new_gases.toml"
with open(GASES_TOML_PATH, "rb") as f:
    gases_config = tomllib.load(f)


def parse_gas_config():
    """
    Parse new_gases.toml to extract gas information for each input.

    Returns
    -------
    dict
        Dictionary mapping input numbers to their gas configurations.
    """
    input_configs = {}

    # Parse inputs to get MFC configuration
    inputs = gases_config.get("inputs", {})
    for input_num_str, input_config in inputs.items():
        input_num = int(input_num_str)

        # Check if MFCs are configured for A and B lines
        mfc_a = input_config.get("mfc_a", "")
        mfc_b = input_config.get("mfc_b", "")

        input_configs[input_num] = {
            "mfc_a": mfc_a,
            "mfc_b": mfc_b,
            "a_enabled": bool(mfc_a and str(mfc_a).strip()),
            "b_enabled": bool(mfc_b and str(mfc_b).strip()),
        }

    # Parse gas assignments to get available gases for each input
    gas_assignments = gases_config.get("gas_assignments", {})

    for input_num_str, assignment in gas_assignments.items():
        input_num = int(input_num_str)
        available_gases = []

        # Extract gas names from the assignment
        if "valve_off" in assignment:
            available_gases.append(assignment["valve_off"])
        if "valve_on" in assignment:
            available_gases.append(assignment["valve_on"])
        if "valve_null" in assignment:
            available_gases.append(assignment["valve_null"])

        # Add gas information to existing config
        if input_num in input_configs:
            input_configs[input_num].update(
                {"available_gases": available_gases, "assignment": assignment}
            )
        else:
            input_configs[input_num] = {
                "available_gases": available_gases,
                "assignment": assignment,
                "mfc_a": "",
                "mfc_b": "",
                "a_enabled": False,
                "b_enabled": False,
            }

    # Add gas configuration details
    gas_config = gases_config.get("gas_config", {})
    for input_num, config in input_configs.items():
        gas_details = {}
        for gas_name in config.get("available_gases", []):
            if gas_name in gas_config:
                gas_details[gas_name] = gas_config[gas_name]
        config["gas_details"] = gas_details

    return input_configs


def create_input_line_class(input_num, config):
    """
    Create an InputLineSim class for a specific input with its gas configuration.

    Parameters
    ----------
    input_num : int
        Input number (1-7)
    config : dict
        Configuration for this input from parse_gas_config()

    Returns
    -------
    type
        InputLineSim subclass with appropriate gas options and limits.
    """
    available_gases = config.get("available_gases", [])
    gas_details = config.get("gas_details", {})
    a_enabled = config.get("a_enabled", False)
    b_enabled = config.get("b_enabled", False)

    # Determine flow limits based on available gases
    # Use the highest upper limit among available gases
    max_flow = 0.0
    for gas_name, details in gas_details.items():
        if isinstance(details, dict) and "flow_range" in details:
            max_flow = max(max_flow, details["flow_range"][1])
        elif isinstance(details, dict):
            # Handle nested gas configs (like CO.high, CO.low)
            for sub_gas, sub_details in details.items():
                if isinstance(sub_details, dict) and "flow_range" in sub_details:
                    max_flow = max(max_flow, sub_details["flow_range"][1])

    # Default to 60 sccm if no flow range found
    if max_flow == 0.0:
        max_flow = 60.0

    class_attrs = {
        "__doc__": f"""
        Simulated input line {input_num} with gas selection and gas flows.
        
        Available gases: {', '.join(available_gases)}
        A line enabled: {a_enabled}
        B line enabled: {b_enabled}
        """,
        # Gas selection (determines which gas is available)
        "Gas_Selection": pvproperty(
            value=0,
            enum_strings=available_gases,
            record="mbbo",
            dtype=ChannelType.ENUM,
            doc=f"Gas selection for Input {input_num}",
        ),
        # Gas name (reflects current selection)
        "Gas_Name": pvproperty(
            value=available_gases[0] if available_gases else "",
            dtype=str,
            max_length=20,
            read_only=True,
            doc="Current gas name based on selection",
        ),
        # Gas flow for line A (only if enabled)
        "A_SP": pvproperty(
            value=0.0,
            dtype=float,
            doc=f"Setpoint for Input {input_num}, A line (sccm)",
            units="sccm",
            lower_ctrl_limit=0.0,
            upper_ctrl_limit=max_flow,
        ),
        "A_RB": pvproperty(
            value=0.0,
            dtype=float,
            read_only=True,
            doc=f"Readback for Input {input_num}, A line (sccm)",
            units="sccm",
        ),
        "A_ENABLED": pvproperty(
            value=a_enabled,
            dtype=bool,
            read_only=True,
            doc=f"A line enabled for Input {input_num}",
        ),
        # Gas flow for line B (only if enabled)
        "B_SP": pvproperty(
            value=0.0,
            dtype=float,
            doc=f"Setpoint for Input {input_num}, B line (sccm)",
            units="sccm",
            lower_ctrl_limit=0.0,
            upper_ctrl_limit=max_flow,
        ),
        "B_RB": pvproperty(
            value=0.0,
            dtype=float,
            read_only=True,
            doc=f"Readback for Input {input_num}, B line (sccm)",
            units="sccm",
        ),
        "B_ENABLED": pvproperty(
            value=b_enabled,
            dtype=bool,
            read_only=True,
            doc=f"B line enabled for Input {input_num}",
        ),
    }

    # Create the class
    InputLineClass = type(f"Input{input_num}Sim", (PVGroup,), class_attrs)

    # Add the putter method for gas selection
    @InputLineClass.Gas_Selection.putter
    async def Gas_Selection(self, instance, value):
        # Accept int, string index, or string label
        if isinstance(value, str):
            if value.isdigit():
                value = int(value)
            elif value in available_gases:
                value = available_gases.index(value)
            else:
                raise ValueError(f"Invalid gas selection: {value}")
        elif isinstance(value, int):
            pass
        else:
            raise ValueError(f"Invalid type for gas selection: {type(value)}")
        if not (0 <= value < len(available_gases)):
            raise ValueError(f"Invalid gas selection index: {value}")
        gas_name = available_gases[value]
        await self.Gas_Name.write(gas_name)
        return value

    return InputLineClass


# Parse the gas configuration
INPUT_CONFIGS = parse_gas_config()
print(f"DEBUG: Parsed input configurations: {INPUT_CONFIGS}")


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
    Temp_Hold : pvproperty
        Write 1 to hold at current temperature and cancel any ongoing ramp.
        Auto-resets to 0.
    Status : pvproperty
        Status of the Eurotherm controller (0=idle, 1=running).
    """

    Temp_Setpoint = pvproperty(
        value=22.0, dtype=float, doc="Temperature setpoint (degC)"
    )
    Temp_Rate = pvproperty(value=1.0, dtype=float, doc="Ramp rate (degC/min)")
    Temp_Trigger = pvproperty(value=0, dtype=int, doc="Write 1 to start ramp")
    Temp_Readback = pvproperty(
        value=22.0, dtype=float, read_only=True, doc="Current temperature (degC)"
    )
    Temp_Hold = pvproperty(
        value=0,
        dtype=int,
        doc=(
            """
            Hold the current temperature and cancel any ongoing ramp.

            Write 1 to hold at the current temperature. The device will auto-reset 
            this PV to 0.
            """
        ),
    )
    Status = pvproperty(
        value="idle",
        enum_strings=["idle", "running"],
        record="mbbo",
        dtype=ChannelType.ENUM,
        doc="Status of the Eurotherm controller (0=idle, 1=running)",
        read_only=True,
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._ramp_task = None
        self._hold = False
        self._hold_task = None

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
        try:
            current = self.Temp_Readback.value
            step = rate / 60.0  # degC per second
            while abs(current - target) > 0.01:
                if self._hold:
                    break
                if current < target:
                    current = min(current + step, target)
                else:
                    current = max(current - step, target)
                await self.Temp_Readback.write(current)
                await asyncio.sleep(1)
            if not self._hold:
                await self.Temp_Readback.write(target)
        except asyncio.CancelledError:
            pass
        await self.Status.write("idle")  # idle

    async def _hold_timer(self, minutes):
        """
        Hold at current temperature for the specified number of minutes.

        Parameters
        ----------
        minutes : float
            Hold duration in minutes.
        """
        try:
            await self.Status.write(1)  # running
            await asyncio.sleep(minutes * 60)
        except asyncio.CancelledError:
            pass
        await self.Status.write("idle")  # idle
        await self.Temp_Hold.write(0)

    @Temp_Trigger.putter
    async def Temp_Trigger(self, instance, value):
        """
        Start a temperature ramp when set to 1. Cancels any running ramp and clears hold.
        """
        await instance.write(value, verify_value=False)
        if value == 1:
            # Cancel any running ramp
            if self._ramp_task is not None and not self._ramp_task.done():
                self._ramp_task.cancel()
                try:
                    await self._ramp_task
                except Exception:
                    pass
            self._hold = False
            target = self.Temp_Setpoint.value
            rate = self.Temp_Rate.value
            await self.Status.write("running")
            self._ramp_task = asyncio.create_task(self._ramp_temperature(target, rate))
        await asyncio.sleep(0.2)
        return 0

    @Temp_Hold.putter
    async def Temp_Hold(self, instance, value):
        """
        Hold the current temperature and cancel any ongoing ramp or hold timer.

        If value > 0, hold for that many minutes (status running, then idle).
        If value == 0, cancel any ramp/hold and set status to idle.
        """
        await instance.write(value, verify_value=False)
        # Cancel any running ramp
        if self._ramp_task is not None and not self._ramp_task.done():
            self._ramp_task.cancel()
            try:
                await self._ramp_task
            except Exception:
                pass
        # Cancel any running hold timer
        if self._hold_task is not None and not self._hold_task.done():
            self._hold_task.cancel()
            try:
                await self._hold_task
            except Exception:
                pass
        if value > 0:
            await self.Status.write("running")  # running
            self._hold_task = asyncio.create_task(self._hold_timer(value))
        else:
            await self.Status.write("idle")  # idle
            await asyncio.sleep(0.2)
            return 0
        await asyncio.sleep(0.2)
        return 0


def create_flowsms_class():
    """
    Dynamically create FlowSMSSim class with input line PVs.

    Returns
    -------
    type
        FlowSMSSim class with all input line PVs defined.
    """
    # Start with the base class attributes
    class_attrs = {
        "__doc__": """
        Simulated FlowSMS gas flow controller.

        PVs are organized by physical inputs with gas selection and flow controls.

        Attributes
        ----------
        Input_<N>_Gas_Selection : pvproperty
            Gas selection for input N (enum with available gases).
        Input_<N>_Gas_Name : pvproperty
            Gas name for input N (reflects current selection).
        Input_<N>_A_SP : pvproperty
            Setpoint for input N, line A (sccm).
        Input_<N>_A_RB : pvproperty
            Readback for input N, line A (sccm).
        Input_<N>_B_SP : pvproperty
            Setpoint for input N, line B (sccm).
        Input_<N>_B_RB : pvproperty
            Readback for input N, line B (sccm).
        Flow_Apply : pvproperty
            Write 1 to apply all setpoints to readbacks.
        """,
        "Flow_Apply": pvproperty(
            value=0, dtype=int, doc="Apply all setpoints to readbacks"
        ),
    }

    # Add input line subgroups using the factory
    for input_num in range(1, 8):
        input_name = f"Input_{input_num}"

        if input_num in INPUT_CONFIGS:
            # Create input line class using factory
            input_class = create_input_line_class(input_num, INPUT_CONFIGS[input_num])
            class_attrs[input_name] = SubGroup(
                input_class, prefix=f"Input_{input_num}_"
            )
        else:
            # Fallback for missing inputs
            print(f"Warning: No configuration found for input {input_num}")

    # Create the class
    FlowSMSSim = type("FlowSMSSim", (PVGroup,), class_attrs)

    # Add the putter method
    @FlowSMSSim.Flow_Apply.putter
    async def Flow_Apply(self, instance, value):
        """
        Apply all setpoints to readbacks when set to 1.
        """
        await instance.write(value, verify_value=False)
        if value == 1:
            # Apply all A and B line setpoints to readbacks
            for input_num in range(1, 8):
                input_line = getattr(self, f"Input_{input_num}")

                # Apply A line
                a_sp = input_line.A_SP.value
                await input_line.A_RB.write(a_sp)

                # Apply B line
                b_sp = input_line.B_SP.value
                await input_line.B_RB.write(b_sp)
        await asyncio.sleep(0.2)
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
        Enum: ["idle", "running"]
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
        value="idle",
        enum_strings=["idle", "running"],
        record="mbbo",
        dtype=ChannelType.ENUM,
        read_only=True,
        doc="Pulse status (0=idle, 1=running)",
    )

    async def _run_pulses(self, count, pulse_time):
        await asyncio.sleep(count * pulse_time)
        await self.Pulse_Status.write("idle")  # idle

    @Pulse_Trigger.putter
    async def Pulse_Trigger(self, instance, value):
        """
        Start pulse sequence when set to 1.
        """
        await instance.write(value, verify_value=False)
        if value == 1:
            count = self.Pulse_Count.value
            pulse_time = self.Pulse_Time.value
            await self.Pulse_Status.write("running")  # running
            self._pulse_task = asyncio.create_task(self._run_pulses(count, pulse_time))
        await asyncio.sleep(0.2)
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
    Segment_Status : pvproperty
        Overall segment status (0=idle, 1=running)
    """

    eurotherm = SubGroup(EurothermSim, prefix="eurotherm}")
    flowsms = SubGroup(FlowSMSSim, prefix="flowsms}")
    pulse = SubGroup(PulseSim, prefix="pulse}")
    Segment_Status = pvproperty(
        value="idle",
        name="}Segment_Status",
        enum_strings=["idle", "running"],
        record="mbbo",
        dtype=ChannelType.ENUM,
        doc="Overall segment status (0=idle, 1=running)",
        read_only=True,
    )

    @Segment_Status.scan(period=5)
    async def Segment_Status(self, instance, async_lib):
        """
        Periodically update Segment_Status based on child statuses.
        """
        eurotherm_status = self.eurotherm.Status.value
        pulse_status = self.pulse.Pulse_Status.value
        # print(
        #     f"DEBUG: Eurotherm status: {eurotherm_status}, Pulse status: {pulse_status}"
        # )
        if eurotherm_status == "running" or pulse_status == "running":
            # print("DEBUG: Segment status: running")
            await instance.write("running")
        else:
            # print("DEBUG: Segment status: idle")
            await instance.write("idle")


if __name__ == "__main__":
    ioc_options, run_options = ioc_arg_parser(
        default_prefix="",
        desc="FASSTCAT Simulated IOC",
    )
    ioc = FasstcatSimDevice(**ioc_options)
    run(ioc.pvdb, **run_options)

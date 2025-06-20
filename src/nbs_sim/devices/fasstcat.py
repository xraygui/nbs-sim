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

        input_configs[input_num] = {
            "available_gases": available_gases,
            "assignment": assignment,
        }

    # Add gas configuration details
    gas_config = gases_config.get("gas_config", {})
    for input_num, config in input_configs.items():
        gas_details = {}
        for gas_name in config["available_gases"]:
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
    available_gases = config["available_gases"]
    gas_details = config["gas_details"]

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
        # Gas flow for line A
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
        # Gas flow for line B
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
    }

    # Create the class
    InputLineClass = type(f"Input{input_num}Sim", (PVGroup,), class_attrs)

    # Add the putter method for gas selection
    @InputLineClass.Gas_Selection.putter
    async def Gas_Selection(self, instance, value):
        """Update gas name when gas selection changes."""
        if value < len(available_gases):
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
    Gas_Options : pvproperty
        Comma-separated string of available gas flow options.
    """

    eurotherm = SubGroup(EurothermSim, prefix="eurotherm}")
    flowsms = SubGroup(FlowSMSSim, prefix="flowsms}")
    pulse = SubGroup(PulseSim, prefix="pulse}")

    # Generate gas options from parsed configuration
    def _get_gas_options():
        """Get all available gas names from the configuration."""
        all_gases = set()
        for config in INPUT_CONFIGS.values():
            all_gases.update(config["available_gases"])
        return sorted(list(all_gases))

    Gas_Options = pvproperty(
        value=",".join(_get_gas_options()),
        dtype=str,
        max_length=1000,
        read_only=True,
        doc="Available gas flow options (comma-separated)",
    )


if __name__ == "__main__":
    ioc_options, run_options = ioc_arg_parser(
        default_prefix="",
        desc="FASSTCAT Simulated IOC",
    )
    ioc = FasstcatSimDevice(**ioc_options)
    run(ioc.pvdb, **run_options)

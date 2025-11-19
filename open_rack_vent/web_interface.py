"""
Uses fastAPI to create a web interface that can set the state of the fans and read data from the
sensors.
"""

import itertools
import statistics
from enum import Enum
from typing import Dict, List

import fastapi
import uvicorn

from open_rack_vent.host_hardware import OpenRackVentHardwareInterface


class RackLevel(str, Enum):
    """
    Vertical level of the rack.
    """

    lower_rack = "lower"
    upper_rack = "upper"


class RackSide(str, Enum):
    """
    Hot/Cold Side of the rack.
    """

    intake = "intake"
    exhaust = "exhaust"


def create_web_interface(hardware_interface: OpenRackVentHardwareInterface) -> None:
    """
    Main entry point for open_rack_vent
    :return: None
    """

    app = fastapi.FastAPI()

    @app.get("/")
    def read_root() -> Dict[str, str]:
        """
        Proves the server is working.
        :return: Response dict.
        """
        return {"Hello": "World"}

    @app.post("/fan/{level}/{side}/{power}", description="Sets the power of different fans.")
    def change_fan_power(
        level: RackLevel = fastapi.Path(description="The location in the rack to affect."),
        side: RackSide = fastapi.Path(description="The side of the rack to affect."),
        power: float = fastapi.Path(ge=0, le=1.0, description="Power level to set"),
    ) -> Dict[str, List[str]]:
        """
        Set the power of a given fan module based on rack level and side.
        :param level: See FastAPI docs.
        :param side: See FastAPI docs.
        :param power: See FastAPI docs.
        :return: The commands executed to set the fan state. This is debugging information and
        can be ignored.
        """

        if level == RackLevel.lower_rack:
            if side == RackSide.intake:
                controls = hardware_interface.lower_intake_fan_controls
            else:
                raise ValueError(f"Invalid rack side: {side}")
        elif level == RackLevel.upper_rack:
            if side == RackSide.intake:
                controls = hardware_interface.upper_intake_fan_controls
            elif side == RackSide.exhaust:
                controls = hardware_interface.upper_exhaust_fan_controls
            else:
                raise ValueError(f"Invalid rack side: {side}")
        else:
            raise ValueError(f"Invalid rack level: {level}")

        return {
            "commands": list(
                itertools.chain.from_iterable([fan_control(power) for fan_control in controls])
            )
        }

    @app.get(
        "/temperature/{side}",
        description="Get the average temperature of the thermistors on the specified rack side.",
    )
    def read_average_temperature(
        side: RackSide = fastapi.Path(
            description="The side of the rack to read the temperature from."
        ),
    ) -> Dict[str, float]:
        """
        Get the average temperature of all thermistors on a given rack side.

        :param side: Side of the rack to read temperatures from (intake or exhaust).
        :return: Dictionary with the average temperature, e.g. {"temperature": 32.5}.
        """
        if side == RackSide.intake:
            read_temperatures = hardware_interface.read_all_intake_temperatures
        elif side == RackSide.exhaust:
            read_temperatures = hardware_interface.read_all_exhaust_temperatures
        else:
            raise ValueError(f"Invalid rack side: {side}")

        return {"temperature": statistics.mean(read_temperatures())}

    uvicorn.run(app, host="0.0.0.0", port=8000)

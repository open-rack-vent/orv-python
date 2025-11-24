"""
Uses fastAPI to create a web interface that can set the state of the fans and read data from the
sensors.
"""

import itertools
import statistics
from typing import Dict, List

import fastapi
import uvicorn

from open_rack_vent.host_hardware import OnboardLED, OpenRackVentHardwareInterface
from open_rack_vent.host_hardware.board_interface_types import RackLocation


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

    @app.post("/fan/location/{power}", description="Sets the power of different fans.")
    def change_fan_power(
        location: RackLocation = fastapi.Path(description="The location in the rack to affect."),
        power: float = fastapi.Path(ge=0, le=1.0, description="Power level to set"),
    ) -> Dict[str, List[str]]:
        """
        Set the power of a given fan module based on rack level and side.
        :param location: See FastAPI docs.
        :param power: See FastAPI docs.
        :return: The commands executed to set the fan state. This is debugging information and
        can be ignored.
        """

        try:
            controls = hardware_interface.fan_controllers[location]
        except KeyError as key_error:
            raise ValueError(f"Invalid Rack Location: {location}") from key_error

        return {
            "commands": list(
                itertools.chain.from_iterable([fan_control(power) for fan_control in controls])
            )
        }

    @app.get(
        "/temperature/{location}",
        description="Get the average temperature of the thermistors near the specified location.",
    )
    def read_average_temperature(
        location: RackLocation = fastapi.Path(description="The location in the rack to read from"),
    ) -> Dict[str, float]:
        """
        Get the average temperature of all thermistors on a given rack side.

        :param side: Side of the rack to read temperatures from (intake or exhaust).
        :return: Dictionary with the average temperature, e.g. {"temperature": 32.5}.
        """
        try:
            read_temperatures = hardware_interface.temperature_readers[location]
        except KeyError as key_error:
            raise ValueError(f"Invalid Rack Location: {location}") from key_error

        return {
            "temperature": statistics.mean([read_function() for read_function in read_temperatures])
        }

    @app.get(
        "/setLED/{led}/{state}",
        description="Get the average temperature of the thermistors on the specified rack side.",
    )
    def set_led(
        led: OnboardLED = fastapi.Path(description="The LED to modify"),
        state: bool = fastapi.Path(description="The state to set the LED to."),
    ) -> Dict[str, List[str]]:
        """
        Override the LED state of the different status LEDs.

        :param led: The board marking of the LED to modify.
        :param state: The on/off state of the LED. True to turn it on... please...
        :return: A dict containing the commands executed to set the LED. For debugging.
        """

        return {"commands": hardware_interface.set_onboard_led(led, state)}

    uvicorn.run(app, host="0.0.0.0", port=8000)

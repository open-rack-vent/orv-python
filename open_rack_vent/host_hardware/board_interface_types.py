"""
Defines the BoardInterface, a collection of callables that facilitate "low level" interaction with
the hardware components on the PCB. This "BoardInterface" is the object that the different control
methods (the REST API, the MQTT interface with Home Assistant) interact with.
"""

from enum import Enum
from typing import Callable, Dict, List, NamedTuple, Protocol

from pydantic import BaseModel

from open_rack_vent.host_hardware import board_markings


class RackLocation(str, Enum):
    """
    Flat, Enum representation of each of the locations in the rack. Easy to input by user and
    easy to add more locations as the project grows at the cost of being a bit ham-fisted.

    Intake vs. Exhaust: Hot/Cold Side of the rack.
    Upper vs. Lower: Vertical position in the rack. Typically, heat rises in server racks, so the
    most temperature sensitive gear is placed lower.

    """

    intake_lower = "intake_lower"
    intake_upper = "intake_upper"
    exhaust_lower = "exhaust_lower"
    exhaust_upper = "exhaust_upper"


class HardwarePlatform(str, Enum):
    """
    Different supported hardware backends that can drive the Open Rack Vent PCBs.
    This is mostly future-proofing `create_hardware_interface`, there is no intent to support
    other hardware platforms at the time of writing.
    """

    beaglebone_black = "BeagleBoneBlack"


class PCBRevision(str, Enum):
    """
    Different hardware revisions of the Open Rack Vent PCB.
    """

    v100 = "v1.0.0"


class WireMappingVersion(str, Enum):
    """
    Because the associated `WireMapping` is coming from an environment variable (or config file)
    this data exists outside the code and therefor needs a version to maintain compatibility with
    the code.
    """

    version_1 = "1"


class WireMapping(BaseModel):
    """
    Defines the user configurable data structure that describes how the connections are made to the
    ORV pcb.
    """

    version: WireMappingVersion

    fans: Dict[RackLocation, List[board_markings.BoardMarkingActiveLowPWM]]
    thermistors: Dict[RackLocation, List[board_markings.BoardMarkingThermistorPin]]


class FanController(Protocol):
    """
    Defines the API for setting fan power.
    """

    def __call__(self, drive_power: float) -> List[str]:
        """
        :param drive_power: Float from 0-1 where 0 is the fan is off and 1 is fan is full blast.
        :return: List of commands sent to the fans.
        """


class TemperatureReader(Protocol):
    """
    Defines the API for reading from a temperature sensor.
    """

    def __call__(self) -> float:
        """
        :return: Current temperature in celsius.
        """


class OpenRackVentHardwareInterface(NamedTuple):
    """
    Provides a unified interface for interacting with the Open Rack Vent hardware. This interface
    could be ported to other hardware backends, like the Raspberry Pi and the rest of the
    application would function the same.
    """

    set_onboard_led: Callable[[board_markings.OnboardLED, bool], List[str]]

    fan_controllers: Dict[RackLocation, List[FanController]]
    temperature_readers: Dict[RackLocation, List[TemperatureReader]]


if __name__ == "__main__":

    # This is a simple WireMapping

    builtin_mapping = WireMapping(
        version=WireMappingVersion.version_1,
        fans={
            RackLocation.intake_lower: [
                board_markings.BoardMarkingActiveLowPWM.pn2,  # Bottom Right Fan
                board_markings.BoardMarkingActiveLowPWM.pn5,  # Bottom left Fan
            ],
            RackLocation.intake_upper: [
                board_markings.BoardMarkingActiveLowPWM.onboard,  # Top Right Fan
                board_markings.BoardMarkingActiveLowPWM.pn3,  # Top Left Fan
            ],
        },
        thermistors={
            RackLocation.intake_lower: [
                board_markings.BoardMarkingThermistorPin.tmp0,
                board_markings.BoardMarkingThermistorPin.tmp1,
            ],
            RackLocation.intake_upper: [
                board_markings.BoardMarkingThermistorPin.tmp4,
                board_markings.BoardMarkingThermistorPin.tmp5,
            ],
        },
    )

    print(builtin_mapping.model_dump_json())

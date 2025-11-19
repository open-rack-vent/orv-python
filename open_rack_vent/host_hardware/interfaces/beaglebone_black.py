"""
Implements the `OpenRackVentHardwareInterface` for a BeagleBone Black driving an Open Rack Vent PCB
version v1.0.0. This is a bit gritty, it's nice to be able to keep the definition modules cleaner.
"""

import subprocess
from enum import Enum
from functools import partial
from pathlib import Path
from typing import Callable, Dict, List, NamedTuple

from open_rack_vent import thermistor
from open_rack_vent.host_hardware import board_markings
from open_rack_vent.host_hardware.board_interface_types import (
    OpenRackVentHardwareInterface,
    WireMapping,
)


def echo_value(path: Path, value: str) -> str:
    """
    Open the path and write the value to it. Return a summary of what happened as a string
    :param path: Path to write to.
    :param value: String to write.
    :return: Summary of what happened as a string, for printing etc.
    """

    with open(str(path.resolve()), "w", encoding="utf-8") as file:
        file.write(value)

    return f"echo {path} > {value}"


def cat_value(path: Path) -> str:
    """
    Read the contents of a file, like the `cat` command.
    :param path: Path to read.
    :return: The contents of the file as a string.
    """

    with open(str(path.resolve()), "r", encoding="utf-8") as file:
        return file.read()


class PWMPin(str, Enum):
    """
    The different port/pin combos that can be attached to PWM signals.
    """

    P9_31 = "P9_31"
    P9_29 = "P9_29"
    P9_22 = "P9_22"
    P9_14 = "P9_14"
    P9_16 = "P9_16"
    P8_19 = "P8_19"
    P8_13 = "P8_13"


class PWMChannel(NamedTuple):
    """
    Combinations of the PWM id and channel. This will be written to the device tree as:

    /dev/bone/pwm/{pwm_id}/{channel}
    """

    pwm_id: int
    channel: str


_PWM_CHANNEL_LOOKUP: Dict[PWMPin, PWMChannel] = {
    PWMPin.P9_31: PWMChannel(pwm_id=0, channel="a"),
    PWMPin.P9_29: PWMChannel(pwm_id=0, channel="b"),
    PWMPin.P9_22: PWMChannel(pwm_id=0, channel="a"),
    PWMPin.P9_14: PWMChannel(pwm_id=1, channel="a"),  # Mux 1 ?
    PWMPin.P9_16: PWMChannel(pwm_id=1, channel="b"),  # Mux 1 ?
    PWMPin.P8_19: PWMChannel(pwm_id=2, channel="a"),
    PWMPin.P8_13: PWMChannel(pwm_id=2, channel="b"),
}
"""
Taken from beagleboard docs:
https://docs.beagleboard.org/books/beaglebone-cookbook/04motors/motors.html#py-servomotor-code
Wish I had a better source for this table than this blog post...
"""


def configure_pwm_pin(pwm_pin: PWMPin, period_ns: int, duty_pct: float) -> List[str]:
    """
    Set the period (...frequency) of a pwm output channel.

    In order...

        * The `config-pin` utility is used to make sure the pin is set to PWM mode.
        * period is set.
        * duty cycle is set.
        * pwm is enabled.

    :param pwm_pin: To modify.
    :param period_ns: Period of the pwm square wave in nanoseconds.
    :param duty_pct: Duty cycle of the PWM signal as a float from 0 to 1.
    :return: The echo write strings for printing/logging etc.
    """

    pwm_channel = _PWM_CHANNEL_LOOKUP[pwm_pin]

    _ = subprocess.run(
        f"config-pin {pwm_pin.value} pwm", shell=True, check=True, capture_output=True
    )

    device_tree_base_path = Path(f"/dev/bone/pwm/{pwm_channel.pwm_id}/{pwm_channel.channel}")

    return [
        echo_value(
            path=device_tree_base_path.joinpath("period"),
            value=str(period_ns),
        ),
        echo_value(
            path=device_tree_base_path.joinpath("duty_cycle"),
            value=str(int(period_ns * duty_pct)),
        ),
        echo_value(
            path=device_tree_base_path.joinpath("enable"),
            value=str(1),
        ),
    ]


class ADCPin(str, Enum):
    """
    Different pins that can be used to read in ADC values.
    """

    P9_33 = "P9_33"
    P9_35 = "P9_35"
    P9_36 = "P9_36"
    P9_37 = "P9_37"
    P9_38 = "P9_38"
    P9_39 = "P9_39"
    P9_40 = "P9_40"


_ANALOG_IN_LOOKUP: Dict[ADCPin, int] = {
    ADCPin.P9_39: 0,
    ADCPin.P9_40: 1,
    ADCPin.P9_37: 2,
    ADCPin.P9_38: 3,
    ADCPin.P9_33: 4,
    ADCPin.P9_36: 5,
    ADCPin.P9_35: 6,
}


def read_adc_counts(adc_pin: ADCPin) -> int:  # pylint: disable=unused-argument
    """
    Read the ADC counts of a given analog input.
    :param adc_pin: The name of the ADC pin to read.
    :return: ADC counts as an int.
    """

    return int(
        cat_value(
            Path(f"/sys/bus/iio/devices/iio:device0/in_voltage{_ANALOG_IN_LOOKUP[adc_pin]}_raw")
        )
    )


class GPIOPin(str, Enum):
    """
    Pins used for general IO.
    """

    P8_17 = "P8_17"  # NMOS2
    P8_28 = "P8_28"  # GPIO0
    P8_18 = "P8_18"  # NMOS3
    P8_16 = "P8_16"  # SW0
    P9_41 = "P9_41"  # NMOS0
    P9_13 = "P9_13"  # LED2
    P9_11 = "P9_11"  # LED0
    P9_42 = "P9_42"  # NMOS1
    P9_12 = "P9_12"  # LED1


class GPIOBankIndex(NamedTuple):
    """
    Describes a GPIO pin by its controller bank and the index within that bank.
    """

    gpio_bank: int
    gpio_index: int


_GPIO_LOOKUP: Dict[GPIOPin, GPIOBankIndex] = {
    GPIOPin.P8_16: GPIOBankIndex(gpio_bank=1, gpio_index=14),
    GPIOPin.P8_17: GPIOBankIndex(gpio_bank=0, gpio_index=27),
    GPIOPin.P8_18: GPIOBankIndex(gpio_bank=2, gpio_index=1),
    GPIOPin.P8_28: GPIOBankIndex(gpio_bank=2, gpio_index=24),
    GPIOPin.P9_11: GPIOBankIndex(gpio_bank=0, gpio_index=30),
    GPIOPin.P9_12: GPIOBankIndex(gpio_bank=1, gpio_index=28),
    GPIOPin.P9_13: GPIOBankIndex(gpio_bank=0, gpio_index=31),
    GPIOPin.P9_41: GPIOBankIndex(gpio_bank=0, gpio_index=20),
    GPIOPin.P9_42: GPIOBankIndex(gpio_bank=0, gpio_index=7),
}
"""
Taken from the beaglebone docs...
https://docs.beagleboard.org/boards/beaglebone/black/ch07.html
"""


def configure_gpio_pin(gpio_pin: GPIOPin, value: bool) -> List[str]:
    """
    Configure a GPIO pin as output and set its logical value.

    Steps:
        * use config-pin to switch the pin to gpio mode
        * export the GPIO number if needed
        * set the pin direction to 'out'
        * write the logical value

    :param gpio_pin: GPIOPin to configure.
    :param value: True = drive high, False = drive low.
    :return: list of echo command strings executed (for logging)
    """

    bank_index = _GPIO_LOOKUP[gpio_pin]

    gpio_num = (bank_index.gpio_bank * 32) + bank_index.gpio_index

    # Put pin into mode "gpio"
    _ = subprocess.run(
        f"config-pin {gpio_pin.value} gpio",
        shell=True,
        check=True,
        capture_output=True,
    )

    cmds = []

    # Export (may already exist)
    gpio_path = Path(f"/sys/class/gpio/gpio{gpio_num}")

    if not gpio_path.exists():
        cmds.append(
            echo_value(
                path=Path("/sys/class/gpio/export"),
                value=str(gpio_num),
            )
        )

    # Set direction
    cmds.append(
        echo_value(
            path=gpio_path.joinpath("direction"),
            value="out",
        )
    )

    # Set value
    cmds.append(
        echo_value(
            path=gpio_path.joinpath("value"),
            value="1" if value else "0",
        )
    )

    return cmds


class BoardMarkingLookups(NamedTuple):
    """
    Describes the connections internal to an Open Rack Vent PCB. This maps how the pins described
    by the board markings (screw terminal labels etc.) are connected to corresponding output devices
    on the beaglebone black.
    """

    pwm: Dict[board_markings.BoardMarkingActiveLowPWM, PWMPin]
    thermistor: Dict[board_markings.BoardMarkingTempPin, ADCPin]
    led: Dict[board_markings.OnboardLED, GPIOPin]


BBB_V100_BOARD_MARKINGS_TO_PINS = BoardMarkingLookups(
    pwm={
        board_markings.BoardMarkingActiveLowPWM.onboard: PWMPin.P8_13,  # Top Right
        board_markings.BoardMarkingActiveLowPWM.pn1: PWMPin.P9_14,
        board_markings.BoardMarkingActiveLowPWM.pn2: PWMPin.P9_16,  # Bottom Right
        board_markings.BoardMarkingActiveLowPWM.pn3: PWMPin.P9_22,  # Top Left
        board_markings.BoardMarkingActiveLowPWM.pn4: PWMPin.P9_29,
        board_markings.BoardMarkingActiveLowPWM.pn5: PWMPin.P8_19,  # Bottom left
    },
    thermistor={
        board_markings.BoardMarkingTempPin.tmp0: ADCPin.P9_35,
        board_markings.BoardMarkingTempPin.tmp1: ADCPin.P9_36,
        board_markings.BoardMarkingTempPin.tmp2: ADCPin.P9_33,
        board_markings.BoardMarkingTempPin.tmp3: ADCPin.P9_37,
        board_markings.BoardMarkingTempPin.tmp4: ADCPin.P9_39,
        board_markings.BoardMarkingTempPin.tmp5: ADCPin.P9_38,
        board_markings.BoardMarkingTempPin.tmp6: ADCPin.P9_40,
    },
    led={
        board_markings.OnboardLED.run: GPIOPin.P9_13,
        board_markings.OnboardLED.web: GPIOPin.P9_12,
        board_markings.OnboardLED.fault: GPIOPin.P9_11,
    },
)
"""
Hardware mapping for the v1.0.0 PCB. There is a bunch of functionality that exists on the PCB that
isn't being used at this time. The NMOS GPIO outputs, the bare GPIO output, the switch input etc.
Those will be invoked in future versions. 
"""


def create_interface(
    board_marking_lookup: BoardMarkingLookups, wire_mapping: WireMapping
) -> OpenRackVentHardwareInterface:
    """
    Given the mapping from the drivers to the GPIO pins, and a description of how the overall
    system is wired together inside the rack, produces a controller that can drive the fans and
    read from the temperature sensors in the rack.
    :param board_marking_lookup: How the PCB is assembled.
    :param wire_mapping: How the fans are connected to the PCB.
    :return: Collection of callables consumed by the rest of the application.
    """

    temperature_converter = thermistor.create_adc_counts_to_temperature_converter()

    def create_read_all_temperatures(
        input_board_markings: List[board_markings.BoardMarkingTempPin],
    ) -> List[float]:
        """
        Read the temperatures for the thermistor pins.
        :param input_board_markings: To read.
        :return: List of resulting temperatures in Celsius.
        """

        return [
            temperature_converter(
                read_adc_counts(adc_pin=board_marking_lookup.thermistor[board_marking])
            )
            for board_marking in input_board_markings
        ]

    def create_fan_controls(
        input_board_markings: List[board_markings.BoardMarkingActiveLowPWM],
    ) -> List[Callable[[float], List[str]]]:
        """
        Returns a list of functions that have the pre-populated driver function as the callable.
        :param input_board_markings: One output function per this input.
        :return: List of callables for the API.
        """

        return [
            partial(configure_pwm_pin, board_marking_lookup.pwm[board_marking], 1_000)
            for board_marking in input_board_markings
        ]

    return OpenRackVentHardwareInterface(
        set_onboard_led=lambda onboard_led, value: configure_gpio_pin(
            gpio_pin=board_marking_lookup.led[onboard_led], value=value
        ),
        read_all_intake_temperatures=lambda: create_read_all_temperatures(
            wire_mapping.intake_temperature_pins
        ),
        read_all_exhaust_temperatures=lambda: create_read_all_temperatures(
            wire_mapping.exhaust_temperature_pins
        ),
        lower_intake_fan_controls=create_fan_controls(
            input_board_markings=wire_mapping.lower_intake_fans
        ),
        upper_intake_fan_controls=create_fan_controls(
            input_board_markings=wire_mapping.upper_intake_fans
        ),
        upper_exhaust_fan_controls=create_fan_controls(
            input_board_markings=wire_mapping.upper_exhaust_fans
        ),
    )

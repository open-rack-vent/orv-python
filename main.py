"""Main module."""

import subprocess
from enum import Enum
from pathlib import Path
from typing import Annotated, Dict, List, NamedTuple

import fastapi
import uvicorn

from open_rack_vent import thermistor


class PWMPin(str, Enum):
    """
    The different port/pin combos that can be attached to PWM signals.
    """

    P9_31 = "P9_31"
    P9_29 = "P9_29"
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
    PWMPin.P9_14: PWMChannel(pwm_id=1, channel="a"),
    PWMPin.P9_16: PWMChannel(pwm_id=1, channel="b"),
    PWMPin.P8_19: PWMChannel(pwm_id=2, channel="a"),
    PWMPin.P8_13: PWMChannel(pwm_id=2, channel="b"),
}
"""
Taken from beagleboard docs:
https://docs.beagleboard.org/books/beaglebone-cookbook/04motors/motors.html#py-servomotor-code
Wish I had a better source for this table than this blog post...
"""


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


_ADC_PORT_LOOKUP: Dict[ADCPin, int] = {
    ADCPin.P9_39: 0,
    ADCPin.P9_40: 1,
    ADCPin.P9_37: 2,
    ADCPin.P9_38: 3,
    ADCPin.P9_33: 4,
    ADCPin.P9_36: 5,
    ADCPin.P9_35: 6,
}


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


def read_adc_counts(adc_port: int) -> int:  # pylint: disable=unused-argument
    """

    :param adc_pin:
    :return:
    """

    return 4096 // 2


def main() -> None:
    """
    Main entry point for open_rack_vent
    :return: None
    """

    app = fastapi.FastAPI()

    # Somehow, this mapping will be passed in from the user.
    module_to_pin: Dict[int, PWMPin] = {
        0: PWMPin.P9_14,
    }

    temperature_converter = thermistor.create_adc_counts_to_temperature_converter()

    @app.get("/")
    def read_root() -> Dict[str, str]:
        return {"Hello": "World"}

    @app.post("/fan/{module_number}/{power}")
    def change_module_power(
        module_number: int,
        power: Annotated[float, fastapi.Path(ge=0, le=1.0)],
    ) -> Dict[str, str | List[str]]:

        pwm_pin = module_to_pin[module_number]
        pwm_channel = _PWM_CHANNEL_LOOKUP[pwm_pin]

        return {
            "pwm_channel": str(pwm_channel),
            "commands": configure_pwm_pin(pwm_pin=pwm_pin, period_ns=40_000, duty_pct=power),
        }

    @app.get("/temperature/{adc_port}")
    def read_temperature(
        adc_port: Annotated[
            int,
            fastapi.Path(ge=min(_ADC_PORT_LOOKUP.values()), le=max(_ADC_PORT_LOOKUP.values())),
        ]
    ) -> Dict[str, str]:
        """

        :param adc_port:
        :return:
        """

        return {str(adc_port): str(temperature_converter(read_adc_counts(adc_port=adc_port)))}

    uvicorn.run(app, host="0.0.0.0", port=8000)


if __name__ == "__main__":
    main()

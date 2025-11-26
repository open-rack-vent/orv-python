"""Main module."""

import json
import logging
from enum import Enum
from functools import partial
from itertools import count
from typing import Any, Callable, List, Optional, Type, get_args, get_origin

import click
from apscheduler.schedulers.background import BackgroundScheduler
from bonus_click import options
from pydantic import BaseModel, ValidationError

from open_rack_vent import canonical_stop_event
from open_rack_vent.canonical_stop_event import SignalEvent
from open_rack_vent.control_api import mqtt_api, web_api
from open_rack_vent.control_api.control_api_common import APIController
from open_rack_vent.host_hardware import (
    HardwarePlatform,
    OnboardLED,
    PCBRevision,
    WireMapping,
    create_hardware_interface,
)
from open_rack_vent.host_hardware.board_interface_types import OpenRackVentHardwareInterface

LOGGER_FORMAT = "[%(asctime)s - %(process)s - %(name)20s - %(levelname)s] %(message)s"
LOGGER_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

logging.basicConfig(
    level=logging.INFO,
    format=LOGGER_FORMAT,
    datefmt=LOGGER_DATE_FORMAT,
)

LOGGER = logging.getLogger(__name__)


logging.getLogger("apscheduler").setLevel(logging.ERROR)


def type_to_str(annotation: type) -> str:
    """
    Convert a type annotation into a readable representation for help text.

    Supports:
    - Enums -> "Enum[A, B, C]"
    - NamedTuple -> "Racklocation(vertical: Racklevel, side: Rackside)"
    - Generics like List[int], Dict[str, Enum], etc.
    - Capitalizes outer container types (List, Dict, Set...).

    :param annotation: The type annotation to convert.
    :return: Readable type string.
    """
    origin = get_origin(annotation)

    # Handle NamedTuple types
    if (
        isinstance(annotation, type)
        and issubclass(annotation, tuple)
        and hasattr(annotation, "_fields")
    ):
        field_parts = []
        for field_name, field_type in annotation.__annotations__.items():
            field_parts.append(f"{field_name}: {type_to_str(field_type)}")
        field_str = ", ".join(field_parts)
        return f"{annotation.__name__.title()}({field_str})"

    # Handle Enums
    if isinstance(annotation, type) and issubclass(annotation, Enum):
        # Use enum *values* rather than names, uppercased
        return f"Enum[{', '.join(e.value.upper() for e in annotation)}]"

    # Handle non-generic simple types
    if origin is None:
        return annotation.__name__.title()

    # Handle generic types (List, Dict, etc.)
    args = get_args(annotation)
    origin_name = getattr(origin, "__name__", str(origin)).title()

    if args:
        inner = ", ".join(type_to_str(a) for a in args)
        return f"{origin_name}[{inner}]"

    return origin_name


def click_help_for_pydantic_model(help_prefix: str, model: Type[BaseModel]) -> str:
    """
    Generate a help string for a Pydantic v2 model, one key per line.
    :param help_prefix: Prepended to the help content about the keys.
    :param model: The Pydantic model to generate help for.
    :return: Help text, pre-escaped with \b's for click.
    """
    lines = [
        f"{name}: {type_to_str(field.annotation)}" for name, field in model.model_fields.items()
    ]
    return "".join(["\b\n", help_prefix, "".join(["\b\n   • " + line for line in lines])])


def validate_pydantic_json(
    model: Type[BaseModel], _ctx: click.Context, _param: click.Parameter, value: str
) -> BaseModel:
    """
    Click callback to validate a JSON string against a Pydantic model.

    :param model: The Pydantic model to validate against.
    :param _ctx: Click context (provided automatically by Click).
    :param _param: Click parameter object (provided automatically by Click).
    :param value: The raw JSON string to validate.
    :return: An instance of the validated Pydantic model.
    :raises click.BadParameter: If JSON parsing or Pydantic validation fails.
    """
    try:
        data: dict[str, Any] = json.loads(value)  # type: ignore[misc]
        return model(**data)
    except json.JSONDecodeError as e:
        raise click.BadParameter(f"Invalid JSON: {e.msg}")
    except ValidationError as e:
        raise click.BadParameter(f"Pydantic validation failed: {e}")


def toggling_job(bool_callable: Callable[[bool], None], state_count: "count[int]") -> None:
    """
    Apscheduler job function that takes a bool callable and a thread safe counter and repeatedly
    calls `bool_callable` with true/false (using the state_count).
    :param bool_callable: To call
    :param state_count: Used to get the toggling behavior.
    :return: None
    """

    bool_callable(bool(next(state_count) % 2 == 0))


@click.group()
def cli() -> None:
    """
    Programs to manage the airflow inside a server rack.

    \f

    :return: None
    """


@cli.command(short_help="Main program to actually drive the fans")
@options.create_enum_option(
    arg_flag="--platform",
    help_message="The type of hardware running this application.",
    default=HardwarePlatform.beaglebone_black,
    input_enum=HardwarePlatform,
    envvar="ORV_PLATFORM",
)
@options.create_enum_option(
    arg_flag="--pcb-revision",
    help_message="The revision of the board driving the fans etc.",
    default=PCBRevision.v100,
    input_enum=PCBRevision,
    envvar="ORV_PCB_REVISION",
)
@click.option(
    "--wire-mapping-json",
    "wire_mapping",
    required=True,
    callback=partial(validate_pydantic_json, WireMapping),
    help=click_help_for_pydantic_model(
        help_prefix="JSON payload string with keys:", model=WireMapping
    ),
    default=(
        '{"version":"1","fans":{"intake_lower":["PN2","PN5"],"intake_upper":["ONBOARD","PN3"]},'
        '"thermistors":{"intake_lower":["TMP0","TMP1"],"intake_upper":["TMP4","TMP5"]}}'
    ),
    envvar="ORV_WIRE_MAPPING_JSON",
    show_envvar=True,
)
@click.option(
    "--web-api",
    "enable_web_api",
    required=True,
    help="Providing this enables the web control api.",
    is_flag=True,
    default=True,
    show_default=True,
    envvar="ORV_WEB_API_ENABLED",
    show_envvar=True,
)
@click.option(
    "--mqtt-api",
    "enable_mqtt_api",
    required=True,
    help="Providing this enables the MQTT api.",
    is_flag=True,
    default=True,
    show_default=True,
    envvar="ORV_MQTT_API_ENABLED",
    show_envvar=True,
)
@click.option(
    "--web-api-host",
    default="0.0.0.0",
    show_default=True,
    help="Host address the web API binds to.",
    envvar="ORV_WEB_API_HOST",
    show_envvar=True,
    type=click.STRING,
)
@click.option(
    "--web-api-port",
    default=8000,
    show_default=True,
    help="Port the web API listens on.",
    envvar="ORV_WEB_API_PORT",
    show_envvar=True,
    type=click.INT,
)
@click.option(
    "--mqtt-broker-host",
    default="homeassistant",
    show_default=True,
    help="Hostname or IP of the MQTT broker.",
    envvar="ORV_MQTT_BROKER_HOST",
    show_envvar=True,
    type=click.STRING,
)
@click.option(
    "--mqtt-broker-port",
    default=1883,
    show_default=True,
    help="Port of the MQTT broker.",
    envvar="ORV_MQTT_BROKER_PORT",
    show_envvar=True,
    type=click.INT,
)
@click.option(
    "--mqtt-device-id",
    default="orv-1",
    show_default=True,
    help="Device ID used for MQTT discovery/state topics.",
    envvar="ORV_MQTT_DEVICE_ID",
    show_envvar=True,
    type=click.STRING,
)
@click.option(
    "--mqtt-username",
    default="orv_user",
    show_default=True,
    help="MQTT Broker username.",
    envvar="ORV_MQTT_USERNAME",
    show_envvar=True,
    type=click.STRING,
)
@click.option(
    "--mqtt-password",
    default="password",
    show_default=True,
    help="MQTT Broker password.",
    envvar="ORV_MQTT_PASSWORD",
    show_envvar=True,
    type=click.STRING,
)
def run(  # pylint: disable=too-many-arguments, too-many-positional-arguments, too-many-locals
    platform: HardwarePlatform,
    pcb_revision: PCBRevision,
    wire_mapping: WireMapping,
    enable_web_api: bool,
    enable_mqtt_api: bool,
    web_api_host: str,
    web_api_port: int,
    mqtt_broker_host: str,
    mqtt_broker_port: int,
    mqtt_device_id: str,
    mqtt_username: str,
    mqtt_password: str,
) -> None:
    """
    Main air management program. Controls fans, reads sensors.

    \f

    :param platform: See click docs!
    :param pcb_revision: See click docs!
    :param wire_mapping: See click docs!
    :param enable_web_api: See click docs!
    :param enable_mqtt_api: See click docs!
    :param web_api_host: See click docs!
    :param web_api_port: See click docs!
    :param mqtt_broker_host: See click docs!
    :param mqtt_broker_port: See click docs!
    :param mqtt_device_id: See click docs!
    :param mqtt_username: See click docs!
    :param mqtt_password: See click docs!
    :return: None
    """

    stop_event: SignalEvent = canonical_stop_event.create_signal_event()
    canonical_stop_event.entry_point_exit_condition(signal_event=stop_event)

    controller_apis: List[APIController] = []

    hardware_interface: Optional[OpenRackVentHardwareInterface] = None

    try:

        hardware_interface = create_hardware_interface(
            pcb_revision=pcb_revision,
            platform=platform,
            wire_mapping=wire_mapping,
        )

        hardware_interface.set_onboard_led(OnboardLED.fault, False)

        scheduler = BackgroundScheduler()

        scheduler.add_job(
            toggling_job,
            "interval",
            seconds=0.5,
            args=(lambda v: hardware_interface.set_onboard_led(OnboardLED.run, v), count(0)),
        )

        if any([web_api, mqtt_api]):
            scheduler.add_job(
                toggling_job,
                "interval",
                seconds=0.5,
                args=(lambda v: hardware_interface.set_onboard_led(OnboardLED.web, v), count(0)),
            )

        if enable_web_api:
            controller_apis.append(
                web_api.create_web_api(
                    orv_hardware_interface=hardware_interface,
                    host=web_api_host,
                    port=web_api_port,
                )
            )

        if enable_mqtt_api:
            controller_apis.append(
                mqtt_api.run_open_rack_vent_mqtt(
                    orv_hardware_interface=hardware_interface,
                    broker_host=mqtt_broker_host,
                    broker_port=mqtt_broker_port,
                    device_id=mqtt_device_id,
                    pcb_revision=pcb_revision,
                    publish_interval=1,
                    mqtt_username=mqtt_username,
                    mqtt_password=mqtt_password,
                )
            )

        scheduler.start()

        for controller_api in controller_apis:
            controller_api.non_blocking_run()

        LOGGER.info("All APIs up.")

        # Frees the CPU
        stop_event.wait()

    except Exception:  # pylint: disable=broad-except
        if hardware_interface is not None:
            hardware_interface.set_onboard_led(OnboardLED.fault, True)
        LOGGER.exception("Uncaught Runtime Error")
    finally:
        for controller_api in controller_apis:
            controller_api.stop()

        # Don't need to now but could add hardware cleanup here.

        LOGGER.info("Stopping ORV. Bye!")


if __name__ == "__main__":

    # TODO -- want an entrypoint to install a systemd unit

    cli()

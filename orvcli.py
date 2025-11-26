"""Main module."""

import json
import logging
import os
import sys
from enum import Enum
from functools import partial
from itertools import count
from pathlib import Path
from typing import Any, Callable, List, Optional, Type, get_args, get_origin

import click
from apscheduler.schedulers.background import BackgroundScheduler
from bonus_click import options
from click.decorators import FC
from jinja2 import Template
from pydantic import BaseModel, ValidationError

from open_rack_vent import assets, canonical_stop_event
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


_ENV_VAR_MAPPING = {
    "platform": "ORV_PLATFORM",
    "pcb_revision": "ORV_PCB_REVISION",
    "wire_mapping_json": "ORV_WIRE_MAPPING_JSON",
    "web_api": "ORV_WEB_API_ENABLED",
    "mqtt_api": "ORV_MQTT_API_ENABLED",
    "web_api_host": "ORV_WEB_API_HOST",
    "web_api_port": "ORV_WEB_API_PORT",
    "mqtt_broker_host": "ORV_MQTT_BROKER_HOST",
    "mqtt_broker_port": "ORV_MQTT_BROKER_PORT",
    "mqtt_device_id": "ORV_MQTT_DEVICE_ID",
    "mqtt_username": "ORV_MQTT_USERNAME",
    "mqtt_password": "ORV_MQTT_PASSWORD",
}
"""
Used to make sure the environment variables match in the systemd unit and CLI arguments.
"""


def run_options() -> Callable[[FC], FC]:
    """
    Creates the group of click options that define a run.
    :return: Wrapped command.
    """

    def output(command: FC) -> FC:
        """
        Wrap the input command.
        :param command: To wrap.
        :return: Wrapped input.
        """

        decorators = [
            options.create_enum_option(
                arg_flag="--platform",
                help_message="The type of hardware running this application.",
                default=HardwarePlatform.beaglebone_black,
                input_enum=HardwarePlatform,
                envvar=_ENV_VAR_MAPPING["platform"],
            ),
            options.create_enum_option(
                arg_flag="--pcb-revision",
                help_message="The revision of the board driving the fans etc.",
                default=PCBRevision.v100,
                input_enum=PCBRevision,
                envvar=_ENV_VAR_MAPPING["pcb_revision"],
            ),
            click.option(
                "--wire-mapping-json",
                "wire_mapping",
                required=True,
                callback=partial(validate_pydantic_json, WireMapping),
                help=click_help_for_pydantic_model(
                    help_prefix="JSON payload string with keys:", model=WireMapping
                ),
                default=(
                    '{"version":"1","fans":{"intake_lower":["PN2","PN5"],'
                    '"intake_upper":["ONBOARD","PN3"]},'
                    '"thermistors":{"intake_lower":["TMP0","TMP1"],"intake_upper":["TMP4","TMP5"]}}'
                ),
                envvar=_ENV_VAR_MAPPING["wire_mapping_json"],
                show_envvar=True,
            ),
            click.option(
                "--web-api",
                "enable_web_api",
                required=True,
                help="Providing this enables the web control api.",
                is_flag=True,
                default=True,
                show_default=True,
                envvar=_ENV_VAR_MAPPING["web_api"],
                show_envvar=True,
            ),
            click.option(
                "--mqtt-api",
                "enable_mqtt_api",
                required=True,
                help="Providing this enables the MQTT api.",
                is_flag=True,
                default=True,
                show_default=True,
                envvar=_ENV_VAR_MAPPING["mqtt_api"],
                show_envvar=True,
            ),
            click.option(
                "--web-api-host",
                default="0.0.0.0",
                show_default=True,
                help="Host address the web API binds to.",
                envvar=_ENV_VAR_MAPPING["web_api_host"],
                show_envvar=True,
                type=click.STRING,
            ),
            click.option(
                "--web-api-port",
                default=8000,
                show_default=True,
                help="Port the web API listens on.",
                envvar=_ENV_VAR_MAPPING["web_api_port"],
                show_envvar=True,
                type=click.INT,
            ),
            click.option(
                "--mqtt-broker-host",
                default="homeassistant",
                show_default=True,
                help="Hostname or IP of the MQTT broker.",
                envvar=_ENV_VAR_MAPPING["mqtt_broker_host"],
                show_envvar=True,
                type=click.STRING,
            ),
            click.option(
                "--mqtt-broker-port",
                default=1883,
                show_default=True,
                help="Port of the MQTT broker.",
                envvar=_ENV_VAR_MAPPING["mqtt_broker_port"],
                show_envvar=True,
                type=click.INT,
            ),
            click.option(
                "--mqtt-device-id",
                default="orv-1",
                show_default=True,
                help="Device ID used for MQTT discovery/state topics.",
                envvar=_ENV_VAR_MAPPING["mqtt_device_id"],
                show_envvar=True,
                type=click.STRING,
            ),
            click.option(
                "--mqtt-username",
                default="orv_user",
                show_default=True,
                help="MQTT Broker username.",
                envvar=_ENV_VAR_MAPPING["mqtt_username"],
                show_envvar=True,
                type=click.STRING,
            ),
            click.option(
                "--mqtt-password",
                default="password",
                show_default=True,
                help="MQTT Broker password.",
                envvar=_ENV_VAR_MAPPING["mqtt_password"],
                show_envvar=True,
                type=click.STRING,
            ),
        ]

        for dec in reversed(decorators):
            dec(command)

        return command

    return output


RUN_COMMAND_NAME = "run"


@cli.command(name=RUN_COMMAND_NAME, short_help="Main program to actually drive the fans")
@run_options()
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


def render_systemd_file(  # pylint: disable=too-many-arguments, too-many-positional-arguments, too-many-locals
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
) -> str:
    """
    Coerce the input args to strings and populate the asset systemd unit file.
    :param platform: Passed to systemd file.
    :param pcb_revision: Passed to systemd file.
    :param wire_mapping: Passed to systemd file.
    :param enable_web_api: Passed to systemd file.
    :param enable_mqtt_api: Passed to systemd file.
    :param web_api_host: Passed to systemd file.
    :param web_api_port: Passed to systemd file.
    :param mqtt_broker_host: Passed to systemd file.
    :param mqtt_broker_port: Passed to systemd file.
    :param mqtt_device_id: Passed to systemd file.
    :param mqtt_username: Passed to systemd file.
    :param mqtt_password: Passed to systemd file.
    :return: The contents of the systemd file. Go write it to disk!
    """

    def systemd_escape(value: str) -> str:
        """
        Escape a value for systemd Environment= line.

        - Backslashes are escaped first
        - Double quotes are escaped
        - Dollar signs are doubled
        """
        value = str(value)  # in case it’s not a string
        value = value.replace("\\", "\\\\")
        value = value.replace('"', '\\"')
        value = value.replace("$", "$$")
        return value

    template = Template(assets.SYSTEMD_SERVICE_TEMPLATE_PATH.read_text(encoding="utf-8"))

    rendered = template.render(
        user=os.getlogin(),
        exec_start=" ".join([sys.executable, os.path.abspath(__file__), RUN_COMMAND_NAME]),
        env_vars={
            k: systemd_escape(str(v))
            for k, v in {
                _ENV_VAR_MAPPING["platform"]: platform.value,
                _ENV_VAR_MAPPING["pcb_revision"]: pcb_revision.value,
                _ENV_VAR_MAPPING["wire_mapping_json"]: wire_mapping.model_dump_json(),
                _ENV_VAR_MAPPING["web_api"]: str(enable_web_api).upper(),
                _ENV_VAR_MAPPING["mqtt_api"]: str(enable_mqtt_api).upper(),
                _ENV_VAR_MAPPING["web_api_host"]: web_api_host,
                _ENV_VAR_MAPPING["web_api_port"]: str(web_api_port),
                _ENV_VAR_MAPPING["mqtt_broker_host"]: mqtt_broker_host,
                _ENV_VAR_MAPPING["mqtt_broker_port"]: mqtt_broker_port,
                _ENV_VAR_MAPPING["mqtt_device_id"]: mqtt_device_id,
                _ENV_VAR_MAPPING["mqtt_username"]: mqtt_username,
                _ENV_VAR_MAPPING["mqtt_password"]: mqtt_password,
            }.items()
        },
    )

    return rendered


@cli.command(short_help="Creates a systemd unit that will start the run at boot.")
@run_options()
@click.option(
    "--output-path",
    default=Path("./open_rack_vent.service").resolve(),
    show_default=True,
    help="The resulting systemd service def will be written to this path.",
    type=click.Path(
        file_okay=True, dir_okay=False, writable=True, resolve_path=True, path_type=Path
    ),
)
def render_systemd(  # pylint: disable=too-many-arguments, too-many-positional-arguments, too-many-locals
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
    output_path: Path,
) -> None:
    """
    Creates a systemd unit that will start the run at boot with the given parameters. The current
    executable is used as the systemd executable and all arguments are pre-validated and passed
    as environment variables in the unit.

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
    :param output_path: See click docs!
    :return: None
    """

    file_contents = render_systemd_file(
        platform=platform,
        pcb_revision=pcb_revision,
        wire_mapping=wire_mapping,
        enable_web_api=enable_web_api,
        enable_mqtt_api=enable_mqtt_api,
        web_api_host=web_api_host,
        web_api_port=web_api_port,
        mqtt_broker_host=mqtt_broker_host,
        mqtt_broker_port=mqtt_broker_port,
        mqtt_device_id=mqtt_device_id,
        mqtt_username=mqtt_username,
        mqtt_password=mqtt_password,
    )

    with open(output_path, "w", encoding="utf-8") as output_file:
        output_file.write(file_contents)

    click.echo(f"Wrote systemd unit to {output_path}")
    click.echo(file_contents)


if __name__ == "__main__":

    # TODO -- want an entrypoint to install a systemd unit

    cli()

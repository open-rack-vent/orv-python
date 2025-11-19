"""Main module."""

import json
from enum import Enum
from functools import partial
from typing import Any, Type, get_args, get_origin

import click
from bonus_click import options
from pydantic import BaseModel, ValidationError

from open_rack_vent import web_interface
from open_rack_vent.host_hardware import (
    HardwarePlatform,
    PCBRevision,
    WireMapping,
    create_hardware_interface,
)


def type_to_str(annotation: type) -> str:
    """
    Convert a type annotation to a readable string for help.
    Handles generics like list[int], list[Enum], dicts, etc.
    Capitalizes the outer type name (List, Dict, etc.).
    :param annotation: The type annotation to convert.
    :return: The type as a string
    """
    origin = get_origin(annotation)
    if origin is None:
        # Handle enums nicely
        if isinstance(annotation, type) and issubclass(annotation, Enum):
            return f"Enum[{', '.join( [e.value for e in annotation])}]"

        return annotation.__name__.title()

    annotation_args = get_args(annotation)
    origin_name = getattr(origin, "__name__", str(origin)).title()

    if annotation_args:
        inner = ", ".join(type_to_str(a) for a in annotation_args)
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
    envvar="ORV_WIRE_MAPPING_JSON",
    show_envvar=True,
)
@click.option(
    "--web-api",
    required=True,
    help="Providing this enables the web control api.",
    is_flag=True,
    default=True,
    show_default=True,
    envvar="ORV_WEB_API_ENABLED",
    show_envvar=True,
)
def run(
    platform: HardwarePlatform, pcb_revision: PCBRevision, wire_mapping: WireMapping, web_api: bool
) -> None:
    """
    Main air management program. Controls fans, reads sensors.

    \f

    :param platform: See click docs!
    :param pcb_revision: See click docs!
    :param wire_mapping: See click docs!
    :return: None
    """

    hardware_interface = create_hardware_interface(
        pcb_revision=pcb_revision,
        platform=platform,
        wire_mapping=wire_mapping,
    )

    if web_api:
        web_interface.create_web_interface(hardware_interface=hardware_interface)


if __name__ == "__main__":

    # TODO -- want an entrypoint to install a systemd unit
    # Also needs to be a click program

    cli()

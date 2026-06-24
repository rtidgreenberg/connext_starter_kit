
# WARNING: THIS FILE IS AUTO-GENERATED. DO NOT MODIFY.

# This file was generated from ExampleTypes.idl
# using RTI Code Generator (rtiddsgen) version 4.3.1.
# The rtiddsgen tool is part of the RTI Connext DDS distribution.
# For more information, type 'rtiddsgen -help' at a command shell
# or consult the Code Generator User's Manual.

from dataclasses import field
from typing import Union, Sequence, Optional
import rti.idl as idl
from enum import IntEnum
import sys
import os


example_types = idl.get_module("example_types")

example_types_MAX_ID_LENGTH = 32

example_types.MAX_ID_LENGTH = example_types_MAX_ID_LENGTH

example_types_MAX_NAME_LENGTH = 64

example_types.MAX_NAME_LENGTH = example_types_MAX_NAME_LENGTH

example_types_MAX_MESSAGE_LENGTH = 128

example_types.MAX_MESSAGE_LENGTH = example_types_MAX_MESSAGE_LENGTH

example_types_MAX_VALUE_LENGTH = 128

example_types.MAX_VALUE_LENGTH = example_types_MAX_VALUE_LENGTH

example_types_MAX_IMAGE_DATA_SIZE = 3145728

example_types.MAX_IMAGE_DATA_SIZE = example_types_MAX_IMAGE_DATA_SIZE

example_types_MAX_POINT_CLOUD_SIZE = 512000

example_types.MAX_POINT_CLOUD_SIZE = example_types_MAX_POINT_CLOUD_SIZE

@idl.enum
class example_types_CommandType(IntEnum):
    START = 0
    STOP = 1
    PAUSE = 2
    RESET = 3
    SHUTDOWN = 4

example_types.CommandType = example_types_CommandType

@idl.enum
class example_types_SystemState(IntEnum):
    INIT = 0
    RUNNING = 0
    ERROR = 1
    RESTARTING = 2
    SHUTTING_DOWN = 3

example_types.SystemState = example_types_SystemState

@idl.enum
class example_types_ButtonState(IntEnum):
    RELEASED = 0
    PRESSED = 1
    HELD = 2
    DOUBLE_CLICK = 3

example_types.ButtonState = example_types_ButtonState

@idl.struct(
    type_annotations = [idl.type_name("example_types::Command"), idl.xtypes_compliance(0x0000068C), ],
    member_annotations = {
        'command_id': [idl.key, idl.bound(example_types.MAX_ID_LENGTH)],
        'destination_id': [idl.bound(example_types.MAX_ID_LENGTH)],
        'message': [idl.bound(example_types.MAX_MESSAGE_LENGTH)],
    }
)
class example_types_Command:
    command_id: str = ""
    destination_id: str = ""
    command_type: example_types.CommandType = example_types.CommandType.START
    message: str = ""
    urgent: idl.uint16 = 0

example_types.Command = example_types_Command

@idl.struct(
    type_annotations = [idl.type_name("example_types::Position"), idl.xtypes_compliance(0x0000068C), ],
    member_annotations = {
        'source_id': [idl.key, idl.bound(example_types.MAX_ID_LENGTH)],
    }
)
class example_types_Position:
    source_id: str = ""
    latitude: float = 0.0
    longitude: float = 0.0
    altitude: float = 0.0
    timestamp_sec: idl.uint32 = 0

example_types.Position = example_types_Position

@idl.struct(
    type_annotations = [idl.type_name("example_types::State"), idl.xtypes_compliance(0x0000068C), ],
    member_annotations = {
        'source_id': [idl.key, idl.bound(example_types.MAX_ID_LENGTH)],
        'error_message': [idl.bound(example_types.MAX_MESSAGE_LENGTH)],
    }
)
class example_types_State:
    source_id: str = ""
    state_value: example_types.SystemState = example_types.SystemState.INIT
    error_message: str = ""

example_types.State = example_types_State

@idl.struct(
    type_annotations = [idl.type_name("example_types::Button"), idl.xtypes_compliance(0x0000068C), ],
    member_annotations = {
        'source_id': [idl.key, idl.bound(example_types.MAX_ID_LENGTH)],
        'button_id': [idl.key, idl.bound(example_types.MAX_ID_LENGTH)],
    }
)
class example_types_Button:
    source_id: str = ""
    button_id: str = ""
    button_state: example_types.ButtonState = example_types.ButtonState.RELEASED
    press_count: idl.uint32 = 0
    last_press_timestamp_sec: idl.uint32 = 0
    hold_duration_sec: float = 0.0

example_types.Button = example_types_Button

@idl.struct(
    type_annotations = [idl.type_name("example_types::AppConfig"), idl.xtypes_compliance(0x0000068C), ],
    member_annotations = {
        'app_id': [idl.key, idl.bound(example_types.MAX_ID_LENGTH)],
        'app_name': [idl.bound(example_types.MAX_NAME_LENGTH)],
        'version': [idl.bound(example_types.MAX_VALUE_LENGTH)],
        'description': [idl.bound(example_types.MAX_MESSAGE_LENGTH)],
    }
)
class example_types_AppConfig:
    app_id: str = ""
    app_name: str = ""
    domain_id: idl.uint32 = 0
    version: str = ""
    publish_rate_hz: float = 0.0
    debug_enabled: bool = False
    description: str = ""

example_types.AppConfig = example_types_AppConfig

@idl.struct(
    type_annotations = [idl.type_name("example_types::Image"), idl.xtypes_compliance(0x0000068C), ],
    member_annotations = {
        'image_id': [idl.key, idl.bound(example_types.MAX_ID_LENGTH)],
        'format': [idl.bound(example_types.MAX_NAME_LENGTH)],
        'data': [idl.bound(example_types.MAX_IMAGE_DATA_SIZE)],
    }
)
class example_types_Image:
    image_id: str = ""
    width: idl.uint32 = 0
    height: idl.uint32 = 0
    format: str = ""
    data: Sequence[idl.uint8] = field(default_factory = idl.array_factory(idl.uint8))

example_types.Image = example_types_Image

@idl.struct(
    type_annotations = [idl.final, idl.type_name("example_types::FinalFlatImage"), idl.xtypes_compliance(0x0000068C), ],
    member_annotations = {
        'image_id': [idl.key, ],
        'data': [idl.array([example_types.MAX_IMAGE_DATA_SIZE])],
    }
)
class example_types_FinalFlatImage:
    image_id: idl.uint32 = 0
    width: idl.uint16 = 0
    height: idl.uint16 = 0
    format: idl.uint16 = 0
    data: Sequence[idl.uint8] = field(default_factory = idl.array_factory(idl.uint8, [example_types.MAX_IMAGE_DATA_SIZE]))

example_types.FinalFlatImage = example_types_FinalFlatImage

@idl.struct(
    type_annotations = [idl.final, idl.type_name("example_types::FinalFlatPointCloud"), idl.xtypes_compliance(0x0000068C), ],
    member_annotations = {
        'point_cloud_id': [idl.key, ],
        'data': [idl.array([example_types.MAX_POINT_CLOUD_SIZE])],
    }
)
class example_types_FinalFlatPointCloud:
    point_cloud_id: idl.uint32 = 0
    data: Sequence[idl.uint8] = field(default_factory = idl.array_factory(idl.uint8, [example_types.MAX_POINT_CLOUD_SIZE]))

example_types.FinalFlatPointCloud = example_types_FinalFlatPointCloud

example_types_MAX_PARAMETER_NAME_LENGTH = 256

example_types.MAX_PARAMETER_NAME_LENGTH = example_types_MAX_PARAMETER_NAME_LENGTH

example_types_MAX_PARAMETER_STRING_VALUE_LENGTH = 256

example_types.MAX_PARAMETER_STRING_VALUE_LENGTH = example_types_MAX_PARAMETER_STRING_VALUE_LENGTH

example_types_MAX_PARAMETER_ARRAY_SIZE = 64

example_types.MAX_PARAMETER_ARRAY_SIZE = example_types_MAX_PARAMETER_ARRAY_SIZE

example_types_MAX_PARAMETERS_PER_MESSAGE = 64

example_types.MAX_PARAMETERS_PER_MESSAGE = example_types_MAX_PARAMETERS_PER_MESSAGE

@idl.enum
class example_types_ParameterType(IntEnum):
    PARAMETER_NOT_SET = 0
    PARAMETER_BOOL = 1
    PARAMETER_INTEGER = 2
    PARAMETER_DOUBLE = 3
    PARAMETER_STRING = 4
    PARAMETER_BYTE_ARRAY = 5
    PARAMETER_BOOL_ARRAY = 6
    PARAMETER_INTEGER_ARRAY = 7
    PARAMETER_DOUBLE_ARRAY = 8
    PARAMETER_STRING_ARRAY = 9

example_types.ParameterType = example_types_ParameterType

@idl.union(
    type_annotations = [idl.type_name("example_types::ParameterValue"), idl.xtypes_compliance(0x0000068C), ],
    member_annotations = {
        'string_value': [idl.bound(example_types.MAX_PARAMETER_STRING_VALUE_LENGTH)],
        'byte_array_value': [idl.bound(example_types.MAX_PARAMETER_ARRAY_SIZE)],
        'bool_array_value': [idl.bound(example_types.MAX_PARAMETER_ARRAY_SIZE)],
        'integer_array_value': [idl.bound(example_types.MAX_PARAMETER_ARRAY_SIZE)],
        'double_array_value': [idl.bound(example_types.MAX_PARAMETER_ARRAY_SIZE)],
        'string_array_value': [idl.bound(example_types.MAX_PARAMETER_ARRAY_SIZE), idl.element_annotations([idl.bound(example_types.MAX_PARAMETER_STRING_VALUE_LENGTH)])],
    }
)
class example_types_ParameterValue:

    discriminator: example_types.ParameterType = example_types.ParameterType.PARAMETER_NOT_SET
    value: Union[bool, int, float, str, Sequence[idl.uint8], Sequence[bool], Sequence[int], Sequence[float], Sequence[str], bool] = False

    bool_value: bool = idl.case(example_types.ParameterType.PARAMETER_BOOL)
    integer_value: int = idl.case(example_types.ParameterType.PARAMETER_INTEGER)
    double_value: float = idl.case(example_types.ParameterType.PARAMETER_DOUBLE)
    string_value: str = idl.case(example_types.ParameterType.PARAMETER_STRING)
    byte_array_value: Sequence[idl.uint8] = idl.case(example_types.ParameterType.PARAMETER_BYTE_ARRAY)
    bool_array_value: Sequence[bool] = idl.case(example_types.ParameterType.PARAMETER_BOOL_ARRAY)
    integer_array_value: Sequence[int] = idl.case(example_types.ParameterType.PARAMETER_INTEGER_ARRAY)
    double_array_value: Sequence[float] = idl.case(example_types.ParameterType.PARAMETER_DOUBLE_ARRAY)
    string_array_value: Sequence[str] = idl.case(example_types.ParameterType.PARAMETER_STRING_ARRAY)
    not_set: bool = idl.case(is_default=True)

example_types.ParameterValue = example_types_ParameterValue

@idl.struct(
    type_annotations = [idl.type_name("example_types::Parameter"), idl.xtypes_compliance(0x0000068C), ],
    member_annotations = {
        'name': [idl.bound(example_types.MAX_PARAMETER_NAME_LENGTH)],
    }
)
class example_types_Parameter:
    name: str = ""
    value: example_types.ParameterValue = field(default_factory = example_types.ParameterValue)

example_types.Parameter = example_types_Parameter

@idl.struct(
    type_annotations = [idl.type_name("example_types::ParameterEvent"), idl.xtypes_compliance(0x0000068C), ],
    member_annotations = {
        'node_id': [idl.key, idl.bound(example_types.MAX_ID_LENGTH)],
        'new_parameters': [idl.bound(example_types.MAX_PARAMETERS_PER_MESSAGE)],
        'changed_parameters': [idl.bound(example_types.MAX_PARAMETERS_PER_MESSAGE)],
        'deleted_parameters': [idl.bound(example_types.MAX_PARAMETERS_PER_MESSAGE)],
    }
)
class example_types_ParameterEvent:
    node_id: str = ""
    timestamp_ns: idl.uint64 = 0
    new_parameters: Sequence[example_types.Parameter] = field(default_factory = list)
    changed_parameters: Sequence[example_types.Parameter] = field(default_factory = list)
    deleted_parameters: Sequence[example_types.Parameter] = field(default_factory = list)

example_types.ParameterEvent = example_types_ParameterEvent

@idl.struct(
    type_annotations = [idl.type_name("example_types::SetParametersRequest"), idl.xtypes_compliance(0x0000068C), ],
    member_annotations = {
        'node_id': [idl.key, idl.bound(example_types.MAX_ID_LENGTH)],
        'parameters': [idl.bound(example_types.MAX_PARAMETERS_PER_MESSAGE)],
    }
)
class example_types_SetParametersRequest:
    node_id: str = ""
    request_id: idl.uint64 = 0
    parameters: Sequence[example_types.Parameter] = field(default_factory = list)

example_types.SetParametersRequest = example_types_SetParametersRequest

@idl.struct(
    type_annotations = [idl.type_name("example_types::SetParameterResult"), idl.xtypes_compliance(0x0000068C), ],
    member_annotations = {
        'reason': [idl.bound(example_types.MAX_MESSAGE_LENGTH)],
    }
)
class example_types_SetParameterResult:
    successful: bool = False
    reason: str = ""

example_types.SetParameterResult = example_types_SetParameterResult

@idl.struct(
    type_annotations = [idl.type_name("example_types::SetParametersResponse"), idl.xtypes_compliance(0x0000068C), ],
    member_annotations = {
        'node_id': [idl.key, idl.bound(example_types.MAX_ID_LENGTH)],
        'results': [idl.bound(example_types.MAX_PARAMETERS_PER_MESSAGE)],
    }
)
class example_types_SetParametersResponse:
    node_id: str = ""
    request_id: idl.uint64 = 0
    results: Sequence[example_types.SetParameterResult] = field(default_factory = list)

example_types.SetParametersResponse = example_types_SetParametersResponse

@idl.struct(
    type_annotations = [idl.type_name("example_types::GetParametersRequest"), idl.xtypes_compliance(0x0000068C), ],
    member_annotations = {
        'node_id': [idl.key, idl.bound(example_types.MAX_ID_LENGTH)],
        'names': [idl.bound(example_types.MAX_PARAMETERS_PER_MESSAGE), idl.element_annotations([idl.bound(example_types.MAX_NAME_LENGTH)])],
    }
)
class example_types_GetParametersRequest:
    node_id: str = ""
    request_id: idl.uint64 = 0
    names: Sequence[str] = field(default_factory = list)

example_types.GetParametersRequest = example_types_GetParametersRequest

@idl.struct(
    type_annotations = [idl.type_name("example_types::GetParametersResponse"), idl.xtypes_compliance(0x0000068C), ],
    member_annotations = {
        'node_id': [idl.key, idl.bound(example_types.MAX_ID_LENGTH)],
        'parameters': [idl.bound(example_types.MAX_PARAMETERS_PER_MESSAGE)],
    }
)
class example_types_GetParametersResponse:
    node_id: str = ""
    request_id: idl.uint64 = 0
    parameters: Sequence[example_types.Parameter] = field(default_factory = list)

example_types.GetParametersResponse = example_types_GetParametersResponse

@idl.struct(
    type_annotations = [idl.type_name("example_types::ListParametersRequest"), idl.xtypes_compliance(0x0000068C), ],
    member_annotations = {
        'node_id': [idl.key, idl.bound(example_types.MAX_ID_LENGTH)],
        'prefixes': [idl.bound(16), idl.element_annotations([idl.bound(example_types.MAX_NAME_LENGTH)])],
    }
)
class example_types_ListParametersRequest:
    node_id: str = ""
    request_id: idl.uint64 = 0
    prefixes: Sequence[str] = field(default_factory = list)
    depth: idl.uint32 = 0

example_types.ListParametersRequest = example_types_ListParametersRequest

@idl.struct(
    type_annotations = [idl.type_name("example_types::ListParametersResponse"), idl.xtypes_compliance(0x0000068C), ],
    member_annotations = {
        'node_id': [idl.key, idl.bound(example_types.MAX_ID_LENGTH)],
        'names': [idl.bound(example_types.MAX_PARAMETERS_PER_MESSAGE), idl.element_annotations([idl.bound(example_types.MAX_NAME_LENGTH)])],
    }
)
class example_types_ListParametersResponse:
    node_id: str = ""
    request_id: idl.uint64 = 0
    names: Sequence[str] = field(default_factory = list)

example_types.ListParametersResponse = example_types_ListParametersResponse

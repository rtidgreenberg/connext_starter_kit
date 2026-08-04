
# WARNING: THIS FILE IS AUTO-GENERATED. DO NOT MODIFY.

# This file was generated from CycloneConnext.idl
# using RTI Code Generator (rtiddsgen) version 4.7.0.
# The rtiddsgen tool is part of the RTI Connext DDS distribution.
# For more information, type 'rtiddsgen -help' at a command shell
# or consult the Code Generator User's Manual.

from dataclasses import field
from typing import Union, Sequence, Optional
import rti.idl as idl
import rti.rpc as rpc
from enum import IntEnum
import sys
import os
from abc import ABC



DoctorShared = idl.get_module("DoctorShared")

@idl.struct(
    type_annotations = [idl.type_name("DoctorShared::Nested"), idl.xtypes_compliance(0x000001A9), ],

    member_annotations = {
        'n_id': [idl.id(0), ],
        'n_val': [idl.id(1), ],
    }
)
class DoctorShared_Nested:
    n_id: idl.int32 = 0
    n_val: float = 0.0

DoctorShared.Nested = DoctorShared_Nested

@idl.struct(
    type_annotations = [idl.type_name("DoctorShared::Sample"), idl.xtypes_compliance(0x000001A9), ],

    member_annotations = {
        'id': [idl.key, idl.id(0), ],
        'label': [idl.id(1), idl.bound(255),],
        'nested': [idl.id(2), ],
        'scores': [idl.id(3), idl.bound(100),],
    }
)
class DoctorShared_Sample:
    id: idl.int32 = 0
    label: str = ""
    nested: DoctorShared.Nested = field(default_factory = DoctorShared.Nested)
    scores: Sequence[float] = field(default_factory = idl.array_factory(float))

DoctorShared.Sample = DoctorShared_Sample

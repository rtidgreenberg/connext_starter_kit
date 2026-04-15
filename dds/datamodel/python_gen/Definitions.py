
# WARNING: THIS FILE IS AUTO-GENERATED. DO NOT MODIFY.

# This file was generated from Definitions.idl
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


qos_profiles = idl.get_module("qos_profiles")

qos_profiles_LARGE_DATA_PARTICIPANT = "DPLibrary::LargeDataSHMEMParticipant"

qos_profiles.LARGE_DATA_PARTICIPANT = qos_profiles_LARGE_DATA_PARTICIPANT

qos_profiles_LARGE_DATA_UDP_PARTICIPANT = "DPLibrary::LargeDataUdpParticipant"

qos_profiles.LARGE_DATA_UDP_PARTICIPANT = qos_profiles_LARGE_DATA_UDP_PARTICIPANT

qos_profiles_DEFAULT_PARTICIPANT = "DPLibrary::DefaultParticipant"

qos_profiles.DEFAULT_PARTICIPANT = qos_profiles_DEFAULT_PARTICIPANT

qos_profiles_ASSIGNER = "DataPatternsLibrary::AssignerQoS"

qos_profiles.ASSIGNER = qos_profiles_ASSIGNER

qos_profiles_EVENT = "DataPatternsLibrary::EventQoS"

qos_profiles.EVENT = qos_profiles_EVENT

qos_profiles_PARAMETER = "DataPatternsLibrary::ParameterQoS"

qos_profiles.PARAMETER = qos_profiles_PARAMETER

qos_profiles_STATUS = "DataPatternsLibrary::StatusQoS"

qos_profiles.STATUS = qos_profiles_STATUS

qos_profiles_COMMAND_STRENGTH_10 = "DataPatternsLibrary::CommandStrength10QoS"

qos_profiles.COMMAND_STRENGTH_10 = qos_profiles_COMMAND_STRENGTH_10

qos_profiles_COMMAND_STRENGTH_20 = "DataPatternsLibrary::CommandStrength20QoS"

qos_profiles.COMMAND_STRENGTH_20 = qos_profiles_COMMAND_STRENGTH_20

qos_profiles_COMMAND_STRENGTH_30 = "DataPatternsLibrary::CommandStrength30QoS"

qos_profiles.COMMAND_STRENGTH_30 = qos_profiles_COMMAND_STRENGTH_30

qos_profiles_LARGE_DATA_SHMEM = "DataPatternsLibrary::LargeDataSHMEMQoS"

qos_profiles.LARGE_DATA_SHMEM = qos_profiles_LARGE_DATA_SHMEM

qos_profiles_LARGE_DATA_SHMEM_ZC = "DataPatternsLibrary::LargeDataSHMEM_ZCQoS"

qos_profiles.LARGE_DATA_SHMEM_ZC = qos_profiles_LARGE_DATA_SHMEM_ZC

qos_profiles_BURST_LARGE_DATA_UDP = "DataPatternsLibrary::BurstLargeDataUdpQoS"

qos_profiles.BURST_LARGE_DATA_UDP = qos_profiles_BURST_LARGE_DATA_UDP

domains = idl.get_module("domains")

domains_DEFAULT_DOMAIN_ID = 1

domains.DEFAULT_DOMAIN_ID = domains_DEFAULT_DOMAIN_ID

domains_TEST_DOMAIN_ID = 100

domains.TEST_DOMAIN_ID = domains_TEST_DOMAIN_ID

topics = idl.get_module("topics")

topics_COMMAND_TOPIC = "Command"

topics.COMMAND_TOPIC = topics_COMMAND_TOPIC

topics_POSITION_TOPIC = "Position"

topics.POSITION_TOPIC = topics_POSITION_TOPIC

topics_STATE_TOPIC = "State"

topics.STATE_TOPIC = topics_STATE_TOPIC

topics_BUTTON_TOPIC = "Button"

topics.BUTTON_TOPIC = topics_BUTTON_TOPIC

topics_IMAGE_TOPIC = "Image"

topics.IMAGE_TOPIC = topics_IMAGE_TOPIC

topics_FINAL_FLAT_IMAGE_TOPIC = "FinalFlatImage"

topics.FINAL_FLAT_IMAGE_TOPIC = topics_FINAL_FLAT_IMAGE_TOPIC

topics_POINT_CLOUD_TOPIC = "PointCloud"

topics.POINT_CLOUD_TOPIC = topics_POINT_CLOUD_TOPIC

topics_CONFIG_TOPIC = "AppConfig"

topics.CONFIG_TOPIC = topics_CONFIG_TOPIC

topics_PARAMETER_EVENTS_TOPIC = "ParameterEvents"

topics.PARAMETER_EVENTS_TOPIC = topics_PARAMETER_EVENTS_TOPIC

topics_SET_PARAMETERS_REQUEST_TOPIC = "SetParametersRequest"

topics.SET_PARAMETERS_REQUEST_TOPIC = topics_SET_PARAMETERS_REQUEST_TOPIC

topics_SET_PARAMETERS_RESPONSE_TOPIC = "SetParametersResponse"

topics.SET_PARAMETERS_RESPONSE_TOPIC = topics_SET_PARAMETERS_RESPONSE_TOPIC

topics_GET_PARAMETERS_REQUEST_TOPIC = "GetParametersRequest"

topics.GET_PARAMETERS_REQUEST_TOPIC = topics_GET_PARAMETERS_REQUEST_TOPIC

topics_GET_PARAMETERS_RESPONSE_TOPIC = "GetParametersResponse"

topics.GET_PARAMETERS_RESPONSE_TOPIC = topics_GET_PARAMETERS_RESPONSE_TOPIC

topics_LIST_PARAMETERS_REQUEST_TOPIC = "ListParametersRequest"

topics.LIST_PARAMETERS_REQUEST_TOPIC = topics_LIST_PARAMETERS_REQUEST_TOPIC

topics_LIST_PARAMETERS_RESPONSE_TOPIC = "ListParametersResponse"

topics.LIST_PARAMETERS_RESPONSE_TOPIC = topics_LIST_PARAMETERS_RESPONSE_TOPIC

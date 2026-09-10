# (c) Copyright, Real-Time Innovations, 2026.  All rights reserved.
# RTI grants Licensee a license to use, modify, compile, and create derivative
# works of the software solely for use with RTI Connext DDS. Licensee may
# redistribute copies of the software provided that all such copies are subject
# to this license. The software is provided "as is", with no warranty of any
# type, including any warranty for fitness for any purpose. RTI is under no
# obligation to maintain or support the software. RTI shall not be liable for
# any incidental or consequential damages arising out of the use or inability
# to use the software.
"""Test fakes for rti_view."""


class FakeMember:
    def __init__(self, name, member_type):
        self.name = name
        self.type = member_type


class FakeDynamicType:
    def __init__(self, kind, name="", members=()):
        self.kind = kind
        self.name = name
        self._members = tuple(members)

    @property
    def member_count(self):
        return len(self._members)

    def member(self, index):
        return self._members[index]

    def members(self):
        return iter(self._members)


class FakeInfo:
    def __init__(self, valid=True):
        self.valid = valid


class FakeReader:
    def __init__(self, samples):
        self._samples = list(samples)

    def take(self):
        samples = list(self._samples)
        self._samples.clear()
        return samples


class FakeKey:
    def __init__(self, value):
        self.value = value


class FakeEndpointData:
    def __init__(self, key, participant_key, topic_name="Telemetry", type_name="Telemetry", dynamic_type=None):
        self.key = FakeKey(key)
        self.participant_key = FakeKey(participant_key)
        self.topic_name = topic_name
        self.type_name = type_name
        self.type = dynamic_type
        self.type_information = None
        self.type_object = None
        self.type_consistency = "fake_type_consistency"
        self.representation = "fake_representation"
        self.reliability = None
        self.durability = None
        self.deadline = None
        self.ownership = None
        self.presentation = None
        self.partition = None


class FakeParticipantName:
    def __init__(self, name):
        self.name = name


class FakeLocator:
    def __init__(self, address=(0, 0, 0, 0, 127, 0, 0, 1)):
        self.address = address


class FakeParticipantData:
    def __init__(self, key=(1, 2, 3, 4), name="TelemetryPublisher"):
        self.key = FakeKey(key)
        self.participant_name = FakeParticipantName(name)
        self.default_unicast_locators = [FakeLocator()]

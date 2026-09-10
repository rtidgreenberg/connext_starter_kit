# (c) Copyright, Real-Time Innovations, 2026.  All rights reserved.
# RTI grants Licensee a license to use, modify, compile, and create derivative
# works of the software solely for use with RTI Connext DDS. Licensee may
# redistribute copies of the software provided that all such copies are subject
# to this license. The software is provided "as is", with no warranty of any
# type, including any warranty for fitness for any purpose. RTI is under no
# obligation to maintain or support the software. RTI shall not be liable for
# any incidental or consequential damages arising out of the use or inability
# to use the software.
"""Shared test doubles for rs_gui headless tests.

Canonical implementations of FakeHandle and FakeSpawner. Import from here
instead of duplicating process-manager doubles across test files.
"""


class FakeHandle:
    """Fake process handle for ServiceProcessManager tests."""

    def __init__(self, pid=4321, output_path=""):
        self.pid = pid
        self.returncode = None
        self.terminate_calls = 0
        self.kill_calls = 0
        self.output_path = output_path

    def poll(self):
        return self.returncode

    def terminate(self):
        self.terminate_calls += 1

    def kill(self):
        self.kill_calls += 1
        self.returncode = -9


class FakeSpawner:
    """Fake process spawner that yields queued FakeHandle instances."""

    def __init__(self, *handles):
        self.handles = list(handles)
        self.calls = []

    def start(self, command_line, working_dir="", environment=None):
        self.calls.append(tuple(command_line))
        if not self.handles:
            raise RuntimeError("no fake handles queued")
        return self.handles.pop(0)

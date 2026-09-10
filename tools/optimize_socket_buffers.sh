# (c) Copyright, Real-Time Innovations, 2026.  All rights reserved.
# RTI grants Licensee a license to use, modify, compile, and create derivative
# works of the software solely for use with RTI Connext DDS. Licensee may
# redistribute copies of the software provided that all such copies are subject
# to this license. The software is provided "as is", with no warranty of any
# type, including any warranty for fitness for any purpose. RTI is under no
# obligation to maintain or support the software. RTI shall not be liable for
# any incidental or consequential damages arising out of the use or inability
# to use the software.
# !/bin/bash
# This script optimizes the socket buffer sizes for better network performance
# Simply run with: sudo ./tools/optimize_socket_buffers.sh

sudo sysctl -w net.core.rmem_default="65536"
sudo sysctl -w net.core.wmem_default="65536"
sudo sysctl -w net.core.rmem_max="10485760"
sudo sysctl -w net.core.wmem_max="10485760"
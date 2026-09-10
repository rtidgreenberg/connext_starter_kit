#!/bin/bash
# (c) Copyright, Real-Time Innovations, 2026.  All rights reserved.
# RTI grants Licensee a license to use, modify, compile, and create derivative
# works of the software solely for use with RTI Connext DDS. Licensee may
# redistribute copies of the software provided that all such copies are subject
# to this license. The software is provided "as is", with no warranty of any
# type, including any warranty for fitness for any purpose. RTI is under no
# obligation to maintain or support the software. RTI shall not be liable for
# any incidental or consequential damages arising out of the use or inability
# to use the software.
# XML App Creation - Framework Setup Script
# This is a POC script that simulates copying template files

echo "============================================"
echo "  XML App Creation - Framework Setup"
echo "============================================"
echo ""
echo "[1/4] Copying XML application template files..."
sleep 1
echo "  ✓ Copied USER_QOS_PROFILES.xml"
echo "  ✓ Copied APPLICATION_DEFINITION.xml"
echo ""
echo "[2/4] Copying participant configuration..."
sleep 1
echo "  ✓ Copied DomainParticipant XML config"
echo "  ✓ Copied Publisher/Subscriber XML config"
echo ""
echo "[3/4] Setting up directory structure..."
sleep 1
echo "  ✓ Created apps/xml_app/"
echo "  ✓ Created apps/xml_app/config/"
echo "  ✓ Created apps/xml_app/src/"
echo ""
echo "[4/4] Generating build files..."
sleep 1
echo "  ✓ Created CMakeLists.txt"
echo ""
echo "============================================"
echo "  XML App Creation setup complete!"
echo "  Next: Edit APPLICATION_DEFINITION.xml"
echo "  to define your DDS entities."
echo "============================================"

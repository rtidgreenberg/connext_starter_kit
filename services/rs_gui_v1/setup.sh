#!/bin/bash
# Setup script for Python Recording Service Remote Control
#
# This script uses rtiddsgen to:
#   1. Convert admin and monitoring IDL files to XML for use with
#      DynamicData / QosProvider.
#   2. Normalize monitoring XML enum/discriminator references so Python
#      DynamicData readers can deserialize Recording Service monitoring data.
#
# Reference: https://community.rti.com/static/documentation/connext-dds/current/doc/manuals/connext_dds_professional/code_generator/users_manual/code_generator/users_manual/CommandLineArgs.htm

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
XML_OUT_DIR="$SCRIPT_DIR/xml_types"
PREFERRED_CONNEXT_VERSION="${PREFERRED_CONNEXT_VERSION:-7.6.0}"

# --- NDDSHOME Auto-Detection ---
if [ -z "$NDDSHOME" ]; then
    echo "NDDSHOME not set. Searching for RTI Connext installation..."
    PREFERRED_RTI="$HOME/rti_connext_dds-$PREFERRED_CONNEXT_VERSION"
    if [ -d "$PREFERRED_RTI" ]; then
        LATEST_RTI="$PREFERRED_RTI"
    else
        LATEST_RTI=$(ls -d ~/rti_connext_dds-* 2>/dev/null | sort -V | tail -n 1)
    fi

    if [ -n "$LATEST_RTI" ] && [ -d "$LATEST_RTI" ]; then
        export NDDSHOME="$LATEST_RTI"
        echo "✓ Found RTI installation: $NDDSHOME"
    else
        echo "ERROR: NDDSHOME not set and no RTI installation found in ~/rti_connext_dds-*"
        exit 1
    fi
else
    echo "✓ NDDSHOME: $NDDSHOME"
fi

# --- Verify rtiddsgen ---
RTIDDSGEN="$NDDSHOME/bin/rtiddsgen"
if [ ! -f "$RTIDDSGEN" ]; then
    echo "ERROR: rtiddsgen not found at $RTIDDSGEN"
    exit 1
fi
echo "✓ rtiddsgen: $RTIDDSGEN"

# --- Verify source IDL files ---
IDL_DIR="$NDDSHOME/resource/idl"

# IDL files converted to XML for DynamicData CDR serialization and monitoring
XML_IDL_FILES=("ServiceCommon.idl" "ServiceAdmin.idl" "RecordingServiceTypes.idl"
               "RecordingServiceMonitoring.idl" "RoutingServiceMonitoring.idl"
               "ServiceMonitoring.idl")

# All unique IDL files for verification
ALL_IDL_FILES=("ServiceCommon.idl" "ServiceAdmin.idl" "RecordingServiceTypes.idl"
               "RecordingServiceMonitoring.idl" "RoutingServiceMonitoring.idl"
               "ServiceMonitoring.idl")

for idl in "${ALL_IDL_FILES[@]}"; do
    if [ ! -f "$IDL_DIR/$idl" ]; then
        echo "ERROR: IDL file not found: $IDL_DIR/$idl"
        exit 1
    fi
done
echo "✓ Source IDL files found in: $IDL_DIR"

# --- Install sqlite3 (needed by rtirecordingservice_list_tags) ---
if ! command -v sqlite3 &>/dev/null; then
    echo
    echo "Installing sqlite3 (required by rtirecordingservice_list_tags)..."
    if command -v apt-get &>/dev/null; then
        sudo apt-get install -y sqlite3
    elif command -v yum &>/dev/null; then
        sudo yum install -y sqlite
    elif command -v dnf &>/dev/null; then
        sudo dnf install -y sqlite
    elif command -v pacman &>/dev/null; then
        sudo pacman -S --noconfirm sqlite
    else
        echo "WARNING: Could not detect package manager. Please install sqlite3 manually."
    fi

    if command -v sqlite3 &>/dev/null; then
        echo "✓ sqlite3 installed: $(sqlite3 --version)"
    else
        echo "WARNING: sqlite3 installation may have failed. rtirecordingservice_list_tags may not work."
    fi
else
    echo "✓ sqlite3 already installed: $(sqlite3 --version)"
fi

# --- Convert IDL to XML (for DynamicData / CDR serialization) ---
mkdir -p "$XML_OUT_DIR"
echo
echo "Converting admin and monitoring IDL files to XML..."

for idl in "${XML_IDL_FILES[@]}"; do
    echo "  Converting $idl → XML..."
    "$RTIDDSGEN" -convertToXML -d "$XML_OUT_DIR" -I "$IDL_DIR" "$IDL_DIR/$idl" -replace 2>&1
done

literalize_monitoring_xml() {
    local file
    local from
    local to
    local replacements=(
        "RTI::Service::BOUNDED_STRING_LENGTH_MAX|255"
        "RTI::Service::FILE_PATH_MAX_LENGTH|1024"
        "RTI::Service::RESOURCE_IDENTIFIER_LENGTH_MAX|2048"
        "RTI::Service::BUILTIN_TOPIC_KEY_VALUE_LENGTH|4"
        "RTI::Service::Monitoring::RESOURCE_GUID_VALUE_LENGTH|16"
        "RTI::RecordingService::DATA_TAG_MAX_STRING_SIZE|256"
        "(RTI::RecordingService::TIMESTAMP)|0"
        "(RTI::RecordingService::TAG_NAME)|1"
        "(RTI::RecordingService::OFFSET)|0"
        "(RTI::RecordingService::SLICE)|1"
        "(RTI::Service::Monitoring::ROUTING_INDEX)|10000"
        "(RTI::Service::Monitoring::RECORDING_INDEX)|20000"
        "(RTI::Service::Monitoring::CDS_INDEX)|30000"
        "(RTI::Service::Monitoring::ROUTING_SERVICE)|10000"
        "(RTI::Service::Monitoring::ROUTING_DOMAIN_ROUTE)|10001"
        "(RTI::Service::Monitoring::ROUTING_SESSION)|10002"
        "(RTI::Service::Monitoring::ROUTING_AUTO_ROUTE)|10003"
        "(RTI::Service::Monitoring::ROUTING_ROUTE)|10004"
        "(RTI::Service::Monitoring::ROUTING_INPUT)|10005"
        "(RTI::Service::Monitoring::ROUTING_OUTPUT)|10006"
        "(RTI::Service::Monitoring::RECORDING_SERVICE)|20000"
        "(RTI::Service::Monitoring::RECORDING_SESSION)|20001"
        "(RTI::Service::Monitoring::RECORDING_TOPIC_GROUP)|20002"
        "(RTI::Service::Monitoring::RECORDING_TOPIC)|20003"
        "(RTI::Service::Monitoring::CDS_SERVICE)|30000"
        "(RTI::Service::Monitoring::CDS_FORWARDER)|30001"
        "(RTI::Service::Monitoring::CDS_DATABASE)|30002"
        "(RTI::Service::Monitoring::CDS_RECEIVER)|30003"
        "(RTI::Service::Monitoring::CDS_SENDER)|30004"
    )

    for file in "$XML_OUT_DIR"/*.xml; do
        [ -f "$file" ] || continue
        for replacement in "${replacements[@]}"; do
            from="${replacement%%|*}"
            to="${replacement##*|}"
            sed -i "s|$from|$to|g" "$file"
        done
        sed -i 's|<typedef name="XmlString" stringMaxLength="255" type="string"/>|<typedef name="XmlString" stringMaxLength="65535" type="string"/>|g' "$file"
        sed -i 's| deprecated="true"||g' "$file"
    done
}

echo
echo "Normalizing monitoring XML enum/discriminator values..."
literalize_monitoring_xml

echo
echo "✓ XML type files generated in: $XML_OUT_DIR"
ls -la "$XML_OUT_DIR"/*.xml

STAMP_FILE="$XML_OUT_DIR/.generated_from_nddshome"
NDDSHOME_REAL="$(readlink -f "$NDDSHOME")"
CONNEXT_VERSION="${NDDSHOME_REAL##*-}"
{
    echo "nddshome=$NDDSHOME_REAL"
    echo "version=$CONNEXT_VERSION"
} > "$STAMP_FILE"
echo "✓ XML type metadata stamped: $STAMP_FILE"

echo
echo "=== Setup complete ==="
echo "You can now run: ./run.sh --help"
echo "Or use the venv directly: ../../connext_dds_env/bin/python recording_service_control.py --help"

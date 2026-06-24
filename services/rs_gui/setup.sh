#!/bin/bash
# Generate XML DynamicData type files used by rs_gui Connext adapters.

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
XML_OUT_DIR="$SCRIPT_DIR/xml_types"
PREFERRED_CONNEXT_VERSION="${PREFERRED_CONNEXT_VERSION:-7.7.0}"
INSTALL_PYTHON_DEPS=true

usage() {
    cat <<'EOF'
Usage: ./setup.sh [--skip-python-deps]

Options:
  --skip-python-deps  Skip Python dependency installation
  -h, --help          Show this help message
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --skip-python-deps)
            INSTALL_PYTHON_DEPS=false
            shift
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            echo "ERROR: Unknown option: $1"
            usage
            exit 1
            ;;
    esac
done

if [ -z "$NDDSHOME" ]; then
    PREFERRED_RTI="$HOME/rti_connext_dds-$PREFERRED_CONNEXT_VERSION"
    if [ -d "$PREFERRED_RTI" ]; then
        export NDDSHOME="$PREFERRED_RTI"
    else
        LATEST_RTI=$(ls -d ~/rti_connext_dds-* 2>/dev/null | sort -V | tail -n 1)
        if [ -n "$LATEST_RTI" ] && [ -d "$LATEST_RTI" ]; then
            export NDDSHOME="$LATEST_RTI"
        else
            echo "ERROR: NDDSHOME not set and no RTI Connext installation found."
            exit 1
        fi
    fi
fi

RTIDDSGEN="$NDDSHOME/bin/rtiddsgen"
IDL_DIR="$NDDSHOME/resource/idl"
XML_IDL_FILES=("ServiceCommon.idl" "ServiceAdmin.idl" "RecordingServiceTypes.idl"
               "ServiceMonitoring.idl" "RecordingServiceMonitoring.idl"
               "RoutingServiceMonitoring.idl")

if [ ! -f "$RTIDDSGEN" ]; then
    echo "ERROR: rtiddsgen not found: $RTIDDSGEN"
    exit 1
fi

for idl in "${XML_IDL_FILES[@]}"; do
    if [ ! -f "$IDL_DIR/$idl" ]; then
        echo "ERROR: IDL file not found: $IDL_DIR/$idl"
        exit 1
    fi
done

mkdir -p "$XML_OUT_DIR"
echo "Generating rs_gui XML types in: $XML_OUT_DIR"
for idl in "${XML_IDL_FILES[@]}"; do
    "$RTIDDSGEN" -convertToXML -d "$XML_OUT_DIR" -I "$IDL_DIR" "$IDL_DIR/$idl" -replace
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

literalize_monitoring_xml

STAMP_FILE="$XML_OUT_DIR/.generated_from_nddshome"
NDDSHOME_REAL="$(readlink -f "$NDDSHOME")"
CONNEXT_VERSION="${NDDSHOME_REAL##*-}"
{
    echo "nddshome=$NDDSHOME_REAL"
    echo "version=$CONNEXT_VERSION"
} > "$STAMP_FILE"

echo "Generated XML type files:"
ls -1 "$XML_OUT_DIR"/*.xml
echo "Wrote metadata stamp: $STAMP_FILE"

if [ "$INSTALL_PYTHON_DEPS" = true ]; then
    VENV_PYTHON="$SCRIPT_DIR/../../connext_dds_env/bin/python"
    REQUIREMENTS_FILE="$SCRIPT_DIR/requirements.txt"

    if [ -f "$REQUIREMENTS_FILE" ]; then
        if [ -x "$VENV_PYTHON" ]; then
            echo
            echo "Installing rs_gui Python dependencies from: $REQUIREMENTS_FILE"
            "$VENV_PYTHON" -m pip install -r "$REQUIREMENTS_FILE"
        else
            echo
            echo "WARNING: Repository virtual environment not found at $VENV_PYTHON"
            echo "Skipping Python dependency installation."
            echo "Run apps/python/install.sh, then rerun ./setup.sh"
        fi
    fi
fi
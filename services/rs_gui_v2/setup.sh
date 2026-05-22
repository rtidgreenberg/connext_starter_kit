#!/bin/bash
# Generate XML DynamicData type files used by rs_gui_v2 Connext adapters.

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
XML_OUT_DIR="$SCRIPT_DIR/xml_types"
PREFERRED_CONNEXT_VERSION="${PREFERRED_CONNEXT_VERSION:-7.6.0}"

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
XML_IDL_FILES=("ServiceCommon.idl" "ServiceAdmin.idl" "RecordingServiceTypes.idl")

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
echo "Generating rs_gui_v2 XML types in: $XML_OUT_DIR"
for idl in "${XML_IDL_FILES[@]}"; do
    "$RTIDDSGEN" -convertToXML -d "$XML_OUT_DIR" -I "$IDL_DIR" "$IDL_DIR/$idl" -replace
done

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
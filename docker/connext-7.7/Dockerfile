# (c) Copyright, Real-Time Innovations, 2026.  All rights reserved.
# RTI grants Licensee a license to use, modify, compile, and create derivative
# works of the software solely for use with RTI Connext DDS. Licensee may
# redistribute copies of the software provided that all such copies are subject
# to this license. The software is provided "as is", with no warranty of any
# type, including any warranty for fitness for any purpose. RTI is under no
# obligation to maintain or support the software. RTI shall not be liable for
# any incidental or consequential damages arising out of the use or inability
# to use the software.

FROM ubuntu:24.04

ARG CONNEXT_VERSION=7.7.0
ARG CONNEXTDDS_ARCH=x64Linux4gcc8.5.0

ENV DEBIAN_FRONTEND=noninteractive \
    NDDSHOME=/opt/rti.com/rti_connext_dds-${CONNEXT_VERSION} \
    CONNEXTDDS_ARCH=${CONNEXTDDS_ARCH} \
    PATH=/opt/rti.com/rti_connext_dds-${CONNEXT_VERSION}/bin:${PATH} \
    PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        ca-certificates \
        cmake \
        curl \
        git \
        gnupg \
        gstreamer1.0-libav \
        gstreamer1.0-plugins-bad \
        gstreamer1.0-plugins-good \
        libgstreamer-plugins-base1.0-dev \
        libgstreamer1.0-dev \
        libpython3.12 \
        pkg-config \
        python3 \
        python3-pip \
        python3-tk \
        python3-venv \
    && rm -rf /var/lib/apt/lists/*

RUN curl -fsSL -o /usr/share/keyrings/rti-official-archive.gpg \
        https://packages.rti.com/deb/official/repo.key \
    && printf 'deb [arch=%s signed-by=%s] %s %s main\n' \
        "$(dpkg --print-architecture)" \
        /usr/share/keyrings/rti-official-archive.gpg \
        https://packages.rti.com/deb/official \
        "$(. /etc/os-release && printf '%s' "$VERSION_CODENAME")" \
        > /etc/apt/sources.list.d/rti-official.list

RUN printf 'rti-connext-dds-%s-common rti-connext-dds-%s/license/accepted select true\n' \
        "${CONNEXT_VERSION}" "${CONNEXT_VERSION}" \
        | debconf-set-selections \
    && apt-get update \
    && apt-get install -y --no-install-recommends \
        "rti-connext-dds-${CONNEXT_VERSION}" \
    && rm -rf /var/lib/apt/lists/*

COPY tools/rti_doctor/requirements.txt /tmp/rti-doctor-requirements.txt
RUN python3 -m venv /opt/connext-venv \
    && /opt/connext-venv/bin/python -m pip install --no-cache-dir \
        "rti.connext==${CONNEXT_VERSION}" \
        -r /tmp/rti-doctor-requirements.txt \
    && rm -f /tmp/rti-doctor-requirements.txt

WORKDIR /workspace

CMD ["bash"]
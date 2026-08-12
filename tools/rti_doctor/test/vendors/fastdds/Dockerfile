FROM ubuntu:22.04

ARG FASTDDS_VERSION=v3.6.2
ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential ca-certificates cmake git libasio-dev libfoonathan-memory-dev libssl-dev libtinyxml2-dev openjdk-17-jdk \
    && rm -rf /var/lib/apt/lists/*

RUN git clone --depth 1 --branch ${FASTDDS_VERSION} \
    https://github.com/eProsima/Fast-DDS.git /src/Fast-DDS \
    && cmake -S /src/Fast-DDS -B /build -DCMAKE_BUILD_TYPE=Release -DTHIRDPARTY=ON \
    && cmake --build /build -j"$(nproc)" \
    && cmake --install /build \
    && cmake -S /src/Fast-DDS/examples/cpp/hello_world -B /example-build \
    && cmake --build /example-build -j"$(nproc)"

RUN git clone --depth 1 --branch v4.3.0 --recurse-submodules \
        https://github.com/eProsima/Fast-DDS-Gen.git /src/Fast-DDS-Gen \
    && cd /src/Fast-DDS-Gen \
    && ./gradlew install --install_path /usr/local

COPY CMakeLists.txt ExtensibilityEndpoint.cpp /doctor-extensibility/
COPY final /doctor-extensibility/final/
COPY appendable /doctor-extensibility/appendable/

RUN mkdir -p /doctor-extensibility/generated/final /doctor-extensibility/generated/appendable \
    && fastddsgen -d /doctor-extensibility/generated/final /doctor-extensibility/final/Sample.idl \
    && fastddsgen -d /doctor-extensibility/generated/appendable /doctor-extensibility/appendable/Sample.idl \
    && cmake -S /doctor-extensibility -B /doctor-extensibility-build -DCMAKE_BUILD_TYPE=Release \
    && cmake --build /doctor-extensibility-build -j"$(nproc)"

ENTRYPOINT ["/example-build/hello_world"]
CMD ["publisher", "--samples", "0"]
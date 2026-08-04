FROM ubuntu:22.04

ARG FASTDDS_VERSION=v2.14.6
ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential ca-certificates cmake git libasio-dev libfoonathan-memory-dev libssl-dev libtinyxml2-dev \
    && rm -rf /var/lib/apt/lists/*

RUN git clone --depth 1 --branch ${FASTDDS_VERSION} \
    https://github.com/eProsima/Fast-DDS.git /src/Fast-DDS \
    && cmake -S /src/Fast-DDS -B /build -DCMAKE_BUILD_TYPE=Release -DTHIRDPARTY=ON \
    && cmake --build /build -j"$(nproc)" \
    && cmake --install /build \
    && cmake -S /src/Fast-DDS/examples/cpp/dds/HelloWorldExample -B /example-build \
    && cmake --build /example-build -j"$(nproc)"

COPY CMakeLists.txt ExtensibilityEndpoint.cpp /doctor-extensibility/

RUN mkdir -p /doctor-extensibility/generated \
    && cp /src/Fast-DDS/examples/cpp/dds/ContentFilteredTopicExample/HelloWorld* \
          /doctor-extensibility/generated/ \
    && cp /src/Fast-DDS/examples/cpp/dds/HelloWorldExample/HelloWorldv1.* \
          /src/Fast-DDS/examples/cpp/dds/HelloWorldExample/HelloWorldCdrAux.* \
          /doctor-extensibility/generated/ \
    && cmake -S /doctor-extensibility -B /doctor-extensibility-build -DCMAKE_BUILD_TYPE=Release \
    && cmake --build /doctor-extensibility-build -j"$(nproc)"

ENTRYPOINT ["/example-build/DDSHelloWorldExample"]
CMD ["publisher", "--samples", "0", "--interval", "100"]
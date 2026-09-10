# (c) Copyright, Real-Time Innovations, 2026.  All rights reserved.
# RTI grants Licensee a license to use, modify, compile, and create derivative
# works of the software solely for use with RTI Connext DDS. Licensee may
# redistribute copies of the software provided that all such copies are subject
# to this license. The software is provided "as is", with no warranty of any
# type, including any warranty for fitness for any purpose. RTI is under no
# obligation to maintain or support the software. RTI shall not be liable for
# any incidental or consequential damages arising out of the use or inability
# to use the software.
cmake_minimum_required(VERSION 3.16)
project(DoctorFastDdsExtensibility LANGUAGES CXX)

find_package(fastcdr REQUIRED)
find_package(fastdds 3 REQUIRED)

function(add_extensibility_endpoint extensibility)
  set(source_dir "${CMAKE_CURRENT_SOURCE_DIR}/generated/${extensibility}/doctor-extensibility/${extensibility}")

  add_executable(doctor_fastdds_${extensibility}
      ExtensibilityEndpoint.cpp
      "${source_dir}/SamplePubSubTypes.cxx"
      "${source_dir}/SampleTypeObjectSupport.cxx"
  )
  target_include_directories(doctor_fastdds_${extensibility} PRIVATE "${source_dir}")
  target_compile_features(doctor_fastdds_${extensibility} PRIVATE cxx_std_11)
  target_link_libraries(doctor_fastdds_${extensibility} fastdds fastcdr)
endfunction()

add_extensibility_endpoint(final)
add_extensibility_endpoint(appendable)
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
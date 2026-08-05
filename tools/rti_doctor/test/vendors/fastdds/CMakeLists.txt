cmake_minimum_required(VERSION 3.16)
project(DoctorFastDdsExtensibility LANGUAGES CXX)

find_package(fastcdr REQUIRED)
find_package(fastdds 3 REQUIRED)

function(replace_required source search replacement output description)
  string(FIND "${source}" "${search}" match_index)
  if(match_index EQUAL -1)
    message(FATAL_ERROR "Missing expected ${description}: ${search}")
  endif()
  string(REPLACE "${search}" "${replacement}" transformed "${source}")
  set(${output} "${transformed}" PARENT_SCOPE)
endfunction()

function(add_extensibility_endpoint extensibility)
  set(source_dir "${CMAKE_CURRENT_BINARY_DIR}/${extensibility}")
  file(MAKE_DIRECTORY "${source_dir}")
  foreach(file HelloWorld.hpp HelloWorldCdrAux.hpp HelloWorldCdrAux.ipp
               HelloWorldPubSubTypes.hpp HelloWorldPubSubTypes.cxx
               HelloWorldTypeObjectSupport.hpp HelloWorldTypeObjectSupport.cxx)
    configure_file("${CMAKE_CURRENT_SOURCE_DIR}/generated/${file}"
                   "${source_dir}/${file}" COPYONLY)
  endforeach()
  file(READ "${source_dir}/HelloWorldPubSubTypes.cxx" pubsub_source)
  replace_required("${pubsub_source}" "set_name(\"HelloWorld\")"
                   "set_name(\"DoctorExtensibility::Sample\")" pubsub_source
                   "generated PubSub type name")
  file(WRITE "${source_dir}/HelloWorldPubSubTypes.cxx" "${pubsub_source}")
  file(READ "${source_dir}/HelloWorldTypeObjectSupport.cxx" type_object_source)
  replace_required("${type_object_source}" "\"HelloWorld\""
                   "\"DoctorExtensibility::Sample\"" type_object_source
                   "generated TypeObject type name")
  if(extensibility STREQUAL "final")
    replace_required("${type_object_source}" "ExtensibilityKind::APPENDABLE"
                     "ExtensibilityKind::FINAL" type_object_source
                     "FINAL TypeObject flag")
  else()
    string(FIND "${type_object_source}" "ExtensibilityKind::APPENDABLE" appendable_index)
    if(appendable_index EQUAL -1)
      message(FATAL_ERROR "APPENDABLE TypeObject flag is missing")
    endif()
  endif()
  file(WRITE "${source_dir}/HelloWorldTypeObjectSupport.cxx" "${type_object_source}")

  add_executable(doctor_fastdds_${extensibility}
      ExtensibilityEndpoint.cpp
      "${source_dir}/HelloWorldPubSubTypes.cxx"
      "${source_dir}/HelloWorldTypeObjectSupport.cxx")
  target_include_directories(doctor_fastdds_${extensibility} PRIVATE "${source_dir}")
  target_compile_features(doctor_fastdds_${extensibility} PRIVATE cxx_std_11)
  target_link_libraries(doctor_fastdds_${extensibility} fastdds fastcdr)
endfunction()

add_extensibility_endpoint(final)
add_extensibility_endpoint(appendable)
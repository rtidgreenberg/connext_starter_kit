/*
 * (c) Copyright, Real-Time Innovations, 2025.  All rights reserved.
 * RTI grants Licensee a license to use, modify, compile, and create derivative
 * works of the software solely for use with RTI Connext DDS. Licensee may
 * redistribute copies of the software provided that all such copies are subject
 * to this license. The software is provided "as is", with no warranty of any
 * type, including any warranty for fitness for any purpose. RTI is under no
 * obligation to maintain or support the software. RTI shall not be liable for
 * any incidental or consequential damages arising out of the use or inability
 * to use the software.
 */

#ifndef DDS_PARAMETER_SETUP_HPP
#define DDS_PARAMETER_SETUP_HPP

/*
 * Convenience header that includes all parameter setup components:
 *   - DDSParameterUtils:         Static utilities (make_parameter, load_from_yaml, etc.)
 *   - DDSServerParameterSetup:   Parameter server with async handlers
 *   - DDSClientParameterSetup:   Parameter client with requesters
 */

#include "DDSParameterUtils.hpp"
#include "DDSServerParameterSetup.hpp"
#include "DDSClientParameterSetup.hpp"

#endif // DDS_PARAMETER_SETUP_HPP

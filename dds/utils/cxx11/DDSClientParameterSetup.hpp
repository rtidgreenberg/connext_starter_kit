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

#ifndef DDS_CLIENT_PARAMETER_SETUP_HPP
#define DDS_CLIENT_PARAMETER_SETUP_HPP

#include <rti/rti.hpp>

#include <string>
#include <vector>
#include <atomic>
#include <mutex>
#include <condition_variable>
#include <functional>
#include <iostream>
#include <stdexcept>

#include "DDSParticipantSetup.hpp"
#include "DDSReaderSetup.hpp"
#include "DDSWriterSetup.hpp"
#include "DDSParameterUtils.hpp"
#include "ExampleTypes.hpp"
#include "Definitions.hpp"

using namespace rti::all;

/*
 * DDSClientParameterSetup
 * 
 * Parameter client using simple pub/sub:
 *   - Writers publish requests to any server (servers filter on node_id)
 *   - Readers receive responses and filter on request_id
 *   - Single set of endpoints for all target nodes
 * 
 * Usage:
 *   DDSClientParameterSetup client(participant, event_callback);
 *   client.set_parameters("robot1", params);
 *   client.set_parameters("robot2", other_params);
 */
class DDSClientParameterSetup {
public:
    using ParameterEventCallback = std::function<void(const example_types::ParameterEvent&)>;

    /**
     * Create a parameter client.
     * Sets up writers/readers for parameter services.
     * 
     * @param participant_setup  Shared participant with AsyncWaitSet
     * @param event_callback     Optional callback for ParameterEvent notifications
     * @param qos_profile        QoS profile for pub/sub
     */
    explicit DDSClientParameterSetup(
            std::shared_ptr<DDSParticipantSetup>& participant_setup,
            ParameterEventCallback event_callback = nullptr,
            const std::string& qos_profile = qos_profiles::ASSIGNER)
        : _participant_setup(participant_setup),
          _qos_profile(qos_profile),
          _event_callback(event_callback),
          _next_request_id(1)
    {
        setup_endpoints();
        std::cout << "[DDSClientParameterSetup] Ready" << std::endl;
    }

    //--------------------------------------------------------------------------
    // Remote Parameter Operations
    //--------------------------------------------------------------------------

    /**
     * Set parameters on a remote node.
     * @throws std::runtime_error if no response received within timeout
     */
    example_types::SetParametersResponse set_parameters(
        const std::string& target_node,
        const std::vector<example_types::Parameter>& params,
        const dds::core::Duration& timeout = dds::core::Duration::from_secs(5))
    {
        uint64_t req_id = _next_request_id++;
        
        example_types::SetParametersRequest request;
        request.node_id(target_node);
        request.request_id(req_id);
        for (const auto& p : params) {
            request.parameters().push_back(p);
        }

        // Send request
        _set_request_writer->writer().write(request);
        
        // Wait for response with matching request_id
        return wait_for_response<example_types::SetParametersResponse>(
            _set_response_reader->reader(), req_id, target_node, timeout);
    }

    example_types::SetParametersResponse set_parameters(
        const std::string& target_node,
        std::initializer_list<example_types::Parameter> params,
        const dds::core::Duration& timeout = dds::core::Duration::from_secs(5))
    {
        return set_parameters(target_node, std::vector<example_types::Parameter>(params), timeout);
    }

    /**
     * Get parameters from a remote node.
     * @throws std::runtime_error if no response received within timeout
     */
    std::vector<example_types::Parameter> get_parameters(
        const std::string& target_node,
        const std::vector<std::string>& names,
        const dds::core::Duration& timeout = dds::core::Duration::from_secs(5))
    {
        uint64_t req_id = _next_request_id++;
        
        example_types::GetParametersRequest request;
        request.node_id(target_node);
        request.request_id(req_id);
        for (const auto& n : names) {
            request.names().push_back(n);
        }

        _get_request_writer->writer().write(request);
        
        auto response = wait_for_response<example_types::GetParametersResponse>(
            _get_response_reader->reader(), req_id, target_node, timeout);
        
        std::vector<example_types::Parameter> results;
        for (const auto& p : response.parameters()) {
            results.push_back(p);
        }
        return results;
    }

    std::vector<example_types::Parameter> get_parameters(
        const std::string& target_node,
        std::initializer_list<std::string> names,
        const dds::core::Duration& timeout = dds::core::Duration::from_secs(5))
    {
        return get_parameters(target_node, std::vector<std::string>(names), timeout);
    }

    /**
     * List parameters on a remote node.
     * @throws std::runtime_error if no response received within timeout
     */
    std::vector<std::string> list_parameters(
        const std::string& target_node,
        const std::vector<std::string>& prefixes = {},
        uint32_t depth = 0,
        const dds::core::Duration& timeout = dds::core::Duration::from_secs(5))
    {
        uint64_t req_id = _next_request_id++;
        
        example_types::ListParametersRequest request;
        request.node_id(target_node);
        request.request_id(req_id);
        request.depth(depth);
        for (const auto& p : prefixes) {
            request.prefixes().push_back(p);
        }

        _list_request_writer->writer().write(request);
        
        auto response = wait_for_response<example_types::ListParametersResponse>(
            _list_response_reader->reader(), req_id, target_node, timeout);
        
        std::vector<std::string> results;
        for (const auto& n : response.names()) {
            results.push_back(std::string(n));
        }
        return results;
    }

private:
    template<typename ResponseType>
    ResponseType wait_for_response(
        dds::sub::DataReader<ResponseType> reader,
        uint64_t request_id,
        const std::string& target_node,
        const dds::core::Duration& timeout)
    {
        auto deadline = std::chrono::steady_clock::now() + 
            std::chrono::seconds(timeout.sec()) + 
            std::chrono::nanoseconds(timeout.nanosec());
        
        while (std::chrono::steady_clock::now() < deadline) {
            auto samples = reader.take();
            for (const auto& sample : samples) {
                if (sample.info().valid() && 
                    sample.data().request_id() == request_id &&
                    std::string(sample.data().node_id()) == target_node) {
                    return sample.data();
                }
            }
            std::this_thread::sleep_for(std::chrono::milliseconds(10));
        }
        
        throw std::runtime_error("No response from node '" + target_node + "' - timeout");
    }

    void setup_endpoints()
    {
        // Request writers
        _set_request_writer = std::make_shared<DDSWriterSetup<example_types::SetParametersRequest>>(
            _participant_setup, topics::SET_PARAMETERS_REQUEST_TOPIC, _qos_profile);
        _get_request_writer = std::make_shared<DDSWriterSetup<example_types::GetParametersRequest>>(
            _participant_setup, topics::GET_PARAMETERS_REQUEST_TOPIC, _qos_profile);
        _list_request_writer = std::make_shared<DDSWriterSetup<example_types::ListParametersRequest>>(
            _participant_setup, topics::LIST_PARAMETERS_REQUEST_TOPIC, _qos_profile);
        
        // Response readers (no async handler - we poll in wait_for_response)
        _set_response_reader = std::make_shared<DDSReaderSetup<example_types::SetParametersResponse>>(
            _participant_setup, topics::SET_PARAMETERS_RESPONSE_TOPIC, _qos_profile);
        _get_response_reader = std::make_shared<DDSReaderSetup<example_types::GetParametersResponse>>(
            _participant_setup, topics::GET_PARAMETERS_RESPONSE_TOPIC, _qos_profile);
        _list_response_reader = std::make_shared<DDSReaderSetup<example_types::ListParametersResponse>>(
            _participant_setup, topics::LIST_PARAMETERS_RESPONSE_TOPIC, _qos_profile);
        
        // Event subscriber
        _event_reader = std::make_shared<DDSReaderSetup<example_types::ParameterEvent>>(
            _participant_setup, topics::PARAMETER_EVENTS_TOPIC, _qos_profile);
        
        if (_event_callback) {
            _event_reader->set_data_available_handler(
                [this](dds::sub::DataReader<example_types::ParameterEvent>& reader) {
                    auto samples = reader.take();
                    for (const auto& sample : samples) {
                        if (sample.info().valid() && _event_callback) {
                            _event_callback(sample.data());
                        }
                    }
                });
        }
    }

private:
    std::shared_ptr<DDSParticipantSetup> _participant_setup;
    std::string _qos_profile;
    ParameterEventCallback _event_callback;
    std::atomic<uint64_t> _next_request_id;

    // Request writers
    std::shared_ptr<DDSWriterSetup<example_types::SetParametersRequest>> _set_request_writer;
    std::shared_ptr<DDSWriterSetup<example_types::GetParametersRequest>> _get_request_writer;
    std::shared_ptr<DDSWriterSetup<example_types::ListParametersRequest>> _list_request_writer;
    
    // Response readers
    std::shared_ptr<DDSReaderSetup<example_types::SetParametersResponse>> _set_response_reader;
    std::shared_ptr<DDSReaderSetup<example_types::GetParametersResponse>> _get_response_reader;
    std::shared_ptr<DDSReaderSetup<example_types::ListParametersResponse>> _list_response_reader;
    
    // Event subscriber
    std::shared_ptr<DDSReaderSetup<example_types::ParameterEvent>> _event_reader;
};

#endif // DDS_CLIENT_PARAMETER_SETUP_HPP

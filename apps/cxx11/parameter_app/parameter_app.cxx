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

#include <iostream>
#include <thread>
#include <chrono>

#include <rti/rti.hpp>
#include <rti/distlogger/DistLogger.hpp>
#include <rti/config/Logger.hpp>

#include "application.hpp"

// Enable YAML support before including DDSParameterSetup
#define DDS_PARAMETER_YAML_SUPPORT
#include "DDSParameterSetup.hpp"

using namespace rti::all;
using namespace rti::dist_logger;

constexpr int ASYNC_WAITSET_THREADPOOL_SIZE = 5;
const std::string APP_NAME = "Parameter App";

void run_server(
    std::shared_ptr<DDSParticipantSetup> participant_setup,
    const std::string& params_file,
    const std::string& node_name)
{
    auto& rti_logger = rti::config::Logger::instance();
    
    // Create server - all setup done in constructor
    DDSServerParameterSetup server(participant_setup, node_name);
    
    // Load and set parameters - auto-publishes ParameterEvent
    auto initial_params = DDSParameterUtils::load_from_yaml(params_file);
    server.set_parameters(initial_params);
    std::cout << "[SERVER] Loaded " << server.parameter_count() 
              << " parameters from " << params_file << std::endl;
    
    rti_logger.notice(("Parameter Server '" + node_name + "' running (async). Press Ctrl+C to stop.").c_str());
    
    // Wait for shutdown - all requests handled async in background
    while (!application::shutdown_requested) {
        std::this_thread::sleep_for(std::chrono::milliseconds(500));
    }
    
    rti_logger.notice("Parameter Server stopped");
}

void run_client(
    std::shared_ptr<DDSParticipantSetup> participant_setup,
    const std::string& params_file,
    const std::string& target_service)
{
    auto& rti_logger = rti::config::Logger::instance();
    
    // Create client - requesters created on-demand per target node
    DDSClientParameterSetup client(
        participant_setup,
        [](const example_types::ParameterEvent& event) {
            std::cout << "[PARAM_EVENT] From node: " << event.node_id() << std::endl;
            for (const auto& p : event.new_parameters()) {
                std::cout << "  NEW: " << p.name() << std::endl;
            }
            for (const auto& p : event.changed_parameters()) {
                std::cout << "  CHANGED: " << p.name() << std::endl;
            }
            for (const auto& p : event.deleted_parameters()) {
                std::cout << "  DELETED: " << p.name() << std::endl;
            }
        });
    
    // Load parameters from YAML to send
    auto params_to_set = DDSParameterUtils::load_from_yaml(params_file);
    std::cout << "[CLIENT] Loaded " << params_to_set.size() << " parameters to send" << std::endl;
    
    rti_logger.notice(("Parameter Client connecting to '" + target_service + "'. Press Ctrl+C to stop.").c_str());
    
    // Wait for discovery
    std::this_thread::sleep_for(std::chrono::seconds(2));
    
    try {
        // 1. List all parameters on the server
        std::cout << "\n=== LIST PARAMETERS ===" << std::endl;
        auto names = client.list_parameters(target_service);
        std::cout << "[LIST] Found " << names.size() << " parameters on " << target_service << ":" << std::endl;
        for (const auto& name : names) {
            std::cout << "  - " << name << std::endl;
        }
        
        // 2. Get specific parameters
        std::cout << "\n=== GET PARAMETERS ===" << std::endl;
        if (!names.empty()) {
            auto fetched = client.get_parameters(target_service, names);
            std::cout << "[GET] Retrieved " << fetched.size() << " parameters:" << std::endl;
            for (const auto& p : fetched) {
                std::cout << "  " << p.name() << " = " << DDSParameterUtils::type_to_string(DDSParameterUtils::get_type(p)) << std::endl;
            }
        }
        
        // 3. Set parameters
        std::cout << "\n=== SET PARAMETERS ===" << std::endl;
        if (!params_to_set.empty()) {
            auto response = client.set_parameters(target_service, params_to_set);
            
            std::cout << "[SET] Response from: " << response.node_id() << std::endl;
            int i = 0;
            for (const auto& result : response.results()) {
                std::cout << "  Result[" << i++ << "]: " 
                          << (result.successful() ? "SUCCESS" : "FAILED")
                          << (result.reason().size() > 0 ? " - " + std::string(result.reason()) : "")
                          << std::endl;
            }
        }
    } catch (const std::exception& e) {
        std::cerr << "[ERROR] " << e.what() << std::endl;
    }
    
    // Keep running to receive ParameterEvent broadcasts
    while (!application::shutdown_requested) {
        std::this_thread::sleep_for(std::chrono::milliseconds(500));
    }
    
    rti_logger.notice("Parameter Client stopped");
}

int main(int argc, char *argv[])
{
    using namespace application;

    auto arguments = parse_arguments(argc, argv);
    if (arguments.parse_result == ParseReturn::exit) {
        return EXIT_SUCCESS;
    } else if (arguments.parse_result == ParseReturn::failure) {
        return EXIT_FAILURE;
    }
    setup_signal_handlers();

    std::string service_name = arguments.server_mode ? arguments.node_name : arguments.target_name;

    try {
        auto participant_setup = std::make_shared<DDSParticipantSetup>(
            arguments.domain_id,
            ASYNC_WAITSET_THREADPOOL_SIZE,
            arguments.qos_file_path,
            qos_profiles::DEFAULT_PARTICIPANT,
            APP_NAME);

        // Setup Distributed Logger
        DistLoggerOptions options;
        options.domain_participant(participant_setup->participant());
        options.application_kind(APP_NAME);       
        DistLogger::set_options(options);
        auto& dist_logger = DistLogger::get_instance();
        dist_logger.set_verbosity(rti::config::LogCategory::user, arguments.verbosity);
        dist_logger.set_filter_level(dist_logger.get_info_log_level());

        if (arguments.server_mode) {
            run_server(participant_setup, arguments.params_file_path, service_name);
        } else {
            run_client(participant_setup, arguments.params_file_path, service_name);
        }
        
        DistLogger::get_instance().finalize();
        
    } catch (const std::exception& ex) {
        std::cerr << "Exception: " << ex.what() << std::endl;
        return EXIT_FAILURE;
    }

    dds::domain::DomainParticipant::finalize_participant_factory();
    return EXIT_SUCCESS;
}

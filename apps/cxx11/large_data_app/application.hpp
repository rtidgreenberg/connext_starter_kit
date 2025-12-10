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

#ifndef APPLICATION_HPP
#define APPLICATION_HPP

#include <iostream>
#include <csignal>
#include <string>
#include <dds/core/ddscore.hpp>
#include "Definitions.hpp"

namespace application {

    // Catch control-C and tell application to shut down
    bool shutdown_requested = false;

    inline void stop_handler(int)
    {
        shutdown_requested = true;
        std::cout << "preparing to shut down..." << std::endl;
    }

    inline void setup_signal_handlers()
    {
        signal(SIGINT, stop_handler);
        signal(SIGTERM, stop_handler);
    }

    enum class ParseReturn {
        ok,
        failure,
        exit
    };

    struct ApplicationArguments {
        ParseReturn parse_result;
        unsigned int domain_id;
        rti::config::Verbosity verbosity;
        std::string qos_file_path;

        ApplicationArguments(
            ParseReturn parse_result_param,
            unsigned int domain_id_param,
            rti::config::Verbosity verbosity_param,
            const std::string& qos_file_path_param)
            : parse_result(parse_result_param),
            domain_id(domain_id_param),
            verbosity(verbosity_param),
            qos_file_path(qos_file_path_param) {}
    };

    inline void set_verbosity(
        rti::config::Verbosity& verbosity,
        int verbosity_value)
    {
        switch (verbosity_value) {
            case 0:
            verbosity = rti::config::Verbosity::SILENT;
            break;
            case 1:
            verbosity = rti::config::Verbosity::EXCEPTION;
            break;
            case 2:
            verbosity = rti::config::Verbosity::WARNING;
            break;
            case 3:
            verbosity = rti::config::Verbosity::STATUS_ALL;
            break;
            default:
            verbosity = rti::config::Verbosity::EXCEPTION;
            break;
        }
    }

    // Parses application arguments for example.
    inline ApplicationArguments parse_arguments(int argc, char *argv[])
    {
        int arg_processing = 1;
        bool show_usage = false;
        ParseReturn parse_result = ParseReturn::ok;
        unsigned int domain_id = domains::DEFAULT_DOMAIN_ID;
        rti::config::Verbosity verbosity(rti::config::Verbosity::EXCEPTION);
        std::string qos_file_path = "../../../../dds/qos/DDS_QOS_PROFILES.xml"; // Default QoS file

        while (arg_processing < argc) {
            if ((argc > arg_processing + 1) 
            && (strcmp(argv[arg_processing], "-d") == 0
            || strcmp(argv[arg_processing], "--domain") == 0)) {
                domain_id = atoi(argv[arg_processing + 1]);
                arg_processing += 2;
            } else if ((argc > arg_processing + 1)
            && (strcmp(argv[arg_processing], "-v") == 0
            || strcmp(argv[arg_processing], "--verbosity") == 0)) {
                set_verbosity(verbosity, atoi(argv[arg_processing + 1]));
                arg_processing += 2;
            } else if ((argc > arg_processing + 1)
            && (strcmp(argv[arg_processing], "-q") == 0
            || strcmp(argv[arg_processing], "--qos-file") == 0)) {
                qos_file_path = argv[arg_processing + 1];
                arg_processing += 2;
            } else if (strcmp(argv[arg_processing], "-h") == 0
            || strcmp(argv[arg_processing], "--help") == 0) {
                std::cout << "Example I/O application with Command, Button, Config inputs and Position outputs." << std::endl;
                show_usage = true;
                parse_result = ParseReturn::exit;
                break;
            } else {
                std::cout << "Bad parameter." << std::endl;
                show_usage = true;
                parse_result = ParseReturn::failure;
                break;
            }
        }
        if (show_usage) {
            std::cout << "Usage:\n"\
            "    -d, --domain       <int>   Domain ID this application will\n" \
            "                               subscribe in.  \n"
            "                               Default: 1\n"\
            "    -v, --verbosity    <int>   How much debugging output to show.\n"\
            "                               Range: 0-3 \n"
            "                               Default: 1\n"
            "    -q, --qos-file     <str>   Path to QoS profile XML file.\n"\
            "                               Default: ../../../../dds/qos/DDS_QOS_PROFILES.xml"
            << std::endl;
        }

        return ApplicationArguments(parse_result, domain_id, verbosity, qos_file_path);
    }

}  // namespace application

#endif  // APPLICATION_HPP
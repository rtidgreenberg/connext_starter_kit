# Command Override Application

Demonstrates RTI Connext DDS advanced patterns including ownership strength control, and programmatic QoS modification.

## Features

- **Ownership Strength Control**: Priority-based command arbitration
- **Programmatic QoS**: Dynamic ownership strength changes at runtime
- **AsyncWaitSet Processing**: Event-driven command processing
- **Multiple Command Writers**: 3 writers with different strengths (10, 20, 30)

## Behavior

### Phase 1: Single Writer (10s)
- Writer 1 only (strength 10, START commands)

### Phase 2: Two Writers (10s)
- Writer 1 + Writer 2 (strength 20, PAUSE commands win)

### Phase 3: All Writers (10s)
- Writer 1 + Writer 2 + Writer 3 (strength 30, RESET commands win)

### Phase 4: Dynamic QoS (10s)
- All writers, Writer 1 strength changed to 50 (START commands win)

## Building

```bash
cd /home/rti/connext_starter_kit/apps/cxx11/command_override/build
make -j4
```

## Running

```bash
./command_override [OPTIONS]

Options:
  -d, --domain <int>    Domain ID (default: 1)
  -v, --verbosity <int> Verbosity 0-3 (default: 1)
  -q, --qos-file <str>  QoS XML path
  -h, --help           Show help
```

## Key Concepts

**Ownership Strength**: Multiple writers compete for same instance; higher strength wins
**Programmatic QoS**: Runtime modification of ownership strength without recreating entities

### 3. **AsyncWaitSet Event Processing**
- Non-blocking, event-driven message processing
- Efficient handling of high-frequency data updates

### 4. **Progressive Publishing Pattern**
- Systematic activation of additional data sources
- Useful for staged system bring-up scenarios

## File Structure

```
command_override/
├── command_override.cxx    # Main application logic
├── application.hpp        # Command line parsing utilities  
├── CMakeLists.txt        # Build configuration
├── README.md             # This file
└── build/                # Build output directory
    └── command_override   # Executable
```

## Dependencies

- **DDS Utilities Library**: `libdds_utils_datamodel.so`
- **RTI Connext DDS Core**: Core DDS functionality
- **RTI Extensions**: AsyncWaitSet and other advanced features
- **Generated Types**: ExampleTypes from IDL compilation

## Troubleshooting

### Common Issues
1. **Build Errors**: Ensure DDS library is built first (`make` in `dds/cxx11/build`)
2. **QoS Profile Not Found**: Check QoS file path and profile names
3. **Domain Connectivity**: Verify domain ID matches between instances
4. **Permission Errors**: Ensure proper file permissions for executable

### Debug Tips
- Use `-v 3` for maximum verbosity
- Check DDS_QOS_PROFILES.xml for profile definitions
- Monitor RTI Admin Console for DDS discovery issues
- Use timeout wrapper for controlled test runs: `timeout 30s ./command_override`

## Related Documentation

- [RTI Connext DDS User's Manual](https://community.rti.com/static/documentation/connext-dds/7.3.0/doc/manuals/connext_dds_professional/users_manual/index.htm)
- [C++ API Reference](https://community.rti.com/static/documentation/connext-dds/7.3.0/doc/api/connext_dds/api_cpp2/index.html)
- [QoS Provider Guide](https://community.rti.com/static/documentation/connext-dds/7.3.0/doc/manuals/connext_dds_professional/users_manual/index.htm#users_manual/QoS_Provider.htm)
- [Ownership QoS Policy](https://community.rti.com/static/documentation/connext-dds/7.3.0/doc/manuals/connext_dds_professional/users_manual/index.htm#users_manual/OWNERSHIP_QosPolicy.htm)

---

**Copyright © 2025 Real-Time Innovations, Inc. All rights reserved.**
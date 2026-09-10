# Uncommitted Worktree Review

## Scope

Review of the uncommitted worktree as of 2026-09-10. The worktree contains
substantive changes across 366 tracked files: 2,963 additions and 181
deletions. The review covered correctness, consistency, operator-facing
accuracy and clarity, and unnecessary complexity.

## Findings

### High

1. **Direct `rti_view` startup can miss the requested topic.**
   `tools/rti_view/rti_view/views/main_window.py` restricts direct-topic
   discovery to the first automatically selected participant. A requested
   topic published by another discovered participant is not auto-subscribed.
   Resolve direct topic requests across all discovered participants and add a
   multi-participant regression test.

2. **Changing an `rti_view` topic retains the prior subscription.**
   `tools/rti_view/rti_view/views/main_window.py` clears the selected topic's
   UI state without closing or replacing `self._subscription`. Samples from
   the previous topic can continue to display after a selection change. Close
   the subscription on topic changes or resubscribe immediately, with a
   regression test.

3. **External-type recording references the wrong generated XML location.**
   `services/recording_service_config_external_types.xml` includes
   `../dds/build/xml_gen/ExampleTypes.xml`, while CMake produces the file at
   `build/dds/xml_gen/ExampleTypes.xml`. The external-type recording workflow
   cannot locate its generated XML.

4. **Connext 7.3 uses the Connext 7.7 Python selection policy.**
   `scripts/python_env.sh` always selects the 7.7 resolver from
   `python_env_configure_for_connext_version()`, including when `NDDSHOME`
   points to Connext 7.3. This conflicts with the 7.3 test expectations in
   `scripts/test_python_env.sh` and can select an incompatible environment.

### Medium

5. **RS GUI scripts and documentation use obsolete virtual-environment paths.**
   RS GUI test runners, setup code, and manuals reference `connext_dds_env`
   or a fixed `py311` directory, while the shared resolver selects versioned
   environments such as `connext_dds_env_7.7_py312`. Affected files include
   `services/rs_gui/test/run_all_tests.py`, `services/rs_gui/setup.sh`,
   `services/rs_gui/README.md`, and `services/rs_gui/CLI_REFERENCE.md`.
   Route each workflow through the shared resolver or pass its resolved
   interpreter explicitly.

6. **Recording and conversion launchers require a specific working directory.**
   `services/start_record.sh` and `services/start_convert.sh` calculate
   `SCRIPT_DIR` but pass configuration paths relative to the caller's current
   directory. They fail when invoked from the repository root. Use paths based
   on `SCRIPT_DIR`, as `start_replay.sh` already does.

7. **DDS CMake options can leave application configuration broken.**
   `dds_typesupport` is conditional in `dds/CMakeLists.txt`, but applications
   link it unconditionally. Disabling documented generation options therefore
   leaves application targets unconfigurable. Enforce the prerequisites or
   make applications honor the options.

8. **The Docker Compose configuration exposes the host broadly.**
   `docker-compose.connext-7.7.yml` combines host networking with a
   read-write workspace mount into a root container. This gives build/test
   code access to host-network services and the entire repository. Prefer
   isolated networking and a narrower or read-only mount where practical.

9. **The Compose license mount prevents license-free image builds and can mask
   missing paths.**
   `docker-compose.connext-7.7.yml` requires `RTI_LICENSE_HOST_PATH` for
   build-oriented invocations even though the license is only needed at
   runtime. Its short mount syntax can turn a missing source file into a
   directory, producing a misleading container error. Make the runtime mount
   optional or profile-specific and use long bind-mount syntax with host-path
   creation disabled.

10. **`rti_view` does not validate plot-history values.**
    `tools/rti_view/rti_view/views/plot_view.py` constructs a bounded deque
    directly from `history_seconds * 20`. Negative values raise `ValueError`;
    zero creates a permanently empty plot. Validate that `--history` is
    positive or clamp it consistently with the interactive control.

### Low

11. **`rti_spy` documents the wrong interval default.**
    `tools/rti_spy/rtispy.py` says `--interval` defaults to `2.0`, while the
    argparse default is `10`. Align the help text and implementation.

12. **`rti_spy` installs a development dependency for end users.**
    `tools/rti_spy/requirements.txt` includes `textual-dev`, although runtime
    code requires only Textual. Move this dependency to development-only test
    tooling.

13. **The DDS README gives the wrong top-level build path.**
    From `dds/`, `dds/README.md` directs readers to `../../build/`; the
    repository build directory is `../build/`.

14. **The Docker build is not reproducible.**
    `docker/connext-7.7/Dockerfile` leaves the base image, OS packages, RTI
    repository key/packages, and Python dependency resolution unpinned. Pin
    image/package versions where practical, verify the repository-key
    fingerprint, and lock Python dependencies.

15. **The contributor guide uses an insecure CLA link.**
    `CONTRIBUTING.md` links to the CLA over HTTP and spells GitHub as
    "Github". Use the HTTPS URL and the standard product spelling.

## Validation

- `git diff --check` passed with no whitespace or conflict-marker errors.
- `bash -n` passed for 49 modified Bash scripts; one non-Bash `.sh` file was
  excluded.
- Focused `rti_view` and `rti_spy` Python tests could not run: the `py312`
  environment has a broken interpreter symlink, and the executable `py314`
  environment does not provide `rti.connextdds`.

## Suggested Repair Order

1. Fix the high-severity `rti_view`, recording XML, and Python-version
   resolver issues, adding focused tests for each behavioral change.
2. Make launchers, test runners, setup scripts, and their documentation use
   the same environment/path resolution contract.
3. Address Docker safety and reproducibility before encouraging use in shared
   development or CI environments.
4. Correct the remaining CLI and README inaccuracies while updating the
   affected workflows.

## Resolution Status

Updated 2026-09-10 after the review follow-up work.

- Resolved: findings 1-6 and 10-13. The `rti_view` subscription behavior,
   external recording XML path, Connext 7.7 Python policy, RS GUI resolver
   integration, service launcher paths, CLI text, and DDS documentation have
   been corrected.
- Resolved: finding 8. The workspace bind mount is read-only; host networking
   remains intentional for DDS discovery with host tools.
- Resolved: finding 9. Runtime tests use a license copied to the ignored
   `shared/` directory. Artifact-producing runs copy the read-only workspace to
   `/tmp` before execution.
- Resolved and validated: finding 5. The full Connext 7.7 Docker package
   supplies the six service IDLs required by RS GUI. The containerized RS GUI
   suite passed with 436 tests run, 34 skipped, and no failures.
- Resolved and validated: finding 7. A disabled C++ generation prerequisite
   fails during configuration with the intended explanation; the default
   Connext 7.7 container configuration builds all targets successfully.
- Deferred: finding 14 (Docker reproducibility).
- Resolved: finding 15. The contributor-guide CLA link now uses HTTPS and the
   GitHub spelling is correct.

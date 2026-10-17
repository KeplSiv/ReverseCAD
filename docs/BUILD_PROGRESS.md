# Build progress

## Working plan
1. Read complete specification and phone plan; inspect host and establish shared contracts.
2. Implement capture/replay, reconstruction, CAD, service reliability, and native UI in parallel.
3. Integrate production path; run independent geometry benchmarks, API/CAD/unit tests and repair failures.
4. Build/run dedicated Simulator, inspect screenshots, build unsigned device target.
5. Verify clean setup instructions and record exact evidence and remaining hardware gates.

## Evidence
- 2026-10-16: Read complete CODEX_BUILD_PROMPT, REVERSE_CAD_SPEC, PHONE_TEST_PLAN, research/SOURCES.
- Host: Apple silicon arm64, macOS 26.6.2 (25G83), Xcode 26.6 (17F113), XcodeGen 2.46.0; iOS 26.5 Simulator runtime available.
- Python system 3.9 unsuitable; installed uv-managed CPython 3.11.16 selected and pinned.
- Initial dependency installation required approval. Installation and subsequent frozen bootstrap completed; reports/bootstrap.log records 103 checked packages, synthetic sample generation and Xcode project generation. Full-access execution is now enabled.
- OPENAI_API_KEY absent from environment; no API-key provisioning tool exposed. Live provider remains blocked, not a passed test.
- No original implementation or applicable AGENTS.md in workspace ancestry. No relevant memory registry entry found.
- Build model setting is controlled by caller; this implementation does not claim to have changed the parent agent model.

## Final software outcome

- 167 Python tests, 15 shared Swift tests, 17 native unit tests and 2 actual-service UI workflows passed after fixing integration and STL precision failures.
- All 33 clean benchmark gates passed across 90 retained production stage runs; final source/input hashes matched.
- Latest unsigned iPhone build and dedicated Simulator build/install/launch passed. Actual screenshots and native downloads were inspected; both saved CAD revisions independently reimported successfully.
- Mac service is running in explicit LAN mode at `http://48.local:8767`, preserving `var/service`. Existing unrelated services were left untouched.
- See `reports/TEST_REPORT.md` for commands, logs, result bundle, screenshots and exact evidence. `PHONE_TEST_PLAN.md` covers the next physical trial.
- Live provider smoke remains blocked by the absent API key. Signed phone installation, real sensing/network/accuracy and printed fit remain untested.

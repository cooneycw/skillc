# Final capture controls

`cases.json` names the intact receipt and mutations of retained mailbox,
registry, raw remote, directory population, manifest and digest. Every mutation
runs after an independently checked intact baseline. UNKNOWN means evidence
was lost or changed; these controls do not authenticate agent messages.

`exports.json` drives DockerWave.close through healthy transfer, partial shared
or remote transfer, manifest publication loss and corruption before final
reporting. Cleanup is independently asserted in every case. The paired stopped
writer controls in `controls/docker-wave/final-capture.json` include unknown or
running roles, missing planned roles, and unknown or running fixture helpers.
Their healthy case requires stop, independent confirmation, then export order.

The helper-order and two helper-stop controls fail on checkpoint `03a593ec`;
the original role-stop controls fail on main `5d24a34`. These are model-free
lifecycle/custody controls, not physical Docker qualification or Git validity
proof. Empty observed roots, absent roots, unsupported entries, inventory bounds,
post-capture original deletion and retained permission changes have additional
direct controls in `tests/test_wave_capture.py`.

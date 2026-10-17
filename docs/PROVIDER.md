# Reasoning provider boundary

`backend/reversecad/reasoning.py` sends at most three resized selected RGB keyframes, one bounded oblique rendering of the actual reconstructed scan, bounded measurements, selected contacts, repair intent and the supported template catalog to the OpenAI Responses API. Images and descriptions are untrusted evidence. The response is a strict `RepairIntent` schema, followed by semantic checks for references, bounds, source, units, family and unchanged attachment method. A confirmed critical dimension cannot be changed. Model text is never executed. Trusted CadQuery code alone builds parts.

Manual mode is deterministic and uses no provider. Numeric design settings are labeled design inference until they reference an actual measurement record. Fixture mode is a deterministic intent fixture for exercising the same validator; it is not a recorded successful live response. HTTP adapter unit tests use an explicit mock transport only at the provider boundary.

Live mode needs `OPENAI_API_KEY` on the Mac and explicit app consent to send selected evidence. There was no configured key during the initial environment check. The phone stores only the service pairing token in Keychain. Keys are never included in the app, examples, reports or request logs. Configure them privately in `.env` (gitignored), then restart the service.

Defaults are model `gpt-6-astra`, reasoning `high`. Supported efforts are `low`, `medium`, `high`, `xhigh`, `max`; `ultra` is rejected as an API value. These were checked against [OpenAI's model documentation](https://developers.openai.com/api/docs/models/gpt-6-astra) and [Structured Outputs documentation](https://developers.openai.com/api/docs/guides/structured-outputs) on October 16, 2026. Account/model availability is only established by a successful live request.

A request has at most three attempts, each at most90 seconds and at most120 seconds total. Refusal, incomplete output, HTTP failure and transport failure stop explicitly; malformed/semantically invalid proposals can get two corrections. Workers impose an additional CPU, memory and wall-time limit. No provider key means only the live check is blocked.

After configuring a key, a real smoke test using the synthetic sample is:

```sh
.venv/bin/python scripts/trial_cli.py --live --family bridge_handle --output reports/live-provider
```

This explicitly sends the sample's selected images to OpenAI. A valid model response alone is insufficient: the script requires verified generated artifacts and independent STEP/STL reimport. Inspect the job's provider status and CAD validation. Do not interpret a mocked adapter test as live-provider success.

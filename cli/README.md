# cli/

User commands (`vm-claim`, `vm-extend`, `vm-release`, `vm-status`, `vm-run`,
`sim-start`, `sim-stop`). Code: `src/gpuboard_agent/cli/`. Installed as
console scripts by `pip install`.

## Claim commands

These commands use `/etc/gpuboard/agent.yaml` by default, or `--config PATH`
to select a config. The configured claim directory must already exist and
be writable by the users sharing claims. The intended group permissions are
described in the [install guide](../docs/README.md#permissions-model).

```sh
vm-claim --project gazebo --message "Testing" --duration 4h
vm-extend 90m
vm-release
```

Durations use minutes (`m`), hours (`h`), or days (`d`), with optional
decimals, e.g. `1.5h`. They must be at least one second. A claim's default
duration is `default_claim_hours` in the configuration.

`vm-claim` uses the invoking Linux account. It can replace an automatic claim,
but will not replace a manual, run, or planned claim, including an expired
manual or run claim. The owner can release it, or it can be removed by idle
cleanup once that feature is implemented. An owner may extend their own claim;
the duration is added to the existing end, or to the current time if expired.
`vm-release --force` permits release of another user's claim: ask first.

Claim updates use a persistent `.claim.json.lock` file alongside the claim
(named after the configured file). All future claim writers and cleanup must
take the same lock to prevent lost updates. This is coordination, not security
enforcement; users with directory access can modify the files directly.
Cleanup is not implemented yet. `vm-run` and `sim-start`/`sim-stop` are
deferred optional enhancements and are not implemented.

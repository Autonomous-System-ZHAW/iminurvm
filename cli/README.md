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
cleanup when enabled. An owner may extend their own claim;
the duration is added to the existing end, or to the current time if expired.
`vm-release --force` permits release of another user's claim: ask first.

Claim updates use a persistent `.claim.json.lock` file alongside the claim
(named after the configured file). All future claim writers and cleanup must
take the same lock to prevent lost updates. This is coordination, not security
enforcement; users with directory access can modify the files directly.
`vm-cleanup` and its timer remove expired claims only when no activity is
detected; see the [agent guide](../agent/README.md#expired-claim-cleanup)
for the exact checks and limitations. `vm-run` and `sim-start`/`sim-stop`
are deferred optional enhancements and are not implemented.

## Expired claims and blocked claims

An expired manual or run claim remains in the claim file until it is released
or cleanup removes it. `vm-claim` refuses to replace it, even for the current
owner. Cleanup may keep it indefinitely if it detects a closing login session
or a lingering VS Code server process, even if nobody is currently connected.
Cleanup must also be installed and enabled to run automatically.

If a claim blocks you:

1. Check the existing claim and ask its owner about any remaining work. Do not
   stop their processes or containers without asking.
2. The owner can extend it with `vm-extend 2h`, or release it with
   `vm-release` and then create a new claim.
3. If another user needs to release it, ask the owner first. After agreeing,
   `vm-release --force` removes the claim; a new claim can then be created
   with `vm-claim`. Releasing a claim does **not** stop workloads.

Use the same `--config PATH` on these commands if a non-default configuration
is in use.

The planned collector's status is based on observed activity, not whether the
claim file can be replaced:

- `CLAIM_EXPIRED`: the expired claim's owner has an observed session, VS Code
  process signal, or GPU process.
- `UNCLAIMED_USAGE`: the claim is expired and only other users have observed
  activity.
- `FREE`: the claim is expired and no activity is observed. The claim file
  may still exist during the grace period, while cleanup is disabled, or after
  a cleanup error, so `vm-claim` can still refuse a new claim.

These are status rules, not a live dashboard: the collector is not yet
implemented. The cleanup policy and this mismatch are future discussion items;
see [issue #4](https://github.com/Autonomous-System-ZHAW/iminurvm/issues/4).

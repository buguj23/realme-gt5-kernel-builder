# Local ROM build in Actions

`watch-local-rom.yml` attaches to the existing `bianyi-build.service` on the
laptop. It streams a sanitized log tail and memory, swap, disk, load and
pressure measurements every 15 seconds. Open **Stream local build (15s)** for
live updates; step summaries are snapshots uploaded when the step ends.

The workflow watches `infinity_ossi-userdebug`, Android 15, with the
Pure-OGKI 5.15.149 prebuilt kernel. A successful graph analysis, source sync,
or monitor startup does not count as a successful ROM build. The Actions job
succeeds only after the build state reports `completed / delivery_verified`.
It fails if the build fails, disappears without verified delivery, or is
replaced by a different systemd invocation. Stopping the monitor leaves the
separately managed local build running.

The runner uses only the custom `bianyi-monitor` label (no default labels),
and this workflow accepts manual dispatches by the repository owner on
`5.15.149`. It fetches only the monitor script's exact workflow commit from
GitHub through the local `127.0.0.1:7890` proxy. Source, kernel and ROM data
remain in the existing build directory. All runner files, credentials,
working files and logs are inside `bianyi/`; protect that directory.

After starting a local build, obtain its identity and dispatch the monitor:

```bash
invocation=$(systemctl --user show bianyi-build.service -p InvocationID --value)
gh workflow run watch-local-rom.yml --ref 5.15.149 -f invocation_id="$invocation"
```

The monitor API is also usable locally:

```bash
python3 scripts/rom-watch-local.py --root /path/to/bianyi \
  --invocation "$invocation" --report /path/to/bianyi/state/live.json --once
```

The progress counters printed by Soong/Ninja belong to their current build
step; they are not an overall ROM completion percentage. Full logs stay at
`bianyi/logs/build.log`; the monitor condenses large bursts to avoid flooding
the Actions interface. Subscription settings, proxy credentials and signing
keys are not part of the monitor input.

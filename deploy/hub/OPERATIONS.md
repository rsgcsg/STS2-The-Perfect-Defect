# Hub access and daily maintenance

This is the operator companion to the [deployment runbook](RUNBOOK.md), not another
deployment recipe. It defines the supported access and maintenance procedure; applying it
and recording fresh connection/service checks remain host operations. A source change does
not establish a new firewall, recovery route or monitoring service.

Collectors use the workbench and cloud login. Neither a project `member` nor a Hub browser
`admin` role grants SSH, a Unix account or `sudo`. Host operators separately hold the SSH key,
provider-console access and private recovery inventory. Cloudflare email OTP is not an Ubuntu
console password. Keep compute budget zero unless a separate campaign authorizes compute.

## One saved operator connection

Keep the exact VPS address, Unix user, SSH port, key path and verified server host-key
fingerprint in the operator's private inventory, outside Git. Use the actual deployment
configuration for state directories; `/srv/stpd/hub` in examples is not a discovery rule.
Record the current and previous compatible worker/Caddy digests, database schema, backup
receipt, source revision and external configuration recovery location there as well.

Use the operating system's OpenSSH client. An optional private `~/.ssh/config` entry makes
the daily command `ssh stpd-hub`; replace placeholders and verify the effective configuration
with `ssh -G stpd-hub` before using it. Keep the file/key private. Do not paste configuration
or verbose SSH logs into public issues. A passphrase-protected key must be unlocked locally
through the approved SSH agent before the noninteractive authentication below can succeed.

```sshconfig
Host stpd-hub
    HostName REPLACE_WITH_EXACT_VPS_ADDRESS
    User REPLACE_WITH_OPERATOR_UNIX_USER
    Port 22
    IdentityFile /ABS/PRIVATE/operator-key
    IdentitiesOnly yes
    PreferredAuthentications publickey
    PasswordAuthentication no
    KbdInteractiveAuthentication no
    BatchMode yes
    StrictHostKeyChecking yes
    ConnectTimeout 15
    ForwardAgent no
    ControlMaster no
    ControlPath none
```

Enroll the server host key only after comparing its fingerprint through the provider console
or existing protected inventory. `ssh-keyscan` alone is not identity verification. A changed
host key requires investigation, not deleting `known_hosts` or disabling checking. Inspect
any inherited proxy/identity configuration; this recipe requires no jump host, VPN or SSH
service inside Cloudflare. See the [OpenSSH client manual](https://man.openbsd.org/ssh) and
[client configuration](https://man.openbsd.org/ssh_config).

Use the established key-only server policy and preferably a non-root operator with sudo.
Client flags alone do not enforce server policy: inspect `sudo /usr/sbin/sshd -T` and its
connection-specific `-C` output for applicable `Match` blocks. Confirm public-key login is
enabled, password/keyboard-interactive login is disabled, and review any other enabled methods.
Do not rewrite the authentication stack just because a timeout occurred. Requiring
`AuthenticationMethods publickey` or further restricting root login is a separate controlled
change when needed, not an extra gate imposed on an already key-only installation.

If an actual configuration correction is required, first prove a fresh key-only login and
the required sudo access for the intended **non-root** operator before removing any existing
administrative route. If that account is absent, stop for separately authorized provisioning.
Keep the original session open, preserve its configuration privately, validate the proposed
configuration with `sudo /usr/sbin/sshd -t` and inspect effective values before reloading.
Prove a fresh connection after the reload before closing the original. A later-named drop-in
does not necessarily override an earlier value. Follow [Ubuntu's SSH procedure](https://ubuntu.com/server/docs/how-to/security/openssh-server/)
and [`sshd` validation options](https://man.openbsd.org/sshd).

## Change network without losing SSH

An allow rule for one public source IP follows that network exit address, not the laptop or
SSH key. A home-network change, mobile hotspot or local proxy can change it. HTTP egress IP
can differ from SSH egress; the successful server-side `SSH_CONNECTION` is the final check.
Public 80/443 are separate from operator-only TCP/22; 8765 stays loopback-only.

1. Keep the old working SSH session and its network route open. Arrange a second terminal
   on the intended new route, or another already-authorized host operator. Confirm the
   provider console is accessible and its independent Unix login is usable before changing
   access. Do not assume an existing SSH key can log into a password-only KVM prompt.
2. In the old session, inspect `sudo ufw status numbered` and the provider network firewall.
   Record the current exact source rule privately. Obtain the new SSH route's public address
   from trusted network configuration; add only that single IPv4 `/32` or IPv6 `/128`, never
   `0.0.0.0/0`, `::/0`, a guessed broad subnet or public `allow 22`.
3. Add the new rule without deleting the old one. The example uses a single literal address
   and the existing port 22; check the actual configured port first. Coordinate any required
   provider firewall change separately. These commands run on the Hub, not the laptop:

   ```bash
   STPD_NEW_SSH_SOURCE='REPLACE_WITH_NEW_PUBLIC_IP'
   python3 -c 'import ipaddress,sys; print(ipaddress.ip_address(sys.argv[1]))' "$STPD_NEW_SSH_SOURCE" &&
   sudo ufw --dry-run allow proto tcp from "$STPD_NEW_SSH_SOURCE" to any port 22 comment 'stpd operator'
   ```

   After address validation and dry-run review succeed:

   ```bash
   sudo ufw allow proto tcp from "$STPD_NEW_SSH_SOURCE" to any port 22 comment 'stpd operator'
   sudo ufw status numbered
   ```

   Stop if address validation or rule review fails. Do not change UFW defaults, reset UFW,
   disable it or flush rules. Existing sessions do not prove a new rule works.
4. From the new network, run `ssh -S none stpd-hub`. Connection sharing is disabled so this
   must authenticate a new connection. On that new session, inspect `printf '%s\n' "$SSH_CONNECTION"`,
   `id -un` and `sudo -n true`. The observed client address must match the new authorized
   address and the expected account/key must work. If sudo requires a local policy-approved
   password, test it interactively there; do not change sudo policy to make this check pass.
   Keep the old session/rule if any check fails.
5. Only after the new connection passes, remove the old exact rule through the new session.
   Re-read the current rule list first; if old and new addresses are identical, remove
   nothing. For the simple rule shape above, use
   `sudo ufw delete allow proto tcp from OLD_EXACT_PUBLIC_IP to any port 22` after replacing
   the placeholder. Match any original interface/destination restriction rather than deleting
   an unrelated rule number. Preserve other operators' separately authorized rules.
6. Verify another fresh connection from the new route after removal, then close the old
   session. Update the private inventory with the new source, timestamp and observed result.
   If validation fails, use the still-open authorized session to restore the old exact rule.

The [Ubuntu UFW manual](https://manpages.ubuntu.com/manpages/noble/man8/ufw.8.html) defines rule
syntax and deletion. No application login automatically changes either firewall.

## If the host becomes unreachable

Start with the saved exact address/port/key and the last successful source address. Compare
local routing/proxy changes and provider firewall state before changing the host. Preserve
the current working route/session when one exists.

| Observation | Next check |
|---|---|
| SSH timeout | destination, actual IP family/route, source-IP rules, provider network and host availability; a timeout does not prove an authentication failure |
| SSH host-key mismatch | compare the server identity with protected inventory/provider console; do not bypass host-key checking |
| `Permission denied (publickey)` | expected Unix user, selected/unlocked key and server authorization; do not enable password SSH |
| Website fails but SSH works | inspect Caddy/Hub health, DNS/TLS, current image and storage; avoid changing SSH rules |
| KVM shows Ubuntu `login:` | use the independently held Unix console credential; cloud account OTP and SSH private-key bytes are not that password |
| `No space left on device` | measure blocks and inodes on the failing filesystem; the service printing the error is not necessarily the disk consumer |

Use a retained allowed network or an authorized second operator first. Provider KVM is a
separate recovery route that must be tested and documented privately. If no console credential
exists, report that missing recovery capability explicitly. Provider password reset, rescue
boot or reboot are deliberate separately authorized recovery actions, not automatic responses
to an SSH timeout. A restart can discard the only usable session without repairing its cause.

## Daily check and before any deployment or build

Use the runbook's `dc` and `hubctl` helpers from the approved exact deployment checkout:

```bash
hubctl status
dc ps
sudo python3 /opt/stpd-deploy/source/deploy/hub/maintenance.py status --config /etc/stpd/deployment.env --image-store /ABS/ACTUAL/image-store
sudo systemctl list-timers stpd-backup.timer
df -h
df -i
sudo journalctl --disk-usage
sudo docker system df -v
sudo docker buildx du
```

Check public `/health` separately from browser login. Review pending verification age, real
upload failures, paused/zero-budget state, backup freshness and the host filesystem containing
the **configured** state directory. Missing/unreadable status is not PASS. Keep measurements
and incident output private; publish only redacted source/image identities and findings.

Replace `/ABS/ACTUAL/image-store` with the observed Docker/containerd image-store directory;
do not assume it is on the state filesystem. `maintenance.py status` is read-only, includes
the host capacity result, and exits nonzero for attention/unknown or unhealthy backup status.
Capacity pressure does not itself disable scheduled backups or restart the Hub. The web page
can observe its state filesystem; it cannot qualify a separate host image-store filesystem.

Before admitting a deployment/build, run the owning capacity check with explicitly estimated
additional peak **bytes and inodes**, including temporary build files/layers. Use `0` only for
a verified already-present exact image with no extra operation allocation; an unknown build
peak is not zero. Replace all placeholders with reviewed values:

```bash
sudo python3 deploy/hub/preflight.py --capacity --config /etc/stpd/deployment.env --image-store /ABS/ACTUAL/image-store --additional-bytes APPROVED_PEAK_BYTES --additional-inodes APPROVED_PEAK_INODES
sudo python3 deploy/hub/preflight.py --config /etc/stpd/deployment.env --host
```

Both checks must pass before proceeding. `--capacity` compares available space with the
owner-defined operating margin; it does not reserve disk or validate configuration, identity,
schema or service health. Remeasure just before the operation and coordinate concurrent builds.
The separate `--host` check and runbook qualification still apply. Do not lower the reserve
or hide an unavailable measurement to admit an operation.

On pressure, locate usage with `du -xhd1` on the large filesystem directories, then inspect
the largest child. If `df` and `du` disagree, inspect deleted-but-open files with `lsof +L1`
when available. A historical ENOSPC log does not establish that space is still exhausted;
record the current timestamp, available bytes and inodes. Docker layers can be shared and uv
cache files can be hard-linked to the installed environment; do not add their displayed sizes
and claim that sum is reclaimable disk space.

The default small production Hub is a service host, **not the default full dependency-build
machine**. A full worker build installs the research dependencies and can exceed its spare
disk even when the running service fits. Use an already-authorized separate builder when a
full dependency rebuild is needed; if none exists, report that build prerequisite instead of
silently purchasing compute or trying an oversized build on production. A source-only update
may use the existing [qualified-parent refresh](RUNBOOK.md#source-only-image-refresh-with-an-unchanged-dependency-lock)
only after the capacity check; the recipe must prove an unchanged lock and exact parent/new
source. It does not qualify the new service automatically.

Keep the current and one previous **compatible qualified rollback** image locally, together
with their exact image/config/schema/backup pairing. Older history stays in immutable registry
objects plus protected receipts after remote retrievability has been verified. Before removing
one specifically identified unused local image/cache record, check running/stopped containers,
active builds, qualification tasks and both retained digests. Record before/after physical free
space. Do not run broad `docker system prune -a --volumes`, delete Docker/containerd internals,
or remove all dangling images by habit; an untagged object may still be required for rollback.

Preserve Operations SQLite and its WAL/SHM, configured state and retired recovery directories,
external identity/configuration secrets, Caddy TLS state, backup receipts and raw/quarantined
evidence. Successful scheduled snapshots have their own verified-delete rule; failed/manual
snapshots require reviewed retention, not a blanket age rule. When space is critically low,
do not begin a large build, schema migration, vacuum or another full local backup before
freeing measured disposable space. `hubctl pause` pauses compute dispatch, **not upload
verification**; it is not a disk-write freeze. Follow the runbook to quiesce the actual writers
when recovery requires it, including any already-running backup container.

[Consistent backup](RUNBOOK.md#consistent-private-off-host-backup),
[restore](RUNBOOK.md#restore-into-paused-state) and schema migration remain owned by the runbook.
The backup service covers Operations SQLite, not the full host. Retain provider access, SSH
recovery and external secrets/TLS/configuration through the separate protected recovery
inventory. Prove an isolated compatible restore after schema/deployment changes. Until a
separately tested off-host alert channel exists, inspect status daily; neither the cloud page
nor a dead host can promise to notify the operator of its own outage.

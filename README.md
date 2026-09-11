# ZKTeco Agent — Attendance Bridge for Hosted Odoo 18

Standalone agent that reads punches from **ZKTeco biometric devices** on a local network and
pushes them to an **externally hosted Odoo 18** over outbound HTTPS.

```
ZKTeco device ──pyzk/LAN──> ZKTeco Agent ──XML-RPC/HTTPS──> Odoo (dnd_hr_biometric_attendance)
  192.168.x.x:4370          (client's Windows PC)            action_receive_punches
```

## Why this exists

`dnd_hr_biometric_attendance` normally connects **from Odoo to the device**. That only works
when Odoo sits on the same network. When Odoo is hosted (Hetzner, Odoo.sh, any VPS), the
device is behind NAT on a private address and Odoo can never reach it.

This agent inverts the direction. It runs inside the client's network, so:

- **No inbound firewall rule, no port forwarding, no VPN.**
- The device's private IP never leaves the LAN.
- On a shared multi-tenant Odoo server, one client's network gets **no** route to any other
  tenant — the agent authenticates as a normal Odoo user scoped to one database.

Devices reachable directly from Odoo do not need this agent: leave them on
`Connection Mode = Direct` and the built-in cron keeps working.

## What it does and does not do

Does: reads attendance punches and delivers them to Odoo, on a timer, idempotently.

Does **not**: write to the device. Card provisioning, user creation, fingerprint enrollment
and offboarding still require Odoo to reach the device directly.

## Odoo setup

### 1. Install the module

`dnd_hr_biometric_attendance` must be installed on the target database.

### 2. Create the agent user

Settings → Users. Create a dedicated user, for example `zkteco.agent`:

- Must have **Attendances / Administrator** (`hr_attendance.group_hr_attendance_manager`).
  Without it every punch is silently rejected by the access rules.
- Must be allocated to the **company that owns the device**. The module's record rules filter
  on company; a mismatch produces zero attendance with no error.
- Do not reuse a human's account. Attendance records will be attributed to this user.

### 3. Generate an API key

From the user's **Account Security → New API Key**.

> **Important:** Odoo 18 caps self-service API keys at the duration allowed by the user's
> groups (90 days by default). A key that expires stops attendance silently. For a permanent
> key, generate it from an administrator session, or run in `odoo shell`:
>
> ```python
> user = env['res.users'].search([('login', '=', 'zkteco.agent')], limit=1)
> key = env['res.users.apikeys'].with_user(user).sudo()._generate('rpc', 'zkteco agent key', None)
> print(key)
> env.cr.commit()
> ```
>
> The `.sudo()` is what allows an expiration of `None`. `with_user()` is what makes the key
> belong to the agent instead of the administrator.

### 4. Configure the device record

Biometric Devices → open the device:

- Set **Connection Mode** to `Remote Agent`. The download cron then skips this device
  instead of failing against an unreachable IP every 5 minutes.
- Fill **Serial Number** — this is how the agent identifies the device. If empty, connect once
  from the LAN and press *Get Device Info*, or read it from the device menu.
- Set **Timezone** to the device's own clock timezone. The agent sends raw device timestamps;
  Odoo converts to UTC using this field. Wrong timezone means punches land at the wrong hour.
- Link every employee to their device user ID (*Import from Device* or the link wizard).
  **Punches from unlinked users are counted and logged, but not recorded.**

## Agent installation (Windows)

Requires Python 3.10+ and network access to the device on port 4370.

```powershell
cd C:\zkteco-agent
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt

copy .env.example .env
notepad .env
notepad config\daemon.yml
```

Verify before installing the service:

```powershell
.venv\Scripts\python -m src.main
```

Expect `Authenticated as uid=...` then a per-device line each cycle. Stop with Ctrl+C.

### Run as a service with NSSM

A scheduled task is not enough — the agent must restart after a power cut.

```powershell
nssm install ZKTecoAgent "C:\zkteco-agent\.venv\Scripts\python.exe" "-m" "src.main"
nssm set ZKTecoAgent AppDirectory C:\zkteco-agent
nssm set ZKTecoAgent Start SERVICE_AUTO_START
nssm set ZKTecoAgent AppExit Default Restart
nssm start ZKTecoAgent
```

Logs rotate under `logs\zkteco_agent.log` (5 MB, 5 files).

## Configuration

`.env` holds credentials, `config/daemon.yml` holds devices and timing.

```yaml
daemon:
  poll_interval: 300        # seconds between cycles

devices:
  - name: Main Entrance
    serial_number: ABC1234567   # must match the Odoo device record
    ip: 192.168.1.201
    port: 4370
    password: 0
    timeout: 30
    force_udp: false          # true for K40 and some older firmwares
    ommit_ping: false         # true when ICMP is blocked but port 4370 is open
```

## How delivery stays safe

- **The device log is never cleared.** `clear_attendance()` is never called, so punches remain
  on the device as a recovery buffer. An agent outage of days loses nothing.
- **Replays are harmless.** Odoo enforces a unique constraint on
  `(device, device user, punch time)`. Re-sending stored punches creates nothing.
- **The cursor is an optimisation, not the safety net.** `state.json` records the last punch
  timestamp per device so each cycle only sends new records. Deleting it causes one larger
  batch, all rejected as duplicates. It advances only after Odoo confirms without error.
- **One dead device cannot block the others.** Each device is polled inside its own error
  boundary.

## Testing without hardware

`tools/zk_simulator.py` feeds synthetic punches through the real poller, Odoo client and
cursor store — everything except pyzk's device I/O.

```bash
.venv/bin/python tools/zk_simulator.py --users 7,8 --days 1 --dry-run   # print only
.venv/bin/python tools/zk_simulator.py --users 7,8 --days 1             # send to Odoo
```

## Troubleshooting

| Symptom | Cause |
|---|---|
| `can't reach device (ping ...)` | ICMP blocked. Set `ommit_ping: true`. |
| `timed out` / `failed to connect` | Port 4370 blocked, or a COMM key is set in the device menu. Clear it on the device. K40 and older firmware often need `force_udp: true`. |
| `Authentication rejected` | Wrong DB name, wrong login, or an expired API key. |
| Agent reports `stored 0` forever | Every punch already known — normal. |
| `punches for users not linked to any employee` | Those device user IDs have no `biometric.attendance.devices` link. Punches are discarded until linked. |
| Punches land at the wrong hour | Device record's **Timezone** does not match the device clock. |
| Attendance stops after ~90 days | The API key expired. Regenerate a persistent one (see above). |
| Nothing in `hr.attendance` but rows in `attendance.log` | The *Biometric: Calculate Attendance* cron is inactive in Odoo. |

`agent_last_seen` on the device record is stamped on every delivery — use it to confirm the
agent is alive.

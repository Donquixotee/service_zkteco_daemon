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

Settings → Users & Companies → **Users → New**:

- **Name** `ZKTeco Agent`, **Email / login** `zkteco.agent`
- Under **Access Rights**, set **Attendances** to **Administrator**
  (`hr_attendance.group_hr_attendance_manager`). Without it every punch is silently rejected
  by the access rules.
- Set **Company** to the company that owns the devices, and tick it under **Allowed
  Companies**. The module's record rules filter on company; a mismatch produces zero
  attendance with no error.
- Leave it as an *Internal User*. Do not reuse a human's account — attendance records are
  attributed to whoever the agent authenticates as.

### 3. Generate an API key

**Odoo 18 caps self-service API keys** at the duration allowed by the creating user's groups —
90 days by default. When the key expires the agent stops delivering and nothing in Odoo
explains why, so do not leave it on the default. Pick one:

**Option A — raise the cap for the group, then use the UI.** No server access needed.

1. Enable developer mode.
2. Settings → Users & Companies → **Groups** → open *Attendances / Administrator*.
3. Set **API Keys maximum duration days** to e.g. `3650`, save.
4. Log in **as `zkteco.agent`** → avatar → **My Profile → Account Security → New API Key**,
   pick a long duration, copy the key.

**Option B — a key with no expiry at all**, from `odoo shell` on the server:

```python
user = env['res.users'].search([('login', '=', 'zkteco.agent')], limit=1)
key = env['res.users.apikeys'].with_user(user).sudo()._generate('rpc', 'zkteco agent key', None)
print(key)
env.cr.commit()
```

`.sudo()` is what permits an expiration of `None`; `with_user()` is what makes the key belong
to the agent rather than to the administrator running the shell.

**Option C — accept 90 days** and diarise the rotation. Not recommended: the failure is
silent and lands on a client site.

The key is displayed **once**. Copy it straight into `.env`. Each Odoo database issues its own
keys — a key from a test database will not authenticate against production.

### 4. Configure the device record

Biometric Devices → open the device:

- Set **Punch Direction**. `Alternate` suits a single device used for both entering and
  leaving. With **separate entrance and exit readers**, set the entrance to `Always Check In`
  and the exit to `Always Check Out` — otherwise punches alternate per device and a person who
  enters on three consecutive days is recorded as in, out, in.
- Set **Connection Mode** to `Remote Agent`. The download cron then skips this device
  instead of failing against an unreachable IP every 5 minutes.
- Fill **Serial Number** — this is how the agent identifies the device. If empty, connect once
  from the LAN and press *Get Device Info*, or read it from the device menu.
- Set **Timezone** to the device's own clock timezone. The agent sends raw device timestamps;
  Odoo converts to UTC using this field. Wrong timezone means punches land at the wrong hour.
- Link every employee to their device user ID (*Import from Device* or the link wizard).
  **Punches from unlinked users are counted and logged, but not recorded.**

## Agent installation

The agent is pure Python with no platform-specific code. It runs on **Windows, Linux or
macOS** — only the service wrapper differs. Python 3.10+ and network access to the device on
port 4370 are the only requirements.

### Windows

Requires Python 3.10+ and network access to the device on port 4370.

Prerequisites on the client PC:

1. **Python 3.10+** from python.org — tick **"Add python.exe to PATH"** during install.
2. **NSSM** from https://nssm.cc/download — extract `win64\nssm.exe` to `C:\nssm\nssm.exe`.
3. The PC must reach the device on port 4370 and reach Odoo over HTTPS.

Copy the repository to `C:\zkteco-agent`, then configure:

```powershell
cd C:\zkteco-agent
copy .env.example .env
notepad .env                  # ODOO_URL, ODOO_DB, ODOO_USER_LOGIN, ODOO_API_KEY
notepad config\daemon.yml     # device ip, port and serial_number
```

**Run the preflight check before installing anything.** It verifies Odoo authentication,
performs a real handshake with each device, and confirms the serial number matches a device
record in Odoo:

```powershell
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python tools\preflight.py
```

Every line must say `PASS` before continuing. Then install the service:

```powershell
# from an Administrator PowerShell
.\deploy\install-windows.ps1
```

The script creates the virtualenv, installs dependencies, disables sleep and hibernation,
registers the service with auto-start and restart-on-failure, and starts it.

To run in the foreground instead (useful while diagnosing):

```powershell
.venv\Scripts\python -m src.main
```

Expect `Authenticated as uid=...` then a per-device line each cycle. Stop with Ctrl+C.

#### Without NSSM

If NSSM is not available on the machine, `deploy\install-task.ps1` registers the agent as a
Windows scheduled task instead. It checks the virtualenv and configuration, runs the preflight
check and refuses to install if it fails, disables sleep, then registers a task that starts at
boot as SYSTEM and restarts every minute if the agent exits.

```powershell
# Administrator PowerShell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force
.\deploy\install-task.ps1
```

Remove it again with `.\deploy\install-task.ps1 -Remove`.

#### Managing the service

```powershell
C:\nssm\nssm.exe status  ZKTecoAgent
C:\nssm\nssm.exe restart ZKTecoAgent
C:\nssm\nssm.exe stop    ZKTecoAgent
Get-Content C:\zkteco-agent\logs\zkteco_agent.log -Wait -Tail 30
```

Logs rotate under `logs\zkteco_agent.log` (5 MB, 5 files).

**Two things that silently break an always-on Windows PC:**

- **Sleep.** The install script disables standby and hibernation on AC power. If someone
  re-enables them, the agent stops collecting while asleep. Punches stay on the device, so
  nothing is lost, but attendance appears in bursts.
- **Windows Update reboots.** The service auto-starts, so this is survivable — but confirm
  `Startup type: Automatic` in `services.msc` after the first patch cycle.

### Linux

```bash
sudo useradd --system --home /opt/zkteco-agent zkteco
sudo mkdir -p /opt/zkteco-agent
sudo chown zkteco:zkteco /opt/zkteco-agent

sudo -u zkteco git clone <repo> /opt/zkteco-agent
cd /opt/zkteco-agent
sudo -u zkteco python3 -m venv .venv
sudo -u zkteco .venv/bin/pip install -r requirements.txt
sudo -u zkteco cp .env.example .env && sudo -u zkteco nano .env
```

Verify in the foreground first:

```bash
sudo -u zkteco .venv/bin/python -m src.main
```

Then install the unit shipped in `deploy/zkteco-agent.service`:

```bash
sudo cp deploy/zkteco-agent.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now zkteco-agent
sudo systemctl status zkteco-agent
journalctl -u zkteco-agent -f
```

`Restart=always` covers crashes and reboots. Leave `ZK_LOG_FILE` unset on Linux to log to
the journal instead of a file.

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

Two levels, neither of which needs a device.

**Unit tests** cover the device layer using real pyzk `Attendance` objects, so the
conversion, malformed-punch skipping and disconnect behaviour are verified without hardware:

```bash
.venv/bin/python -m unittest discover -s tests -v
```

**`tools/zk_simulator.py`** feeds synthetic punches through the real poller, Odoo client and
cursor store, exercising authentication, delivery, deduplication and the cursor:

```bash
.venv/bin/python tools/zk_simulator.py --users 7,8 --days 1 --dry-run   # print only
.venv/bin/python tools/zk_simulator.py --users 7,8 --days 1             # send to Odoo
```

It replaces `read_punches` entirely, so it is a punch injector rather than a device
simulator. **The pyzk wire protocol against real hardware is not covered by either.**
Connecting to an actual device on the LAN remains a required acceptance step — that is where
firmware quirks (`force_udp`, COMM keys, K40 behaviour) surface.

## Adding an employee later

Enrolling someone on a reader does **not** create them in Odoo. Punches from a device user who
is not linked to an employee are counted, logged and discarded. The order is always:

1. Create the employee in Odoo
2. Give them a badge number (`tools/assign_badges.py`)
3. Push them to the readers with **`tools/add_employee.py`**
4. They enrol a fingerprint at each reader

```powershell
.venv\Scripts\python tools\add_employee.py --login <admin> --name "NEW EMPLOYEE"
.venv\Scripts\python tools\add_employee.py --login <admin> --name "NEW EMPLOYEE" --apply
```

It appends the person at the next free uid and leaves everyone else untouched.

**Never re-run `provision_devices.py` on readers people have already enrolled on.** It assigns
uids by alphabetical position, and fingerprint templates are stored against the uid, so adding
one name near the start of the alphabet shifts everybody after it and their fingerprints end up
on the wrong people. The tool now refuses to do this unless `--wipe` or `--force-renumber` is
given.

## Field deployment

`docs/FIELD_TEST.md` is a step-by-step runbook for commissioning a site over remote access:
recon, read-only device probe, Odoo configuration, first controlled sync, then service install.

`tools/device_probe.py` inspects the devices without writing anything — serial, model,
firmware, device clock, user list and punch count. Run it before anything else on a new site.

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

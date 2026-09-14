# Field Test Runbook — Two K50 Readers over AnyDesk

Site as reported by the client:

| Role | IP | Port | Netmask | Gateway | DHCP |
|---|---|---|---|---|---|
| Entrance (IN) | 192.168.1.201 | 4370 | 255.255.255.0 | 0.0.0.0 | off |
| Exit (OUT) | 192.168.1.200 | 4370 | 255.255.255.0 | 0.0.0.0 | off |

Two things follow from that table before you touch anything:

- **Gateway is 0.0.0.0.** The readers have no default route, so they can only answer hosts on
  `192.168.1.0/24`. The agent PC *must* sit on that subnet. It also confirms these devices can
  never be reached from hosted Odoo, whatever the firewall does.
- **K50 is in the family the field reports flag.** If a plain connection fails, the fix is
  `force_udp: true` and/or `ommit_ping: true`, not more firewall work. Try these before
  concluding anything is broken.

## Phase 0 — Before the AnyDesk session

Decide and note down:

1. **Which reader is IN and which is OUT.** 201 = entrance = `punch_direction: in`,
   200 = exit = `punch_direction: out`. Getting this backwards silently inverts everyone's
   attendance. Confirm with the client, do not assume from the IP.
2. **The device timezone.** The K50 shows its own clock; Odoo needs the matching `time_zone`
   on each device record. A wrong value shifts every punch by hours.
3. **Employee ↔ device user IDs.** You need the mapping before any punch will be recorded.
   Phase 3 dumps what is actually on the devices.

## Phase 1 — Recon on the client PC (read-only, 10 minutes)

Open PowerShell over AnyDesk:

```powershell
ipconfig                        # must show a 192.168.1.x address
ping 192.168.1.201
ping 192.168.1.200
Test-NetConnection 192.168.1.201 -Port 4370
Test-NetConnection 192.168.1.200 -Port 4370
python --version                # 3.10+ ; if missing, install with "Add to PATH"
powercfg /query SCHEME_CURRENT SUB_SLEEP    # check the PC does not sleep
```

Record which of these fail. `ping` failing but port 4370 answering is normal on some
firmwares — that is exactly what `ommit_ping` is for.

> If `ipconfig` shows the PC on a different subnet (192.168.0.x, 10.x.x.x), stop. With no
> gateway on the readers, nothing will work until the PC is on `192.168.1.0/24`.

## Phase 1b — Install Python if it is missing

If `python --version` answers with *"Python est introuvable"* / *"Python was not found"* and
mentions the Microsoft Store, Python is **not installed** — that message comes from a Windows
stub alias, not from Python.

**Do not install from the Microsoft Store.** The Store build is sandboxed per user and its
paths are awkward for a Windows service. Use the official installer:

1. Download the **Windows installer (64-bit)** for Python 3.12 from
   https://www.python.org/downloads/windows/
2. On the first screen of the installer, tick **both**:
   - **Install launcher for all users**
   - **Add python.exe to PATH**
3. Choose **Customize installation → Next → tick "Install for all users"**, which puts it in
   `C:\Program Files\Python312`. This matters: the agent runs as a Windows service, and a
   per-user install under `AppData` is awkward for a service account to reach.
4. Close and reopen PowerShell, then confirm:

```powershell
python --version
where.exe python
```

`where.exe python` must show the real path, not `WindowsApps`. If it still shows
`WindowsApps\python.exe`, turn off the stub:
**Settings → Apps → Advanced app settings → App execution aliases**, and switch off
**python.exe** and **python3.exe**.

No internet on the client PC? Download the installer on your own machine and copy it over
AnyDesk's file transfer. You will also need the wheels for `pyzk`, `PyYAML` and
`python-dotenv` — run `pip download -r requirements.txt -d wheels` on a connected machine,
copy the `wheels` folder, and install with
`.venv\Scripts\pip install --no-index --find-links wheels -r requirements.txt`.

## Phase 2 — Install the agent, do not start the service yet

```powershell
# copy the repository to C:\zkteco-agent
cd C:\zkteco-agent
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
copy .env.example .env
notepad .env
```

Fill `.env` with the Odoo URL, database, `zkteco.agent` login and the **persistent** API key.

Then `notepad config\daemon.yml`:

```yaml
daemon:
  poll_interval: 300

devices:
  - name: Entrance
    serial_number: FILL_FROM_PHASE_3
    ip: 192.168.1.201
    port: 4370
    password: 0
    timeout: 30
    force_udp: false
    ommit_ping: false

  - name: Exit
    serial_number: FILL_FROM_PHASE_3
    ip: 192.168.1.200
    port: 4370
    password: 0
    timeout: 30
    force_udp: false
    ommit_ping: false
```

## Phase 3 — Probe the devices (read-only, this is the real test)

```powershell
.venv\Scripts\python tools\device_probe.py
```

`device_probe.py` only calls `get_serialnumber`, `get_device_name`, `get_firmware_version`,
`get_platform`, `get_time`, `get_users` and `get_attendance`. **It writes nothing and never
clears the device log.**

Expect per device: serial number, model, firmware, the device clock, a user list and a punch
count with oldest/newest timestamps.

**This is the moment the whole project has been waiting for** — it is the first time pyzk
touches real hardware.

If a device fails, work through this in order:

1. Set `ommit_ping: true` for that device, re-run. Fixes ICMP-filtered setups.
2. Set `force_udp: true` as well, re-run. This is the documented K40/K50-era workaround.
3. Raise `timeout` to 60.
4. On the device keypad, check **Comm → Security → COMM Key** (clé de communication). If it
   is non-zero, either clear it on the device or set the same number as `password:` in
   `daemon.yml`.

Record from the output:

- **Both serial numbers** — copy them into `daemon.yml` and into Odoo.
- **The device clock** versus real local time. A drifting clock means wrong punch times and
  no amount of Odoo configuration fixes it.
- **The user list** — `user_id` is the value that must go into each employee's biometric link
  in Odoo. Screenshot it.
- **The punch count.** A device holding thousands of old punches means your first sync will be
  large; that is fine and idempotent, but expect it.

## Phase 4 — Configure Odoo (from your machine, not the client PC)

Create **two** device records in `biometric.config`:

| Field | Entrance | Exit |
|---|---|---|
| Name | Entrance | Exit |
| Serial Number | from Phase 3 | from Phase 3 |
| Connection Mode | Remote Agent | Remote Agent |
| **Punch Direction** | **Always Check In** | **Always Check Out** |
| Timezone | device's real timezone | same |
| Device IP | 192.168.1.201 | 192.168.1.200 |

`Device IP` is ignored in agent mode but is still a required field. `Serial Number` is what
actually links the agent to the record.

### Linking employees in bulk

With a large staff list, do not create links by hand — an employee needs one link row **per
device**, so 122 employees across two readers is 244 rows.

On the client PC, once the device serials are in both `daemon.yml` and Odoo:

```powershell
.venv\Scripts\python tools\link_employees.py
```

This reads the user list from each device, pulls the active employees from Odoo, matches them
by name — ignoring case, accents, punctuation, word order and the device's 24-character
truncation — and writes `employee_links.csv` **without changing anything**.

Review that file. Rows marked `no match, map by hand` or `device user has no name` need an
`employee_id` filled in; you can find the id in Odoo's URL when the employee form is open.
Employees sharing an identical name are deliberately left unmatched rather than guessed.

Then apply it:

```powershell
.venv\Scripts\python tools\link_employees.py --from-csv employee_links.csv
```

Rows already linked are skipped, so it is safe to re-run after correcting the CSV.

## Phase 5 — Preflight

Back on the client PC:

```powershell
.venv\Scripts\python tools\preflight.py
```

Every line must read `PASS`. It authenticates to Odoo, performs a real handshake with each
device, and verifies each serial exists in Odoo in agent mode with a timezone set.

## Phase 6 — First controlled sync

Run one cycle in the foreground and watch it:

```powershell
.venv\Scripts\python -m src.main
```

Expect per device: `sent N, stored N, already known 0`. Let it complete one cycle, then
**Ctrl+C**.

Check in Odoo, *Attendance Logs*:

- Punches from the Entrance record are all **Check In**; from Exit all **Check Out**.
- Times match the wall-clock times the client expects, not shifted by hours.
- `Agent Last Seen` is populated on both device records.

Then have someone scan at each reader and re-run one cycle. The new punches should appear with
the correct direction.

**If you see `punches for users not linked to any employee`**, that is the mapping from
Phase 3 being incomplete. Those punches are skipped, not lost — fix the links and re-run with
`state.json` deleted; duplicates are rejected automatically.

## Phase 7 — Install the service

Only once Phase 6 is clean:

```powershell
# Administrator PowerShell
.\deploy\install-windows.ps1
C:\nssm\nssm.exe status ZKTecoAgent
Get-Content C:\zkteco-agent\logs\zkteco_agent.log -Wait -Tail 30
```

## Phase 8 — Leave it running, check the next day

- `Agent Last Seen` on both devices should be within the last 5 minutes.
- `hr.attendance` should show paired check-in/check-out for people who used both readers.
- Someone who only scanned at the entrance will have an open attendance. That is correct
  behaviour, not a bug.

## Safety rules for this session

- **Never run `clear_attendance()`.** The device log is the recovery buffer. Nothing in the
  agent calls it.
- **Do not use Odoo's write buttons** (Sync Employees, Delete from Device). In agent mode they
  refuse with a clear message; that is expected, not a fault.
- `device_probe.py` and `preflight.py` are read-only. `src.main` only reads from the device
  and writes to Odoo.
- Re-running anything is safe. Odoo rejects duplicate punches on
  `(device, device user, punch time)`.

## Rollback

Nothing on the devices is modified, so there is nothing to roll back there. To stop the agent:

```powershell
C:\nssm\nssm.exe stop ZKTecoAgent
C:\nssm\nssm.exe remove ZKTecoAgent confirm
```

To discard test data in Odoo, delete the `attendance.log` rows for those devices; logs already
marked *Calculated* refuse deletion, so remove the generated `hr.attendance` records first.

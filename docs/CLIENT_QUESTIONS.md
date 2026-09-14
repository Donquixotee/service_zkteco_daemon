# Questions for Elcherif Distribution — Attendance Go-Live

## Blocking — needed before attendance can be trusted

### 1. Confirm 67 employee ↔ badge matches

67 employees in Odoo have a name that is spelled differently on the attendance readers, so
the system could not link them automatically. For each one we have prepared a likely match.

> *Please ask someone who knows the staff to review the attached list and confirm, for each
> employee, which badge number on the reader is theirs.*

Pay particular attention to lines marked **CHECK**. Those are masculine/feminine name pairs
such as KARIM / KARIMA or AMINE / AMINA — they look alike but are usually two different people.
A wrong match records one person's attendance under another's name.

### 2. Two employees are not on the readers at all

> *These two employees do not appear on either reader. Are they enrolled? If yes, what is
> their badge number on the device? If not, should they be enrolled?*

(Send the two names from the `not found on device` rows of the CSV.)

### 3. About 113 users have no name, only a long number

Each reader holds about 113 users named with a 10-digit number or `NN-` followed by digits.
They generate roughly **30% of all punches** (1,054 of 3,413 on the entrance, 1,176 of 3,879 on
the exit).

> *Are these employees who badge with a card? Visitors? Old cards that are no longer in use?*

If they are current employees, their attendance is **not being recorded today**, and each one
needs to be matched to an employee.

### 4. Should past attendance be imported?

The readers hold punches going back to **19 August 2026**.

> *Do you want attendance imported from 19 August, or only from a go-live date? If a date,
> which one?*

This matters for August payroll: importing history creates attendance records for those weeks.

### 5. Is the time on both readers correct?

> *Do both readers show the correct local time right now?*

Attendance is recorded using each reader's own clock. A reader running one hour fast puts every
punch one hour late, and nothing in Odoo corrects it — the clock must be fixed on the device.

## Important — does not block go-live

### 6. Two people are enrolled twice

| Employee | Badge numbers on the reader |
|---|---|
| MEZIANE MOHAMED CHAKIB | 226 and 529 |
| SERIR YOUCEF | 260 and 268 |

> *Is each pair the same person enrolled twice?*

Both numbers are currently linked to that employee, which is correct if so.

### 7. A badge is being rejected

Badge `1090519040` was presented at the exit **four times within 17 seconds** on 19 August,
which usually means the reader refused it.

> *Whose badge is this? Is it still meant to work?*

### 8. People who do not badge out

Someone who badges in but not out is left with an open attendance for that day.

> *What should happen in that case — leave it open for HR to fix, or close it automatically at
> the end of the day?*

### 9. Former staff on the readers

Each reader holds 800 users for 122 current employees.

> *Are the remaining users former staff? Do you want them removed from the readers later?*

Removal is permanent — fingerprints deleted from a reader cannot be recovered — so this should
be a deliberate decision, not part of go-live.

### 10. Managing badges from Odoo

With Odoo hosted outside your network, Odoo can **read** attendance from the readers but cannot
**write** to them. Adding a new employee's badge, changing a card, or removing someone who
leaves is still done at the reader.

> *Is that acceptable for now, or do you need these done from Odoo?*

### 11. When to switch to the live database

Everything is currently running against the **test** copy of your database.

> *Once the matches above are confirmed and a few days of attendance look right, can we switch
> to the live database? Who should validate the test results first?*

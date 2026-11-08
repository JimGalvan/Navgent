# RP-214 paste sheet (meeting on Tuesday, November 10, 2026)

Paste each block into the matching field on Reprobe's New screen. Same text as the ticket view.

## Steps to reproduce

```text
1. Sign in as the demo admin account.
2. Open Calendar, select Conference Room A, and go to November 9 to November 15, 2026. Confirm Product Sprint Review appears only on November 10 at 10:00 AM to 11:00 AM.
3. Open Reservations and search for "Product Sprint Review".
4. Open Jordan Lee's reservation and click Edit Reservation.
5. Keep the date November 10, 2026. Change the start to 1:00 PM and end to 2:00 PM, then click Save changes.
6. Check the details page. It shows 1:00 PM to 2:00 PM and a successful update message.
7. Open Calendar for Conference Room A and the week of November 9 to November 15, 2026.
8. Check Tuesday, November 10, then refresh the page.
```

## Expected

```text
Product Sprint Review appears only at 1:00 PM to 2:00 PM. Its original 10:00 AM to 11:00 AM slot is available.
```

## Actual

```text
The details show 1:00 PM to 2:00 PM. The calendar shows Product Sprint Review twice: at 10:00 AM and at 1:00 PM. Both remain after a refresh.
```

## App URL

```text
https://roompilot-production.up.railway.app
```

## Credentials

Leave the saved RoomPilot credential selected. Don't type anything.

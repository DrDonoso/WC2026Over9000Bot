# Session Log: /hoy Jornada Rollover — Commit ad0b59a

**Date:** 2026-06-18T07:09:04Z

## Feature

`/hoy` rolls forward to next non-finished 9am–9am window. Today returns time-only format; future jornadas return dated format. Fallback: finished results or empty state.

## Tests

1304 green (baseline 1297, +7 new).

## Coordinator Verified

At 09:53 offset 0 had 4 TIMED matches. Rendered correctly with rollover date headers.

## Ready

For merge + container rebuild.

# QuietComfort Ultra 2 Earbuds Battery

## Device

- Product ID: `0x4062`
- Bose codename: `edith`
- `bosectl` device type: `qc_ultra2_earbuds`
- BMAP transport: Bluetooth RFCOMM

The earbuds use the same tested feature map as the QC Ultra 2 headphones for
the controls currently exposed by `bosectl`. Their battery response contains
component records that the headphone response does not use.

## Battery Status

Battery status is read from BMAP `[2.2]`. A response is a sequence of four-byte
records:

```text
[level, reserved, reserved, component_id]
```

`level` is a percentage from 0 to 100. The two middle bytes have been `ff` in
the observed responses and are not interpreted. Records must be identified by
`component_id`, not by their position in the payload.

Observed component IDs for product `0x4062`:

| ID | Meaning | Panel display |
|---:|---|---|
| `1` | Right earbud | Right |
| `2` | Left earbud | Left |
| `3` | Charging case | Case |
| `4` | Combined earbud reading | Not displayed |

Example test payload:

```text
3cffff01 3cffff02 3cffff04 50ffff03
```

This decodes to Right `60%`, Left `60%`, combined earbuds `60%`, and Case
`80%`. The combined record is intentionally ignored because the panel already
has the two individual earbud values.

The ordinary aggregate `Battery` value is returned from the ID `4` combined
earbud record. For headphones, a response such as `50ffff00` means `80%` with
component ID `0`. The component IDs remain the source of truth for the Right,
Left, and Case rows; the ID `4` value is used only for the generic aggregate
`Battery` line.

## Status Flow

The current `bosectl status` command performs these operations:

1. `dev.status()` reads `[2.2]` once and keeps the aggregate and component
   records in one battery snapshot.
2. The CLI prints the aggregate `Battery` line, followed by known component
   lines in configured order: `Right`, `Left`, and `Case`.
3. Omabose runs that command with `BOSE_MAC` and `BMAP_DEVICE` and parses the
   labelled lines into `Model.parseStatus()`.

The single response is the source of truth for both the aggregate value and
the component map, avoiding inconsistent values from back-to-back reads.

Implementation references:

- [`qc_ultra2_earbuds.py`](../bosectl/python/pybmap/devices/qc_ultra2_earbuds.py)
- [`parsers.py`](../bosectl/python/pybmap/devices/parsers.py)
- [`connection.py`](../bosectl/python/pybmap/connection.py)
- [`cli.py`](../bosectl/python/pybmap/cli.py)
- [`Model.js`](../Model.js)
- [`Service.qml`](../Service.qml)

## Charging State: Not Yet Proven

The Case row currently reports case battery level only. Case charging is not
exposed as a boolean or icon.

Controlled observations with the lid open show that `[2.5]` is a combined
seating state, not a charger state:

| Earbud placement | Charger | `[2.5]` |
|---|---|---|
| Both seated | Disconnected | `01` |
| Both seated | Connected | `01` |
| Right removed, left seated | Connected | `00` |
| Both removed | Disconnected | `00` |

The other readable candidates tested in the same state matrix, `[2.16]` and
`[2.21]`, stayed at `01`. `[2.20]` changed over time but did not correlate with
the charger transition. No stable charging bit has been found, so the current
implementation intentionally leaves case charging as work in progress.

When the lid is closed, the earbuds disconnect and the RFCOMM BMAP channel is
unavailable. A user-level Bluetooth LE scan found no separate case address,
advertisement data, or LE bearer for the device. Closed-case charging status
therefore cannot be queried through the current BMAP connection or BlueZ device
properties on this hardware.

Do not infer charging from any of these alone:

- A change in the Case percentage.
- The order of the `[2.2]` component records.
- The aggregate `Battery` value.
- Whether the earbuds are currently inside the case.

## Case-Charging Capture Plan

Before adding case charging support, capture the full request and response for
`[2.2]` and `[2.5]` across a repeated state matrix:

1. Earbuds out, case open, USB power disconnected.
2. Earbuds in, case open, USB power disconnected.
3. Earbuds in, case closed, USB power disconnected.
4. Earbuds in, case closed, USB power connected.
5. Earbuds out, case open, USB power connected.
6. USB power disconnected again, with the case state unchanged otherwise.

For every state, record the case percentage, both earbud percentages, the raw
`[2.2]` and `[2.5]` payloads, timestamps, and whether the transition was
observed immediately or after a delay. Repeat each transition more than once
and include a case with a low battery level if possible.

A safe implementation should only expose charging after a field or transition
is stable across those captures and is distinguishable from stale data. Add a
fixture and parser test before adding the UI state.

The current safe reporting rule is therefore: always display the Case percentage
from its `[2.2]` component record; optionally use `[2.5]` only as a combined
“both earbuds seated” state; never label `[2.5]` as charging.

## Tests

The current payload and component mapping are covered by:

- [`test_device_parsers.py`](../bosectl/python/tests/test_device_parsers.py)
- [`test_connection.py`](../bosectl/python/tests/test_connection.py)
- [`test_cli.py`](../bosectl/python/tests/test_cli.py)
- [`test_qc_ultra2.py`](../bosectl/python/tests/test_qc_ultra2.py)

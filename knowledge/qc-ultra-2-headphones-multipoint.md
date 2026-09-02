# QuietComfort Ultra 2 Headphones Multipoint

## Device And Scope

- Product ID: `0x4082`
- Bose codename: `wolverine`
- BMAP version observed by related implementations: `1.2.0`
- Local BMAP transport: Bluetooth Classic RFCOMM
- Local observations: 2026-09-01

This note distinguishes local hardware observations from findings in public
implementations. It covers two separate concerns:

1. Managing remembered and connected audio sources through BMAP.
2. Keeping the BMAP control connection available while two audio sources are
   connected.

The short conclusion is that multipoint itself does not make BMAP unavailable.
The current evidence instead points to contention for a Classic SPP control
session. The firmware also exposes BMAP over BLE/GATT, which is the best route
to control that is independent of the two Classic audio links.

## Local RFCOMM Observations

### Initial Failure And Recovery

With Linux and a second source connected, attempts to open the BMAP RFCOMM
transport on channels 2, 8, and 9 all failed with `ECONNREFUSED` (`Errno 111`).
The result was unchanged when playback was active on Linux and when playback was
active on the second source.

After the second source disconnected, the panel's existing polling recovered
automatically and the controls appeared without reopening the panel.

That transition proves the failure and recovery behavior, but not that two
audio links alone caused the refusal. A later snapshot provided the missing
counterexample.

### BMAP Works With Two Sources Connected

Later, while BMAP was working, Device Management `[4.4]` returned a connected
mask of `0x03`. `[4.5]` independently marked both the Linux source and the
second source as connected:

```text
[4.4] STATUS 03 <linux-mac> <second-source-mac> <remembered-macs...>
[4.5] STATUS <linux-mac> 03 0203 <linux-name>
[4.5] STATUS <second-source-mac> 01 0203 <second-source-name>
```

The `[4.5]` flag byte uses bit 0 for connected and bit 1 for the local app
device. Linux therefore had flags `0x03` and the second source had `0x01`.

Extended Info `[4.6]` made the likely contention mechanism visible:

```text
[4.6] STATUS <linux-mac>        0f 0f 9ce9
[4.6] STATUS <second-source-mac> 0f 07 9ce9
```

The first profile byte is the paired-profile mask and the second is the
connected-profile mask. Bits 0 through 4 represent A2DP, HFP, AVRCP, SPP, and
iAP. Linux had connected mask `0x0f` because the active BMAP query itself held
SPP. The second source had `0x07`: all three audio/control profiles, but no SPP.

The strongest current explanation is therefore:

- Two audio sources can remain connected while Linux uses BMAP.
- A second source can temporarily own the device's SPP/BMAP control session.
- While that session is occupied or stale, new Linux RFCOMM opens are refused.
- Disconnecting that source releases the session; it can reconnect with audio
  profiles only, after which Linux BMAP works again.

The SPP bit was not captured during the failure, so ownership by the second
source remains a well-supported hypothesis rather than a completed proof.

Do not report `Errno 111` as proof that a second audio source is connected.
Describe it as a likely Bose control-channel conflict and keep retrying.

### Active Source Is Not A Connection List

After the second source disconnected and BMAP recovered, Audio Management
`[5.1]` still returned that source's address. The field is the routed or last
active source, not proof that the source remains connected.

Use `[4.4]` and `[4.5]` for connection state. Never infer the connected-source
set from `[5.1]`.

## Official-Style Source Management

The following reads were accepted by the local `0x4082` hardware:

| Address | Meaning | Local result |
|---|---|---|
| `[4.4]` | Remembered-device list and connected mask | Accepted |
| `[4.5]` | Name, connection flags, and local-device flag for one MAC | Accepted |
| `[4.6]` | Paired and connected profile masks for one MAC | Accepted |
| `[4.9]` | Address of the app/control source | Linux adapter MAC |
| `[4.14]` | Device Management capabilities | `01` |
| `[4.12]` | Routing/carousel selection | `FuncNotSupp` |

Public reverse engineering of Bose's packet models documents the associated
actions:

```text
[4.1] START [00, mac(6)]  connect a remembered source
[4.2] START [mac(6)]      disconnect a source
[4.3] START [mac(6)]      forget a source
```

Only the reads were exercised locally. Connect, disconnect, and forget must be
live-tested with restoration before being exposed in the panel. Forget is
destructive and should always require confirmation.

The `[4.4]` list order can change between reads. Interpret byte 0 as a bitmask
over the MAC addresses in that same response and never cache a list index.
Query `[4.5]` for each address to obtain a stable identity and display name.

The local `[4.14]` value `01` means cross-transport key derivation is supported,
while device carousel and source barge-in are not advertised. `[4.12]` also
returns `FuncNotSupp`, so the existing `route(mac)` assumption is not valid for
this firmware. Official-style switching is expected to disconnect one source
with `[4.2]` and let audio move to the remaining source, rather than writing a
dedicated route register.

## Multipoint Setting `[1.10]`

The local enabled response is:

```text
[1.10] STATUS 07
```

Recovered Bose packet models and independent hardware observations identify
the bits as:

| Bit | Meaning |
|---:|---|
| 0 | Multipoint currently enabled |
| 1 | Multipoint supported |
| 2 | Disabling multipoint supported |

Consequently, `0x07` is enabled and `0x06` is disabled. Earlier vendored code
checked bit 1 and therefore read the capability bit rather than the current
state; the local runtime now checks bit 0.

For writes, prefer a read-modify-write that changes bit 0 and preserves the
capability bits. Some models accept a bare `00` or `01`; preserving the full
byte is the safer candidate for the newer headphone and earbud implementations
and still requires a live restoration test on this hardware.

## BMAP Over BLE/GATT

Modern Bose devices expose the same BMAP messages over BLE. Public live captures
for the QC Ultra 2 Headphones identify:

| Role | UUID |
|---|---|
| BMAP service | `0000febe-0000-1000-8000-00805f9b34fb` |
| Unsecure write characteristic | `d417c028-9818-4354-99d1-2ac09d074591` |
| Secure notify characteristic | `c65b8f2f-aee2-4c89-b758-bc4892d6f2d8` |

The working exchange writes to the unsecure characteristic with
write-without-response and receives BMAP responses as notifications on the
secure characteristic. Each raw BMAP packet gains a one-byte BLE segmentation
header. `0x00` is a complete single-segment packet; larger messages use the high
nibble for the final segment index and the low nibble for the current index.

Most settings require an encrypted BLE link. The local `[4.14]` capability value
indicates cross-transport key derivation support, so in principle the existing
Classic bond can secure the LE link without another user-visible pairing.

BLE is the closest match to the official app's architecture because it does not
need to consume either Classic audio source slot or win the RFCOMM/SPP control
session. Public reverse engineering of Bose's Android SDK shows BLE, SPP, and LE
CoC connection managers feeding the same BMAP parser.

### Current Linux Barrier

The headphones advertise on their public address while the Classic audio link
is active. A local LE scan observed Bose manufacturer data (`0x009e`) and Fast
Pair service data (`0xfe2c`) from that address.

BlueZ currently presents only the Classic services for this merged dual-mode
device:

- `ServicesResolved` is false.
- There are no GATT service or characteristic objects below the headphone's
  D-Bus device path.
- The cached UUID list does not include `FEBE`.

Two read-only `btgatt-client` attempts explicitly targeting the public LE
address, with low and medium security, remained at `Connecting to device` until
timeout. They did not alter headset settings or the Classic connection.

This does not disprove BLE support: exact-model CoreBluetooth captures already
show the service. It means Linux transport establishment must be solved before a
BLE fallback can be shipped. BlueZ's normal `Device1.Connect()` does not provide
a reliable way to choose LE instead of BR/EDR for a merged, already-connected
dual-mode object.

## Workaround Options

### 1. Reuse Or Hold The RFCOMM Session

The smallest near-term workaround is a long-lived BMAP helper that reuses one
RFCOMM socket for status and actions instead of opening a new socket for every
bridge invocation.

Benefits:

- It can reserve the SPP control session before another source takes it.
- It avoids repeated open/close races and the firmware's post-close refusal
  window.
- It supports the full existing BMAP feature set plus `[4.x]` source management.

Limitations:

- It cannot preempt a session already owned by another source.
- It may prevent the Bose app or another controller from opening Classic BMAP.
- An always-on socket may affect device power, so it should have an idle timeout
  and reconnect backoff.

This is suitable as an incremental improvement, not a complete substitute for
BLE.

### 2. Add A BLE BMAP Transport

The durable approach is to separate BMAP framing from transport and add a
BLE/GATT implementation with RFCOMM fallback.

Required work:

1. Establish an encrypted LE connection on Linux without dropping Classic
   audio.
2. Discover `FEBE` and the secure/unsecure characteristics.
3. Subscribe to secure notifications before sending requests.
4. Add and remove the one-byte segmentation framing.
5. Reuse the existing BMAP parsers and device configuration.
6. Keep the BLE session alive or reconnect with bounded retry/backoff.

Before implementation, capture the failed Linux LE connection with `btmon` to
identify the HCI status, then test a forced-LE connection under controlled
conditions. Testing after dropping Linux Classic audio would interrupt playback
and should only be done with explicit approval.

### 3. Fast Pair Message Stream As A Limited Fallback

The device advertises the Google Fast Pair Message Stream UUID
`df21fe2c-2515-4fdb-8886-f12c4d67927c`. Google's public protocol offers:

- Audio Switch group `0x07`: multipoint state, switching preferences, active
  source switching, and connection status.
- Hearable Controls group `0x08`: coarse ANC modes.

This is not a drop-in BMAP replacement. Mutating Audio Switch messages require
an account key, nonce, and message authentication code, and the protocol does
not expose Bose-specific EQ, audio modes, or all settings. It may eventually be
useful for status or coarse controls, but BLE BMAP is the more complete target.

### 4. Graceful RFCOMM Recovery

Until either transport improvement exists:

- Show a likely control-channel conflict for `ECONNREFUSED` rather than claiming
  multipoint with certainty.
- Continue polling with bounded backoff so controls recover automatically.
- Do not ask users to disable multipoint globally.
- Suggest closing the other Bose controller or disconnecting and reconnecting
  the competing source only as a manual recovery step.

## Recommended Implementation Order

1. Correct `[1.10]` parsing to use bit 0 and preserve capability bits on writes.
2. Add read-only `[4.4]`, `[4.5]`, `[4.6]`, `[4.9]`, and `[4.14]` parsing.
3. Display remembered sources and their connection state without adding writes.
4. Add confirmed `[4.1]` connect and `[4.2]` disconnect actions with live
   restoration tests; do not implement `[4.12]` routing.
5. Improve the RFCOMM lifecycle with session reuse and an idle timeout.
6. Treat BLE BMAP as a separate transport milestone after the Linux LE bearer is
   proven on this machine.

## References

- [Boss BMAP protocol notes](https://github.com/cmqui/boss/blob/main/docs/bmap-protocol-notes.md): exact-model QC Ultra 2 Headphones BLE service, characteristics, framing, and live captures.
- [Bose Control protocol notes](https://github.com/depau/bosectl-android/blob/main/docs/PROTOCOL.md): recovered Bose SDK transports, Device Management packets, multipoint semantics, and encrypted BLE behavior.
- [bozo](https://github.com/NerdySouth/bozo): BMAP-over-BLE implementation derived from Bose Music and tested on QC Ultra headphones.
- [Google Fast Pair Audio Switch](https://developers.google.com/nearby/fast-pair/specifications/extensions/sass): authenticated multipoint and source-switch protocol.
- [Google Fast Pair Hearable Controls](https://developers.google.com/nearby/fast-pair/specifications/extensions/hearablecontrols): coarse ANC controls over Message Stream.

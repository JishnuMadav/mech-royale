# Mech Royale — Oval Sentinel

Python bot for the 2026 Builders Buildathon Mech Royale track.
No third-party runtime dependencies. The root Dockerfile is the submission entrypoint.

This branch tests `combat.py`, a combat and cover candidate built on the original
bot's geometry helpers and the rooftop candidate's indexed terrain model. It
prioritizes a laser early, selects weapon-specific aim, manages laser release
and mortar trajectories, strafes during fights, protects reloads, and lets
lightning recharge between bursts. It holds territory until zone travel is
necessary instead of automatically moving toward a crowded center. A bounded
ground-route planner steers around buildings, and wounded mechs seek reachable
cover while continuing to defend themselves until they break line of sight.
`survivor.py` remains available for comparison but is not the entrypoint here.
The initial baseline remains at commit `d4b7934b5ccbc02b6f29859bb9db385f0829ec4e`.

## Strategy

- Move toward the next safe circle with a travel-time margin.
- Strafe and maintain distance from opponents, retreating at low health.
- Avoid building prisms, map boundaries, and shots into building cover.
- Lead moving targets and fire only when the actual torso aim is aligned.
- Collect nearby cubes and a second weapon; favor lasers and sustain upgrades.
- Manage reloads and energy reserves; jump/jet when stuck.

This is an experimental heuristic entry. Navigation combines a ground grid with
local collision checks; rooftops still use local steering.
The starter recording cannot measure placement or validate movement in a live game.
Only scored practice matches establish playing strength.

## Validation

From this directory (Python 3.12+):

```sh
python3 setup_kit.py
python3 -m unittest -v test_bot.py
python3 mechfight-kit/check/check.py -- python3 -u bot.py
python3 mechfight-kit/check/check.py -- python3 -u survivor.py
python3 mechfight-kit/check/check.py -- python3 -u combat.py
docker build --platform linux/amd64 -t mech-royale:initial .
python3 mechfight-kit/check/check.py --map-dir /arena -- docker run --rm -i --network none --cpus 1 --memory 512m --memory-swap 512m --pids-limit 128 --cap-drop ALL --read-only --tmpfs /tmp:rw,size=64m --user 65534:65534 -v "$PWD/mechfight-kit/arena:/arena:ro" mech-royale:initial
```

The official checker validates 300 recorded observations, timing, queue handling,
schema compliance, and shutdown. It is not a simulator.

Validated on 2026-11-21: all three regression checks passed; the official checker
passed on Windows Python, local WSL Docker, and the Ubuntu VM Docker container.
The VM answered all 300 observations within 50 ms (median 6.3 ms, p99 13.9 ms,
maximum 17.5 ms), with no bad messages or stale responses. Its practice score
was 1.29 (receipt BB-C2349777).
The rooftop candidate also passed restricted WSL Docker validation: 300/300
within budget, median 2.5 ms, p99 7.4 ms, maximum 11.2 ms. These are protocol
measurements, not evidence of better placement; its practice score was 0.44
(receipt BB-D8559723), so it did not replace the baseline as the selected entry.
The combat-v3 candidate scored 3.67 (receipt BB-9D2EC473, commit
`5dbeec64befaf446c7f43aa76fc9fa1a31630319`) and became the best entry. Sustain-v4
also scored 3.67 (receipt BB-AA2FFC04, commit
`cd85a4b0bed134e019b07006e089bf3261a55ac9`); the earlier v3 remains selected.
V6 scored 5.10 (BB-B3606475, `3efe92acc5bc15778bcf94ee8ad5a78ffca52972`).
V7 scored **5.46** (BB-D98A5863, `dd71d123ec8b9754d4570b2c3e8849d14359a068`)
and is the current selected entry. The target is strictly greater than 6.
V8 tests the laser charge rounding fix against that 5.46 version: the observed
charge can be .56 while the full-charge threshold is .563. A .01 tolerance
prevents a full beam from waiting for its automatic two-second hold timeout.
V6 adds enemy spacing during zone travel, earlier boost
use near attackers, and exploration when a spawn offers no visible equipment.
V7 additionally captures nearby uncontested supply drops for full repair and
power cubes. It uses the supplied landing and capture timing from observations.
When no target is visible, it faces recent incoming damage instead of exposing
its rear armor while scanning.
The laser correction scored **5.73** (BB-DF9C6D15,
`53c7150303aa26d5733e0c5aa01e1681a36ea10d`) and became the selected entry.
V9 tests faster early growth with that fix: it seeks the six-cube upgrade, farms isolated
drones and crates from farther away, and can run to a safe supply drop.

## Submission

Publish this directory as a public GitHub repository, retaining the Dockerfile
at the repository root. Submit the repository URL on the official track page:
https://www.joinbuilders.org/buildathon/tracks/builders

The submitted commit must stay under 20 MB. The track allows four submissions
per hour. Keep the repository public until results are published.

## Attribution

`mechfight.py` comes from the organizer-provided Mech Royale starter kit.
`setup_kit.py` downloads the exact kit used for validation into an ignored local
directory; the submission does not need the kit because the scorer mounts its map.
The kit was downloaded on 2026-11-21 and includes the original
example bots, protocol, schema, test recording, and arena. Our bot implementation
is in `bot.py`, `survivor.py`, `combat.py`, and `navigation.py`. No other
pre-existing bot code or external runtime libraries are used.

Project code is released under the MIT License as required by the Buildathon.

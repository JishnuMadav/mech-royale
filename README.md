# Mech Royale — Oval Sentinel

Python bot for the 2026 Builders Buildathon Mech Royale track.
No third-party runtime dependencies. The root Dockerfile is the submission entrypoint.

This branch tests `combat.py`, a combat and loot candidate built on the original
bot's geometry helpers and the rooftop candidate's indexed terrain model. It
acquires a second weapon early, selects weapon-specific aim, manages laser
release and mortar trajectories, strafes during fights, and protects reloads.
`survivor.py` remains available for comparison but is not the entrypoint here.
The initial baseline remains at commit `d4b7934b5ccbc02b6f29859bb9db385f0829ec4e`.

## Strategy

- Move toward the next safe circle with a travel-time margin.
- Strafe and maintain distance from opponents, retreating at low health.
- Avoid building prisms, map boundaries, and shots into building cover.
- Lead moving targets and fire only when the actual torso aim is aligned.
- Collect nearby cubes and lightning weapons; prioritize survival upgrades.
- Manage reloads and energy reserves; jump/jet when stuck.

This is an initial heuristic entry, not a measured competitive result. Navigation
uses local sampled prism checks, not global pathfinding or terrain slope analysis.
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
is in `bot.py`. No other pre-existing bot code or external libraries are used.

Project code is released under the MIT License as required by the Buildathon.

"""Standalone Mech Royale controller for collecting resources, positioning and combat."""

import math
import time

import mechfight as mf
from bot import angle_delta, unit
from navigation import Navigator
from ring_routes import RingRoutes
from survivor import TerrainArena
from weapon_geometry import WeaponGeometry


def distance(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


class ArenaPlanner(WeaponGeometry):
    name = "Oval-Arena-Planner"

    def __init__(self, hello):
        self.config = hello["config"]
        self.arena = TerrainArena(hello["map"]["dir"])
        self.nav = Navigator(self.arena)
        self.rings = RingRoutes(self.nav)
        self.ring_waypoint = False
        self.flight = None
        self.side = 1 if hello["slot"] % 2 else -1
        self.seen = {}
        self.drones = {}
        self.loot = {}
        self.last_hit = (-100, 0, None)
        self.laser_until = -1
        self.focus = None
        self.phase = "opening"
        self.goal = None
        self.recovery = False
        self.shelter = None
        self.cover_check = -1
        self.move = (0, 0)
        self.steer_key = None
        self.steer_after = -1
        self.anchor = None
        self.anchor_time = -1
        self.arc_rest = False
        self.visits = {}
        self.position = None
        self.position_after = -1

    def observe(self, obs, enemies, gear):
        now, me = obs["t"], obs["self"]
        self.phase = (
            "duel"
            if obs["alive"] == 2
            else "endgame"
            if obs["alive"] <= 4
            else "opening"
            if now < 35 and (len(gear) == 1 or me["cubes"] == 0)
            else "midgame"
        )
        self.seen = {i: (t, e) for i, (t, e) in self.seen.items() if now - t < 3}
        for enemy in enemies:
            self.seen[enemy["id"]] = now, enemy
            if (
                "laser" in enemy.get("weapons", ())
                and distance(me["pos"], enemy["pos"]) < self.config["weapons"]["laser"]["range"]
            ):
                self.laser_until = now + 4
        for event in obs["events"]:
            if event["type"] == "damaged" and event.get("bearing") is not None:
                self.last_hit = now, event["bearing"], event.get("by")
                if event.get("weapon") == "laser":
                    self.laser_until = now + 4
        visible = {item["id"] for key in ("pickups", "cubes") for item in obs[key]}
        self.loot = {
            i: entry
            for i, entry in self.loot.items()
            if now - entry[0] < 6 and (i in visible or distance(me["pos"], entry[2]["pos"]) > 7)
        }
        for key in ("pickups", "cubes"):
            for item in obs[key]:
                self.loot[item["id"]] = now, key, item
        hp = me["hp"] / me["max_hp"]
        self.recovery = hp < 0.25 or (self.recovery and hp < 0.6)
        self.arc_rest = me["energy"] < (55 if self.arc_rest else 16)
        self.drones = {
            e["id"]: e
            for e in obs["mechs"]
            if e["kind"] == "npc"
            and (
                distance(me["pos"], e["pos"]) <= 45
                or (e["id"] == self.last_hit[2] and now - self.last_hit[0] < 2)
            )
        }
        self.visits[(round(me["pos"][0] / 24), round(me["pos"][1] / 24))] = now

    def choose_position(self, obs, threats):
        """Compare reachable arena cells for exploration, ring access and escape routes."""
        now, me, zone = obs["t"], obs["self"], obs["zone"]
        p, center = me["pos"], zone["next_center"]
        if zone["next_radius"] < 20:
            return "rotate", center
        if self.position is not None and now < self.position_after and distance(p, self.position) > 5:
            return "position", self.position
        if now < self.position_after and self.position is None:
            return "hold", p
        self.visits = {k: t for k, t in self.visits.items() if now - t < 30}
        self.position, self.position_after = None, now + 3
        candidates = []
        heading = math.atan2(center[1] - p[1], center[0] - p[0])
        for length in (25, 50, 75):
            for i in range(12):
                a = heading + self.side * i * math.tau / 12
                cell = (
                    round((p[0] + length * math.cos(a) - self.nav.x0) / self.nav.STEP),
                    round((p[1] + length * math.sin(a) - self.nav.y0) / self.nav.STEP),
                )
                q = self.nav.points.get(cell)
                if (
                    q is None
                    or len(self.nav.links[cell]) < 2
                    or distance(q, zone["center"]) > zone["radius"] - 6
                ):
                    continue
                edge = max(0, distance(q, center) - max(0, zone["next_radius"] - 14))
                visited = self.visits.get((round(q[0] / 24), round(q[1] / 24)), -100)
                score = -0.14 * length - 0.5 * edge - max(0, 24 - now + visited)
                score += min(8, q[2] - p[2]) * 0.55 + 0.4 * len(self.nav.links[cell])
                score += 0.11 * (distance(p, center) - distance(q, center))
                for e in threats:
                    sep = distance(q, e["pos"])
                    score -= max(0, 70 - sep) * 0.4
                candidates.append((score, q))
        for _, q in sorted(candidates, reverse=True)[:2]:
            if self.nav.path(p, q, limit=350):
                self.position = q
                self.position_after = now + 4.5
                return "position", q
        return "hold", p

    def target(self, obs, gear):
        me, now = obs["self"], obs["t"]
        pos = me["pos"]
        options = []
        for victim in obs["mechs"] + [dict(c, kind="crate") for c in obs["crates"]]:
            kind = victim["kind"]
            gap = distance(pos, victim["pos"])
            hostile_drone = kind == "npc" and victim["id"] in self.drones
            if (
                kind != "mech"
                and not hostile_drone
                and (gap > 80 or self.recovery or now - self.last_hit[0] < 2 or self.phase == "duel")
            ):
                continue
            if gap > max((w["stats"].get("range", 230) for _, w in gear.values()), default=0):
                continue
            exposure = 0
            if now - self.last_hit[0] < 2:
                yaw = math.atan2(victim["pos"][1] - pos[1], victim["pos"][0] - pos[0])
                exposure = 32 * (1 - math.cos(angle_delta(yaw, self.last_hit[1])))
            score = gap * 0.65 + min(1800, victim.get("hp", 1400)) * 0.047 + exposure
            if hostile_drone:
                score += 26 if self.phase == "duel" else 6
            elif kind != "mech":
                score += 65 if self.phase == "opening" else 110
            if victim["id"] == self.focus:
                score -= 12
            if victim["id"] == self.last_hit[2] and now - self.last_hit[0] < 2:
                score -= 26
            if kind == "mech" and victim.get("hp", 1400) < 280:
                score -= 38
            if "laser" in gear and "mortar" in victim.get("weapons", ()):
                score -= 19
            options.append((score, victim))
        muzzle = [*pos[:2], pos[2] + me["stats"]["muzzle_height"]]
        for _, victim in sorted(options, key=lambda pair: pair[0])[:6]:
            q = victim["pos"]
            height = 4.5 * (1 + 0.05 * victim.get("cubes", 0)) if victim["kind"] == "mech" else 1.5
            if self.arena.clear_shot(muzzle, [*q[:2], q[2] + height]):
                self.focus = victim["id"]
                return victim
        self.focus = None
        return None

    def objective(self, obs, gear, target, action):
        now, me, zone = obs["t"], obs["self"], obs["zone"]
        p, center = me["pos"], zone["next_center"]
        walk = me["stats"]["walk_speed"]
        remaining = zone["shrink_end"] - now
        travel, entry, self.ring_waypoint = self.rings.entry(p, zone, now)
        forced = not me["in_zone"] or (travel > 0 and travel / walk + 5 >= remaining)
        if forced or (zone["next_radius"] <= 8 and distance(p, center) > 5):
            return "rotate", entry
        threats = [e for _, e in self.seen.values()]
        near = min((distance(p, e["pos"]) for e in threats), default=math.inf)
        nearby_attackers = threats + list(self.drones.values())
        if self.recovery and nearby_attackers:
            if now >= self.cover_check:
                self.shelter = self.nav.cover(p, nearby_attackers, zone)
                self.cover_check = now + 1.8
            if self.shelter and distance(self.shelter, center) < zone["next_radius"] + 15:
                return "recover", self.shelter
        if not self.recovery:
            self.shelter = None

        # Score opportunities by benefit, travel time and whether an opponent
        # can contest the destination. Comparable scores allow a nearby cube
        # to beat a distant weapon or a dangerous supply drop.
        options = []
        ranks = {"gun": 0, "mortar": 1, "lightning": 2, "laser": 3}
        other = next((k for k in gear if k != "gun"), None)
        for _, group, item in self.loot.values():
            q = item["pos"]
            d = distance(p, q)
            if abs(q[2] - p[2]) > 4 or d > 125:
                continue
            if group == "pickups":
                k = item["kind"]
                if (
                    k in gear
                    or ranks[k] <= ranks.get(other, -1)
                    or (k == "mortar" and now <= self.laser_until)
                ):
                    continue
                if d <= self.config["loot"]["pickup_radius"]:
                    action["take"] = item["id"]
                    if other is not None:
                        action["drop"] = gear[other][0]
                value = (21 + 5 * ranks[k]) if other is None else 11 + 3 * ranks[k]
            else:
                if me["cubes"] >= 10 and not self.recovery:
                    continue
                value = 22 if me["cubes"] in (0, 2, 5, 9) else 14
            rival = min((distance(q, e["pos"]) for e in threats), default=math.inf)
            if rival + 5 < d and rival < 45:
                continue
            score = value / (1 + d / walk * 0.38) - max(0, 50 - rival) * 0.2
            options.append((score, group, q))
        for drop in obs["drops"]:
            if me["cubes"] >= 10 and me["hp"] >= me["max_hp"] * 0.95:
                continue
            q = drop["pos"]
            if drop["holder"] not in (None, me["id"]) or distance(q, center) > zone["next_radius"] - 6:
                continue
            d = distance(p, q)
            if d > 130:
                continue
            rival = min((distance(q, e["pos"]) for e in threats), default=math.inf)
            if rival < 50 and not (drop["holder"] == me["id"] and drop["capture_s"] - drop["progress"] < 1):
                continue
            eta = max(d / walk, drop["lands_in"]) + drop["capture_s"] - drop["progress"]
            value = 15 + 35 * (1 - me["hp"] / me["max_hp"]) + min(3, max(0, 10 - me["cubes"])) * 5
            options.append((value / (1 + 0.3 * eta), "supply", q))
        if target and target["kind"] == "mech":
            options.append((9 if len(gear) == 1 and near > 40 else 15, "fight", target["pos"]))
        elif target and target["id"] in self.drones:
            options.append((13, "fight", target["pos"]))
        elif target and self.phase == "opening":
            options.append((7, "harvest", target["pos"]))
        if options:
            score, kind, q = max(
                options,
                key=lambda row: (
                    row[0]
                    + (
                        1.5
                        if self.goal and row[1] == self.goal[0] and distance(row[2], self.goal[1]) < 8
                        else 0
                    )
                ),
            )
            if score >= 4:
                return kind, q
        # Explore toward the next playable area when under-equipped. Hold a
        # useful safe position when ready, with weapons free while rotating.
        if travel > 0 and remaining < travel / walk + 18:
            return "rotate", entry
        return self.choose_position(obs, threats)

    def preferred_range(self, gear, enemy):
        if "laser" in gear:
            return 112 if "lightning" in enemy.get("weapons", ()) else 85
        if "lightning" in gear and not self.arc_rest:
            return 32
        return 65 if "mortar" in gear else 57

    def steer(self, obs, objective, point, gear, target):
        me, zone, now = obs["self"], obs["zone"], obs["t"]
        pos, stats = me["pos"], me["stats"]
        gap = distance(pos, point)
        if (
            objective == "hold"
            or (objective == "supply" and gap < 4)
            or (objective in ("recover", "rotate") and gap < 2)
        ):
            self.move = (0, 0)
            self.steer_key = None
            return self.move
        current = sorted((e for _, e in self.seen.values()), key=lambda e: distance(pos, e["pos"]))[:3]
        if self.drones:
            current += [min(self.drones.values(), key=lambda e: distance(pos, e["pos"]))]
        if objective == "fight" and target:
            ex, ey = unit(point[0] - pos[0], point[1] - pos[1])
            radius = self.preferred_range(gear, target) + (15 if len(current) > 1 else 0)
            radial = max(-1.8, min(1.5, (gap - radius) / 16))
            side = self.side if int(now / 3) % 2 == 0 else -self.side
            want = unit(ex * radial - side * ey, ey * radial + side * ex)
        else:
            wp = (
                self.nav.waypoint(pos, point, now)
                if gap > 18 and not (objective == "rotate" and self.ring_waypoint)
                else point
            )
            want = unit(wp[0] - pos[0], wp[1] - pos[1])
        key = (
            objective,
            self.focus,
            tuple(e["id"] for e in current),
            round(math.atan2(want[1], want[0]) * 2),
        )
        if (
            self.steer_key == key
            and now < self.steer_after
            and self.arena.clear_move(pos, self.move, stats)
        ):
            return self.move
        self.steer_key, self.steer_after = key, now + 0.25
        heading = math.atan2(want[1], want[0])
        delay = max(0, zone["shrink_start"] - now)
        fraction = min(
            1, max(0, 1.25 - delay) / max(0.05, zone["shrink_end"] - max(now, zone["shrink_start"]))
        )
        center = [
            zone["center"][i] + fraction * (zone["next_center"][i] - zone["center"][i]) for i in (0, 1)
        ]
        radius = zone["radius"] + fraction * (zone["next_radius"] - zone["radius"])
        candidates = []
        above_ground = pos[2] > self.arena.ground(*pos[:2]) + 4
        for offset in (0, 0.5, -0.5, 1, -1, 1.6, -1.6, 2.25, -2.25, math.pi):
            d = (math.cos(heading + offset), math.sin(heading + offset))
            foot = list(pos)
            for _ in range(4):
                if not self.arena.clear_move(foot, d, stats):
                    break
                x, y = foot[0] + 3 * d[0], foot[1] + 3 * d[1]
                ground = self.arena.ground(x, y)
                foot = [x, y, max(pos[2], ground) if above_ground else ground]
            moved = distance(pos, foot)
            if moved < 1:
                continue
            score = 1.8 * math.cos(offset) - 0.24 * (12 - moved)
            score -= 0.65 * max(0, distance(foot, center) - max(0, radius - stats["radius"]))
            if objective == "rotate":
                score += 0.13 * (distance(pos, zone["next_center"]) - distance(foot, zone["next_center"]))
            for e in current:
                q = e["pos"]
                v = e.get("vel", (0, 0, 0))
                projected = (q[0] + 0.7 * v[0], q[1] + 0.7 * v[1])
                danger_range = 68 if "lightning" in e.get("weapons", ()) and "laser" in gear else 24
                score -= 0.14 * max(0, danger_range - distance(foot, projected))
                if e.get("charging"):
                    dx, dy = foot[0] - q[0], foot[1] - q[1]
                    aim = e["aim"][0]
                    if dx * math.cos(aim) + dy * math.sin(aim) > 0:
                        score -= max(0, 1 - abs(dx * math.sin(aim) - dy * math.cos(aim)) / 8) * 2
            for projectile in obs["projectiles"][:20]:
                q, v = projectile["pos"], projectile["vel"]
                rx, ry = q[0] - pos[0], q[1] - pos[1]
                vx, vy = v[0] - d[0] * stats["walk_speed"], v[1] - d[1] * stats["walk_speed"]
                dt = -(rx * vx + ry * vy) / max(1, vx * vx + vy * vy)
                if 0 < dt < 0.6 and pos[2] - 1 < q[2] + dt * v[2] < pos[2] + stats["height"] + 1:
                    score -= max(0, stats["radius"] + 2 - math.hypot(rx + vx * dt, ry + vy * dt)) * 0.65
            candidates.append((score, d, foot))
        best = -math.inf
        self.move = (0, 0)
        sight_deadline = time.perf_counter() + 0.004
        for score, d, foot in sorted(candidates, key=lambda c: -c[0])[:3]:
            if self.move != (0, 0) and time.perf_counter() >= sight_deadline:
                break
            for enemy in current:
                if objective == "fight" and enemy["id"] == self.focus:
                    continue
                q = enemy["pos"]
                if self.arena.clear_shot([q[0], q[1], q[2] + 7], [foot[0], foot[1], foot[2] + 6]):
                    score -= 1.8 if len(current) > 1 or self.recovery else 0.6
            if score > best:
                best, self.move = score, d
        return self.move

    def weapons(self, obs, target, gear, sprint, action):
        me, now = obs["self"], obs["t"]
        gun = gear.get("gun")
        if gun:
            w = gun[1]
            action["reload"] = w.get("ammo", 0) == 0 or (
                not target and now - self.last_hit[0] > 3 and w["ammo"] <= w["stats"]["mag"] - 4
            )
        if not target:
            if now - self.last_hit[0] < 2.5:
                yaw = self.last_hit[1]
            elif self.seen:
                _, e = max(self.seen.values(), key=lambda pair: pair[0])
                yaw = math.atan2(e["pos"][1] - me["pos"][1], e["pos"][0] - me["pos"][0])
            else:
                sounds = [
                    s
                    for s in obs["sounds"]
                    if s["dist"] == "near"
                    and s["kind"] in ("gun", "laser_charge", "mortar", "lightning", "laser")
                ]
                yaw = sounds[0]["bearing"] if sounds else me["aim"][0] + self.side * 0.45
            action["aim"] = [yaw, 0]
            return
        gap = math.dist(me["pos"], target["pos"])
        solutions = {}
        plans = []
        for kind, (slot, w) in gear.items():
            stats = w["stats"]
            if gap > stats.get("range", 240) or (kind == "mortar" and gap < 20):
                continue
            solution = self.aim_at(me, target, kind, w)
            if not solution:
                continue
            aim, origin, hit = solution
            if kind == "gun" and not self.arena.clear_shot(origin, hit):
                continue
            solutions[kind] = aim
            if kind == "gun" and (w.get("reload", 0) > 0.1 or not w["ammo"]):
                continue
            if kind == "lightning" and (self.arc_rest or me["energy"] < stats["energy"] + 5):
                continue
            windup = abs(angle_delta(aim[0], me["aim"][0])) / me["stats"]["turn_rate"]
            delay = max(w["cooldown"], windup, 0.10)
            if kind == "laser":
                delay += max(0, stats["charge"] - w["charge"])
                if not self.laser_should_release(me, target, w):
                    delay += 1
            damage = min(target.get("hp", 1400) + 15, stats["damage"])
            plans.append((damage / (delay + 0.2), kind, aim))
        if plans:
            _, chosen, aim = max(plans, key=lambda row: row[0])
        else:
            chosen = None
            aim = (
                next(iter(solutions.values()))
                if solutions
                else self.aim_at(me, target, "laser", {"stats": {}})[0]
            )
        action["aim"] = aim
        for kind, (slot, w) in gear.items():
            if kind not in solutions:
                continue
            intended = solutions[kind]
            tolerance = math.atan2(2.5, max(1, gap))
            aligned = (
                self.aligned(me, intended, gap)
                and abs(angle_delta(aim[0], intended[0])) <= tolerance
                and abs(aim[1] - intended[1]) <= tolerance
            )
            if kind == "laser":
                release = self.laser_should_release(me, target, w) or sprint or not me["in_zone"]
                action["fire"][slot] = (not release and w["cooldown"] <= 0.1) or (
                    w["charge"] > 0 and not aligned
                )
                if w["charge"] and release and not aligned and chosen != "laser":
                    action["aim"] = intended
                    action["fire"] = [False, False]
                    action["fire"][slot] = not self.aligned(me, intended, gap)
                    break
            elif kind == "lightning":
                action["fire"][slot] = (
                    not self.arc_rest
                    and abs(angle_delta(me["aim"][0], intended[0]))
                    < math.radians(w["stats"]["cone_deg"]) * 0.85
                )
            else:
                action["fire"][slot] = (
                    aligned
                    and w["cooldown"] <= 0.1
                    and (kind != "gun" or (w["ammo"] > 0 and w.get("reload", 0) <= 0.1))
                )

    def act(self, obs):
        me, now = obs["self"], obs["t"]
        gear = {w["kind"]: (i, w) for i, w in enumerate(me["weapons"]) if w}
        enemies = [e for e in obs["mechs"] if e["kind"] == "mech"]
        self.observe(obs, enemies, gear)
        action = {"tick": obs["tick"], "fire": [False, False], "jump": False}
        if obs["offer"]:
            ranks = {
                "plating": 100,
                "armor": 98,
                "laser_damage": 112,
                "laser_charge": 110,
                "servos": 95,
                "lightning_range": 108,
                "lightning_efficiency": 102,
                "nanites": 97 if self.recovery else 82,
                "gun_rate": 90,
                "gun_mag": 87,
                "reactor": 83,
            }
            action["pick"] = max(
                range(len(obs["offer"]["choices"])),
                key=lambda i: ranks.get(obs["offer"]["choices"][i]["id"], 50),
            )
        target = self.target(obs, gear)
        objective, point = self.objective(obs, gear, target, action)
        if self.goal is None or self.goal[0] != objective:
            self.nav.route_after = -1
        self.goal = objective, list(point)
        move = self.steer(obs, objective, point, gear, target)
        action["move"] = list(move)
        arc_close = "laser" in gear and any(
            "lightning" in e.get("weapons", ()) and distance(me["pos"], e["pos"]) < 60 for e in enemies
        )
        sprint = (objective in ("rotate", "recover", "pickups") or arc_close) and me["energy"] > (
            25 if objective == "rotate" else 42
        )
        action["boost"] = bool(any(move) and me["grounded"] and sprint)
        if self.anchor is None or now - self.anchor_time >= 1.8:
            if (
                self.anchor is not None
                and objective != "hold"
                and distance(me["pos"], point) > 10
                and distance(me["pos"], self.anchor) < 2
            ):
                self.nav.route_after = -1
                self.steer_after = -1
                action["jump"] = me["grounded"] and me["energy"] > 50
            self.anchor, self.anchor_time = list(me["pos"]), now
        if objective == "rotate" and self.rings.launch and not self.flight:
            landing, altitude = self.rings.launch
            climb = max(0, altitude - me["pos"][2])
            if me["energy"] >= min(90, 25 + climb * 2):
                self.flight = landing, altitude, now
            else:
                action.update(move=[0, 0], boost=False, jump=False)
        if self.flight:
            landing, altitude, started = self.flight
            gap = distance(me["pos"], landing)
            if gap <= 4 or now - started > 5 or (me["energy"] < 3 and me["grounded"]):
                self.flight = None
            else:
                climbing = me["pos"][2] < altitude - 0.5
                action["jump"] = me["grounded"] and climbing
                action["boost"] = me["energy"] > 3 and (climbing or me.get("vel", [0, 0, 0])[2] < -1.5)
                action["move"] = (
                    [0, 0]
                    if me["pos"][2] < altitude - 3
                    else list(unit(landing[0] - me["pos"][0], landing[1] - me["pos"][1]))
                )
        self.weapons(obs, target, gear, arc_close or (objective == "rotate" and not me["in_zone"]), action)
        return action


if __name__ == "__main__":
    mf.run(ArenaPlanner)

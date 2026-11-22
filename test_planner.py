"""End-to-end decision checks for the planner's distinct match objectives."""

import copy
import gzip
import json
import unittest
from pathlib import Path

from planner import ArenaPlanner

ROOT = Path(__file__).resolve().parent


class PlannerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with gzip.open(ROOT / "mechfight-kit/check/stream.jsonl.gz", "rt") as stream:
            records = map(json.loads, stream)
            cls.hello = next(r for r in records if r["type"] == "hello")
            cls.sample = next(r for r in records if r["type"] == "obs")
        cls.hello["map"]["dir"] = str(ROOT / "mechfight-kit/arena")

    def setUp(self):
        self.bot = ArenaPlanner(self.hello)
        self.obs = copy.deepcopy(self.sample)
        me = self.obs["self"]
        self.p = me["pos"]
        self.obs.update(t=1, alive=16, offer=None)
        me.update(in_zone=True, grounded=True, cubes=0, aim=[0, 0], hp=me["max_hp"])
        me["weapons"][1] = None
        for k in ("mechs", "pickups", "cubes", "crates", "drops", "projectiles", "sounds", "events"):
            self.obs[k] = []
        self.obs["zone"].update(
            center=self.p[:2], next_center=self.p[:2], radius=200, next_radius=160, shrink_end=110
        )
        self.bot.arena.clear_move = lambda *args: True
        self.bot.arena.clear_shot = lambda *args: True

    def test_opening_takes_laser_and_first_cube_is_a_separate_objective(self):
        p = self.p
        item = {"id": 8001, "kind": "laser", "pos": [p[0] + 2, p[1], p[2]]}
        self.obs["pickups"] = [item]
        self.assertEqual(self.bot.act(self.obs)["take"], 8001)
        self.assertEqual(self.bot.goal[0], "pickups")
        self.obs.update(t=2, pickups=[], cubes=[{"id": 5010, "pos": [p[0] + 4, p[1], p[2]]}])
        self.obs["self"]["weapons"][1] = {
            "kind": "laser",
            "cooldown": 0,
            "charge": 0,
            "stats": self.hello["config"]["weapons"]["laser"],
        }
        self.bot.act(self.obs)
        self.assertEqual(self.bot.goal[0], "cubes")

    def test_rotation_preempts_supply_and_duel_holds_the_final_center(self):
        self.obs["drops"] = [
            {"pos": self.p[:], "holder": None, "lands_in": 0, "capture_s": 4, "progress": 0}
        ]
        self.obs["self"]["in_zone"] = False
        self.bot.act(self.obs)
        self.assertEqual(self.bot.goal[0], "rotate")
        self.obs.update(t=415, alive=2, drops=[])
        self.obs["self"]["in_zone"] = True
        self.obs["zone"].update(next_radius=0, radius=1)
        self.assertEqual(self.bot.act(self.obs)["move"], [0, 0])
        self.assertEqual(self.bot.phase, "duel")

    def test_aligned_full_laser_and_loaded_gun_share_one_aim(self):
        me = self.obs["self"]
        me["weapons"][0].update(ammo=9, cooldown=0, reload=0)
        weapon = {
            "kind": "laser",
            "cooldown": 0,
            "charge": 0.75,
            "stats": self.hello["config"]["weapons"]["laser"],
        }
        me["weapons"][1] = weapon
        foe = {
            "id": (me["id"] + 1) % 16,
            "kind": "mech",
            "pos": [self.p[0] + 75, *self.p[1:]],
            "vel": [0, 0, 0],
            "hp": 900,
        }
        self.obs.update(mechs=[foe], alive=2)
        me["aim"] = self.bot.aim_at(me, foe, "laser", weapon)[0]
        action = self.bot.act(self.obs)
        self.assertEqual(action["fire"], [True, False])
        self.assertEqual(self.bot.goal[0], "fight")

    def test_critical_health_recovers_and_forgets_shelter_after_healing(self):
        me = self.obs["self"]
        me["hp"] = me["max_hp"] * 0.2
        self.obs["mechs"] = [{"id": 9, "kind": "mech", "hp": 1400, "pos": [self.p[0] + 50, *self.p[1:]]}]
        self.bot.nav.cover = lambda *args: self.p[:]
        self.assertEqual(self.bot.act(self.obs)["move"], [0, 0])
        self.assertEqual(self.bot.goal[0], "recover")
        me["hp"] = me["max_hp"] * 0.8
        self.bot.act(self.obs)
        self.assertIsNone(self.bot.shelter)

    def test_recent_drone_damage_keeps_drone_targetable_while_recovering(self):
        p = self.p
        self.obs["self"]["hp"] = 180
        self.obs["events"] = [{"type": "damaged", "weapon": "npc", "by": 109, "bearing": 0}]
        self.obs["mechs"] = [
            {"kind": "npc", "id": 109, "pos": [p[0] + 18, *p[1:]], "hp": 160, "vel": [0, 0, 0]}
        ]
        self.bot.nav.cover = lambda *args: None
        self.bot.act(self.obs)
        self.assertEqual(self.bot.focus, 109)
        self.assertEqual(self.bot.goal[0], "fight")

    def test_recorded_ridge_has_a_route_into_the_next_ring(self):
        routes = self.bot.rings
        pos = [-193.31, 58.56, 29.64]
        zone = {"next_center": [93.85, -197.31], "next_radius": 240}
        routes.prepare(zone)
        while routes.queue:
            routes.prepare(zone)
        cell = self.bot.nav.nearest(pos)
        self.assertIn(cell, routes.next_node)
        visited = set()
        used_lift = False
        while cell in routes.next_node:
            self.assertNotIn(cell, visited)
            visited.add(cell)
            other = routes.next_node[cell]
            used_lift |= (cell, other) in routes.lifts
            cell = other
        from math import dist

        self.assertLess(dist(self.bot.nav.points[cell][:2], zone["next_center"]), zone["next_radius"])
        self.assertTrue(used_lift)

    def test_mapped_crossing_reserves_energy_then_launches(self):
        me = self.obs["self"]
        p = me["pos"]
        landing = [p[0] + 15, p[1], p[2]]
        self.bot.rings.entry = lambda *args: (90, landing, True)
        self.bot.rings.launch = landing, p[2] + 9
        me.update(energy=10, in_zone=False)
        action = self.bot.act(self.obs)
        self.assertFalse(action["boost"])
        self.assertIsNone(self.bot.flight)
        me["energy"] = 80
        action = self.bot.act(self.obs)
        self.assertTrue(action["jump"])
        self.assertTrue(action["boost"])
        self.assertIsNotNone(self.bot.flight)

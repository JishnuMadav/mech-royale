"""Regression checks for critical-health recovery and zone escape conflicts."""
import copy
import gzip
import json
import math
from pathlib import Path
import unittest

from combat import Combat
from navigation import Navigator

ROOT = Path(__file__).resolve().parent


class RecoveryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        records = [json.loads(line) for line in gzip.open(ROOT / 'mechfight-kit/check/stream.jsonl.gz', 'rt')]
        cls.hello = next(r for r in records if r['type'] == 'hello')
        cls.hello['map']['dir'] = str(ROOT / 'mechfight-kit/arena')
        cls.observation = next(r for r in records if r['type'] == 'obs')

    def scenario(self):
        bot = Combat(self.hello)
        obs = copy.deepcopy(self.observation)
        pos = obs['self']['pos']
        obs['self'].update(hp=obs['self']['max_hp'], in_zone=True, aim=[0, 0])
        for key in ('mechs', 'pickups', 'cubes', 'crates', 'drops', 'projectiles', 'events'):
            obs[key] = []
        obs['offer'] = None
        obs['zone'].update(center=pos[:2], next_center=pos[:2], radius=250, next_radius=200, shrink_end=obs['t'] + 100)
        bot.arena.clear_move = lambda *args: True
        bot.navigator.waypoint = lambda pos, goal, now: goal
        return bot, obs

    def test_weapon_sound_guides_idle_scan_and_yields_to_damage(self):
        bot, obs = self.scenario()
        obs['sounds'] = [dict(kind='gun', dist='far', age=.1, bearing=-2),
                         dict(kind='death', dist='near', age=.1, bearing=-2),
                         dict(kind='laser_charge', dist='mid', age=.5, bearing=-2)]
        self.assertAlmostEqual(bot.act(obs)['aim'][0], .3)
        obs['sounds'].append(dict(kind='gun', dist='near', age=.05, bearing=2.4))
        self.assertAlmostEqual(bot.act(obs)['aim'][0], 2.4)
        obs['sounds'] = []
        obs['t'] += .2
        self.assertAlmostEqual(bot.act(obs)['aim'][0], 2.4)
        obs['events'] = [dict(type='damaged', bearing=-1.5, weapon='gun', amount=45)]
        self.assertAlmostEqual(bot.act(obs)['aim'][0], -1.5)
        obs['events'] = []
        obs['t'] += 2.1
        self.assertAlmostEqual(bot.act(obs)['aim'][0], .3)

    def test_recovery_starts_strictly_below_25_and_finishes_at_60(self):
        bot, _ = self.scenario()
        for hp in (.85, .59, .26, .25):
            bot.update_recovery(hp)
            self.assertFalse(bot.healing)
        bot.update_recovery(.249)
        self.assertTrue(bot.healing)
        bot.update_recovery(.3)
        self.assertTrue(bot.healing)
        bot.update_recovery(.6)
        self.assertFalse(bot.healing)

    def test_does_not_seek_cover_at_half_health_when_outnumbered(self):
        bot, obs = self.scenario()
        pos = obs['self']['pos']
        obs['self']['hp'] *= .5
        obs['mechs'] = [dict(id=i + 20, kind='mech', hp=1400, cubes=0,
                             pos=[pos[0] + 80, pos[1] + i * 10, pos[2]]) for i in range(2)]
        def unexpected_cover(*args):
            self.fail('Cover search must not trigger at half health')
        bot.navigator.cover = unexpected_cover
        bot.act(obs)
        self.assertFalse(bot.healing)

    def test_keeps_safe_shelter_instead_of_relocating(self):
        bot, obs = self.scenario()
        pos = obs['self']['pos']
        obs['self']['hp'] *= .2
        obs['mechs'] = [dict(id=99, kind='mech', hp=1400, cubes=0,
                             pos=[pos[0] + 100, pos[1], pos[2]])]
        bot.cover_goal = list(pos)
        bot.arena.clear_shot = lambda *args: False
        def unexpected_cover(*args):
            self.fail('A safe occupied shelter should be retained')
        bot.navigator.cover = unexpected_cover
        action = bot.act(obs)
        self.assertEqual(bot.cover_goal, pos)
        self.assertEqual(action['move'], [0, 0])
        self.assertEqual(action['fire'], [False, False])

    def test_zone_escape_stops_new_laser_charge_and_releases_existing(self):
        bot, obs = self.scenario()
        pos = obs['self']['pos']
        obs['mechs'] = [dict(id=99, kind='mech', hp=1400, cubes=0,
                             pos=[pos[0] + 80, pos[1], pos[2]], vel=[0, 0, 0])]
        obs['self']['weapons'][1] = dict(kind='laser', cooldown=0, charge=0,
                                       stats=self.hello['config']['weapons']['laser'])
        bot.arena.clear_shot = lambda *args: True
        obs['self']['in_zone'] = False
        self.assertFalse(bot.act(obs)['fire'][1])
        obs['self']['weapons'][1]['charge'] = .2
        action = bot.act(obs)
        self.assertFalse(action['fire'][1])
        self.assertAlmostEqual(action['aim'][0], 0)
        obs['self']['in_zone'] = True
        obs['self']['weapons'][1]['charge'] = 0
        self.assertTrue(bot.act(obs)['fire'][1])

    def test_zone_escape_does_not_stop_to_capture_supply(self):
        bot, obs = self.scenario()
        pos = obs['self']['pos']
        obs['self'].update(in_zone=False, hp=obs['self']['max_hp'] * .2)
        obs['zone'].update(center=[pos[0] + 50, pos[1]], next_center=[pos[0] + 50, pos[1]], radius=40, next_radius=100)
        obs['drops'] = [dict(id=20000, pos=[pos[0] + 1, pos[1], pos[2]], radius=8,
                             lands_in=0, capture_s=4, progress=1, holder=obs['self']['id'])]
        self.assertGreater(bot.act(obs)['move'][0], .8)

    def test_zone_distance_accounts_for_wall_detour(self):
        class Map:
            bounds = dict(minX=-80, maxX=80, minY=-80, maxY=80)
            def ground(self, x, y):
                return 0
            def solid(self, x, y, low, high):
                return -10 <= x <= 10 and -40 <= y <= 40
        nav = Navigator(Map())
        zone = dict(next_center=[50, 0], next_radius=20)
        self.assertGreater(nav.zone_distance([-50, 0, 0], zone, 0), 120)
        self.assertEqual(nav.zone_distance([50, 0, 0], zone, 1), 0)
        nav.path = lambda *args: []
        self.assertGreaterEqual(nav.zone_distance([-50, 0, 0], zone, 3), 92)

    def test_laser_carrier_leaves_lightning_range_even_with_loot_ahead(self):
        bot, obs = self.scenario()
        pos = obs['self']['pos']
        obs['self']['weapons'][1] = dict(kind='laser', cooldown=0, charge=0,
                                         stats=self.hello['config']['weapons']['laser'])
        obs['mechs'] = [dict(id=5, kind='mech', hp=1400, cubes=0, vel=[0, 0, 0],
                             pos=[pos[0]+42, pos[1], pos[2]], weapons=['gun', 'lightning'])]
        obs['cubes'] = [dict(id=3000, pos=[pos[0]+20, pos[1], pos[2]])]
        bot.arena.clear_shot = lambda *args: True
        action = bot.act(obs)
        self.assertLess(action['move'][0], -.8)
        self.assertFalse(action['fire'][1])
        self.assertFalse(bot.healing)
        obs['self']['weapons'][1] = None
        obs['self']['cubes'] = 1
        obs['t'] += 1
        self.assertLess(bot.act(obs)['move'][0], -.8)

    def test_abandons_losing_lightning_duel(self):
        bot, obs = self.scenario()
        me = obs['self']
        pos = me['pos']
        me['weapons'][1] = dict(kind='lightning', cooldown=0,
                                stats=self.hello['config']['weapons']['lightning'])
        obs['mechs'] = [dict(id=(me['id']+1) % 16, kind='mech', hp=me['max_hp'],
                             pos=[pos[0]+45, pos[1], pos[2]], vel=[0,0,0], weapons=['lightning'])]
        bot.arena.clear_shot = lambda *args: True
        bot.act(obs)
        self.assertIsNone(bot.escape_direction)
        me['hp'] *= .85
        obs['t'] += .1
        self.assertLess(bot.act(obs)['move'][0], -.8)
        self.assertIsNotNone(bot.escape_direction)

    def test_two_distinct_mech_hits_trigger_escape_then_expire(self):
        bot, obs = self.scenario()
        obs['self']['cubes'] = 2
        me = obs['self']['id']
        source = (me+1) % 16
        def hit(who):
            return dict(type='damaged', by=who, weapon='gun', bearing=.7, amount=45)
        obs['events'] = [hit(source), hit(source), hit(me), hit(104)]
        bot.act(obs)
        self.assertIsNone(bot.escape_direction)
        obs['t'] += 2.9
        obs['events'] = [hit((me+2) % 16)]
        bot.act(obs)
        self.assertIsNotNone(bot.escape_direction)
        self.assertFalse(bot.healing)
        obs['t'] += .2
        obs['events'] = []
        bot.act(obs)
        self.assertIsNone(bot.escape_direction)

    def test_starter_pressure_yields_to_urgent_zone_travel(self):
        bot, obs = self.scenario()
        pos = obs['self']['pos']
        obs['t'] = 10
        obs['self'].update(cubes=0, weapons=[obs['self']['weapons'][0], None])
        obs['events'] = [dict(type='damaged', by=(obs['self']['id']+1) % 16,
                              bearing=0, weapon='gun', amount=45)]
        bot.arena.clear_shot = lambda *args: True
        self.assertLess(bot.act(obs)['move'][0], -.8)
        obs['self']['in_zone'] = False
        obs['zone']['next_center'] = [pos[0]+50, pos[1]]
        self.assertGreater(bot.act(obs)['move'][0], .8)
        self.assertIsNone(bot.escape_direction)

    def test_crossfire_facing_covers_both_reported_bearings(self):
        bot, obs = self.scenario()
        me = obs['self']['id']
        angles = [-1.2, 1.2]
        obs['events'] = [dict(type='damaged', by=(me+i+1) % 16, weapon='gun',
                              bearing=angle, amount=45) for i, angle in enumerate(angles)]
        action = bot.act(obs)
        self.assertIsNotNone(bot.escape_direction)
        self.assertTrue(all(math.cos(action['aim'][0]-a) > 0 for a in angles))

    def test_repeat_hits_from_an_unseen_gun_break_idle(self):
        bot, obs = self.scenario()
        obs['t'] = 60
        obs['self']['cubes'] = 8
        obs['events'] = [dict(type='damaged', by=(obs['self']['id']+1) % 16,
                              weapon='gun', amount=45, bearing=0)]
        bot.arena.clear_shot = lambda *args: True
        bot.act(obs)
        self.assertIsNone(bot.escape_direction)
        obs['t'] += .3
        self.assertLess(bot.act(obs)['move'][0], -.8)
        obs['events'] = []
        obs['t'] += 1.6
        bot.act(obs)
        self.assertIsNone(bot.escape_direction)


if __name__ == '__main__':
    unittest.main()

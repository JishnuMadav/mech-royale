"""Regression checks for critical-health recovery and zone escape conflicts."""
import copy
import gzip
import json
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

    def test_opening_faces_a_confirmed_hit_and_ignores_the_crate(self):
        bot, obs = self.scenario()
        me = obs['self']
        x,y,z = me['pos']
        me['weapons'][1] = None
        me['cubes'] = 0
        obs.update(t=2,alive=16)
        obs['events'] = [dict(type='damaged',by=(me['id']+1)%16,bearing=2.5,amount=45)]
        obs['crates'] = [dict(id=1000,pos=[x+20,y,z],hp=300)]
        bot.arena.clear_shot = lambda *a: True
        self.assertAlmostEqual(bot.act(obs)['aim'][0],2.5)
        self.assertIsNone(bot.target_id)
        self.assertEqual(bot.phase,'opening')

    def test_endgame_tracks_last_contact_then_expires_it(self):
        bot, obs = self.scenario()
        x,y,z = obs['self']['pos']
        obs.update(alive=6,t=45)
        obs['mechs'] = [dict(id=8,kind='mech',pos=[x,y+50,z],vel=[0,0,0],hp=800)]
        bot.act(obs)
        self.assertEqual(bot.phase,'midgame')
        obs.update(alive=3,t=46,mechs=[],sounds=[])
        self.assertAlmostEqual(bot.act(obs)['aim'][0],1.5707963)
        self.assertEqual(bot.phase,'endgame')
        obs['t']=49
        bot.act(obs)
        self.assertIsNone(bot.guarded_bearing(obs))

    def test_final_four_rotates_before_regular_zone_deadline(self):
        bot, obs = self.scenario()
        me = obs['self']
        x,y,_ = me['pos']
        obs.update(alive=4,t=90)
        obs['zone'].update(next_center=[x+120,y],next_radius=50)
        bot.navigator.zone_distance = lambda *args: 70
        obs['zone']['shrink_end'] = 90+70/me['stats']['walk_speed']+11
        bot.act(obs)
        self.assertTrue(bot.zone_urgent)

    def test_mortar_pickup_respects_recent_laser_but_allows_other_weapons(self):
        bot, obs = self.scenario()
        me = obs['self']
        x,y,z = me['pos']
        me['weapons'][1] = None
        obs.update(alive=8, t=10)
        obs['pickups'] = [dict(id=8014,kind='mortar',pos=[x+1,y,z])]
        obs['mechs'] = [dict(id=5,kind='mech',pos=[x+120,y,z],hp=1200,weapons=['gun','laser'])]
        self.assertNotIn('take',bot.act(obs))
        obs.update(t=12,mechs=[])
        self.assertNotIn('take',bot.act(obs))
        obs['pickups'].append(dict(id=8001,kind='lightning',pos=[x,y+1,z]))
        self.assertEqual(bot.act(obs)['take'],8001)
        obs.update(t=17,pickups=obs['pickups'][:1],sounds=[])
        self.assertEqual(bot.act(obs)['take'],8014)

    def test_final_duel_opens_gap_without_starting_another_charge(self):
        bot, obs = self.scenario()
        me = obs['self']
        x,y,z = me['pos']
        me['grounded'] = True
        me['energy'] = me['max_energy']
        me['weapons'][1] = dict(kind='laser', cooldown=0, charge=0,
                                stats=self.hello['config']['weapons']['laser'])
        obs.update(alive=2,t=60)
        obs['mechs'] = [dict(id=5,kind='mech',hp=1000,pos=[x+35,y,z],weapons=['gun','lightning'])]
        bot.arena.clear_shot = lambda *args: True
        action=bot.act(obs)
        self.assertLess(action['move'][0],-.7)
        self.assertTrue(action['boost'])
        self.assertFalse(action['fire'][1])
        obs.update(t=61,mechs=[])
        self.assertLess(bot.act(obs)['move'][0],-.5)
        obs['t']=64
        self.assertIsNone(bot.read_matchups(obs,[]))
        obs.update(alive=3,t=65)
        self.assertIsNone(bot.read_matchups(obs,[dict(pos=[x+35,y,z],weapons=['lightning'])]))

    def test_duel_chooses_in_circle_heading_near_the_rim(self):
        bot, obs = self.scenario()
        x,y,z = obs['self']['pos']
        obs['zone'].update(center=[x+28,y],radius=30,next_center=[x+28,y],next_radius=30)
        action={}
        bot.phase='endgame'
        bot.navigate(action,obs,(-1,0),(x+20,y),70)
        dx,dy = action['move']
        self.assertLessEqual((10*dx-28)**2+(10*dy)**2,28**2)

    def test_tiny_final_circle_keeps_laser_available(self):
        bot, obs = self.scenario()
        me = obs['self']
        x,y,z = me['pos']
        obs.update(alive=2,t=90)
        obs['zone'].update(center=[x+9,y],radius=16,next_center=[x+9,y],next_radius=16)
        obs['mechs'] = [dict(id=5,kind='mech',hp=1000,pos=[x+16,y,z],weapons=['lightning'])]
        me['weapons'][1] = dict(kind='laser',cooldown=0,charge=0,stats=self.hello['config']['weapons']['laser'])
        bot.arena.clear_shot = lambda *args: True
        self.assertTrue(bot.act(obs)['fire'][1])

    def test_duel_uses_rotation_buffer_only_with_time_to_return(self):
        bot, obs = self.scenario()
        me = obs['self']
        x,y,z = me['pos']
        obs.update(t=90,alive=2)
        obs['zone'].update(next_center=[x+95,y],next_radius=25,shrink_end=107)
        obs['mechs'] = [dict(id=5,kind='mech',hp=1000,pos=[x+40,y,z],weapons=['lightning'])]
        me['weapons'][1] = dict(kind='laser',cooldown=0,charge=0,stats=self.hello['config']['weapons']['laser'])
        bot.navigator.zone_distance = lambda *a:70
        bot.arena.clear_shot = lambda *args: True
        self.assertLess(bot.act(obs)['move'][0],-.5)
        self.assertTrue(bot.zone_urgent)
        obs['zone']['shrink_end'] = 92
        self.assertGreater(bot.act(obs)['move'][0],0)

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


if __name__ == '__main__':
    unittest.main()

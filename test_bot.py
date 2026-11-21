"""Regression checks for interception and every official recorded observation."""
import gzip
import json
import math
from pathlib import Path
import unittest

from bot import Bot, inside, lead


ROOT = Path(__file__).resolve().parent


class BotTests(unittest.TestCase):
    def test_intercept(self):
        target = {'pos': [100, 0, 0], 'vel': [0, 10, 0]}
        point = lead([0, 0, 0], target, 100)
        travel_time = math.dist([0, 0, 0], point) / 100
        self.assertAlmostEqual(point[1], 10 * travel_time)

    def test_polygon(self):
        ring = [0, 0, 10, 0, 10, 10, 0, 10]
        self.assertTrue(inside(5, 5, ring))
        self.assertFalse(inside(15, 5, ring))

    def test_recording_without_wrapper_fallback(self):
        with gzip.open(ROOT / 'mechfight-kit/check/stream.jsonl.gz', 'rt') as stream:
            messages = [json.loads(line) for line in stream if line.strip()]
        hello = next(m for m in messages if m['type'] == 'hello')
        hello['map']['dir'] = str(ROOT / 'mechfight-kit/arena')
        bot = Bot(hello)
        count = 0
        for obs in messages:
            if obs['type'] != 'obs':
                continue
            action = bot.act(obs)
            json.dumps(action, allow_nan=False)
            self.assertEqual(action['tick'], obs['tick'])
            self.assertLessEqual(math.hypot(*action['move']), 1.000001)
            self.assertEqual(len(action['fire']), 2)
            count += 1
        self.assertGreaterEqual(count, 300)


if __name__ == '__main__':
    unittest.main()

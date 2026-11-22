"""Shared aiming geometry for the Mech Royale game weapons."""
import math

from bot import angle_delta, lead


class WeaponGeometry:
    def aim_at(self, me, target, kind, weapon):
        scale = 1 + 0.05 * target.get('cubes', 0)
        height = 4.5 * scale if target.get('kind') == 'mech' else 1.75 if target.get('kind') == 'npc' else 1.0
        stats = weapon['stats']
        origin = [*me['pos'][:2], me['pos'][2] + me['stats']['muzzle_height']]
        center = [*target['pos'][:2], target['pos'][2] + height]
        if kind == 'gun':
            point = lead(origin, dict(target, pos=center), stats['speed'])
        elif kind == 'mortar':
            origin[2] = me['pos'][2] + me['stats']['height'] + 0.5
            point = list(center)
            pitch = None
            for _ in range(3):
                distance = math.dist(origin[:2], point[:2])
                dz = point[2] - origin[2]
                v, g = stats['speed'], stats['gravity']
                disc = v**4 - g * (g * distance**2 + 2 * dz * v*v)
                if disc < 0 or distance < 12:
                    return None
                pitch = math.atan2(v*v - math.sqrt(disc), g * distance)
                flight = distance / max(1, v * math.cos(pitch))
                point = [center[i] + target.get('vel', [0, 0, 0])[i] * flight for i in range(3)]
            if not me['stats']['min_pitch'] <= pitch <= me['stats']['max_pitch']:
                return None
            return [math.atan2(point[1] - origin[1], point[0] - origin[0]), pitch], origin, point
        else:
            point = center
        dx, dy, dz = [point[i] - origin[i] for i in range(3)]
        return [math.atan2(dy, dx), math.atan2(dz, math.hypot(dx, dy))], origin, point

    def laser_should_release(self, me, target, weapon):
        stats = weapon['stats']
        charge = weapon.get('charge', 0)
        if charge + .01 >= stats['charge']:
            return True
        if charge < stats['min_charge']:
            return False
        damage = stats['damage'] * (1 + .04 * min(10, me['cubes']))
        damage *= stats['min_frac'] + (1 - stats['min_frac']) * charge / stats['charge']
        if target.get('kind') == 'mech':
            # Enemy upgrades are hidden. Assume all three armor stacks and
            # leave a margin for rounded HP and observations between ticks.
            damage *= .76
            if 'mortar' in target.get('weapons', []):
                damage *= 1 + stats['cookoff']
        return damage >= target.get('hp', math.inf) + 15

    def aligned(self, me, aim, distance, radius=2.0):
        # The server slews the torso before simulating shots. Permit a trigger
        # when it can align during the next simulation tick, not only when the
        # previous observation already happened to be aligned.
        yaw_error = max(0, abs(angle_delta(aim[0], me['aim'][0])) - me['stats']['turn_rate'] * 0.05)
        pitch_error = max(0, abs(aim[1] - me['aim'][1]) - me['stats']['pitch_rate'] * 0.05)
        return yaw_error <= max(0.018, math.atan2(radius, max(1, distance))) and pitch_error <= max(0.02, math.atan2(3, max(1, distance)))

"""Ground routes for the opening seconds before collecting a cube or second weapon."""
import math
import time

from bot import inside


class Opening:
    def __init__(self, nav):
        self.nav = nav
        self.edges = []
        for point in nav.points.values():
            x, y, z = point
            for dx, dy in ((10, 0), (-10, 0), (0, 10), (0, -10), (8, 8), (-8, 8), (8, -8), (-8, -8)):
                qx, qy = x + dx, y + dy
                nearby = nav.arena.bins.get((math.floor(qx / 32), math.floor(qy / 32)), ())
                if any(p['kind'] == 'building' and p['top'] > z + 5 and x0 <= qx <= x1 and y0 <= qy <= y1
                       and inside(qx, qy, p['ring']) and not any(inside(qx, qy, h) for h in p['holes'])
                       for x0, y0, x1, y1, p in nearby):
                    self.edges.append(point)
                    break
        self.mode = None
        self.route = []
        self.after = -1
        self.key = None

    def route_to(self, pos, goal, stats):
        def direct(a, b):
            distance = math.dist(a[:2], b[:2])
            if distance < 1:
                return True
            direction = ((b[0]-a[0])/distance, (b[1]-a[1])/distance)
            for step in range(0, math.ceil(distance), 3):
                x, y = a[0]+step*direction[0], a[1]+step*direction[1]
                if not self.nav.arena.clear_move((x, y, self.nav.arena.ground(x,y)), direction, stats):
                    return False
            return True
        if direct(pos, goal):
            return [goal], math.dist(pos, goal)
        path = self.nav.path(pos, goal, limit=450)
        if not path or not direct(pos, path[0]) or not direct(path[-1], goal):
            return [], math.inf
        path.append(goal)
        return path, math.dist(pos, path[0]) + sum(math.dist(a, b) for a,b in zip(path,path[1:]))

    def choose(self, me, zone, pickups, enemies, now, radius):
        pos, stats = me['pos'], me['stats']
        items = sorted((p for p in pickups if p['kind'] != 'gun' and abs(p['pos'][2]-pos[2]) <= 4
                        and math.dist(pos, p['pos']) <= 90), key=lambda p: math.dist(pos,p['pos']))[:3]
        enemies = sorted(enemies, key=lambda e: math.dist(pos, e['pos']))[:4]
        key = (tuple(p['id'] for p in items), tuple(e['id'] for e in enemies))
        if now >= self.after or key != self.key:
            self.key, self.after = key, now + .85
            self.mode, self.route = None, []
            deadline = time.perf_counter() + .008
            best = math.inf
            for item in items:
                q = item['pos']
                if math.dist(q[:2], zone['center']) > zone['radius'] - stats['radius']:
                    continue
                route, length = self.route_to(pos, q, stats)
                # Estimate our sprint from available energy; give every visible rival
                # a direct sprint, even when its own route might be obstructed.
                sprint_seconds = max(0, me['energy'] - 30) / max(1, stats.get('boost_drain', 18))
                travel = max(0, length-radius)
                sprint = min(travel, sprint_seconds*stats['boost_speed'])
                eta = sprint/stats['boost_speed'] + (travel-sprint)/stats['walk_speed']
                rival = min((max(0, math.dist(q[:2], e['pos'][:2])-radius) /
                             max(stats['boost_speed'], math.hypot(*e.get('vel', [0,0])[:2])) for e in enemies),
                            default=math.inf)
                if route and eta <= 4 and eta + .35 < rival and eta < best:
                    self.mode, self.route, best = 'weapon', route, eta
                if time.perf_counter() >= deadline:
                    break
            if not self.route:
                center = zone['next_center']
                candidates = sorted((q for q in self.edges if 6 <= math.dist(pos,q) <= 85
                                     and math.dist(q[:2], zone['center']) < zone['radius']-6),
                                    key=lambda q: math.dist(pos,q) + .4*math.dist(q[:2],center))[:12]
                for q in candidates:
                    if time.perf_counter() >= deadline:
                        break
                    route, length = self.route_to(pos, q, stats)
                    if not route or length > 100:
                        continue
                    seen = sum(self.nav.arena.clear_shot([*e['pos'][:2],e['pos'][2]+7],
                                                         [*q[:2],q[2]+7]) for e in enemies)
                    score = length + .65*(math.dist(q[:2],center)-math.dist(pos[:2],center)) + 35*seen
                    if score < best:
                        self.mode, self.route, best = 'edge', route, score
        while len(self.route) > 1 and math.dist(pos[:2],self.route[0][:2]) < 4:
            self.route.pop(0)
        return self.route[0][:2] if self.route else None

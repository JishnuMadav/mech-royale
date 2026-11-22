"""Time-sliced, multi-source routes into the next Mech Royale circle."""

import heapq
import math
import time


class RingRoutes:
    def __init__(self, nav):
        self.nav = nav
        self.incoming = {cell: [] for cell in nav.points}
        labels = {}
        for cell in nav.points:
            if cell in labels:
                continue
            todo = [cell]
            labels[cell] = cell
            while todo:
                node = todo.pop()
                for other, cost in nav.links[node]:
                    self.incoming[other].append((node, cost))
                    if other not in labels:
                        labels[other] = cell
                        todo.append(other)

        # The normal two-way navigation graph excludes drops too steep to
        # climb. Test downward crossings between distinct graph components.
        # Directed links let a mech leave a ridge without routing back up it.
        self.drop_links = set()
        self.lifts = {}
        self.launch = None
        for cell in nav.cover_nodes:
            x, y = cell
            p = nav.points[cell]
            for dx, dy in (
                (1, 0),
                (-1, 0),
                (0, 1),
                (0, -1),
                (1, 1),
                (-1, -1),
                (1, -1),
                (-1, 1),
                (2, 0),
                (-2, 0),
                (0, 2),
                (0, -2),
            ):
                other = (x + dx, y + dy)
                q = nav.points.get(other)
                if q is None or labels[other] == labels[cell]:
                    continue
                length = math.dist(p[:2], q[:2])
                count = math.ceil(length / 2)
                last_z = p[2]
                for step in range(1, count + 1):
                    xx = p[0] + (q[0] - p[0]) * step / count
                    yy = p[1] + (q[1] - p[1]) * step / count
                    ground = nav.arena.ground(xx, yy)
                    if ground > last_z + 2.4 or not nav.open_point(xx, yy, ground):
                        break
                    last_z = ground
                else:
                    self.incoming[other].append((cell, length + 5 + 0.15 * abs(p[2] - q[2])))
                    self.drop_links.add((cell, other))
                    continue
                for height in (max(p[2], q[2]) + 3, max(p[2], q[2]) + 9, max(p[2], q[2]) + 16):
                    if height - p[2] > 25 or height - q[2] > 42:
                        continue
                    if any(nav.arena.solid(x0, y0, z0 + 1, height + 9) for x0, y0, z0 in (p, q)):
                        continue
                    for step in range(count + 1):
                        xx = p[0] + (q[0] - p[0]) * step / count
                        yy = p[1] + (q[1] - p[1]) * step / count
                        if nav.arena.ground(xx, yy) > height - 1 or not nav.open_point(xx, yy, height):
                            break
                    else:
                        self.incoming[other].append((cell, length + 45 + 2 * (height - p[2])))
                        self.lifts[(cell, other)] = height
                        break
        self.key = None
        self.queue = []
        self.cost = {}
        self.next_node = {}

    def prepare(self, zone):
        center = zone["next_center"]
        radius = max(0, zone["next_radius"] - min(15, 0.3 * zone["next_radius"]))
        key = (*center, radius)
        if key != self.key:
            self.key = key
            self.next_node = {}
            seeds = [
                c
                for c, p in self.nav.points.items()
                if max(0, radius - 18) <= math.dist(p[:2], center) <= radius
            ]
            if not seeds:
                c = self.nav.nearest(center)
                seeds = [c] if c is not None else []
            self.cost = {c: 0 for c in seeds}
            self.queue = [(0, c) for c in seeds]
            heapq.heapify(self.queue)
        deadline = time.perf_counter() + 0.0015
        while self.queue and time.perf_counter() < deadline:
            dist, cell = heapq.heappop(self.queue)
            if dist != self.cost[cell]:
                continue
            for source, length in self.incoming[cell]:
                new = dist + length
                if new < self.cost.get(source, math.inf):
                    self.cost[source] = new
                    self.next_node[source] = cell
                    heapq.heappush(self.queue, (new, source))

    def entry(self, pos, zone, now):
        self.launch = None
        self.prepare(zone)
        center = zone["next_center"]
        if math.dist(pos[:2], center) <= self.key[-1]:
            return 0, center, False
        cell = self.nav.nearest(pos)
        if cell not in self.cost:
            return self.nav.zone_distance(pos, zone, now), center, False
        remaining = self.cost[cell] + math.dist(pos, self.nav.points[cell])
        first = self.next_node.get(cell)
        if first is None:
            return remaining, center, False
        # Keep both the departure and landing of a directed drop on the route.
        lift = self.lifts.get((cell, first))
        crossing = (cell, first) in self.drop_links or lift is not None
        if crossing and math.dist(pos[:2], self.nav.points[cell][:2]) > 5:
            return remaining, self.nav.points[cell], True
        if lift is not None:
            self.launch = self.nav.points[first], lift
        return remaining, self.nav.points[first], True

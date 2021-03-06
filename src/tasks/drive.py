from experience import Experience

from collections import defaultdict, namedtuple
import json
import numpy as np
import os

MAP_1 = """
###.*###
###s.###
###..###
*.....w.
.e.....*
###..###
###.n###
###*.###
"""

MAP_2 = """
####*###
####.###
####.###
*.....w.
.e.....*
####.###
####n###
####.###
"""

MAP_3 = """
###.*###
###s.###
###..###
*....###
.e...###
###..###
###.n###
###*.###
"""

MAP_4 = """
##.*####
##s.####
##..####
*.....w.
.e.....*
####..##
####.n##
####*.##
"""

MAP_5 = """
##***###
##...###
##...###
##...###
##...###
##...###
##nnn###
##...###
"""

N_LEX = 83
#N_LEX = 2

MAPS = [MAP_1, MAP_2, MAP_3, MAP_4, MAP_5]
MAP_SHAPE = (8, 8)

DIRS = {"n": 0, "e": 1, "s": 2, "w": 3}

Car = namedtuple("Car", ["pos", "dir", "goal", "done"])

N_FEATURES = (
    len(MAPS)
    + MAP_SHAPE[0] * MAP_SHAPE[1] * 2
    + 1
    + len(DIRS))


class DriveTask(object):
    def __init__(self):
        #self.random = np.random.RandomState(0)
        self.randoms = {
            "train": np.random.RandomState(1290),
            "val": np.random.RandomState(1482),
            "test": np.random.RandomState(9424)
        }
        self.n_agents = 2
        self.symmetric = True
        self.n_actions = (4, 4)
        self.n_features = N_FEATURES
        #self.vocab = {"_": 0, "UNK": 1}
        #self.reverse_vocab = {0: "_", 1: "UNK"}
        #self.lexicon = [[0]]

        self.vocab = {"_": 0, "UNK": 1, "done": 2}
        self.reverse_vocab = {0: "_", 1: "UNK", 2: "done"}
        self.lexicon = [[0], [2]]

        self.roads = []
        for map_str in MAPS:
            template = map_str.split("\n")[1:-1]
            road = np.zeros(MAP_SHAPE)
            for r in range(MAP_SHAPE[0]):
                for c in range(MAP_SHAPE[1]):
                    road[r, c] = 0 if template[r][c] == "#" else 1
            self.roads.append(road)

        self.train_demonstrations, self.test_demonstrations = self.load_traces()
        self.test_counter = 0
        #self.max_desc_len = max(len(d) for dem in self.demonstrations for ex in
        #        dem for d in ex.s1.desc)

    def reset_test(self):
        self.randoms["val"] = np.random.RandomState(1482)
        self.randoms["test"] = np.random.RandomState(9424)

    def load_traces(self):
        traces = []

        ngrams = defaultdict(lambda: 0)

        def tokenize(d):
            return (d.lower()
                    .replace(".", "")
                    .replace(",", "")
                    .replace("?", "")
                    .split())

        for filename in os.listdir("data/drive/server_logs"):
            if not filename.endswith("json"):
                continue
            with open("data/drive/server_logs/" + filename) as trace_f:
                data = json.load(trace_f)

            inputs = data[1::2]
            for inp1, inp2 in inputs:
                t1, t2 = tokenize(inp1["message"]), tokenize(inp2["message"])
                if len(t1) <= 3:
                    ngrams[tuple(t1)] += 1
                if len(t2) <= 3:
                    ngrams[tuple(t2)] += 1
                #for i in range(len(t1) - 2):
                #    ngrams[tuple(t1[i:i+3])] += 1
                #for i in range(len(t2) - 2):
                #    ngrams[tuple(t2[i:i+3])] += 1

        #freq = sorted(ngrams.items(), key=lambda p: -p[1])
        #for f in freq:
        #    print f
        #exit()

        for ngram, count in ngrams.items():
            if count <= 3:
                continue
            for word in ngram:
                if word in self.vocab:
                    continue
                index = len(self.vocab)
                self.vocab[word] = index
                self.reverse_vocab[index] = word
            self.lexicon.append([self.vocab[w] for w in ngram])

        assert len(self.lexicon) == N_LEX, str(len(self.lexicon))

        def make_rep(tokens):
            rep = np.zeros(len(self.lexicon))
            for i_l, l in enumerate(self.lexicon):
                if len(l) > 0 and all(self.reverse_vocab[w] in tokens for w in l):
                    rep[i_l] = 1
            if not rep.any():
                rep[0] = 1
            rep /= np.sum(rep)
            return rep

        for filename in os.listdir("data/drive/server_logs"):
            if not filename.endswith("json"):
                continue
            with open("data/drive/server_logs/" + filename) as trace_f:
                data = json.load(trace_f)

            init = data[0]
            inputs = data[1::2]

            road = np.zeros(MAP_SHAPE)
            for r in range(MAP_SHAPE[0]):
                for c in range(MAP_SHAPE[1]):
                    road[r, c] = init["road"][r][c]

            maybe_map_id = [i for i in range(len(MAPS)) if (self.roads[i] == road).all()]
            if len(maybe_map_id) == 0:
                continue
            map_id, = maybe_map_id

            cars = []
            for car_data in init["cars"]:
                cars.append(Car(
                    tuple(car_data["pos"]), car_data["dir"],
                    tuple(car_data["goal"]), car_data["done"]))

            state = DriveState(map_id, road, cars)
            episode = []
            for inp1, inp2 in inputs:
                action = (inp1["action"], inp2["action"])
                d1 = tokenize(inp1["message"])
                d2 = tokenize(inp2["message"])
                r1, r2 = make_rep(d1), make_rep(d2)
                desc = (r2, r1)
                #r1 = [0, 1] if state.cars[1].done else [1, 0]
                #r2 = [0, 1] if state.cars[0].done else [1, 0]
                #desc = (np.asarray(r1), np.asarray(r2))
                state_, reward, done = state.step(action)
                state_.l_msg = desc
                episode.append(Experience(
                    state, None, action, state_, None, reward, done))
                state = state_

            traces.append(episode)

        train_traces = traces[:-100]
        test_traces = traces[-100:]
        return train_traces, test_traces

    def get_demonstration(self, fold):
        if fold in ("train", "val"):
            demos = self.train_demonstrations
            i = self.randoms[fold].randint(len(demos))
        else:
            assert fold == "test"
            demos = self.test_demonstrations
            i = self.test_counter
            self.test_counter += 1
            self.test_counter %= len(demos)
        return demos[i]

    def get_instance(self, fold, map_id=None):
        random = self.randoms[fold]
        if map_id is None:
            map_id = random.randint(len(MAPS))
        map_str = MAPS[map_id]
        template = map_str.split("\n")[1:-1]
        start_indices = [
                (r, c) for r in range(MAP_SHAPE[0]) for c in range(MAP_SHAPE[1])
                if template[r][c] in ("n", "e", "s", "w")]
        goal_indices = [
                (r, c) for r in range(MAP_SHAPE[0]) for c in range(MAP_SHAPE[1])
                if template[r][c] == "*"]

        agent1_start = start_indices[random.randint(len(start_indices))]
        agent1_dir = DIRS[template[agent1_start[0]][agent1_start[1]]]
        start_indices.remove(agent1_start)
        agent2_start = start_indices[random.randint(len(start_indices))]
        agent2_dir = DIRS[template[agent2_start[0]][agent2_start[1]]]
        agent1_goal = goal_indices[random.randint(len(goal_indices))]
        agent2_goal = goal_indices[random.randint(len(goal_indices))]

        cars = [Car(agent1_start, agent1_dir, agent1_goal, False),
                Car(agent2_start, agent2_dir, agent2_goal, False)]

        return DriveState(map_id, self.roads[map_id], cars)

    def distractors_for(self, state, obs_agent, n_samples):
        random = self.randoms["val"]
        out = []
        for _ in range(n_samples):
            pos = None
            while pos is None:
                pos = (random.randint(MAP_SHAPE[0]),
                            random.randint(MAP_SHAPE[1]))
                if not state.road[pos]:
                    pos = None
            inst = self.get_instance("val", state.map_id)
            cars = []
            for i_car, car in enumerate(state.cars):
                if i_car == obs_agent:
                    cars.append(state.cars[i_car])
                else:
                    cars.append(inst.cars[i_car]._replace(pos=pos, dir=random.randint(4)))
            out.append((DriveState(state.map_id, state.road, cars), 1))
        return out

    def visualize(self, state, agent):
        draw = [[None for _ in range(MAP_SHAPE[1])] for _ in range(MAP_SHAPE[0])]
        car = state.cars[agent]

        for r in range(MAP_SHAPE[0]):
            for c in range(MAP_SHAPE[1]):
                if state.road[r, c]:
                    draw[r][c] = "."
                else:
                    draw[r][c] = " "

        if not car.done:
            r, c = car.pos
            r2, c2 = r, c
            draw[r][c] = "C"
            if car.dir == 0:
                r2 += 1
            elif car.dir == 1:
                c2 -= 1
            elif car.dir == 2:
                r2 -= 1
            elif car.dir == 3:
                c2 += 1
            if 0 <= r2 < state.road.shape[0] and 0 <= c2 < state.road.shape[1]:
                draw[r2][c2] = "C"

            rg, cg = car.goal
            draw[rg][cg] = "*"

        return "<pre style='color: #fff; background: #000'>\n" + "\n".join(["".join(r) for r in draw]) + "\n</pre>"

    def pp(self, indices):
        return " ".join([self.reverse_vocab[i] for i in indices])

class DriveState(object):
    def __init__(self, map_id, road, cars):
        self.map_id = map_id
        self.road = road
        self.cars = cars
        self.l_msg = [np.zeros(N_LEX), np.zeros(N_LEX)]
        self._cached_obs = None
        self.success = all(c.done for c in cars)

    def obs(self):
        if self._cached_obs is None:
            self._cached_obs =  tuple(self._obs(car) for car in self.cars)
            #o = np.concatenate([self._obs(car) for car in self.cars])
            #self._cached_obs = tuple(o for _ in self.cars)
        return self._cached_obs

    def _obs(self, car):
        map_features = np.zeros(len(MAPS))
        map_features[self.map_id] = 1
        if car.done:
            return np.zeros(N_FEATURES)
        goal = np.zeros(self.road.shape)
        pos = np.zeros(self.road.shape)
        direction = np.zeros((len(DIRS),))
        pos[car.pos] = 1
        goal[car.goal] = 1
        #pos = np.array(car.pos) / MAP_SHAPE[0]
        #goal = np.array(car.goal) / MAP_SHAPE[0]
        direction[car.dir] = 1
        return np.concatenate(
                (map_features, 
                    #self.road.ravel(), 
                    pos.ravel(), goal.ravel(), [car.done],
                    #pos, goal,
                    direction))

    def _move(self, car, action):
        nr, nc = car.pos
        ndir = car.dir
        turn = False
        if action == 0:
            pass
        elif action == 1:
            if car.dir == 0:
                nr -= 1
            elif car.dir == 1:
                nc += 1
            elif car.dir == 2:
                nr += 1
            elif car.dir == 3:
                nc -= 1
        elif action == 2:
            ndir -= 1
            turn = True
        elif action == 3:
            ndir += 1
            turn = True
        ndir %= 4

        if turn:
            if ndir == 0:
                nr -= 1
            elif ndir == 1:
                nc += 1
            elif ndir == 2:
                nr += 1
            elif ndir == 3:
                nc -= 1

        nr = min(nr, self.road.shape[0]-1)
        nc = min(nc, self.road.shape[1]-1)
        nr = max(nr, 0)
        nc = max(nc, 0)

        if car.done:
            nr, nc = -1, -1

        return Car((nr, nc), ndir, car.goal, car.done)

    def step(self, actions):
        assert len(actions) == len(self.cars)
        ncars = [self._move(c, a) for c, a in zip(self.cars, actions)]
        occupied = np.zeros(self.road.shape)
        heads = np.zeros(self.road.shape)
        tails = np.zeros(self.road.shape)
        for car in ncars:
            if car.done:
                continue
            pos = car.pos
            r2, c2 = car.pos
            if car.dir == 0:
                r2 += 1
            elif car.dir == 1:
                c2 -= 1
            elif car.dir == 2:
                r2 -= 1
            elif car.dir == 3:
                c2 += 1
            occupied[pos] += 1
            heads[pos] += 1
            if 0 <= r2 < self.road.shape[0] and 0 <= c2 < self.road.shape[1]:
                occupied[r2, c2] += 1
                tails[r2, c2] += 1

        off = 0
        crash = False
        draw = [[None for _ in range(MAP_SHAPE[1])] for _ in range(MAP_SHAPE[0])]
        for r in range(self.road.shape[0]):
            for c in range(self.road.shape[1]):
                draw[r][c] = "." if self.road[r][c] else " "
                for car in ncars:
                    draw[car.goal[0]][car.goal[1]] = "G"
                if heads[r, c] > 0:
                    draw[r][c] = "#"
                if tails[r, c] > 0:
                    draw[r][c] = "O"
                if occupied[r, c] > 0 and self.road[r, c] == 0:
                    off += 1
                if occupied[r, c] > 1:
                    crash = True

        #reverse = len([a for a in actions if a == 1])

        final_cars = []
        n_success = 0
        n_improved = 0
        for ocar, ncar in zip(self.cars, ncars):
            if ncar.done:
                final_cars.append(ncar)
            elif ncar.pos == ncar.goal:
                n_success += 1
                final_cars.append(ncar._replace(done=True))
            else:
                #old_dist = np.sum(np.abs(ocar.goal - ocar.pos))
                #new_dist = np.sum(np.abs(ncar.goal - ncar.pos))
                old_dist = sum(abs(p-q) for p, q in zip(ocar.goal, ocar.pos))
                new_dist = sum(abs(p-q) for p, q in zip(ncar.goal, ncar.pos))
                n_improved += old_dist - new_dist
                final_cars.append(ncar)

        reward = 0
        stop = False
        if all(car.done for car in final_cars):
            stop = True
        if crash:
            reward -= 2.0
            stop = True
        reward -= 0.01
        reward -= 0.5 * off
        reward += 1.0 * n_success
        reward += 0.1 * n_improved

        #print "\n".join(["".join(row) for row in draw])
        #print reward
        #print

        return DriveState(self.map_id, self.road, final_cars), reward, stop

from experience import Experience
import trainer
from util import Break

import json
import numpy as np
import tensorflow as tf

def kl(d1, d2, w1, w2):
    assert len(d1.shape) == len(d2.shape) == 2
    assert len(w1.shape) == len(w2.shape) == 1
    tot = 0
    for i in range(d1.shape[0]):
        for j in range(d1.shape[1]):
            tot += w1[i] * w2[i] * d1[i, j] * (np.log(d1[i,j])-np.log(d2[i,j]))
    return tot

def fkl(d1, d2, w1, w2):
    return kl(d1, d2, w1, w2)

def rkl(d1, d2, w1, w2):
    return kl(d2, d1, w2, w1)

def skl(d1, d2, w1, w2):
    return kl(d1, d2, w1, w2) + kl(d2, d1, w2, w1)

def dot(d1, d2, w1, w2):
    return -np.dot(w1, w2)

def pmi(d1, d2, w1, w2):
    return -np.dot(w1, w2) / (np.sum(w1) * np.sum(w2))

def get_comparator(mode):
    if mode == "skl":
        comparator = skl
    elif mode == "fkl":
        comparator = fkl
    elif mode == "rkl":
        comparator = rkl
    elif mode == "dot":
        comparator = dot
    elif mode == "pmi":
        comparator = pmi
    else:
        assert False
    return comparator

class Lexicographer(object):
    def __init__(self, states, codes, l_msgs, ph, translator, task, session,
            config):
        self.states = states
        self.distractors = []
        self.codes = codes
        self.l_msgs = l_msgs
        self.translator = translator
        self.task = task
        self.config = config
        self.session = session
        self.ph = ph

        xb = np.zeros((config.trainer.n_batch_episodes, task.n_features))
        xa_true = np.zeros((config.trainer.n_batch_episodes, task.n_features))
        xa_noise = np.zeros(
                (config.trainer.n_batch_episodes, config.trainer.n_distractors,
                    task.n_features))
        for i, state in enumerate(states):
            xb[i, :] = state.obs()[1]
            xa_true[i, :] = state.obs()[0]
            distractors = task.distractors_for(state, 1, config.trainer.n_distractors)
            self.distractors.append(distractors)
            for i_dis in range(len(distractors)):
                dis, _ = distractors[i_dis]
                xa_noise[i, i_dis, :] = dis.obs()[0]

        self.xb = xb
        self.xa_true = xa_true
        self.xa_noise = xa_noise

        all_l_beliefs = []
        all_l_weights = []
        for l_msg in l_msgs:
            l_beliefs, l_weights = self.compute_l_belief(l_msg)
            all_l_beliefs.append(l_beliefs)
            all_l_weights.append(l_weights)
        self.l_beliefs = all_l_beliefs
        self.l_weights = all_l_weights

        all_model_beliefs = []
        all_model_weights = []
        for code in codes:
            model_beliefs, model_weights = self.compute_code_belief(code)
            all_model_beliefs.append(model_beliefs)
            all_model_weights.append(model_weights)
        self.model_beliefs = all_model_beliefs
        self.model_weights = all_model_weights

    def compute_l_belief(self, l_msg, raw_features=None):
        l_data = np.zeros(
                (self.config.trainer.n_batch_episodes, len(self.task.lexicon)))
        if raw_features is None:
            l_data[:, self.task.lexicon.index(l_msg)] = 1
        else:
            l_data[:, :] = raw_features
        feed = {
            self.ph.t_xb: self.xb,
            self.ph.t_xa_true: self.xa_true,
            self.ph.t_xa_noise: self.xa_noise,
            self.ph.t_l_msg: l_data
        }
        l_beliefs, l_weights = self.session.run(
                [self.translator.t_desc_belief, self.translator.t_desc_weights],
                feed)
        return l_beliefs, l_weights

    def compute_code_belief(self, code):
        code_data = [code] * self.config.trainer.n_batch_episodes
        feed = {
            self.ph.t_xb: self.xb,
            self.ph.t_xa_true: self.xa_true,
            self.ph.t_xa_noise: self.xa_noise,
            self.ph.t_z: code_data
        }
        model_beliefs, model_weights = self.session.run(
                [self.translator.t_model_belief, self.translator.t_model_weights],
                feed)
        return model_beliefs, model_weights

    def l_to_c(self, l_msg, mode):
        if not l_msg.any():
            return np.zeros(self.config.channel.n_msg)
        l_belief, l_weights = self.compute_l_belief(None, raw_features=l_msg)
        comparator = get_comparator(mode)
        candidates = sorted(
                range(len(self.codes)),
                key=lambda i: comparator(
                    l_belief, self.model_beliefs[i],
                    l_weights, self.model_weights[i]
                ))
        return [self.codes[c] for c in candidates[:10]]

    def c_to_l(self, code, mode):
        if not code.any():
            return [[0]]
        code_belief, code_weights = self.compute_code_belief(code)
        comparator = get_comparator(mode)
        candidates = sorted(
                range(len(self.l_msgs)),
                key=lambda i: comparator(
                    code_belief, self.l_beliefs[i], 
                    code_weights, self.l_weights[i],
                ))
        return [self.l_msgs[c] for c in candidates[:10]]

def run(task, rollout_ph, reconst_ph, model, desc_model, translator, session,
        config):
    assert task.n_agents == 2

    h0, z0, _ = session.run(model.zero_state(1, tf.float32))
    states = []
    codes = []
    l_msgs = task.lexicon[1:]
    try:
        while True:
            replay = []
            trainer._do_rollout(
                    task, rollout_ph, model, desc_model, replay, [], session,
                    config, 10000, h0, z0, "val")
            #replay = [task.get_demonstration("val")]

            for episode in replay:
                for experience in episode[1:]:
                    codes.append(experience.m1[1][config.lexicographer.c_agent])
                    states.append(experience.s1)
                    if len(states) >= config.trainer.n_batch_episodes:
                        raise Break()
    except Break:
        pass

    codes = codes[:50]

    return Lexicographer(
            states, codes, l_msgs, reconst_ph, translator, task, session,
            config)

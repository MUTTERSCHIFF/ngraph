# ******************************************************************************
# Copyright 2017-2018 Intel Corporation
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ******************************************************************************
from __future__ import division
import ngraph as ng
import numpy as np
import abc
import collections
# =======================

# supported lr policies with required parameters
# fixed    = base_lr
# step     = base_lr * gamma ^ (floor(iter / step))
# schedule = base_lr * gamma_1 * gamma_2 * (... up through the number of steps in schedule)
# exp      = base_lr * gamma ^ iter
# inv      = base_lr * (1 + gamma * iter) ^ (-power)
# poly     = base_lr * (1 - iter/max_iter) ^ power
# sigmoid  = base_lr * (1 / (1 + exp(-gamma * (iter - stepsize))))

uint_dtype = np.dtype(np.uint32)


class lr_policy:

    def __init__(self, name, base_lr):
        self.name = name
        self.base_lr = ng.constant(axes=(), const=base_lr)

    @abc.abstractmethod
    def __call__(self, iteration):
        pass


class lr_policy_fixed(lr_policy):
    req_args = ('name', 'base_lr',)

    def __init__(self, params):
        lr_policy.__init__(self, params['name'], params['base_lr'])

    def __call__(self, iteration):
        return self.base_lr


class lr_policy_step(lr_policy):
    req_args = ('name', 'base_lr', 'gamma', 'step')

    def __init__(self, params):
        lr_policy.__init__(self, params['name'], params['base_lr'])
        self.gamma = ng.constant(axes=(), const=params['gamma'])
        self.step = ng.constant(axes=(), const=params['step'], dtype=uint_dtype)

    def __call__(self, iteration):
        return self.base_lr * self.gamma ** (iteration // self.step)


class lr_policy_schedule(lr_policy):
    """

    Implements learning rate change based a predetermined schedule

    Required Arguments:
        name(string): Name of the learning rate schedule
        base_lr(float): Initial learning rate
        gamma(float, list): Multiplicative factor to use when scaling the
                            learning rate. Learning rate will be multiplied
                            by this factor at each trigger point determined
                            by the schedule
        schedule(list): Each point in this list will act as the trigger point
                        to adjust the learning accoring to gamma value

    This learning policy allows you to provide a learning rate schedule, gamma and
    base learning rate.
    Learning rate drops at the provided iteration by multiplying with the gamma.

    Example:
    .. code-block:: python
    # Learning Rate Policy
    learning_rate_policy = {'name': 'schedule',
                            'schedule': [1000, 2000],
                            'gamma': 0.1,
                            'base_lr': 0.1}

    optimizer = GradientDescentMomentum(
        learning_rate=learning_rate_policy,
        momentum_coef=0.9,
        wdecay=0.005,
        iteration=inputs['iteration'])
    """
    req_args = ('name', 'base_lr', 'gamma', 'schedule')

    def __init__(self, params):
        lr_policy.__init__(self, params['name'], params['base_lr'])

        if not isinstance(params['schedule'], collections.Sequence):
            raise ValueError('schedule parameter to schedule policy '
                             'must be a sequence of steps.\n'
                             'Got: {}'.format(params['schedule']))

        num_steps = len(params['schedule'])

        # If gamma is provided as a single value, then just replicate it to
        # match the number of steps in the schedule: e.g. 0.1 --> [0.1, 0.1, 0.1]
        if not isinstance(params['gamma'], collections.Sequence):
            gamma_list = [params['gamma'] for _ in range(num_steps)]
            params['gamma'] = gamma_list

        if len(params['schedule']) != len(params['gamma']):
            raise ValueError('gamma and schedule parameters must have '
                             'same length.  Got {} vs {}'.format(
                                 len(params['gamma']),
                                 len(params['schedule'])
                             ))

        sched_axis = ng.make_axis(length=num_steps, name='schedule')
        self.gamma = ng.constant(axes=[sched_axis], const=params['gamma'])
        self.schedule = ng.constant(axes=[sched_axis], const=params['schedule'], dtype=uint_dtype)

    def __call__(self, iteration):
        masked_gamma = (iteration >= self.schedule) * self.gamma
        masked_holes = (iteration < self.schedule)
        return self.base_lr * ng.prod(masked_gamma + masked_holes, out_axes=())


class lr_policy_exp(lr_policy):
    req_args = ('name', 'base_lr', 'gamma')

    def __init__(self, params):
        lr_policy.__init__(self, params['name'], params['base_lr'])
        self.gamma = ng.constant(axes=(), const=params['gamma'])

    def __call__(self, iteration):
        return self.base_lr * self.gamma ** iteration


class lr_policy_inv(lr_policy):
    req_args = ('name', 'base_lr', 'gamma', 'power')

    def __init__(self, params):
        lr_policy.__init__(self, params['name'], params['base_lr'])
        self.gamma = ng.constant(axes=(), const=params['gamma'])
        self.power = ng.constant(axes=(), const=params['power'])

    def __call__(self, iteration):
        return self.base_lr * (1 + self.gamma * iteration) ** (-self.power)


class lr_policy_poly(lr_policy):
    req_args = ('name', 'base_lr', 'max_iter', 'power')

    def __init__(self, params):
        lr_policy.__init__(self, params['name'], params['base_lr'])
        self.max_iter = ng.constant(axes=(), const=params['max_iter'])
        self.power = ng.constant(axes=(), const=params['power'])

    def __call__(self, iteration):
        return self.base_lr * (1 - iteration / self.max_iter) ** self.power


class lr_policy_sigmoid(lr_policy):
    req_args = ('name', 'base_lr', 'gamma', 'step_size')

    def __init__(self, params):
        lr_policy.__init__(self, params['name'], params['base_lr'])
        self.gamma = ng.constant(axes=(), const=params['gamma'])
        self.step_size = ng.constant(axes=(), const=params['step_size'])

    def __call__(self, iteration):
        return self.base_lr * (1 / (1 + ng.exp(-self.gamma * (iteration - self.step_size))))


class lr_policy_provided(object):
    """
    This learning policy allows providing learning rate to the graph as a placeholder.
    Arguments:
        lr_placeholder: Placeholder which is used for providing learning rate

    Example:
    .. code-block:: python
    # Learning Rate Placeholder
    lr_ph = ng.placeholder(axes=(), initial_value=base_lr)

    # Optimizer
    learning_rate_policy = {'name': 'provided',
                            'lr_placeholder': lr_ph}
    """
    req_args = {'name', 'lr_placeholder'}

    def __init__(self, params):
        self.name = params['name']
        self.base_lr = params['lr_placeholder']

    def __call__(self, iteration):
        return self.base_lr


lr_policies = {
    'provided': {'args': lr_policy_provided.req_args, 'obj': lr_policy_provided},
    'fixed': {'args': lr_policy_fixed.req_args, 'obj': lr_policy_fixed},
    'step': {'args': lr_policy_step.req_args, 'obj': lr_policy_step},
    'schedule': {'args': lr_policy_schedule.req_args, 'obj': lr_policy_schedule},
    'exp': {'args': lr_policy_exp.req_args, 'obj': lr_policy_exp},
    'inv': {'args': lr_policy_inv.req_args, 'obj': lr_policy_inv},
    'poly': {'args': lr_policy_poly.req_args, 'obj': lr_policy_poly},
    'sigmoid': {'args': lr_policy_sigmoid.req_args, 'obj': lr_policy_sigmoid},
}

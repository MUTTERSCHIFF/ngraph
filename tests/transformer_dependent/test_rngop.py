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
"""
Test the usage of ng.constant
"""
from __future__ import print_function

import pytest
import numpy as np
import ngraph as ng
from ngraph.testing import executor

pytestmark = pytest.mark.transformer_dependent


@pytest.fixture()
def input_tensor():
    axes = ng.make_axes([ng.make_axis(length=5),
                         ng.make_axis(length=8)])
    return ng.persistent_tensor(axes, initial_value=10.0)


@pytest.config.argon_disabled(reason="Argon Transformer error")  # TODO triage
def test_uniform_range_pos(input_tensor):
    """TODO."""
    ng_a = ng.uniform(input_tensor, low=0.0, high=0.5)

    with executor(ng_a) as ex:
        result = ex()
    print(result)

    assert np.all(result < 0.5)
    assert np.all(result >= 0.0)
    assert not np.all(result == 0.0)


@pytest.config.argon_disabled(reason="Argon Transformer error")  # TODO triage
def test_uniform_range_posneg(input_tensor):
    """TODO."""
    ng_a = ng.uniform(input_tensor, low=-0.5, high=0.5)

    with executor(ng_a) as ex:
        result = ex()
    print(result)

    assert np.all(result < 0.5)
    assert np.all(result >= -0.5)
    assert not np.all(result >= 0.0)


@pytest.config.argon_disabled(reason="Argon Transformer error")  # TODO triage
def test_rng_repetition():
    """
    Tests rng ops, to make sure they run every execution and not just initialization
    """
    axes = ng.make_axes([ng.make_axis(2), ng.make_axis(2)])
    x = ng.variable(initial_value=np.array([[1, 2], [3, 4]]), axes=axes)
    y = ng.uniform(x)
    mysum = ng.sum(y)
    trans = ng.transformers.make_transformer()
    rand_comp = trans.computation(mysum)
    val1 = rand_comp().copy()
    val2 = rand_comp().copy()
    assert val1 != val2
    trans.close()


@pytest.config.argon_disabled(reason="Argon Transformer error")  # TODO triage
def test_normal_negative_mean():
    """TODO."""
    M = ng.make_axis(100).named('M')
    N = ng.make_axis(100).named('N')

    mean = -0.5
    std = 1.0

    ng_a = ng.persistent_tensor([M, N], initial_value=10.0)
    ng_a = ng.normal(ng_a, loc=mean, scale=std)

    with executor(ng_a) as ex:
        result = ex()
    print(np.mean(result))
    print(np.std(result))

    assert np.allclose(np.mean(result), mean, rtol=0.1, atol=0.02)
    assert np.allclose(np.std(result), std, rtol=0.1, atol=0.02)
    assert not np.all(result >= 0.0)
    assert not np.all(result < 0.0)

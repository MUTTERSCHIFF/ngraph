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
import pytest

import ngraph as ng


@pytest.fixture()
def N():
    return ng.make_axis(length=1)


def test_deriv_missing_connection(N):
    """
    Taking the derivative of an expression with respect to a variable not
    used to compute the expression should raise an exception.
    """
    x = ng.variable([N])
    y = ng.variable([N])
    z = ng.variable([N])

    with pytest.raises(ValueError):
        ng.deriv(x + y, z)


def test_one():
    # Test that the cacheing on constant one used in DerivOp works.
    op = ng.variable([])
    one_0 = op.one
    one_1 = op.one
    assert one_0 is one_1


def test_pad_invalid_paddings_length(N):
    """
    pad should raise an exception if the paddings length is not the same as the
    input dimensionality.
    """
    x = ng.variable([N])
    with pytest.raises(ValueError):
        ng.pad(x, [1, 0])


def test_pad_0(N):
    """
    pad with length 0 should be a nop
    """
    x = ng.variable([N])

    assert ng.pad(x, [0]).axes == x.axes


def test_pad_mixed():
    """
    mix 0 padding with non-0 padding
    """
    input_axes = ng.make_axes([
        ng.make_axis(1),
        ng.make_axis(1)
    ])
    x = ng.variable(input_axes)

    pad = ng.pad(x, [0, 1])

    assert pad.axes[0].name == x.axes[0].name
    assert pad.axes[1].name == x.axes[1].name
    assert pad.axes[0].length == x.axes[0].length
    assert pad.axes[1].length != x.axes[1].length


def test_slice_nop():
    """
    slicing an axis shouldn't change the name
    """
    input_axes = ng.make_axes([
        ng.make_axis(1),
        ng.make_axis(1)
    ])
    x = ng.variable(input_axes)

    s = ng.tensor_slice(x, [
        slice(None, None, None),
        slice(None, None, 1),
    ])

    assert s.axes[0] == x.axes[0]
    assert s.axes[1] == x.axes[1]


def test_tensor_slice():
    """
    slicing a tensor should work like numpy
    """
    input_axes = ng.make_axes([
        ng.make_axis(10),
        ng.make_axis(20),
        ng.make_axis(5)
    ])

    x = ng.placeholder(axes=input_axes)

    assert x[:5].axes.full_lengths == (5, 20, 5)
    assert x[:, 2:7].axes.full_lengths == (10, 5, 5)
    assert x[:5, :, :-1].axes.full_lengths == (5, 20, 4)

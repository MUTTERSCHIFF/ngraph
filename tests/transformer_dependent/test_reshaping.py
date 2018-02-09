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
import numpy as np
import pytest

import ngraph as ng
from ngraph.op_graph.axes import TensorDescription
from ngraph.testing import ExecutorFactory

pytestmark = pytest.mark.transformer_dependent


delta = 1e-3
rtol = atol = 1e-2


@pytest.config.argon_disabled(reason="Argon Transformer error")  # TODO triage
def test_expand_dims():
    """TODO."""
    C = ng.make_axis()
    D = ng.make_axis()
    N = ng.make_axis()

    max_new_axis_length = 4

    tests = [
        {
            'tensor': [[2, 5], [13, 5]],
            'tensor_axes': (N, D),
            'tensor_axes_lengths': (2, 2),
            'new_axis': C,
        },
        {
            'tensor': 2,
            'tensor_axes': (),
            'tensor_axes_lengths': (),
            'new_axis': D
        }
    ]

    for test in tests:
        for new_axis_length in range(1, max_new_axis_length + 1):
            tensor_axes = test['tensor_axes']
            tensor_axes_lengths = test['tensor_axes_lengths']

            for dim in range(len(tensor_axes) + 1):
                for axis, length in zip(tensor_axes, tensor_axes_lengths):
                    axis.length = length

                new_axis = test['new_axis']
                new_axis.length = new_axis_length

                tensor_np = np.array(
                    test['tensor'], dtype=np.float32
                )
                tensor = ng.placeholder(tensor_axes)

                expanded = ng.ExpandDims(tensor, new_axis, dim)
                with ExecutorFactory() as ex:
                    expander_fun = ex.executor(expanded, tensor)
                    num_deriv_fun = ex.numeric_derivative(expanded, tensor, delta)
                    sym_deriv_fun = ex.derivative(expanded, tensor)

                    expanded_shape = tensor_np.shape[:dim] \
                        + (new_axis.length,) + tensor_np.shape[dim:]
                    expanded_strides = tensor_np.strides[:dim] \
                        + (0,) + tensor_np.strides[dim:]
                    expanded_np = np.ndarray(
                        buffer=tensor_np,
                        shape=expanded_shape,
                        strides=expanded_strides,
                        dtype=tensor_np.dtype
                    )

                    expanded_result = expander_fun(tensor_np)
                    assert np.array_equal(expanded_np, expanded_result)

                    # Test backpropagation
                    numeric_deriv = num_deriv_fun(tensor_np)
                    sym_deriv = sym_deriv_fun(tensor_np)
                    ng.testing.assert_allclose(
                        numeric_deriv, sym_deriv, rtol=rtol, atol=atol
                    )


@pytest.config.argon_disabled(reason="Argon Transformer error")  # TODO triage
def test_slice():
    """TODO."""

    C = ng.make_axis()
    D = ng.make_axis()

    tests = [
        {
            'tensor': [[1, 3], [2, 5]],
            'tensor_axes': (C, D),
            'slice': [0, 1],
            'sliced_axes': (),
            'axes_lengths': {C: 2, D: 2},
            'expected': 3
        },
        {
            'tensor': [[1, 3], [2, 5]],
            'tensor_axes': (C, D),
            'slice': [slice(None), 0],
            'sliced_axes': (C,),
            'axes_lengths': {C: 2, D: 2},
            'expected': [1, 2]
        },
        {
            'tensor': [[1, 3], [2, 5]],
            'tensor_axes': (C, D),
            'slice': [1, slice(None)],
            'sliced_axes': (D,),
            'axes_lengths': {C: 2, D: 2},
            'expected': [2, 5]
        },
        {
            'tensor': [[1, 4, 5], [2, 5, 6]],
            'tensor_axes': (C, D),
            'slice': [1, slice(1, 3)],
            'sliced_axes': None,
            'axes_lengths': {C: 2, D: 3},
            'expected': [5, 6]
        }
    ]

    for test in tests:
        with ExecutorFactory() as ex:
            for axis, length in test['axes_lengths'].items():
                axis.length = length
            tensor_axes = test['tensor_axes']

            tensor_np = np.array(
                test['tensor'], dtype='float32'
            )
            tensor = ng.placeholder(tensor_axes)
            expected = np.array(test['expected'], dtype='float32')

            s = test['slice']
            s_axes = test['sliced_axes']

            sliced = ng.tensor_slice(tensor, s, s_axes)
            sliced_val_fun = ex.executor(sliced, tensor)

            num_deriv_fun = ex.numeric_derivative(sliced, tensor, delta)
            # Test backpropagation
            sym_deriv_fun = ex.derivative(sliced, tensor)

            sliced_val = sliced_val_fun(tensor_np)
            assert np.array_equal(sliced_val, expected)

            numeric_deriv = num_deriv_fun(tensor_np)
            sym_deriv = sym_deriv_fun(tensor_np)

            ng.testing.assert_allclose(
                numeric_deriv, sym_deriv, rtol=rtol, atol=atol
            )


def test_reverse_slice():
    """TODO."""

    C = ng.make_axis(length=10)
    D = ng.make_axis(length=10)

    x = ng.placeholder([C, D])
    with pytest.raises(ValueError):
        ng.tensor_slice(x, [slice(0, 10, -1), slice(0, 10)])

    with pytest.raises(ValueError):
        ng.set_item(x, [0, slice(None, None, -1)], 0)


@pytest.config.argon_disabled(reason="#2219 - ArgonSim ValueError: axes don't match array")
@pytest.config.flex_disabled(reason="#1954 UnsliceOp (Slice deriv) - not yet supported")
def test_multiple_slices():
    C = ng.make_axis(length=2)
    D = ng.make_axis(length=3)

    x = ng.placeholder([C, D])

    x0_slice = x[0, :]
    x1_slice = x[1, :]

    y1 = x0_slice * 2 + x1_slice * 3
    # overlapping distinct slices
    y2 = x0_slice * 2 + x1_slice * 3 + 4 * x[1, :]

    with ExecutorFactory() as ex:
        # nonoverlapping
        y1_fun = ex.executor(y1, x)
        num_deriv_fun1 = ex.numeric_derivative(y1, x, delta)
        sym_deriv_fun1 = ex.derivative(y1, x)

        # overlapping
        y2_fun = ex.executor(y2, x)
        num_deriv_fun2 = ex.numeric_derivative(y2, x, delta)
        sym_deriv_fun2 = ex.derivative(y2, x)

        x_np = np.array([[10, 20, 30], [1, 2, 3]], dtype='float32')
        y1_val = y1_fun(x_np)
        y1_np = np.array([23, 46, 69])
        ng.testing.assert_allclose(y1_val, y1_np)
        y2_val = y2_fun(x_np)
        y2_np = np.array([27, 54, 81])
        ng.testing.assert_allclose(y2_val, y2_np)

        f1_num = num_deriv_fun1(x_np)
        f1_sym = sym_deriv_fun1(x_np)
        ng.testing.assert_allclose(f1_num, f1_sym, rtol=rtol, atol=atol)

        f2_num = num_deriv_fun2(x_np)
        f2_sym = sym_deriv_fun2(x_np)
        ng.testing.assert_allclose(f2_num, f2_sym, rtol=rtol, atol=atol)


@pytest.config.argon_disabled(reason="Argon Transformer error")  # TODO triage
def test_padding():
    """TODO."""
    C = ng.make_axis()
    D = ng.make_axis()
    M = ng.make_axis()
    N = ng.make_axis()

    tests = [
        {
            'tensor': [[1, 3], [2, 5]],
            'tensor_axes': (C, D),
            'padding': [(0, 1), (1, 0)],
            'padded_axes': (M, N),
            'axes_lengths': {C: 2, D: 2, M: 3, N: 3}
        },
        {
            'tensor': [[1, 4, 5], [1, 4, 6]],
            'tensor_axes': (C, D),
            'padding': [(0, 1), 1],
            'padded_axes': None,
            'axes_lengths': {C: 2, D: 3}
        }
    ]

    for test in tests:
        with ExecutorFactory() as ex:
            for axis, length in test['axes_lengths'].items():
                axis.length = length
            tensor_axes = test['tensor_axes']
            tensor_np = np.array(
                test['tensor'], dtype='float32'
            )
            tensor = ng.placeholder(tensor_axes)
            padding = test['padding']
            padded_axes = test['padded_axes']
            padded = ng.pad(tensor, padding, padded_axes)
            computed_val_fun = ex.executor(padded, tensor)

            # Test backpropagation
            numeric_deriv_fun = ex.numeric_derivative(padded, tensor, delta)
            sym_deriv_fun = ex.derivative(padded, tensor)

            def to_tuple(p):
                """
                TODO.

                Arguments:
                  p: TODO

                Returns:

                """
                return (p, p) if isinstance(p, int) else p
            np_padding = tuple(to_tuple(p) for p in padding)
            expected_val = np.pad(tensor_np, np_padding, mode='constant')

            computed_val = computed_val_fun(tensor_np)
            assert np.array_equal(expected_val, computed_val)

            numeric_deriv = numeric_deriv_fun(tensor_np)
            sym_deriv = sym_deriv_fun(tensor_np)

            ng.testing.assert_allclose(numeric_deriv, sym_deriv, rtol=rtol, atol=atol)


@pytest.config.argon_disabled(reason="Argon Transformer error")  # TODO triage
def test_cast_axes():
    C = ng.make_axis(length=2)
    D = ng.make_axis(length=3)

    x = ng.placeholder([C, D])

    with pytest.raises(ValueError):
        ng.cast_axes(x, [D, C])

    x_slice = x[1, :]
    # Cast back to known axes
    x_cast = ng.cast_axes(x_slice, [D])

    # Verfiy that the tensor broadcasts along D
    y = (x + x_cast).named('y')
    with ExecutorFactory() as ex:
        y_fun = ex.executor(y, x)
        num_deriv_fun = ex.numeric_derivative(y, x, delta)
        sym_deriv_fun = ex.derivative(y, x)

        x_np = np.array([[10, 20, 30], [1, 2, 3]], dtype='float32')
        y_fun_np = np.array([[11, 22, 33], [2, 4, 6]], dtype='float32')
        y_fun_ng = y_fun(x_np)
        ng.testing.assert_allclose(y_fun_ng, y_fun_np)

        deriv_num = num_deriv_fun(x_np)
        deriv_sym = sym_deriv_fun(x_np)
        ng.testing.assert_allclose(deriv_num, deriv_sym, rtol=rtol, atol=atol)


@pytest.config.argon_disabled(reason="Argon Transformer error")  # TODO triage
def test_shuffled_deriv():
    # This gets the axes of a delta in a generate_add_delta in a different order than the
    # value being updated
    C = ng.make_axis(length=3)
    T = ng.make_axis(length=1)
    R = ng.make_axis(length=5)
    S = ng.make_axis(length=5)

    axes = [R, S, C]
    v = ng.variable([ng.make_axis(_.length) for _ in axes])
    rsc = ng.cast_axes(v, axes)
    trsc = ng.expand_dims(rsc, T, 0)
    ctrs = ng.axes_with_order(trsc, axes=[C, T, R, S])
    cost = ng.sum(ctrs, out_axes=None)
    grad = ng.deriv(cost, v)

    with ExecutorFactory() as ex:
        d_fun = ex.executor(grad)
        d_fun()


def test_slice_tensor_description():
    C = ng.make_axis(2)

    td = TensorDescription(ng.make_axes(C))
    with pytest.raises(ValueError):
        td.slice(
            [slice(None)],
            ng.make_axes([ng.make_axis(1), ng.make_axis(1)]),
        )


def test_tensor_description_init():
    with pytest.raises(ValueError):
        # TensorDescription axes require lengths
        TensorDescription(ng.make_axes(ng.make_axis()))

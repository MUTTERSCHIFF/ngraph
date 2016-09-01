# ----------------------------------------------------------------------------
# Copyright 2016 Nervana Systems Inc.
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ----------------------------------------------------------------------------
from __future__ import division

import numpy as np
from builtins import range

import geon.frontends.base.axis as ax
import geon as be
from geon.util.utils import RandomTensorGenerator, ExecutorFactory
from geon.util.utils import numeric_derivative, executor
from geon.util.derivative_check import check_derivative

rng = RandomTensorGenerator(0, np.float32)


def test_constant_multiply():
    # TODO: better error message when missing axes length in cases where it
    # is needed
    ax.Y.length = 1

    # TODO: don't require axes
    a = be.Constant(np.array([4.0], dtype='float32'), axes=[ax.Y])
    b = be.Constant(np.array([2.0], dtype='float32'), axes=[ax.Y])

    c = be.multiply(a, b)

    result = executor(c)()
    np.testing.assert_allclose(result, [8])


def test_constant_tensor_multiply():
    ax.Y.length = 2

    a = be.Constant(np.array([[1.0, 1.0], [1.0, 1.0]], dtype='float32'), axes=[ax.Y, ax.Y])
    b = be.Constant(np.array([[1.0, 1.0], [1.0, 1.0]], dtype='float32'), axes=[ax.Y, ax.Y])

    c = be.multiply(a, b)

    result = executor(c)()
    np.testing.assert_allclose(result, [[1.0, 1.0], [1.0, 1.0]])


def test_tensor_sum_single_reduction_axes():
    """TODO."""
    ax.N.length = 2
    ax.Y.length = 2

    a = be.Constant(np.array([[1.0, 1.0], [1.0, 1.0]], dtype='float32'), axes=[ax.N, ax.Y])

    b = be.sum(a, reduction_axes=ax.Y)

    result = executor(b)()
    np.testing.assert_allclose(result, [2.0, 2.0])


def test_scalar():
    """TODO."""
    # Simple evaluation of a scalar
    val = 5
    x = be.Constant(val)

    cval = executor(x)()
    assert cval.shape == ()
    np.testing.assert_allclose(cval, val)


def test_tensor_constant():
    # Pass a NumPy array through as a constant
    ax.W.length = 10
    ax.H.length = 20
    aaxes = be.Axes([ax.W, ax.H])
    ashape = aaxes.lengths
    asize = aaxes.size
    aval = np.arange(asize, dtype=np.float32).reshape(ashape)

    x = be.Constant(aval, axes=aaxes)
    cval = executor(x)()
    np.testing.assert_allclose(cval, aval)


def test_placeholder():
    # Pass array through a placeholder
    ax.W.length = 10
    ax.H.length = 20
    aaxes = be.Axes([ax.W, ax.H])
    ashape = aaxes.lengths
    asize = aaxes.size
    aval = np.arange(asize, dtype=np.float32).reshape(ashape)

    x = be.placeholder(axes=[ax.W, ax.H])
    d = 2 * x
    d2 = be.dot(x, x)

    ex = ExecutorFactory()
    # Return placeholder, param is placeholder
    placeholder_fun = ex.executor(x, x)
    prod_fun = ex.executor([d, d2], x)

    cval = placeholder_fun(aval)
    np.testing.assert_allclose(cval, aval)

    # Pass a different array though
    u = rng.uniform(-1.0, 1.0, aaxes)
    cval = placeholder_fun(u)
    np.testing.assert_allclose(cval, u)

    cval, s = prod_fun(aval)
    np.testing.assert_allclose(cval, aval * 2)
    np.testing.assert_allclose(s[()], np.dot(aval.flatten(), aval.flatten()))

    cval, s = prod_fun(u)
    u2 = u * 2
    np.testing.assert_allclose(cval, u2)
    np.testing.assert_allclose(s[()], np.dot(u.flatten(), u.flatten()))


def test_reduction():
    ax.C.length = 4
    ax.W.length = 4
    ax.H.length = 4
    axes = be.Axes([ax.C, ax.W, ax.H])

    u = rng.uniform(-1.0, 1.0, axes)

    for npred, bered, red in [(np.sum, be.sum, 'sum'),
                              (np.max, be.max, 'max'),
                              (np.min, be.min, 'min')]:
        for reduction_axes in [[ax.C],
                               [ax.W],
                               [ax.H],
                               [ax.C, ax.W],
                               [ax.W, ax.H]]:
            p_u = be.placeholder(axes=axes)
            dims = tuple(axes.index(axis) for axis in reduction_axes)
            npval = npred(u, dims)
            graph_reduce = bered(p_u, reduction_axes=reduction_axes)
            graph_val = executor(graph_reduce, p_u)(u)
            np.testing.assert_allclose(
                npval, graph_val), 'red:{red}, axes:{axes}'.format(
                red=red, axes=reduction_axes)


def test_reduction_deriv():
    delta = .001
    ax.C.length = 4
    ax.W.length = 10
    ax.H.length = 10
    axes = be.Axes([ax.C, ax.W, ax.H])

    u = rng.discrete_uniform(1.0, 2.0, 2 * delta, axes)

    # Need to test max/min differently since if two elements are extremums
    # and we modify one, the derivative will change.
    for npred, bered, red in [(np.sum, be.sum, 'sum')]:
        for reduction_axes in [[ax.C],
                               [ax.W],
                               [ax.H],
                               [ax.C, ax.W],
                               [ax.W, ax.H]]:
            p_u = be.placeholder(axes=axes)
            graph_reduce = bered(p_u, reduction_axes=reduction_axes)

            check_derivative(graph_reduce, p_u, delta, u, atol=1e-1, rtol=1e-1)


def test_reciprocal():
    """TODO."""
    ax.W.length = 20
    ax.N.length = 128
    axes = be.Axes([ax.W, ax.N])
    p_u = be.placeholder(axes=axes)
    u = rng.uniform(.1, 5.0, p_u.axes)

    rec_u_np = np.reciprocal(u)
    rec_u = be.reciprocal(p_u)

    ex = ExecutorFactory()
    rec_u_graph = ex.executor(rec_u, p_u)(u)
    np.testing.assert_allclose(rec_u_np, rec_u_graph)


def test_reciprocal_derivative():
    """TODO."""
    delta = .001
    ax.W.length = 20
    ax.N.length = 128
    axes = be.Axes([ax.W, ax.N])
    p_u = be.placeholder(axes=axes)
    u = rng.uniform(.1, 5.0, p_u.axes)

    rec_u = be.reciprocal(p_u)

    check_derivative(rec_u, p_u, delta, u, atol=1e-2, rtol=1e-2)

ELEMENTWISE_BINARY_OPS = [
    (np.add, be.add),
    (np.subtract, be.subtract),
    (np.multiply, be.multiply),
    (np.divide, be.divide),
]


ELEMENTWISE_UNARY_OPS = [
    (np.exp, be.exp),
    (np.log, be.log),
    (np.tanh, be.tanh),
]


def test_elementwise_binary_ops_matched_args():
    """TODO."""
    axes = be.Axes([be.Axis(20), be.Axis(20)])

    for np_op, be_op in ELEMENTWISE_BINARY_OPS:
        # Matched sizes
        p_u = be.placeholder(axes=axes)
        p_v = be.placeholder(axes=axes)
        u = rng.uniform(-1.0, 1.0, p_u.axes)
        v = rng.uniform(1.0, 2.0, p_v.axes)

        compare_f_at_x(
            be_op(p_u, p_v), [p_u, p_v],
            np_op, [u, v],
            atol=1e-4, rtol=1e-4
        )


def test_elementwise_binary_ops_matched_args_deriv_lhs():
    """TODO."""
    axes = be.Axes([be.Axis(20), be.Axis(20)])

    for np_op, be_op in ELEMENTWISE_BINARY_OPS:
        # Matched sizes
        p_u = be.placeholder(axes=axes)
        p_v = be.placeholder(axes=axes)
        u = rng.uniform(-1.0, 1.0, p_u.axes)
        v = rng.uniform(1.0, 2.0, p_v.axes)

        check_derivative(
            be_op(p_u, p_v), p_u, 0.001, u,
            parameters=[p_v],
            parameter_values=[v],
            atol=1e-4, rtol=1e-4,
        )


def test_elementwise_binary_ops_matched_args_deriv_rhs():
    """TODO."""
    axes = be.Axes([be.Axis(20), be.Axis(20)])

    for np_op, be_op in ELEMENTWISE_BINARY_OPS:
        # Matched sizes
        p_u = be.placeholder(axes=axes)
        p_v = be.placeholder(axes=axes)
        u = rng.uniform(-1.0, 1.0, p_u.axes)
        v = rng.uniform(1.0, 2.0, p_v.axes)

        check_derivative(
            be_op(p_u, p_v), p_v, 0.001, v,
            parameters=[p_u],
            parameter_values=[u],
            atol=1e-3, rtol=1e-3,
        )


def test_elementwise_unary_ops_matched_args():
    """TODO."""
    delta = .001
    axes = be.Axes([be.Axis(20), be.Axis(20)])

    for np_op, be_op in ELEMENTWISE_UNARY_OPS:
        p_u = be.placeholder(axes=axes)
        u = rng.uniform(1.0, 2.0, p_u.axes)
        u_np = np_op(u)
        result_op = be_op(p_u)

        ex = ExecutorFactory()
        fun = ex.executor(result_op, p_u)
        dudunum_fun = ex.numeric_derivative(result_op, p_u, delta)
        dudut_fun = ex.derivative(result_op, p_u)

        u_t = fun(u)
        np.testing.assert_allclose(u_np, u_t, atol=1e-4, rtol=1e-4)
        dudunum = dudunum_fun(u)
        dudut = dudut_fun(u)
        np.testing.assert_allclose(dudunum, dudut, atol=1e-3, rtol=1e-3)


def test_elementwise_ops_unmatched_args():
    """TODO."""
    # delta = .001
    ax.W.length = 5
    ax.H.length = 5
    ax.N.length = 32
    sample_axes = [ax.W, ax.H]
    batch_axes = [ax.W, ax.H, ax.N]
    broadcast_dims = (ax.W.length, ax.H.length, 1)

    for np_op, be_op in ELEMENTWISE_BINARY_OPS:
        # Matched sizes
        p_u = be.placeholder(axes=sample_axes)
        p_v = be.placeholder(axes=batch_axes)
        u = rng.uniform(1.0, 2.0, p_u.axes)
        v = rng.uniform(1.0, 2.0, p_v.axes)

        # u op v
        uv_np = np_op(u.reshape(broadcast_dims), v)
        uv_op = be_op(p_u, p_v)

        ex = ExecutorFactory()

        # fun(u, v)
        uv_fun = ex.executor(uv_op, p_u, p_v)
        duvdunum_fun = ex.numeric_derivative(uv_op, p_u, .001, p_v)
        duvdut_fun = ex.derivative(uv_op, p_u, p_v)
        duvdvnum_fun = ex.numeric_derivative(uv_op, p_v, .001, p_u)
        duvdvt_fun = ex.derivative(uv_op, p_v, p_u)

        # fun(v, u)
        vu_np = np_op(v, u.reshape(broadcast_dims))
        vu_op = be_op(p_v, p_u)

        vu_fun = ex.executor(vu_op, p_u, p_v)
        dvudunum_fun = ex.numeric_derivative(vu_op, p_u, .001, p_v)
        dvudut_fun = ex.derivative(vu_op, p_u, p_v)
        dvudvnum_fun = ex.numeric_derivative(vu_op, p_v, .001, p_u)
        dvudvt_fun = ex.derivative(vu_op, p_v, p_u)

        result_be = uv_fun(u, v)
        np.testing.assert_allclose(uv_np, result_be, atol=1e-4, rtol=1e-4)
        duvdunum = duvdunum_fun(u, v)
        duvdut = duvdut_fun(u, v)
        np.testing.assert_allclose(duvdunum, duvdut, atol=1e-3, rtol=1e-3)

        duvdvnum = duvdvnum_fun(v, u)
        duvdvt = duvdvt_fun(v, u)
        np.testing.assert_allclose(duvdvnum, duvdvt, atol=1e-3, rtol=1e-3)

        # v op u

        result_be = vu_fun(u, v)
        np.testing.assert_allclose(vu_np, result_be, atol=1e-4, rtol=1e-4)
        dvudunum = dvudunum_fun(u, v)
        dvudut = dvudut_fun(u, v)
        np.testing.assert_allclose(dvudunum, dvudut, atol=1e-3, rtol=1e-3)

        dvudvnum = dvudvnum_fun(v, u)
        dvudvt = dvudvt_fun(v, u)
        np.testing.assert_allclose(dvudvnum, dvudvt, atol=1e-3, rtol=1e-3)


def np_softmax(x, axis):
    """
    TODO.

    Arguments:
      x: TODO
      axis: TODO

    Returns:
      TODO
    """
    # Shape for broadcasts
    shape = list(x.shape)
    shape[axis] = 1

    exps = np.exp(x - np.max(x, axis).reshape(shape))
    return exps / np.sum(exps, axis).reshape(shape)


def cross_entropy_binary_logistic(x, t):
    """
    TODO.

    Arguments:
      x: TODO
      t: TODO

    Returns:
      TODO
    """
    y = 1.0 / (1.0 + np.exp(-x))
    return -(np.log(y) * t + np.log(1 - y) * (1 - t))


def cross_entropy_binary_logistic_shortcut(x, t):
    """
    TODO.

    Arguments:
      x: TODO
      t: TODO

    Returns:
      TODO
    """
    y = 1.0 / (1.0 + np.exp(-x))
    return (1.0 - t) * x - np.log(y)


def test_cross_entropy_binary_logistic_shortcut():
    """TODO."""
    ax.W.length = 20
    ax.N.length = 128
    axes = be.Axes([ax.W, ax.N])
    p_u = be.placeholder(axes=axes)
    u = rng.uniform(-3.0, 3.0, p_u.axes)
    p_v = be.placeholder(axes=axes)
    v = np_softmax(rng.uniform(-3.0, 3.0, p_u.axes), 0)

    cel = cross_entropy_binary_logistic(u, v)
    cel_shortcut = cross_entropy_binary_logistic_shortcut(u, v)
    np.testing.assert_allclose(cel, cel_shortcut, rtol=1e-5)

    cel_graph = executor(be.cross_entropy_binary_inner(be.sigmoid(p_u), p_v), p_u, p_v)(u, v)
    np.testing.assert_allclose(cel, cel_graph, rtol=1e-5)


def test_cross_entropy_binary():
    """TODO."""
    delta = .001
    ax.W.length = 20
    ax.N.length = 128
    axes = be.Axes([ax.W, ax.N])
    p_u = be.placeholder(axes=axes)
    u = rng.uniform(-3.0, 3.0, p_u.axes)
    p_v = be.placeholder(axes=axes)
    v = rng.uniform(-3.0, 3.0, p_u.axes)

    y = be.sigmoid(p_u)
    t = be.softmax(p_v)
    val_u = be.cross_entropy_binary_inner(y, t)

    ex = ExecutorFactory()
    dval_u_num_fun = ex.numeric_derivative(val_u, p_u, delta, p_v)
    dval_u_graph_fun = ex.derivative(val_u, p_u, p_v)

    dval_u_num = dval_u_num_fun(u, v)
    dval_u_graph = dval_u_graph_fun(u, v)
    np.testing.assert_allclose(dval_u_graph, dval_u_num, atol=1e-2, rtol=1e-2)


def adiff_softmax(x):
    """
    The version of the diff we use in autodiff, without batch axis.

    Arguments:
      x: return:

    Returns:
      TODO
    """

    def softmax_adiff(y_, y):
        """
        TODO.

        Arguments:
          y_: TODO
          y: TODO

        Returns:
          TODO
        """
        z = y_ * y
        zs = z.sum()
        x_ = z - zs * y
        return x_

    y = np_softmax(x, 0)
    n = x.shape[0]
    result = np.zeros((n, n))
    y_ = np.zeros_like(x)
    for i in range(n):
        y_[i] = 1
        result[i, :] = softmax_adiff(y_, y)
        y_[i] = 0
    return result


def test_np_softmax():
    """TODO."""
    ax.N.length = 128
    ax.C.length = 20

    # set up some distributions
    u = np.empty((ax.C.length, ax.N.length))
    u = rng.uniform(0, 1, be.Axes([ax.C, ax.N]))
    u = u / sum(u, 0).reshape(1, ax.N.length)

    # Put them in pre-softmax form
    x = np.log(u) + rng.uniform(-5000, 5000,
                                be.Axes([ax.N])).reshape(1, ax.N.length)

    s = np_softmax(x, 0)
    np.testing.assert_allclose(s, u, atol=1e-6, rtol=1e-3)

    # Drop batch axis and test the derivative
    x0 = x[:, 0]

    def np_softmax_0(x):
        """
        TODO.

        Arguments:
          x: TODO

        Returns:

        """
        return np_softmax(x, 0)

    a = numeric_derivative(np_softmax_0, x0, .001)
    s = adiff_softmax(x0)
    np.testing.assert_allclose(s, a, atol=1e-2, rtol=1e-2)


def np_cross_entropy_multi(y, t, axis=None):
    """
    TODO.

    Arguments:
      y: TODO
      t: TODO
      axis: TODO

    Returns:
      TODO
    """
    return -np.sum(np.log(y) * t, axis=axis)


def test_softmax():
    """TODO."""
    ax.W.length = 128
    ax.N.length = 10
    axes = be.Axes([ax.W, ax.N])

    # set up some distributions
    u = rng.uniform(0, 1, be.Axes([ax.W, ax.N]))
    u = u / sum(u, 0).reshape(1, ax.N.length)

    # Put them in pre-softmax form
    x = np.log(u) + rng.uniform(-5000, 5000,
                                be.Axes([ax.N])).reshape(1, ax.N.length)
    p_x = be.placeholder(axes=axes)

    ex = ExecutorFactory()
    smax_w_fun = ex.executor(be.softmax(p_x, softmax_axes=be.Axes([ax.W])), p_x)
    smax_fun = ex.executor(be.softmax(p_x), p_x)

    s = smax_w_fun(x)
    np.testing.assert_allclose(s, u, atol=1e-6, rtol=1e-3)

    x = rng.uniform(-5000, 5000, be.Axes([ax.W, ax.N]))
    u = np_softmax(x, 0)
    s = smax_w_fun(x)
    np.testing.assert_allclose(s, u, atol=1e-6, rtol=1e-3)

    # Test with softmax_axis default
    s = smax_fun(x)
    np.testing.assert_allclose(s, u, atol=1e-6, rtol=1e-3)


def test_softmax2():
    ax.W.length = 3
    ax.N.length = 10
    axes = be.Axes([ax.W, ax.N])

    x = rng.uniform(0, 1, axes)
    p_x = be.placeholder(axes=axes)

    compare_f_at_x(be.softmax(p_x), p_x, lambda x: np_softmax(x, 0), x)


def test_softmax_deriv():
    ax.W.length = 3
    ax.N.length = 10
    axes = be.Axes([ax.W, ax.N])

    x = rng.uniform(0, 1, axes)
    p_x = be.placeholder(axes=axes)

    check_derivative(be.softmax(p_x), p_x, 0.001, x, atol=1e-2, rtol=1e-2)


def test_softmax_rec():
    ax.W.length = 3
    ax.T.length = 4
    ax.N.length = 10
    axes = be.Axes([ax.W, ax.T, ax.N])

    x = rng.uniform(0, 1, axes)
    p_x = be.placeholder(axes=axes)
    compare_f_at_x(be.softmax(p_x), p_x, lambda x: np_softmax(x, 0), x)


def test_softmax_rec_deriv():
    ax.W.length = 3
    ax.T.length = 4
    ax.N.length = 10
    axes = be.Axes([ax.W, ax.T, ax.N])

    x = rng.uniform(0, 1, axes)
    p_x = be.placeholder(axes=axes)
    check_derivative(be.softmax(p_x), p_x, 0.001, x, atol=1e-2, rtol=1e-2)


def test_cross_entropy_softmax():
    ax.W.length = 3
    ax.N.length = 10
    axes = be.Axes([ax.W, ax.N])

    p_x = be.placeholder(axes=axes)
    p_t = be.placeholder(axes=axes)

    cross_entropy_sm_x_t = be.cross_entropy_multi(be.softmax(p_x), p_t)

    x = rng.uniform(0, 1, axes)
    t = np_softmax(rng.uniform(0, 1, axes), 0)

    def f_np(x, t):
        return np_cross_entropy_multi(np_softmax(x, 0), t, axis=0)

    compare_f_at_x(cross_entropy_sm_x_t, [p_x, p_t], f_np, [x, t], rtol=1e-5)


def test_cross_entropy_softmax_deriv():
    ax.W.length = 3
    ax.N.length = 10
    axes = be.Axes([ax.W, ax.N])

    p_x = be.placeholder(axes=axes)
    p_t = be.placeholder(axes=axes)

    x = rng.uniform(0, 1, axes)
    t = np_softmax(rng.uniform(0, 1, axes), 0)

    check_derivative(
        be.cross_entropy_multi(be.softmax(p_x), p_t),
        p_x, 0.001, x,
        parameters=[p_t],
        parameter_values=[t],
        atol=1e-2, rtol=1e-2
    )


def test_cross_enropy_rec():
    ax.W.length = 3
    ax.T.length = 4
    ax.N.length = 10
    axes = be.Axes([ax.W, ax.T, ax.N])

    p_x = be.placeholder(axes=axes)
    p_t = be.placeholder(axes=axes)

    cross_entropy_sm_x_t = be.cross_entropy_multi(be.softmax(p_x), p_t)

    x = rng.uniform(0, 1, axes)
    t = np_softmax(rng.uniform(0, 1, axes), 0)

    def f_np(x, t):
        return np_cross_entropy_multi(np_softmax(x, 0), t, axis=0)

    compare_f_at_x(cross_entropy_sm_x_t, [p_x, p_t], f_np, [x, t], rtol=1e-5)

def test_cross_entropy_softmax_deriv():
    ax.W.length = 3
    ax.T.length = 4
    ax.N.length = 10
    axes = be.Axes([ax.W, ax.T, ax.N])

    p_x = be.placeholder(axes=axes)
    p_t = be.placeholder(axes=axes)

    x = rng.uniform(0, 1, axes)
    t = np_softmax(rng.uniform(0, 1, axes), 0)

    check_derivative(
        be.cross_entropy_multi(be.softmax(p_x), p_t),
        p_x, 0.001, x,
        parameters=[p_t],
        parameter_values=[t],
        atol=1e-2, rtol=1e-2
    )


def test_sigmoid_deriv():
    """TODO."""
    axes = be.Axes([be.Axis(20), be.Axis(128)])
    p_u = be.placeholder(axes=axes)
    u = rng.uniform(-3.0, 3.0, p_u.axes)

    val_u = be.sigmoid(p_u)

    check_derivative(val_u, p_u, 0.001, u, atol=1e-2, rtol=1e-2)


def test_log_sigmoid_deriv():
    """TODO."""
    axes = be.Axes([be.Axis(20), be.Axis(128)])
    p_u = be.placeholder(axes=axes)
    u = rng.uniform(-3.0, 3.0, p_u.axes)

    log_val_u = be.log(be.sigmoid(p_u))

    check_derivative(log_val_u, p_u, 0.001, u, atol=1e-2, rtol=1e-2)


def compare_f_at_x(f_be, x_be, f_np, x, **kwargs):
    """
    Compare op_graph implementation of a function with numpy implementation

    Arguments:
        f_be: op_graph function
        x_be: argument to op_graph
        f_np: numpy function
        x: value to pass in to both implementations of f
        kwargs: used to pass rtol/atol on to assert_allclose
    """
    # op_graph
    ex = ExecutorFactory()

    # if x_be and x are not tuples or lists, put them in lists with length 1
    if isinstance(x_be, (tuple, list)):
        assert len(x_be) == len(x)
    else:
        x_be = [x_be]
        x = [x]

    # numpy
    val_np = f_np(*x)

    val_be = ex.executor(f_be, *x_be)(*x)

    # compare numpy and op_graph
    np.testing.assert_allclose(val_np, val_be, **kwargs)


def test_sigmoid_value():
    """ check the output of sigmoid is the same as np """
    axes = be.Axes([be.Axis(20), be.Axis(128)])
    p_x = be.placeholder(axes=axes)
    x = rng.uniform(-3.0, 3.0, p_x.axes)

    compare_f_at_x(be.sigmoid(p_x), p_x, lambda x: 1.0 / (1 + np.exp(-x)), x)


def one_hot_comparison(hot_axes, axes):
    """
    TODO.

    Arguments:
      hot_axes: TODO
      axes: TODO
    """
    u = rng.random_integers(0, ax.C.length - 1, axes, dtype=np.int8)
    u_p = be.placeholder(axes=axes, dtype=u.dtype)
    v = np.zeros(hot_axes.lengths, dtype=np.float32)
    udxiter = np.nditer(u, flags=['multi_index'])
    for uiter in udxiter:
        vindex = [int(uiter)]
        vindex.extend(udxiter.multi_index)
        v[tuple(vindex)] = 1

    v_t = executor(be.onehot(u_p, axis=ax.C), u_p)(u)
    np.testing.assert_allclose(v_t, v)


def test_onehot():
    """TODO."""
    ax.C.length = 4
    ax.W.length = 32
    ax.H.length = 32
    ax.N.length = 128
    one_hot_comparison(be.Axes([ax.C, ax.N]), be.Axes([ax.N]))
    one_hot_comparison(be.Axes([ax.C, ax.W, ax.H, ax.N]), be.Axes([ax.W, ax.H, ax.N]))


def test_empty_finalize():
    """Evaluating an empty NumPyTransformer shouldn't raise any exceptions."""
    be.NumPyTransformer().initialize()

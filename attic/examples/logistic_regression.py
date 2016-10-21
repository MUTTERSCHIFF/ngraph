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

from __future__ import print_function
import numpy as np
import ngraph as ng
import ngraph.frontends.base.axis as ax


def numpy_logistic_regression(xs, ys, max_iter, alpha):
    def sigmoid(x):
        return 1. / (1. + np.exp(-x))

    def predict(thetas, xs):
        return sigmoid(np.dot(xs, thetas))

    def get_loss(thetas, xs, ys):
        ys_pred = predict(thetas, xs)
        log_likelihoods = np.log(ys_pred) * ys + np.log(1 - ys_pred) * (1 - ys)
        loss = -np.sum(log_likelihoods)
        return loss

    def get_grad(thetas, xs, ys):
        ys_pred = predict(thetas, xs)
        grad = -np.dot(ys - ys_pred, xs)
        return grad

    # convert to (N, C) layout
    xs = xs.T.copy()

    # init weights
    thetas = np.array([0.0, 0.0, 0.0])

    # gradient descent
    loss = None  # for return safety
    for i in range(max_iter):
        # forward
        loss = get_loss(thetas, xs, ys)
        # backward
        grad = get_grad(thetas, xs, ys)
        # print
        print("grad: %s, loss %s" % (grad, loss))
        # update
        thetas -= grad * alpha

    return loss, thetas


def geon_logistic_regression(xs_np, ys_np, max_iter, alpha):
    def sigmoid(x):
        # return 1. / (1. + ng.exp(-x))
        return ng.sigmoid(x)

    def predict(thetas, xs):
        return sigmoid(ng.dot(xs, thetas))

    def get_loss(thetas, xs, ys):
        ys_pred = predict(thetas, xs)
        log_likelihoods = ng.log(ys_pred) * ys + ng.log(1 - ys_pred) * (1 - ys)
        loss = -ng.sum(log_likelihoods, reduction_axes=[ax.Y, ax.N])
        return loss

    # axis
    ax.C.length = 3
    ax.N.length = 4

    # input tensors
    xs = ng.placeholder(axes=(ax.C, ax.N))
    ys = ng.placeholder(axes=(ax.N))

    # init weights
    thetas_np = np.array([0., 0., 0.])
    thetas_numpy_tensor = ng.Constant(thetas_np, axes=(ax.C))
    thetas = ng.Variable(initial_value=thetas_numpy_tensor, axes=(ax.C))

    # define ops
    loss = get_loss(thetas, xs, ys)
    variable = list(loss.variables())[0]  # we only have one variable
    grad = ng.deriv(loss, variable)
    with ng.Op.saved_user_deps():
        update = ng.assign(lvalue=variable, rvalue=variable - alpha * grad)

    # transformer
    transformer = ng.NumPyTransformer()
    train_eval_func = transformer.computation([grad, loss, thetas, update],
                                              xs, ys)

    # evaluate
    loss_val, thetas_val = (None, None)  # for return safety
    for i in range(max_iter):
        grad_val, loss_val, thetas_val, update_val = train_eval_func(xs_np, ys_np)
        print("grad: %s, loss %s" % (grad_val, loss_val))

    return loss_val, thetas_val


if __name__ == '__main__':
    # xs: (C, N), y: (N,)
    xs = np.array([[ 0.52,  0.88,  0.52,  0.74],
                   [ 1.12, -1.08,  0.06, -2.49],
                   [ 0.77,  0.15, -1.3 ,  1.39]])
    ys = np.array([1, 1, 0, 1])
    max_iter = 10
    alpha = 0.1

    # numpy
    print("# numpy training")
    loss_np, thetas_np = numpy_logistic_regression(xs, ys, max_iter, alpha)
    print(loss_np, thetas_np)

    # geon
    print("# geon training")
    loss_ge, thetas_ge = geon_logistic_regression(xs, ys, max_iter, alpha)
    print(loss_ge, thetas_ge)

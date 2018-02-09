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

from __future__ import print_function

from ngraph.frontends.tensorflow.tf_importer.importer import TFImporter
from ngraph.testing import ExecutorFactory
import ngraph.frontends.common.utils as util
import numpy as np
import tensorflow as tf
import argparse


def logistic_regression(args):
    # setups -> xs: (N, C), y: (N, 1)
    xs_np = np.array([[0.52, 1.12, 0.77], [0.88, -1.08, 0.15],
                      [0.52, 0.06, -1.30], [0.74, -2.49, 1.39]])
    ys_np = np.array([[1], [1], [0], [1]])

    # placeholders
    x = tf.placeholder(tf.float32, shape=(4, 3))
    t = tf.placeholder(tf.float32, shape=(4, 1))
    w = tf.Variable(tf.zeros([3, 1]))
    y = tf.nn.sigmoid(tf.matmul(x, w))
    log_likelihoods = tf.log(y) * t + tf.log(1 - y) * (1 - t)
    cost = -tf.reduce_sum(log_likelihoods)
    init_op = tf.global_variables_initializer()

    # import graph_def
    importer = TFImporter()
    importer.import_graph_def(tf.get_default_graph().as_graph_def())

    # get handle of ngraph ops
    x_ng, t_ng, cost_ng, init_op_ng = importer.get_op_handle([x, t, cost, init_op])

    # transformer and computations
    with ExecutorFactory() as ex:
        updates = util.CommonSGDOptimizer(args.lrate).minimize(cost_ng, cost_ng.variables())

        train_comp = ex.executor([cost_ng, updates], x_ng, t_ng)
        init_comp = ex.executor(init_op_ng)
        ex.transformer.initialize()

        # train
        init_comp()
        ng_cost_vals = []
        for idx in range(args.max_iter):
            cost_val, _ = train_comp(xs_np, ys_np)
            ng_cost_vals.append(float(cost_val))
            print("[Iter %s] Cost = %s" % (idx, cost_val))

    # tensorflow for comparison
    with tf.Session() as sess:
        train_step = tf.train.GradientDescentOptimizer(args.lrate).minimize(cost)
        sess.run(init_op)
        tf_cost_vals = []
        for idx in range(args.max_iter):
            cost_val, _ = sess.run([cost, train_step],
                                   feed_dict={x: xs_np,
                                              t: ys_np})
            tf_cost_vals.append(float(cost_val))
            print("[Iter %s] Cost = %s" % (idx, cost_val))

    return ng_cost_vals, tf_cost_vals


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('-i', '--max_iter', type=int, default=10)
    parser.add_argument('-l', '--lrate', type=float, default=0.1,
                        help="Learning rate")
    args = parser.parse_args()
    logistic_regression(args)

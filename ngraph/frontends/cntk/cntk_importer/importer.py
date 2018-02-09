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

from __future__ import division, print_function

import inspect

import cntk as C
import numpy as np

import ngraph as ng
from ngraph.frontends.cntk.cntk_importer.ops_bridge import OpsBridge
from ngraph.frontends.neon import GradientDescentMomentum


def create_loss_and_learner(
        model, labels, learning_rate,
        momentum_coef=0.0, wdecay=0.0, nesterov=False,
        gradient_clip_norm=None, gradient_clip_value=None):
    """
    Auxiliary function to create loss function (cross entropy and softmax)
    and trainer using stochastic gradient descent with momentum.

    Arguments:
        model - imported model
        labels - placeholder for one-hot labels array
        learning_rate - learning rate for trainer
        momentum_coef - coefficient of momentum (deafult 0.0)
        wdecay - amount of weight decay (default 0.0)
        nesterov - use nesterov accelerated gradient (dafault False)
        gradient_clip_norm - target gradient norm (default None)
        gradient_clip_value - value to element-wise clip gradients (default None)

    Returns:
        Loss function (mean for batch)
    """
    if model.axes.lengths != labels.axes.lengths:
        labels = ng.Transpose(labels)
    assert model.axes.lengths == labels.axes.lengths
    model = ng.cast_axes(model, axes=labels.axes)

    loss = ng.cross_entropy_multi(ng.softmax(model), labels)
    optimizer = GradientDescentMomentum(
        learning_rate, momentum_coef, wdecay,
        gradient_clip_norm, gradient_clip_value, nesterov
    )
    return ng.sequential([optimizer(loss), ng.mean(loss, out_axes=())])


def cross_entropy_with_softmax(model, labels):
    """
    Auxiliary function to add cross entropy and softmax (loss function)
    to imported model for training.

    Arguments:
        model - imported model
        labels - placeholder for one-hot labels array

    Returns:
        Loss function (mean for batch)
    """
    if model.axes.lengths != labels.axes.lengths:
        model = ng.Transpose(model)
    assert model.axes.lengths == labels.axes.lengths
    model = ng.cast_axes(model, axes=labels.axes)

    loss = ng.cross_entropy_multi(ng.softmax(model), labels)
    return ng.mean(loss, out_axes=())


def classification_error(model, labels):
    """
    Auxiliary function to add classification error function to
    imported model for testing.

    Arguments:
        model - imported model
        labels - placeholder for one-hot labels array

    Returns:
        Classification error function (mean for batch)
    """
    try:
        errors = ng.not_equal(
            ng.argmax(model, out_axes=[labels.axes.batch_axis()]),
            ng.argmax(labels, out_axes=[labels.axes.batch_axis()])
        )
    except ValueError:
        errors = ng.not_equal(ng.argmax(model), ng.argmax(labels))

    return ng.mean(errors, out_axes=())


class CNTKImporter:
    """
    Importer for CNTK graph's definition
    """

    def __init__(self, batch_size=1, debug=False):
        self.uid_op_map = dict()
        self.placeholders = []
        self.ops_bridge = OpsBridge()
        self.batch_size = batch_size
        self.debug = debug

    def load_operations(self, cntk_model):
        """
        Save CNTK graph's functions list in reverse (first to last) order.

        Arguments:
            cntk_model: CNTK network model (last operation).
        """
        stack = [cntk_model]
        visited = list()
        if self.debug:
            functions = set()

        while stack:
            node = stack.pop()
            node = node.root_function

            if node.uid in visited:
                continue

            if self.debug:
                functions.add(node.op_name)

            visited.append(node.uid)
            self.uid_op_map[node.uid] = node

            for i in node.inputs:
                if i.is_output:
                    stack.append(i.owner)

        if self.debug:
            print("Functions used in model: {}".format(', '.join(str(i) for i in functions)))
            print("All operations in model:")
            for i in visited:
                print("  " + i + "(" + self.uid_op_map[i].op_name + ")")
            print("")

    def import_operation(self, cntk_op):
        """
        Recursively import and translate CNTK operations.

        Arguments:
            cntk_op: CNTK operation to be imported.

        Returns:
            Translated operation.
        """
        inputs = []
        for i in cntk_op.inputs:
            axes = [
                ng.make_axis(dim) for dim in i.shape
            ]
            dtype = np.dtype(i.dtype)

            if i.is_output:
                uid = i.owner.root_function.uid
                temp = self.uid_op_map[uid]
                if isinstance(temp, C.Function):
                    temp = self.import_operation(temp)
                    if temp is None:
                        raise ValueError("Error translating: " + uid)
                    else:
                        self.uid_op_map[uid] = temp
                inputs.append(temp)
            elif i.is_input:
                if self.batch_size > 1:
                    axes.append(ng.make_axis(self.batch_size, 'N'))
                temp = ng.placeholder(axes, dtype).named(i.uid)
                inputs.append(temp)
                self.placeholders.append(temp)
            else:
                try:
                    input_value = i.value
                except AttributeError:
                    input_value = C.plus(i, np.zeros(i.shape)).eval()
                if i.is_constant:
                    inputs.append(ng.constant(input_value, axes, dtype).named(i.uid))
                elif i.is_parameter:
                    inputs.append(ng.variable(axes, dtype, input_value).named(i.uid))
                else:
                    raise ValueError("Unknown input: " + i.uid)

        if self.debug:
            for _ in range(len(inspect.stack())):
                print(' ', end="")
            print("Importing: " + cntk_op.uid + str(cntk_op.shape) + ": ", end="")
            for i in cntk_op.inputs:
                print(i.uid + str(i.shape) + ", ", end="")
            print("")

        ng_op = self.ops_bridge(cntk_op, inputs)

        if self.debug:
            for _ in range(len(inspect.stack())):
                print(' ', end="")
            print("Imported: " + ng_op.name + str(ng_op.axes.lengths) + ": ", end="")
            for i in inputs:
                print(i.name + str(i.axes.lengths) + ", ", end="")
            print("")

        return ng_op

    def import_model(self, cntk_model):
        """
        Import and translate CNTK network model to ngraph network.

        Arguments:
            cntk_model: CNTK Model (with inputs) to be translated to ngraph.

        Returns:
            Translatedngraph model.
            List of placeholders.
        """
        self.load_operations(cntk_model)

        temp = self.import_operation(cntk_model.root_function)
        if temp is None:
            raise ValueError("Error translating: " + cntk_model.root_function.uid)
        else:
            self.uid_op_map[cntk_model.root_function.uid] = temp

        return temp, self.placeholders

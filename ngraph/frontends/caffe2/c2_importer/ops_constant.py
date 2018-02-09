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

import ngraph as ng
import caffe2.python.core as c2core
import caffe2.proto.caffe2_pb2 as c2proto
import numpy as np
from utils import make_const_op


class OpsConstant():
    """
    Mix-in class for constant ops.
    """

    def ConstantFill(self, c2_op, inputs):
        """
        Creates a constant tensor with constant fill.

        Arguments:
            c2_op: OperatorDef object, the caffe2 node to convert.
            inputs: List of ngraph Ops as inputs to this node.

        Returns:
            A ngraph Op corresponding to the caffe2 node.

        Inputs to c2_op:
            value, dtype, shape, name
        """

        # parse protobuf arguments
        args = {arg.name: arg for arg in c2_op.arg}

        value = args["value"].i if ("dtype" in args.keys()
                                    and args["dtype"].i == c2core.DataType.INT32) \
            else args["value"].f
        # convert to numpy value
        np_val = np.full(tuple(args["shape"].ints), value)

        ng_const = make_const_op(np_val, np_val.shape, c2_op.name)  # TODO simplify
        ng_placeholder = ng.persistent_tensor(axes=ng_const.axes, initial_value=ng_const)
        return ng_placeholder

    def GaussianFill(self, c2_op, inputs):
        """
        Creates a constant tensor with Gaussian fill.

        Arguments:
            c2_op: OperatorDef object, the caffe2 node to convert.
            inputs: List of ngraph Ops as inputs to this node.

        Returns:
            A ngraph Op corresponding to the caffe2 node.

        Inputs to c2_op:
            value, dtype, shape, name
        """
        # parse protobuf arguments
        args = {arg.name: arg for arg in c2_op.arg}

        mean = args["mean"].f if "mean" in args.keys() else 0
        std = args["std"].f if "std" in args.keys() else 1

        # convert to numpy value
        np_val = np.random.normal(mean, std,
                                  tuple(args["shape"].ints))

        ng_const = make_const_op(np_val, np_val.shape, c2_op.name)  # TODO simplify
        ng_placeholder = ng.persistent_tensor(axes=ng_const.axes, initial_value=ng_const)
        return ng_placeholder

    def UniformFill(self, c2_op, inputs):
        """
        Creates a constant tensor with uniform fill.

        Arguments:
            c2_op: OperatorDef object, the caffe2 node to convert.
            inputs: List of ngraph Ops as inputs to this node.

        Returns:
            A ngraph Op corresponding to the caffe2 node.

        Inputs to c2_op:
            value, dtype, shape, name
        """

        # parse protobuf arguments
        args = {arg.name: arg for arg in c2_op.arg}

        # convert to numpy value
        np_val = np.random.uniform(args["min"].f, args["max"].f,
                                   tuple(args["shape"].ints))

        ng_const = make_const_op(np_val, np_val.shape, c2_op.name)  # TODO simplify
        ng_placeholder = ng.persistent_tensor(axes=ng_const.axes, initial_value=ng_const)
        return ng_placeholder

    def UniformIntFill(self, c2_op, inputs):
        """
        Creates a constant tensor with uniform fill.

        Arguments:
            c2_op: OperatorDef object, the caffe2 node to convert.
            inputs: List of ngraph Ops as inputs to this node.

        Returns:
            A ngraph Op corresponding to the caffe2 node.

        Inputs to c2_op:
            value, dtype, shape, name
        """

        # parse protobuf arguments
        args = {arg.name: arg for arg in c2_op.arg}

        # convert to numpy value
        np_val = np.random.random_integers(args["min"].i, args["max"].i,
                                           tuple(args["shape"].ints))
        ng_op = make_const_op(np_val, np_val.shape, c2_op.name)

        return ng_op

    def XavierFill(self, c2_op, inputs):
        """
        Creates a constant tensor with xavier fill.
        Implementation is the same as in caffe2. Thera are other implementations in caffe or TF.
        Xavier fill is uniform fill with variance (range) depending on number of
        input/output neurons.

        Arguments:
            c2_op: OperatorDef object, the caffe2 node to convert.
            inputs: List of ngraph Ops as inputs to this node.

        Returns:
            A ngraph Op corresponding to the caffe2 node.

        Inputs to c2_op:
            value, dtype, shape, name
        """

        # parse protobuf arguments
        args = {arg.name: arg for arg in c2_op.arg}

        # calculate scale like in caffe2
        input_neurons = np.prod(args["shape"].ints)
        scale = np.sqrt(3. / input_neurons)

        # add arguments for uniform fill to list
        arg1, arg2 = c2proto.Argument(), c2proto.Argument()
        arg1.name, arg2.name = "max", "min"
        arg1.f, arg2.f = scale, -scale

        c2_op.arg.extend([arg1, arg2])
        ng_op = self.UniformFill(c2_op=c2_op, inputs=inputs)

        return ng_op

    def GivenTensorFill(self, c2_op, inputs):
        """
        Creates a constant tensor with values provided.

        Arguments:
            c2_op: OperatorDef object, the caffe2 node to convert.
            inputs: List of ngraph Ops as inputs to this node.

        Returns:
            A ngraph Op corresponding to the caffe2 node.

        Inputs to c2_op:
            value, dtype, shape, name
        """
        # parse arguments
        args = {arg.name: arg for arg in c2_op.arg}
        # convert to numpy value
        values = [v for v in args["values"].floats]
        shape = [s for s in args["shape"].ints]
        np_init = np.array(values)
        np_val = np.ndarray(shape)
        np_val[:] = np_init.reshape(shape)[:]

        ng_const = make_const_op(np_val, np_val.shape, c2_op.name)  # TODO simplify
        ng_placeholder = ng.persistent_tensor(axes=ng_const.axes, initial_value=ng_const)
        return ng_placeholder

    def GivenTensorIntFill(self, c2_op, inputs):
        """
        Creates a constant tensor with int values provided.

        Arguments:
            c2_op: OperatorDef object, the caffe2 node to convert.
            inputs: List of ngraph Ops as inputs to this node.

        Returns:
            A ngraph Op corresponding to the caffe2 node.

        Inputs to c2_op:
            value, shape, name
        """
        # parse arguments
        args = {arg.name: arg for arg in c2_op.arg}
        # convert to numpy value
        values = [v for v in args["values"].ints]
        shape = [s for s in args["shape"].ints]
        np_init = np.array(values)
        np_val = np.ndarray(shape)
        np_val[:] = np_init.reshape(shape)[:]

        ng_op = make_const_op(np_val, np_val.shape, c2_op.name)

        return ng_op

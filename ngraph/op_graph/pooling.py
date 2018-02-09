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

from ngraph.op_graph.op_graph import TensorOp


def pooling(poolparams, inputs, axes, docstring=None):
    """

    Args:
        poolparams: Dimensions.
        inputs (TensorOp): Input to pooling.
        docstring (String, optional): Dcoumentation for the computation.

    Returns:
        TensorOp: The pooling computation.
    """
    return PoolingOp(poolparams, inputs, axes=axes, docstring=docstring)


class PoolingOp(TensorOp):

    def __init__(self, pool_params, inputs, *args, **kwargs):
        """
        Arguments:
            inputs  : input tensor.

        Return:
        """
        super(PoolingOp, self).__init__(args=(inputs,), **kwargs)
        if len(inputs.shape) != 5:
            raise ValueError((
                'pooling input shape must be length 5, found {}'
            ).format(len(inputs.shape)))

        pooltype = pool_params['op']
        if pooltype not in ('max', 'avg'):
            raise ValueError((
                "Unsupported pooling type: {pooltype}.  Only max and avg pooling "
                "currently supported. ").format(pooltype=pooltype))

        self.pool_params = pool_params
        self.channel_axes = inputs.axes[0]
        self.spatial_axes = inputs.axes[1:4]

    def copy_with_new_args(self, args):
        return type(self)(self.pool_params, args[0], axes=self.axes)

    def generate_adjoints(self, adjoints, delta, inputs):
        # requires pooling's forward to be completed before backward
        bprop_pool_op = BpropPoolOp(delta, inputs, self)
        bprop_pool_op.add_control_dep(self)
        inputs.generate_add_delta(adjoints, bprop_pool_op)


class BpropPoolOp(TensorOp):
    """
    Maintains index and pool_params through forwarding of the original PoolingOp.

    Arguments:
        fprop: The original PoolingOp.
    """
    def __init__(self, delta, inputs, fprop, **kwargs):
        super(BpropPoolOp, self).__init__(args=(delta,), axes=inputs.axes, **kwargs)
        self.fprop = fprop
        self.inputs = inputs

    def copy_with_new_args(self, args):
        return type(self)(args[0], self.fprop.args[0], self.fprop)

    @property
    def pool_params(self):
        """

        Returns:
            The pooling parameters of the pooling op.

        """
        return self.fprop.forwarded.pool_params

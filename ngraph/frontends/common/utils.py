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
import numbers
from ngraph.frontends.common import learning_rate_policies as lrp
import numpy as np


def common_conv2d_pool_output_shape(input_NHWC, filter_HWIO, stride_NHWC, padding):
    """
    Get output shape for convolution or padding.

    Args:
        input_NHWC: [batch, in_height, in_width, in_channels].
        filter_HWIO: [filter_height, filter_width, in_channels, out_channels].
        stride_NHWC: [stride_batch, stride_height, stride_width, stride_channels].
        padding: A string from: "SAME", "VALID".

    Returns:
        output shape of convolution in NHWC format
    """
    # check inputs
    if padding != 'SAME' and padding != 'VALID':
        raise ValueError("Padding must be 'SAME' or 'valid'.")
    if not (len(input_NHWC) == len(filter_HWIO) == len(stride_NHWC) == 4):
        raise ValueError(
            "input_NHWC, filter_HWIO, stride_NHWC must be length 4.")

    # get input / filter shape
    N, H, W, C = input_NHWC
    R, S, C_, K = filter_HWIO
    if C != C_:
        raise ValueError("Input channel must be the same as filter channel.")

    # only support [1, X, X, 1] stride_NHWC for importer now
    if stride_NHWC[0] != 1 or stride_NHWC[3] != 1:
        raise NotImplementedError("Strides on batch axis (N) and channel axis "
                                  "(C) must be 1 for importer.")

    # get output shape
    if 'SAME' == padding:
        out_height = np.ceil(float(H) / float(stride_NHWC[1]))
        out_width = np.ceil(float(W) / float(stride_NHWC[2]))
    elif 'VALID' == padding:
        out_height = np.ceil(float(H - R + 1) / float(stride_NHWC[1]))
        out_width = np.ceil(float(W - S + 1) / float(stride_NHWC[2]))

    return tuple([int(i) for i in [N, out_height, out_width, K]])


def common_conv2d_pool_padding(input_NHWC, filter_HWIO, stride_NHWC, padding):
    """
    Get padding size for convolution or padding.

    Args:
        input_NHWC: [batch, in_height, in_width, in_channels].
        filter_HWIO: [filter_height, filter_width, in_channels, out_channels].
        stride_NHWC: [stride_batch, stride_height, stride_width, stride_channels].
        padding: A string from: "SAME", "VALID".

    Returns:
        pad_top, pad_bottom, pad_left, pad_right
    """
    # check validity and get output size
    _, out_height, out_width, _ = common_conv2d_pool_output_shape(
        input_NHWC, filter_HWIO, stride_NHWC, padding)
    if padding == 'SAME':
        # get input / filter shape
        N, H, W, C = input_NHWC
        R, S, C_, K = filter_HWIO

        # get padding size
        pad_along_height = ((out_height - 1) * stride_NHWC[1] + R - H)
        pad_along_width = ((out_width - 1) * stride_NHWC[2] + S - W)
        pad_top = int(pad_along_height) // 2
        pad_bottom = int(pad_along_height - pad_top)
        pad_left = int(pad_along_width) // 2
        pad_right = int(pad_along_width - pad_left)
        return (pad_top, pad_bottom, pad_left, pad_right)
    else:
        return (0, 0, 0, 0)


def squeeze_axes(inputs):
    """
    Removes axes with length of 1 for each tensor.

    Arguments:
        inputs: List of inputs to be sliced.

    Returns:
        Sliced inputs.
    """
    sliced_inputs = []
    for i in inputs:
        ones = []
        for axis in i.axes:
            if axis.length == 1:
                ones.append(0)
            else:
                ones.append(slice(None))
        sliced_inputs.append(ng.tensor_slice(i, ones))
    return sliced_inputs


class CommonSGDOptimizer(object):

    def get_iter_buffer(self):
        return self._iteration_buffer

    def get_lr_subgraph(self):
        return self.compute_lr_op

    def __init__(self, lr_params):
        self.compute_lr_op_creation = None

        if hasattr(lr_params, '__call__'):
            # If argument is a function, set it as a callback, which allows user to
            # define a policy.
            # This function should create subgraph for computing learning rate.
            # Buffer containing current iteration number will be passed as parameter
            self.compute_lr_op_creation = lr_params
        else:
            if isinstance(lr_params, numbers.Real):
                # If argument is real number, set policy to fixed and use given value as base_lr
                lr_params = {'name': 'fixed', 'base_lr': lr_params}
            policies = lrp.lr_policies
            if lr_params['name'] not in policies:
                raise NotImplementedError('Unsupported learning rate policy: '
                                          '\nGiven: ' + lr_params['name'] +
                                          '\nSupported policies are: ' + str(policies.keys()))
            else:
                if all([x in lr_params.keys() for x in policies[lr_params['name']]['args']]):
                    # Check if lr_params contains all required parameters for selected policy.
                    self.compute_lr_op_creation = policies[lr_params['name']]['obj'](lr_params)
                else:
                    raise ValueError('Too few arguments passed to CommonSGDOptimizer'
                                     '\nGiven: ' + str(lr_params.keys()) +
                                     '\nExpected: ' + str(policies[lr_params['name']]['args']))

        self._iteration_buffer = ng.placeholder(axes=(), dtype=np.dtype(np.uint32))
        self.compute_lr_op = self.compute_lr_op_creation(self.get_iter_buffer())

    def minimize(self, cost, variables):
        """
        Minimize cost by returning update Ops.

        Arguments:
            cost: The cost Op to be minimized
            variables: TODO

        Returns:
            A doall op containing setitems to variable ops.
        """

        assert cost is not None
        assert variables is not None

        return ng.doall([ng.assign(variable,
                                   variable - self.compute_lr_op * ng.deriv(cost, variable))
                         for variable in variables])


def conv_output_dim(X, S, padding, strides, pooling=False, dilation=1):
    """
    Compute convolution output dimension along one dimension with these sizes, what will be
    the output dimension.

    Arguments:
        X (int): input data dimension
        S (int): filter dimension
        padding (int): padding on each side
        strides (int): striding
        pooling (bool): flag for setting pooling layer size
        dilation (int): dilation of filter
    """

    return ConvParameters(X, S, strides, dilation).get_output_size(padding)


def deconv_output_dim(X, S, padding, strides, dilation=1):
    """
    Compute deconvolution output dimension along one dimension with these sizes, what will be
    the output dimension.

    Arguments:
        X (int): input data dimension
        S (int): filter dimension
        padding (int): padding on each side
        strides (int): striding
        dilation (int): dilation of filter
    """

    return ConvParameters(X, S, strides, dilation).get_transpose_size(padding)


def make_convparams(nout, filter_shape, strides, padding, dilation):
    """
    Make the convparams dictionary to be used by core ngraph

    Arguments:
        nout (int): Number of output filters
        filter_shape (dict): int filter shape with keys of "D", "H", and "W"
        strides (dict): int strides with keys of "D", "H", and "W"
        padding: int padding with keys of "D", "H", and "W"
        dilation: int dilation with keys of "D", "H", and "W"

    Returns:
        Properly formatted convparams dictionary
    """
    convparams = dict()
    convparams["K"] = nout

    for ng_name, filter_name in zip('TRS', 'DHW'):
        convparams[ng_name] = filter_shape[filter_name]

    for name in "DHW":
        for prefix, prop in zip(("str", "pad", "dil"),
                                (strides, padding, dilation)):
            convparams["{}_{}".format(prefix, name.lower())] = prop[name]

    return convparams


def make_poolparams(op, pool_shape, strides, padding):
    """
    Make the poolparams dictionary to be used by core ngraph

    Arguments:
        op (str): One of the supported pooling op types. Currently ["avg", "max"].
        pool_shape (dict): int filter shape with keys of "C", "D", "H", and "W"
        strides (dict): int strides with keys of "C", "D", "H", and "W"
        padding: int padding with keys of "C", "D", "H", and "W"

    Returns:
        Properly formatted poolparams dictionary
    """
    poolparams = dict()
    poolparams["op"] = op

    for name, value in zip("JTRS", [pool_shape[nm] for nm in "CDHW"]):
        poolparams[name] = value

    for name in "CDHW":
        for prefix, prop in zip(("str", "pad"), (strides, padding)):
            poolparams["{}_{}".format(prefix, name.lower())] = prop[name]

    return poolparams


class ConvParameters(object):
    """
    Helper class to compute the output size and required padding for convolution and pooling
    operations.

    Arguments:
        input_size (int): Length of the input
        filter_size (int): Length of the filter
        stride (int, optional): Filter stride
        dilation (int, optional): Filter dilation for dilated / atrous convolutions
        pooling (bool, optional): Whether the computation is for a pooling op.

    Raises:
        ValueError: If the parameters produce invalid output or padding values
    """

    def __init__(self, input_size, filter_size, stride=1, dilation=1, pooling=False):

        self.input_size = input_size
        self.filter_size = filter_size
        self.stride = stride
        self.dilation = dilation
        self.pooling = pooling

    def get_padding_size(self, padding):
        """
        Get the padding size

        Arguments:
            padding (int, tuple, or str): Desired padding value. int values produce symmetric
                padding. tuple values are passed through as-is. str values can be one of:
                - valid: No padding
                - same: Padding to produce the same output size as the strided input
                - causal: Padding to offset the filter so outputs only rely on leftward
                          values of the input
                - full: Padding such that the output contains all points with nonzero overlap
                        between the filters and the input

        Returns:
            Tuple of padding integers

        Raises:
            ValueError: If padding is a str and not in the support str values
        """
        if isinstance(padding, int):
            return (padding, padding)
        elif isinstance(padding, tuple):
            return padding
        elif isinstance(padding, str):
            if padding == "valid":
                return self._get_valid_padding()
            elif padding == "same":
                return self._get_same_padding()
            elif padding == "causal":
                return self._get_causal_padding()
            elif padding == "full":
                return self._get_full_padding()
            elif padding == "caffe_full":
                return self._get_caffe_full_padding()
            else:
                raise ValueError("Padding is not a valid string value: {}".format(padding))

    def get_output_size(self, padding):
        """
        Get the output size following convolution or pooling

        Arguments:
            padding (int, tuple, or str): Desired padding value. int values produce symmetric
                padding. tuple values are passed through as-is. str values can be one of:
                - valid: No padding
                - same: Padding to produce the same output size as the strided input
                - causal: Padding to offset the filter so outputs only rely on leftward
                          values of the input
                - full: Padding such that the output contains all points with nonzero overlap
                        between the filters and the input

        Returns:
            output size (int)

        Raises:
            ValueError: If padding or output sizes are not valid
        """
        padding = self.get_padding_size(padding)
        k = self.dilation * (self.filter_size - 1) + 1
        if self.pooling and (max(padding) >= k):
            raise ValueError("Padding dim {} incompatible with filter size {}".format(padding, k))

        output = (self.input_size + sum(padding) - k) // self.stride + 1
        if output < 0:
            raise ValueError("Invalid convolution specifications, size of output would be <0")
        return int(output)

    def get_transpose_size(self, padding):
        """
        Get the output size following transposed convolution

        Arguments:
            padding (int, tuple, or str): Desired padding value. int values produce symmetric
                padding. tuple values are passed through as-is. str values can be one of:
                - valid: No padding
                - same: Padding to produce the same output size as the strided input
                - causal: Padding to offset the filter so outputs only rely on leftward
                          values of the input
                - full: Padding such that the output contains all points with nonzero overlap
                        between the filters and the input

        Returns:
            output size (int)

        Raises:
            ValueError: If padding or output sizes are not valid
        """
        padding = self.get_padding_size(padding)
        k = self.dilation * (self.filter_size - 1)

        output = self.stride * (self.input_size - 1) + k + 1 - sum(padding)
        if output < 0:
            raise ValueError("Invalid transposed convolution specifications, size of output would "
                             "be <0")
        return int(output)

    def _get_valid_padding(self):
        """
        'Valid' returns only outputs only when the input and filter overlap completely, so padding
        is 0.
        """
        return (0, 0)

    def _get_same_padding(self):
        """
        'Same' returns outputs  with the same size as the strided input

        Notes:
            See https://www.tensorflow.org/api_guides/python/nn#Notes_on_SAME_Convolution_Padding
            for a good reference
        """

        # This could be reduced, if desired.
        total_pad = int(self.stride * (np.ceil(self.input_size / self.stride) - 1) +
                        1 - self.input_size + self.dilation * (self.filter_size - 1))

        return (total_pad // 2, int(np.ceil(total_pad / 2)))

    def _get_causal_padding(self):
        """
        'Causal' returns outputs that only aggregate over past indices in the input.
        """
        return (self.dilation * (self.filter_size - 1), 0)

    def _get_full_padding(self):
        """
        'Full' returns all values where there is any overlap between the input and the filter
        """
        return (self.dilation * (self.filter_size - 1), self.dilation * (self.filter_size - 1))

    def _get_caffe_full_padding(self):
        raise NotImplementedError()

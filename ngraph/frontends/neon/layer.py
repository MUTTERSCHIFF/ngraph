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
from __future__ import division, print_function, absolute_import

import collections
import itertools
import six
from contextlib import contextmanager

import ngraph as ng
from ngraph.frontends.common import utils
from ngraph.frontends.common.utils import make_poolparams
from ngraph.frontends.neon.axis import shadow_axes_map, reorder_spatial_axes, assert_no_shadow_axes
from ngraph.frontends.neon.graph import SubGraph
from ngraph.frontends.neon.initializer import ConstantInit
from ngraph.frontends.neon.utils import get_function_or_class_name
from ngraph.op_graph.axes import IncompatibleAxesError


# Labels should be added as metadata on specific ops and variables
# Hopefully these can be used to efficiently display and filter the computational graph
LABELS = {"weight": "weight",
          "bias": "bias"}


class Layer(SubGraph):
    """
    Base class from which all other layers should inherit.

    Attributes:
        initialized - Whether or not the layer's variables have been created
        variables - All trainable variables defined in the layer
        inputs - Ops that are given as input to the layer
        side_effects - Ops not required to produce the output of the layer but which must run
                       anyway

    Methods:
        inference_mode_on - Context manager for inference mode
        inference_mode_key - cachetools hashing function that accounts for the value of
                             inference mode
    """
    inference_mode = False
    metadata = {}

    def __init__(self, name=None, **kwargs):
        super(Layer, self).__init__(name=name, **kwargs)

    def __call__(self, in_obj, **kwargs):
        raise NotImplementedError()

    @property
    def initialized(self):
        """
        True if the layer's __call__ method has been successfully executed
        """
        return len(self.ops) > 0

    @staticmethod
    @contextmanager
    def inference_mode_on():
        """
        Provides a context manager for doing model inference. This puts certain layers
        into "inference mode", if necessary (e.g. batch normalization and dropout).

        Examples:
            train_loss = ng.squared_l2(target - model(input))
            with Layer.inference_mode_on():
                eval_loss = ng.squared_l2(target - model(input))
        """
        Layer.inference_mode = True
        with ng.metadata(mode="inference"):
            yield
        Layer.inference_mode = False


class Preprocess(Layer):
    """
    TODO: Document
    """
    def __init__(self, functor, **kwargs):
        if ("name" not in kwargs):
            kwargs["name"] = get_function_or_class_name(functor)
        super(Preprocess, self).__init__(**kwargs)
        self.functor = functor

    @SubGraph.scope_op_creation
    def __call__(self, in_obj, **kwargs):
        return self.functor(in_obj)


def cast_tuple(x):
    """
    TODO: Document
    """
    # cast x to a tuple
    if isinstance(x, collections.Iterable):
        return tuple(x)
    else:
        return (x,)


def infer_axes(nout=None, axes=None):
    """
    TODO: Document
    Args:
        nout: int or iterable of ints specifying the lengths of the axes to be returned
        axes: Axes object that describe the output axes that should be returned
    """
    # if out_axes are provided, just return those
    if axes is not None:
        if nout is not None:
            raise ValueError(
                'if out_axes are provided, nout must be None.  Found {}'.format(nout)
            )

        if None in axes.lengths:
            raise ValueError((
                'if out_axes are provided, all lengths must be '
                'specified (not None).  Found {}'
            ).format(axes.lengths))

        return axes
    elif nout is not None:
        return ng.make_axes([ng.make_axis(length) for length in cast_tuple(nout)])
    else:
        raise ValueError(
            'nout and axes were both None, one of them must have a value'
        )


class Linear(Layer):
    """
    Linear layer that multiplies input tensor with a weight tensor.  This
    layer provides a simple interface to select the axes that should be created
    and the axes which should be preserved.

    Args:
        nout (int or iterable of ints, optional): length or lengths of
            feature axes the Linear layer should output.  Must not be
            provided in combination with axes.
        axes (Axes, optional): axes of feature axes the Linear layer
            should output.  Must not be provided in combination with nout.
            Axes should not include recurrent or batch axes.
        keep_axes (Axes, optional): in_obj axes which should be preserved.
            Defaults to preserving batch and recurrent axes.
    """
    def __init__(self, init, nout=None, axes=None, keep_axes=None, **kwargs):
        super(Linear, self).__init__(**kwargs)

        # axes should not include recurrent or batch axes
        if axes is not None:
            axes = ng.make_axes(axes)

            assert_no_shadow_axes(axes, 'axes passed to Linear')

        self.axes = infer_axes(nout, axes)
        self.axes_map = shadow_axes_map(self.axes)

        if keep_axes is not None:
            self.keep_axes = ng.make_axes(keep_axes)

            assert_no_shadow_axes(keep_axes, 'keep_axes passed to Linear')

            common_axes = self.keep_axes & self.axes
            if common_axes:
                raise IncompatibleAxesError((
                    'keep_axes and axes must not have any axes in common. '
                    'found: {}'
                ).format(common_axes))
        else:
            self.keep_axes = None

            if self.axes.batch_axis() is not None:
                raise ValueError((
                    'Axes passed to Linear layer should only be the output feature'
                    'axis.  A batch axis {} was included.'
                ).format(self.axes.batch_axis()))
            if self.axes.recurrent_axis() is not None:
                raise ValueError((
                    'Axes passed to Linear layer should only be the output feature'
                    'axis.  A recurrent axis {} was included.'
                ).format(self.axes.recurrent_axis()))

        self.init = init
        self.W = None

    @SubGraph.scope_op_creation
    def __call__(self, in_obj, reuse=True, **kwargs):

        if not self.initialized:
            if self.keep_axes is not None:
                w_in_axes = (in_obj.axes - self.keep_axes)
            else:
                w_in_axes = in_obj.axes.feature_axes()

            w_out_axes = ng.make_axes(self.axes_map.keys())
            self.W = ng.variable(axes=(w_out_axes + w_in_axes),
                                 initial_value=self.init,
                                 metadata={"label": LABELS["weight"]},
                                 ).named('W')

        # in the event that the in_obj feature axes and the output feature axes
        # share axis names, self.W will have duplicate axes, which are not
        # allowed.  To get around this, we rename the output feature axes to
        # something unique that we can undo after the dot.  This map_roles is
        # undoing this temporary axes name change.
        return ng.map_roles(ng.dot(self.W, in_obj), self.axes_map)


class LookupTable(Layer):
    """
    Lookup table layer that often is used as word embedding layer

    Args:
        vocab_size (int): the vocabulary size
        embed_dim (int): the size of embedding vector
        init (Initializor): initialization function
        update (bool): if the word vectors get updated through training
        pad_idx (int): by knowing the pad value, the update will make sure always
                       have the vector representing pad value to be 0s.
    """

    def __init__(self, vocab_size, embed_dim, init, update=True, pad_idx=None,
                 **kwargs):
        super(LookupTable, self).__init__(**kwargs)

        self.vocab_size = vocab_size
        self.embed_dim = embed_dim
        self.init = init
        self.update = update
        self.pad_idx = pad_idx
        self.W = None

    def lut_init(self, axes, pad_word_axis, pad_idx):
        """
        Initialization function for the lut.
        After using the initialization to fill the whole array, set the part that represents
        padding to be 0.
        """
        init_w = self.init(axes)
        if axes.index(pad_word_axis) is 0:
            init_w[pad_idx] = 0
        else:
            init_w[:, pad_idx] = 0
        return init_w

    @SubGraph.scope_op_creation
    def __call__(self, in_obj, **kwargs):
        """
        Arguments:
            in_obj (Tensor): object that provides the lookup indices
        """
        if in_obj.axes.recurrent_axis() is None:
            in_obj = ng.axes_with_order(in_obj,
                                        ng.make_axes([in_obj.axes.batch_axis()]))
        else:
            in_obj = ng.axes_with_order(in_obj,
                                        ng.make_axes([in_obj.axes.recurrent_axis(),
                                                      in_obj.axes.batch_axis()]))
        in_obj = ng.flatten(in_obj)
        in_axes = in_obj.axes

        # label lut_v_axis as shadow axis for initializers ... once #1158 is
        # in, shadow axis will do more than just determine fan in/out for
        # initializers.
        self.lut_v_axis = ng.make_axis(self.vocab_size).named('V')
        self.axes_map = shadow_axes_map([self.lut_v_axis])
        self.lut_v_axis = list(self.axes_map.values())[0]

        self.lut_f_axis = ng.make_axis(self.embed_dim).named('F')

        self.w_axes = ng.make_axes([self.lut_v_axis, self.lut_f_axis])
        self.lut_o_axes = in_axes | ng.make_axes([self.lut_f_axis])
        self.o_axes = ng.make_axes([self.lut_f_axis]) | in_axes[0].axes

        if not self.initialized:
            self.W = ng.variable(axes=self.w_axes,
                                 initial_value=self.lut_init(
                                     self.w_axes, self.lut_v_axis, self.pad_idx),
                                 metadata={"label": LABELS["weight"]},
                                 ).named('LutW')

        lut_result = ng.lookuptable(self.W, in_obj, self.lut_o_axes, update=self.update,
                                    pad_idx=self.pad_idx)
        return ng.axes_with_order(
            ng.map_roles(ng.unflatten(lut_result), self.axes_map), self.o_axes
        )


class ConvBase(Layer):
    """
    Convolutional layer that performs 3D convolutions. This is used under-the-hood and should not
    be called directly.

    This layer provides an interface to the core convolution support within ngraph. 1D and 2D
    convolutions are automatically represented as 3D convolutions, with extra axes
    temporarily introduced as needed.

    Arguments:
        filter_shape (dict): filter shape -- must contain keys 'D', 'H', 'W', 'K'
        init (function): function for later initializing filters
        strides (dict): stride specification -- can contain keys 'D', 'H', 'W' - defaults to 1
        padding (dict): pad specification -- can contain keys 'D', 'H', 'W' - defaults to 0. Each
            padding value can be one of:
            - (int): specifies a symmetric padding value
            - (tuple): specifies left and right padding values individually
            - (str): one of "same", "valid", "full" or "causal"
        dilation (dict): dilation specification -- can contain keys 'D', 'H', 'W' - defaults to 1

    Attributes:
        W (TensorOp): The convolutional filters. Axes are ordered as:
            C: input channels
            D: depth
            H: height
            W: width
            K: output channels
        nout (int): The number of output channels

    Required Axis Types:
        channel: The input channel axis with default name "C". Currently only one channel axis is
                 supported.
        spatial: The spatial axes over which to convolve. Currently must be between 1 and 3.
            depth: The depth axis with default name "D".
            height: The height axis with default name "H".
            width: The width axis with default name "W".
    """

    def __init__(self, filter_shape, init, strides, padding, dilation, **kwargs):
        super(ConvBase, self).__init__(**kwargs)

        def check_dict(obj, name, keys=None):
            if not isinstance(obj, dict):
                raise TypeError("type({}) must be dict, not {}".format(name, type(obj)))
            if keys is not None:
                for key in keys:
                    if key not in obj:
                        raise ValueError("{} must have specified values for all axes,"
                                         "{}. Found {}".format(name, ", ".join(keys),
                                                               list(obj.keys())))
        self.init = init

        # Setup filter parameters
        check_dict(filter_shape, "filter_shape", "DHWK")
        self.nout = filter_shape.pop("K")
        self.filter_shape = filter_shape

        # Setup strides - default to 1
        check_dict(strides, "strides")
        self.strides = {key: 1 for key in "DHW"}
        self.strides.update(strides)

        # Setup padding - default to 0
        check_dict(padding, "padding")
        self.padding = {key: 0 for key in "DHW"}
        self.padding.update(padding)

        # Setup dilation - default to 1
        check_dict(dilation, "dilation")
        self.dilation = {key: 1 for key in "DHW"}
        self.dilation.update(dilation)

        self.W = None

    def _filter_axes(self, channel_axes, spatial_axes):
        """
        Create the filter axes. They are ordered as (C, D, H, W, K).
        """
        f_axes = channel_axes
        for key, ax in zip("DHW", spatial_axes):
            f_axes += ng.make_axis(length=self.filter_shape[key],
                                   name=ax.name)
        f_axes += ng.make_axis(length=self.nout, name="K")
        return f_axes

    def _output_axes(self, channel_axes, spatial_axes, batch_axis, pad_int):
        """
        Create the convolution output axes.

        TODO: This should be done in the core since it's fully determined.
        """
        output_axes = ng.make_axis(length=self.nout, name=channel_axes.name)
        for key, ax in zip("DHW", spatial_axes):
            output_axes += ng.make_axis(name=ax.name,
                                        length=utils.conv_output_dim(ax.length,
                                                                     self.filter_shape[key],
                                                                     pad_int[key],
                                                                     self.strides[key],
                                                                     False,
                                                                     self.dilation[key]))
        return output_axes + batch_axis

    def _get_pad_int(self, spatial_axes):
        """
        Get integer padding values for each spatial axis. If padding is asymmetric,
        return the required manual paddings.
        """
        # Manual padding might be required for asymmetric paddings
        manual_pad = {}
        padding_int = {}
        for name, ax in zip("DHW", spatial_axes):
            pad = utils.ConvParameters(ax.length,
                                       self.filter_shape[name],
                                       self.strides[name],
                                       self.dilation[name]).get_padding_size(self.padding[name])
            symm_pad = min(pad)
            padding_int[name] = symm_pad
            if pad[0] != pad[1]:
                manual_pad[ax.name] = (pad[0] - symm_pad, pad[1] - symm_pad)

        return padding_int, manual_pad

    def _conv_op(self, in_obj, channel_axes, spatial_axes):
        """
        Setup for the call to ng.convolution.
        """
        manual_pad = collections.OrderedDict([(ax.name, (0, 0)) for ax in in_obj.axes])
        pad_int, extra_pad = self._get_pad_int(spatial_axes)
        manual_pad.update(extra_pad)
        if any((pad != (0, 0)) for pad in manual_pad.values()):
            in_obj = ng.pad(in_obj, manual_pad.values())
            spatial_axes = in_obj.axes.get_by_names(*ng.make_axes(spatial_axes).names)
        output_axes = self._output_axes(channel_axes, spatial_axes, in_obj.axes.batch_axis(),
                                        pad_int)
        convparams = utils.make_convparams(self.nout, self.filter_shape,
                                           self.strides, pad_int, self.dilation)
        return ng.convolution(convparams,
                              in_obj,
                              self.W,
                              axes=output_axes)

    @SubGraph.scope_op_creation
    def __call__(self, in_obj, channel_axes="C", spatial_axes=("D", "H", "W"), **kwargs):
        """
        Arguments:
            in_obj (Op): Input op
            channel_axes (str): name of the expected channel axis type - defaults to "C"
            spatial_axes (tuple): names of expected depth, height and width axis types - defaults
                                  to "D", "H", and "W"
        """
        if isinstance(spatial_axes, dict):
            spatial_axes = tuple(spatial_axes.get(name, name)
                                 for name in ("D", "H", "W"))
        elif isinstance(spatial_axes, tuple):
            if len(spatial_axes) < 3:
                raise ValueError("spatial_axes must have length 3 (e.g. ('D', 'H', 'W'))")
            spatial_axes = tuple(name if name else default
                                 for name, default in zip(spatial_axes, ("D", "H", "W")))

        orig_axes = in_obj.axes
        in_obj = reorder_spatial_axes(in_obj, channel_axes, spatial_axes)
        channel_axes = in_obj.axes.get_by_names(channel_axes)
        spatial_axes = in_obj.axes.get_by_names(*spatial_axes)

        filter_axes = self._filter_axes(channel_axes, spatial_axes)

        # mark 'K' as a shadow axis for the initializers.
        axes_map = shadow_axes_map(filter_axes.find_by_name('K'))
        filter_axes = ng.make_axes([
            axis if axis.name != 'K' else list(axes_map.keys())[0]
            for axis in filter_axes
        ])

        if not self.initialized:
            self.W = ng.variable(axes=filter_axes,
                                 initial_value=self.init,
                                 metadata={"label": LABELS["weight"]}).named("W")
        else:
            if filter_axes != self.W.axes:
                raise ValueError((
                    "{layer_name} layer has already been initialized with an "
                    "input object which has resulted in filter axes: "
                    "{existing_filter_axes}. This new input object has axes: "
                    "{input_axes}, which implies the need for filter axes: "
                    "{new_filter_axes} which are different than the existing "
                    "filter axes."
                ).format(
                    layer_name=self.name,
                    existing_filter_axes=self.W.axes,
                    input_axes=in_obj.axes,
                    new_filter_axes=filter_axes,
                ))

        output = ng.map_roles(self._conv_op(in_obj, channel_axes, spatial_axes), axes_map)
        # Reorder the output to match the input order
        output_axis_order = ng.make_axes([output.axes.find_by_name(ax.name)[0]
                                          for ax in orig_axes])
        # Remove introduced axes. If their length is > 1, then perhaps they should be kept
        slices = [0 if (ax not in orig_axes) and ax.length == 1 else slice(None)
                  for ax in output.axes]
        output = ng.tensor_slice(output, slices)
        # New axes with length > 1 may have been introduced. Add them to the end.
        output_axis_order = output_axis_order | output.axes
        return ng.axes_with_order(output, output_axis_order)


class DeconvBase(ConvBase):
    """
    Deconvolutional layer that performs 3D deconvolutions (otherwise known as transpose
    convolutions or fractionally-strided convolutions).  This is used under-the-hood and should
    not be called directly.

    This layer provides an interface to the core deconvolution support within ngraph. 1D and 2D
    deconvolutions are automatically represented as 3D deconvolutions, with extra axes
    temporarily introduced as needed. The specified strides, padding and dilation arguments are
    for the corresponding forward convolution.

    Arguments:
        filter_shape (dict): filter shape -- must contain keys 'D', 'H', 'W', 'K'
        init (function): function for later initializing filters
        strides (dict): stride specification -- can contain keys 'D', 'H', 'W' - defaults to 1
        padding (dict): pad specification -- can contain keys 'D', 'H', 'W' - defaults to 0. Each
            padding value can be one of:
            - (int): specifies a symmetric padding value
            - (tuple): specifies left and right padding values individually
            - (str): one of "same", "valid", "full" or "causal"
        dilation (dict): dilation specification -- can contain keys 'D', 'H', 'W' - defaults to 1

    Attributes:
        W (TensorOp): The deconvolutional filters. Axes are ordered as:
            K: output channels
            D: depth
            H: height
            W: width
            C: input channels
        nout (int): The number of output channels

    Required Axis Types:
        channel: The input channel axis with default name "C". Currently only one channel axis is
                 supported.
        spatial: The spatial axes over which to deconvolve. Currently must be between 1 and 3.
            depth: The depth axis with default name "D".
            height: The height axis with default name "H".
            width: The width axis with default name "W".
    """
    def _filter_axes(self, channel_axis, spatial_axes):
        """
        Create the filter axes. They are ordered as (K, D, H, W, C).
        """
        f_axes = ng.make_axis(length=self.nout, name="K")
        for key, ax in zip("DHW", spatial_axes):
            f_axes += ng.make_axis(length=self.filter_shape[key],
                                   name=ax.name)
        f_axes += channel_axis
        return f_axes

    def _output_axes(self, channel_axis, spatial_axes, batch_axis, pad_int):
        """
        Create the deconvolution output axes.

        TODO: This should be done in the core since it's fully determined.
        """
        output_axes = ng.make_axis(length=self.nout, name=channel_axis.name)
        for key, ax in zip("DHW", spatial_axes):
            output_axes += ng.make_axis(name=ax.name,
                                        length=utils.deconv_output_dim(ax.length,
                                                                       self.filter_shape[key],
                                                                       pad_int[key],
                                                                       self.strides[key],
                                                                       self.dilation[key]))
        return output_axes + batch_axis

    def _conv_op(self, in_obj, channel_axes, spatial_axes):
        """
        Setup for the call to ng.deconvolution.
        """

        manual_pad = collections.OrderedDict([(ax.name, (0, 0)) for ax in in_obj.axes])
        pad_int, extra_pad = self._get_pad_int(spatial_axes)
        manual_pad.update(extra_pad)
        if any((pad != (0, 0)) for pad in manual_pad.values()):
            in_obj = ng.pad(in_obj, manual_pad.values())
            spatial_axes = in_obj.axes.get_by_names(*ng.make_axes(spatial_axes).names)

        output_axes = self._output_axes(channel_axes, spatial_axes, in_obj.axes.batch_axis(),
                                        pad_int)
        convparams = utils.make_convparams(self.nout, self.filter_shape,
                                           self.strides, pad_int, self.dilation)
        return ng.deconvolution(convparams,
                                in_obj,
                                self.W,
                                axes=output_axes)


def make_conv(filter_shape, init, strides, padding, dilation, deconv=False,
              **kwargs):
    default_filter_shape = {k: 1 for k in "DHWK"}
    if isinstance(filter_shape, (list, tuple)):
        if (len(filter_shape) < 2) or (len(filter_shape) > 4):
            raise ValueError("If filter_shape is a list, its length should be between 2 and 4, "
                             "specifying the filter size for 1 to 3 spatial dimensions and the "
                             "number of filters. Provided: {}".format(filter_shape))
        axis_names = {2: "WK", 3: "HWK", 4: "DHWK"}[len(filter_shape)]
        default_filter_shape.update(list(zip(axis_names, filter_shape)))
        filter_shape = default_filter_shape
    else:
        axis_names = filter_shape.keys()
    if isinstance(strides, int):
        strides = {k: strides for k in axis_names if k != "K"}
    if isinstance(padding, (int, six.string_types, tuple)):
        padding = {k: padding for k in axis_names if k != "K"}
    if isinstance(dilation, int):
        dilation = {k: dilation for k in axis_names if k != "K"}

    if deconv:
        return DeconvBase(filter_shape, init, strides, padding, dilation, **kwargs)
    else:
        return ConvBase(filter_shape, init, strides, padding, dilation, **kwargs)


class Activation(Layer):
    """
    TODO: Document. Why should we pass through this instead of just defining functions? Caching?
    """
    def __init__(self, transform, **kwargs):
        if ("name" not in kwargs) and (transform is not None):
            kwargs["name"] = get_function_or_class_name(transform)
        super(Activation, self).__init__(**kwargs)
        self.transform = transform

    @SubGraph.scope_op_creation
    def __call__(self, in_obj, **kwargs):
        # An activation layer with no transform defaults to identity
        if self.transform:
            return self.transform(in_obj)
        else:
            return in_obj


class PoolBase(Layer):
    """
    Pooling layer that performs 4D poolings. This is used under-the-hood and should not be called
    directly.

    This layer provides an interface to the core pooling support within ngraph. Lower dimensional
    pooling operations are automatically represented as 4D poolings, with extra axes temporarily
    introduced as needed.

    Arguments:
        pool_shape (dict): pooling shape -- must contain keys 'C', 'D', 'H', and 'W'
        strides (dict): stride specification -- can contain keys 'D', 'H', 'W' - defaults to 1
        padding (dict): pad specification -- can contain keys 'D', 'H', 'W' - defaults to 0. Each
            padding value can be one of:
            - (int): specifies a symmetric padding value
            - (tuple): specifies left and right padding values individually
            - (str): one of "same", "valid", "full" or "causal"
        pool_type (str): type of pooling -- can be one of 'max' or 'avg', case-insensitive

    Required Axis Types:
        channel: The input channel axis with default name "C". Currently only one channel axis is
                 supported.
        spatial: The spatial axes over which to convolve. Currently must be between 1 and 3.
            depth: The depth axis with default name "D".
            height: The height axis with default name "H".
            width: The width axis with default name "W".
    """

    def __init__(self, pool_shape, strides, padding, pool_type='max', **kwargs):
        super(PoolBase, self).__init__(**kwargs)

        def check_dict(obj, name, keys=None):
            if not isinstance(obj, dict):
                raise TypeError("type({}) must be dict, not {}".format(name, type(obj)))
            if keys is not None:
                for key in keys:
                    if key not in obj:
                        raise ValueError("{} must have specified values for all axes,"
                                         "{}. Found {}".format(name, ", ".join(keys),
                                                               list(obj.keys())))
        self.pool_type = pool_type.lower()
        if self.pool_type not in ("max", "avg"):
            raise ValueError("pool_type must be one of {}, not {}".format(('max', 'avg'),
                                                                          pool_type))

        # Setup pooling parameters
        check_dict(pool_shape, "pool_shape", "CDHW")
        self.pool_shape = pool_shape

        # Setup strides - default to 1
        check_dict(strides, "strides")
        self.strides = {key: 1 for key in "CDHW"}
        self.strides.update(strides)

        # Setup padding - default to 0
        check_dict(padding, "padding")
        self.padding = {key: 0 for key in "CDHW"}
        self.padding.update(padding)

    def _get_pad_int(self, axes):
        """
        Get integer padding values for each axis. If padding is asymmetric,
        return the required manual paddings.
        """
        # Manual padding might be required for asymmetric paddings
        manual_pad = {}
        padding_int = {}
        for name, ax in zip("CDHW", axes):
            pad = utils.ConvParameters(ax.length,
                                       self.pool_shape[name],
                                       self.strides[name],
                                       pooling=True).get_padding_size(self.padding[name])
            symm_pad = min(pad)
            padding_int[name] = symm_pad
            if pad[0] != pad[1]:
                manual_pad[ax.name] = (pad[0] - symm_pad, pad[1] - symm_pad)

        return padding_int, manual_pad

    def _output_axes(self, channel_axes, spatial_axes, batch_axis, pad_int):
        """
        Create the pooling output axes.

        TODO: This should be done in the core since it's fully determined.
        """
        output_axes = ng.make_axes()
        for name, ax in zip("CDHW", (channel_axes,) + spatial_axes):
            output_axes += ng.make_axis(name=ax.name,
                                        length=utils.conv_output_dim(ax.length,
                                                                     self.pool_shape[name],
                                                                     pad_int[name],
                                                                     self.strides[name],
                                                                     pooling=True))
        return output_axes + batch_axis

    def _pool_op(self, in_obj, channel_axes, spatial_axes):
        """
        Setup for the call to ng.pooling.
        """
        manual_pad = collections.OrderedDict([(ax.name, (0, 0)) for ax in in_obj.axes])
        pad_int, extra_pad = self._get_pad_int((channel_axes, ) + spatial_axes)
        manual_pad.update(extra_pad)
        if any((pad != (0, 0)) for pad in manual_pad.values()):
            in_obj = ng.pad(in_obj, manual_pad.values())
            channel_axes = in_obj.axes.get_by_names(*ng.make_axes(channel_axes).names)
            spatial_axes = in_obj.axes.get_by_names(*ng.make_axes(spatial_axes).names)
        output_axes = self._output_axes(channel_axes, spatial_axes, in_obj.axes.batch_axis(),
                                        pad_int)
        poolparams = make_poolparams(self.pool_type,
                                     self.pool_shape,
                                     self.strides,
                                     pad_int)
        return ng.pooling(poolparams,
                          in_obj,
                          axes=output_axes)

    @SubGraph.scope_op_creation
    def __call__(self, in_obj, channel_axes="C", spatial_axes=("D", "H", "W"), **kwargs):
        """
        Pool over in_obj

        Arguments:
            in_obj (Op): Input op
            channel_axes (str): name of the expected channel axis type - defaults to "C"
            spatial_axes (tuple): names of expected depth, height and width axis types - defaults
                                  to "D", "H", and "W"
        """
        if isinstance(spatial_axes, dict):
            spatial_axes = tuple(spatial_axes.get(name, name)
                                 for name in ("D", "H", "W"))
        elif isinstance(spatial_axes, tuple):
            if len(spatial_axes) < 3:
                raise ValueError("spatial_axes must have length 3 (e.g. ('D', 'H', 'W'))")
            spatial_axes = tuple(name if name else default
                                 for name, default in zip(spatial_axes, ("D", "H", "W")))

        orig_axes = in_obj.axes
        in_obj = reorder_spatial_axes(in_obj, channel_axes, spatial_axes)
        channel_axes = in_obj.axes.get_by_names(channel_axes)
        spatial_axes = in_obj.axes.get_by_names(*spatial_axes)

        output = self._pool_op(in_obj, channel_axes, spatial_axes)
        # Reorder the output to match the input order
        output_axis_order = ng.make_axes([output.axes.find_by_name(ax.name)[0]
                                          for ax in orig_axes])
        # Remove introduced axes
        slices = [0 if (ax not in orig_axes) else slice(None) for ax in output.axes]
        return ng.axes_with_order(ng.tensor_slice(output, slices), output_axis_order)


class Pooling(PoolBase):
    """
    Pooling layer that performs 1D to 4D pooling

    Arguments:
        pool_shape (tuple, dict): Pooling shape expressed as one of (width,), (height, width),
            (depth, height, width), or (channel, depth, height, width) for 1D to 4D pooling,
            respectively. pool_shape also accepts a dict of the format {"H": height, "W": width,
            "D": depth, "C": channels}
        strides (int, dict): Pooling stride value. If strides is a dict, must specify all axes
            given in pool_shape as e.g. {"W": width}.
        padding (int, tuple, str, dict): Input paddings. A padding value can be one of:
            - (int): specifies a symmetric padding value
            - (tuple): specifies left and right padding values individually
            - (str): one of "same", "valid", "full" or "causal"
            - (dict): specified as name: value, where name is one of 'C', 'D', 'H', or 'W' and
                      value is one of the above.
        pool_type (str): Type of pooling to perform. Currently available are 'max' and 'avg',
            case-insensitive

    Required Axis Types:
        channel: The input channel axis with default name "C". Currently only one channel axis is
                 supported.
        spatial: The spatial axes over which to convolve. Currently must be between 1 and 3.
            depth: The depth axis with default name "D".
            height: The height axis with default name "H".
            width: The width axis with default name "W".
    """
    def __init__(self, pool_shape, strides=1, padding=0, pool_type='max', **kwargs):

        default_pool_shape = {k: 1 for k in "CDHW"}
        if isinstance(pool_shape, (list, tuple)):
            if (len(pool_shape) < 1) or (len(pool_shape) > 4):
                raise ValueError("If pool_shape is a list, its length should be between 2 and 4, "
                                 "specifying the pooling size for the channel axis and 1 to 3 "
                                 "spatial dimensions. Provided: {}".format(pool_shape))
            axis_names = {1: "W", 2: "HW", 3: "DHW", 4: "CDHW"}[len(pool_shape)]
            default_pool_shape.update(list(zip(axis_names, pool_shape)))
            pool_shape = default_pool_shape
        else:
            axis_names = pool_shape.keys()
        if isinstance(strides, int):
            strides = {k: strides for k in axis_names}
        if isinstance(padding, (int, six.string_types, tuple)):
            padding = {k: padding for k in axis_names}
        super(Pooling, self).__init__(pool_shape, strides, padding, pool_type=pool_type,
                                      **kwargs)


class Bias(Layer):
    """
    Bias layer, common to linear and convolutional layers

    Args:
        init (function): function for later initializing bias values
        shared (bool): applies only to convolutional biases.  Whether to use same bias for
                       entire feature map.  Default true.

    TODO: Should default be None or 0?
    """
    def __init__(self, init, shared=True, **kwargs):
        super(Bias, self).__init__(**kwargs)
        self.W = None
        self.init = init if init is not None else ConstantInit(0)
        self.shared = shared

    @SubGraph.scope_op_creation
    def __call__(self, in_obj, **kwargs):
        if not self.initialized:
            w_axes = in_obj.axes.feature_axes()
            if self.shared and in_obj.axes.channel_axis() is not None:
                w_axes = ng.make_axes(in_obj.axes.channel_axis())
            self.W = ng.variable(axes=w_axes, initial_value=self.init,
                                 metadata={"label": LABELS["bias"]}).named("bias")
        return in_obj + self.W


class Affine(Layer):
    """
    Affine (fully connected) layer that applies a linear transform of its input
    This layer can optionally add a bias to the transform
    Optionally, it can apply batch normalization after the linear transform
    If batch normalization is used, bias is not used (ignored)
    Output of the the previous steps is passed through the given activation function
    Arguments:
        weight_init (function): Initialization function for the weights
        nout (int): Number of neurons in the layer
        bias_init (function, optional): The bias initialization function. If bias_init is None,
            then no bias is applied. If batch normalization is used, bias_init is ignored.
        activation (function, optional): Activation function to be applied to the output. The
            default uses the identity function.
        batch_norm (bool or layer of type BatchNorm, optional):
            Whether or not to apply batch normalization. Batch
            normalization contains its own bias, so if True, bias_init should not be supplied.
            If set to True, initializes a BatchNorm layer with default parameters
            Alternatively, you can pass in an initialized BatchNorm layer with desired parameters
        axes (Axes, optional): axes of feature axes the Affine layer
            should output.  Must not be provided in combination with nout.
            Axes should not include recurrent or batch axes.
            Typically used in the last layer of the network to match the feature axes

    Attributes:
        linear (Layer): The `Linear` layer that performs the linear transform
        bias (Layer): The `Bias` layer that performs bias addition
        batch_norm_layer (Layer): The `BatchNorm` layer that performs batch normalization
        activation_layer (Layer): The `Activation` layer to transform the output

    Examples:
        .. code-block:: python
           # Create an Affine layer with batch normalization and a ReLU activation
           affine = Affine(nout=50, activation=Rectlin(), batch_norm=True)
           output = affine(input)
        .. code-block:: python
           # Create an Affine layer with ReLU activation, and a batch normalization
           # layer with desired parameters
           affine = Affine(nout=50, activation=Rectlin(), batch_norm=BatchNorm(rho=0.99))
           output = affine(input)

        .. code-block:: python
           # Get the feature axes from the sample target
           output_axes = target.feature_axes()
           # Create an affine layer with the same output feature axes
           affine = Affine(weight_init=GaussianInit(), activation=Softmax(), axes=output_axes)
           output = affine(input)
    """
    def __init__(self, weight_init, nout=None, bias_init=None, activation=None,
                 batch_norm=False, axes=None, **kwargs):
        super(Affine, self).__init__(**kwargs)
        self.weight_init = weight_init
        self.nout = nout
        self.bias_init = bias_init
        self.activation = activation
        self.linear = Linear(init=weight_init, nout=nout, axes=axes)
        self.bias = Bias(init=bias_init) if not batch_norm else None
        self.batch_norm = batch_norm
        bn_layer = isinstance(batch_norm, BatchNorm)
        bn_boolean = isinstance(batch_norm, bool) and batch_norm
        if bn_layer:
            self.batch_norm_layer = batch_norm
        elif batch_norm:
            self.batch_norm_layer = BatchNorm()
        else:
            self.batch_norm_layer = None
        if (bn_layer or bn_boolean) and (bias_init is not None):
            raise ValueError("If batch normalization is used, bias_init should be None.")
        self.activation_layer = Activation(transform=self.activation)

    @SubGraph.scope_op_creation
    def __call__(self, in_obj, **kwargs):
        l_out = self.linear(in_obj)
        # TODO: This is a bit convoluted. Need to clean it up.
        b_out = self.bias(l_out) if not self.batch_norm else l_out
        bn_out = self.batch_norm_layer(b_out) if self.batch_norm else b_out
        return self.activation_layer(bn_out)


class Convolution(SubGraph):
    """
    Compute a 1D to 3D convolution over the input.

    A multi-part layer that computes a convolution over its input. Following convolution,
    it adds a bias or performs batch normalization, then passes the output through an activation
    function.

    Arguments:
        filter_shape (tuple, dict): Filter shape expressed as one of (width, nout), (height,
            width, nout), or (depth, height, width, nout) for 1D to 3D convolutions,
            respectively. filter_shape also accepts a dict of the format {"H": height, "W": width,
            "D": depth, "K": nout}
        filter_init (function): The filter initialization function
        strides (int, dict, optional): Filter strides. If strides is a dictionary, it should be
            formatted as {"H": str_h, "W": str_w}, where str_h and str_w should be integers.
        padding (int, str, dict, optional): Input paddings. A padding value can be one of:
            - (int): specifies a symmetric padding value
            - (tuple): specifies left and right padding values individually
            - (str): one of "same", "valid", "full" or "causal"
            - (dict): specified as {"H": pad_h, "W": pad_w} where pad_h and pad_w are one of the
                      above.
        dilation (int, dict, optional): Filter dilations. If dilation is a dictionary, it should be
            formatted as {"H": dil_h, "W": dil_w}, where dil_h and dil_w should be integers.
        bias_init (function, optional): The bias initialization function. If bias_init is None,
            then no bias is applied. If batch normalization is used, bias_init should be None.
        activation (function, optional): Activation function to be applied to the output. The
            default uses the identity function.
        batch_norm (bool or layer of type BatchNorm, optional):
            Whether or not to apply batch normalization. Batch
            normalization contains its own bias, so if True, bias_init should not be supplied.
            If set to True, initializes a BatchNorm layer with default parameters
            Alternatively, you can pass in an initialized BatchNorm layer with desired parameters

    Attributes:
        conv (Layer): The `ConvBase` layer that performs the convolution
        bias (Layer): The `Bias` layer that performs bias addition
        batch_norm (Layer): The `BatchNorm` layer that performs batch normalization
        activation (Layer): The `Activation` layer to transform the output

    Required Axis Types:
        channel: The input channel axis with default name "C". Currently only one channel axis is
                 supported.
        spatial: The spatial axes over which to convolve. Currently must be between 1 and 3.
            depth: The depth axis with default name "D".
            height: The height axis with default name "H".
            width: The width axis with default name "W".

    Examples:
        .. code-block:: python
           # Create a 5x5 convolutional layer with batch normalization (default parameters)
           #  and a ReLU activation
           conv = Convolution((5, 5, 16), filter_init=UniformInit(-.5, .5), padding="same",
                              activation=Rectlin(), batch_norm=True)
           output = conv(input)

        .. code-block:: python
           # Create a 5x5 convolutional layer with batch normalization (non-default parameters)
           # and a ReLU activation
           conv = Convolution((5, 5, 16), filter_init=UniformInit(-.5, .5), padding="same",
                              activation=Rectlin(), batch_norm=BatchNorm(rho=0.999, eps=1e-2))
           output = conv(input)

        .. code-block:: python
           # Convolve along the "time" axis of a spectrogram
           conv = Convolution((nfrequencies, 11, 16), filter_init=GaussianInit(var=.05),
                              padding="same", activation=Rectlin(), bias_init=ConstantInit(0))
           output = conv(input, spatial_axes={"W": "time"})

        .. code-block:: python
           # Compute a 1-D causal convolution with filter width 2 and dilation 2
           conv = Convolution((2, 16), filter_init=GaussianInit(var=.05), dilation=2,
                              padding="causal", activation=Rectlin(), bias_init=ConstantInit(0))
           output = conv(input)
    """
    def __init__(self, filter_shape, filter_init, strides=1, padding=0, dilation=1, bias_init=None,
                 activation=None, batch_norm=False, **kwargs):
        super(Convolution, self).__init__(**kwargs)
        self._make_conv_layer(filter_shape, filter_init, strides, padding, dilation, **kwargs)

        bn_layer = isinstance(batch_norm, BatchNorm)
        bn_boolean = isinstance(batch_norm, bool) and batch_norm
        if bn_layer:
            self.batch_norm = batch_norm
        elif batch_norm:
            self.batch_norm = BatchNorm()
        else:
            self.batch_norm = None
        if (bn_layer or bn_boolean) and (bias_init is not None):
            raise ValueError("If batch normalization is used, bias_init should be None.")

        self.bias = Bias(init=bias_init) if bias_init is not None else None
        self.activation = Activation(transform=activation)

    def _make_conv_layer(self, filter_shape, filter_init, strides, padding, dilation, **kwargs):
        self.conv = make_conv(filter_shape, filter_init, strides, padding, dilation,
                              deconv=False, **kwargs)

    @SubGraph.scope_op_creation
    def __call__(self, in_obj, channel_axes="C", spatial_axes=("D", "H", "W"), **kwargs):
        """
        Compute a convolution over in_obj

        Arguments:
            in_obj (Op): Input op
            channel_axes (str): name of the expected channel axis type - defaults to "C"
            spatial_axes (tuple): names of expected depth, height and width axis types - defaults
                                  to "D", "H", and "W"
        """
        l_out = self.conv(in_obj, channel_axes=channel_axes, spatial_axes=spatial_axes)
        if self.batch_norm is not None:
            l_out = self.batch_norm(l_out)
        elif self.bias is not None:
            l_out = self.bias(l_out)
        return self.activation(l_out)


class Deconvolution(Convolution):
    """
    Compute a 1D to 3D deconvolution over the input. This is also commonly known as a transpose
    convolution or a fractionally-strided convolution.

    A multi-part layer that computes a deconvolution over its input. Following convolution.
    it adds a bias or performs batch normalization, then passes the output through an activation
    function. The specified strides, padding and dilation arguments are
    for the corresponding forward convolution.

    Arguments:
        filter_shape (tuple, dict): Filter shape expressed as one of (width, nout), (height,
            width, nout), or (depth, height, width, nout) for 1D to 3D deconvolutions,
            respectively. filter_shape also accepts a dict of the format {"H": height, "W": width,
            "D": depth, "K": nout}
        filter_init (function): The filter initialization function
        strides (int, dict, optional): Filter strides. If strides is a dictionary, it should be
            formatted as {"H": str_h, "W": str_w}, where str_h and str_w should be integers.
        padding (int, str, dict, optional): Input paddings. A padding value can be one of:
            - (int): specifies a symmetric padding value
            - (tuple): specifies left and right padding values individually
            - (str): one of "same", "valid", "full" or "causal"
            - (dict): specified as {"H": pad_h, "W": pad_w} where pad_h and pad_w are one of the
                      above.
        dilation (int, dict, optional): Filter dilations. If dilation is a dictionary, it should be
            formatted as {"H": dil_h, "W": dil_w}, where dil_h and dil_w should be integers.
        bias_init (function, optional): The bias initialization function. If bias_init is None,
            then no bias is applied. If batch normalization is used, bias_init should be None.
        activation (function, optional): Activation function to be applied to the output. The
            default uses the identity function.
        batch_norm (bool, optional): Whether or not to apply batch normalization. Batch
            normalization contains its own bias, so if True, bias_init should not be supplied.
        deconv_out_shape (tuple, optional): If given, trims the output to the specified
            shape, given as (depth_size, height_size, width_size). Unused axes can be specified
            as None.

    Attributes:
        conv (Layer): The `DeconvBase` layer that performs the deconvolution
        bias (Layer): The `Bias` layer that performs bias addition
        batch_norm (Layer): The `BatchNorm` layer that performs batch normalization
        activation (Layer): The `Activation` layer to transform the output

    Required Axis Types:
        channel: The input channel axis with default name "C". Currently only one channel axis is
                 supported.
        spatial: The spatial axes over which to convolve. Currently must be between 1 and 3.
            depth: The depth axis with default name "D".
            height: The height axis with default name "H".
            width: The width axis with default name "W".

    Examples:
        .. code-block:: python
           deconv = Deconvolution((1, 1, 16), filter_init=GaussianInit(var=.05), strides=1,
                                  padding=0, activation=Rectlin(), batch_norm=True)
           output = deconv(input)
    """
    def __init__(self, filter_shape, filter_init, strides=1, padding=0, dilation=1, bias_init=None,
                 activation=None, batch_norm=False, deconv_out_shape=None, **kwargs):
        super(Deconvolution, self).__init__(filter_shape, filter_init,
                                            strides=strides, padding=padding, dilation=dilation,
                                            bias_init=bias_init, activation=activation,
                                            batch_norm=batch_norm, **kwargs)
        self.deconv_out_shape = deconv_out_shape

    def _make_conv_layer(self, filter_shape, filter_init, strides, padding, dilation, **kwargs):
        self.conv = make_conv(filter_shape, filter_init, strides, padding, dilation,
                              deconv=True, **kwargs)

    def _slice_output(self, output, spatial_axes):
        """
        Slice output to desired shape given by deconv_out_shape

        Arguments:
            output (TensorOp): tensor to slice
            spatial_axes (tuple): names of spatial axes
        """

        if self.deconv_out_shape is None:
            return output

        if isinstance(spatial_axes, dict):
            spatial_axes = tuple(spatial_axes.get(name, name)
                                 for name in ("D", "H", "W"))
        elif isinstance(spatial_axes, tuple):
            if len(spatial_axes) < 3:
                raise ValueError("spatial_axes must have length 3 (e.g. ('D', 'H', 'W'))")
            spatial_axes = tuple(name if name else default
                                 for name, default in zip(spatial_axes, ("D", "H", "W")))

        slices = [slice(None)] * len(output.axes)
        for ii, ax_name in enumerate(spatial_axes):
            if ax_name in output.axes.names:
                index = output.axes.names.index(ax_name)
                out_size = output.axes[index].length
                trim_size = self.deconv_out_shape[ii]
                if trim_size > out_size:
                    raise ValueError('specified {} output dimension {} is greater than {}'
                                     .format(ax_name, trim_size, out_size))
                elif trim_size < out_size:
                    extra = out_size - trim_size
                    start = extra // 2
                    end = start + trim_size
                    slices[index] = slice(start, end)

        return ng.tensor_slice(output, slices)

    def __call__(self, in_obj, channel_axes="C", spatial_axes=("D", "H", "W"), **kwargs):
        """
        Compute a deconvolution over in_obj

        Arguments:
            in_obj (Op): Input op
            channel_axes (str): name of the expected channel axis type - defaults to "C"
            spatial_axes (tuple): names of expected depth, height and width axis types - defaults
                                  to "D", "H", and "W"
        """

        output = super(Deconvolution, self).__call__(in_obj, channel_axes, spatial_axes)
        return self._slice_output(output, spatial_axes)


class BatchNorm(Layer):
    """
    A batch normalization layer as described in [Ioffe2015]_.

    Normalizes a batch worth of inputs by subtracting batch mean and
    dividing by batch variance.  Then scales by learned factor gamma and
    shifts by learned bias beta. The layer handles recurrent inputs as
    described in [Laurent2016]_.

    Args:
        rho (float): smoothing coefficient for global updating global statistics
        eps (float): constant added to batch variance to prevent instability
        init_gamma (float): initial value for gamma, the scaling coefficient
        init_beta (float): initial value for beta, the constant offset
        reduce_recurrent (bool): whether statistics should be calculated over recurrent axis
                                 as well.
    Notes:

    .. [Ioffe2015] http://arxiv.org/abs/1502.03167
    .. [Laurent2016] https://arxiv.org/abs/1510.01378
    """
    def __init__(self, rho=0.9, eps=1e-3, init_gamma=1.0, init_beta=0.0,
                 **kwargs):
        super(BatchNorm, self).__init__(**kwargs)
        self.eps = eps
        self.init_rho = rho
        self.init_gamma = init_gamma
        self.init_beta = init_beta

        self.rho = None
        self.gamma = None
        self.beta = None
        self.gmean = None
        self.gvar = None

    @SubGraph.scope_op_creation
    def __call__(self, in_obj, **kwargs):
        in_axes = in_obj.axes
        if in_axes.channel_axis() is None:
            red_axes = ng.make_axes(in_axes.recurrent_axis()) + in_axes.batch_axes()
        else:
            red_axes = in_axes - in_axes.channel_axis()

        out_axes = in_axes - red_axes

        if not self.initialized:
            self.gvar = ng.persistent_tensor(axes=out_axes, initial_value=1.0).named("gvar")
            self.gmean = ng.persistent_tensor(axes=out_axes, initial_value=0.0).named("gmean")
            self.gamma = ng.variable(axes=out_axes,
                                     initial_value=self.init_gamma,
                                     metadata={"label": LABELS["weight"]}).named('gamma')
            self.beta = ng.variable(axes=out_axes,
                                    initial_value=self.init_beta,
                                    metadata={"label": LABELS["bias"]}).named('beta')
            self.rho = ng.persistent_tensor(axes=(), initial_value=self.init_rho).named('rho')

        in_obj = ng.flatten(ng.axes_with_order(in_obj, out_axes | red_axes),
                            out_axes | red_axes.flatten(force=True))
        xmean = ng.mean(in_obj, out_axes=out_axes)
        xvar = ng.variance(in_obj, out_axes=out_axes)

        if Layer.inference_mode:
            return ng.unflatten(self.gamma * ((in_obj - self.gmean) *
                                ng.reciprocal(ng.sqrt(self.gvar + self.eps))) + self.beta)
        else:
            return ng.sequential([
                ng.assign(self.gmean, self.gmean * self.rho + xmean * (1.0 - self.rho)),
                ng.assign(self.gvar, self.gvar * self.rho + xvar * (1.0 - self.rho)),
                ng.unflatten(self.gamma * ((in_obj - xmean) *
                             ng.reciprocal(ng.sqrt(xvar + self.eps))) + self.beta)
            ])

    @SubGraph.scope_op_creation
    def set_tuning_iteration(self, batch_index):
        """
        Notes:
            Following tuning, one must multiply self.gvar by rho in order to debias
        """

        if not self.initialized:
            self.rho = ng.persistent_tensor(axes=(), initial_value=self.init_rho).named('rho')

        new_value = batch_index / (batch_index + 1.0)
        return ng.sequential([ng.assign(self.rho, new_value), new_value])


class Dropout(Layer):
    """
    Layer for stochastically dropping activations to prevent overfitting

    Arguments:
        keep (float):  Number between 0 and 1 that indicates probability of any particular
                       activation being kept.  Defaults to 0.5.

    Example:
        .. code-block:: python
        # Place a Dropout layer between two affine layers
        layers = [
            Affine(nout=2048, activation=Rectlin()),
            Dropout(keep=0.6),
            Affine(nout=2048, activation=Rectlin())
        ]
    """
    def __init__(self, keep=0.5, **kwargs):
        super(Dropout, self).__init__(**kwargs)
        self.keep = keep
        self.mask = None

    @SubGraph.scope_op_creation
    def __call__(self, in_obj, **kwargs):
        if Layer.inference_mode:
            return self.keep * in_obj
        else:
            if self.mask is None:
                in_axes = in_obj.axes.sample_axes()
                self.mask = ng.persistent_tensor(axes=in_axes).named('mask')
            self.mask = ng.uniform(self.mask, low=0.0, high=1.0) <= self.keep
            return self.mask * in_obj


def get_steps(x, time_axis, backward=False):
    """
    TODO: Document
    """
    time_iter = list(range(time_axis.length))
    if backward:
        time_iter = reversed(time_iter)
    # TODO: This is pretty ugly. Is there a better way to handle gates?
    if isinstance(x, dict):
        return [{k: ng.slice_along_axis(x[k], time_axis, i) for k in x.keys()} for i in time_iter]
    else:
        return [ng.slice_along_axis(x, time_axis, i) for i in time_iter]


class Recurrent(Layer):
    """
    Basic recurrent layer.
    Arguments:
        nout (int): Number of hidden/output units
        init (Initializer): Function for initializing the model's input to hidden weights.  By
                            default, this initializer will also be used for recurrent parameters
                            unless init_inner is also specified.  Biases will always be
                            initialized to zero.
        init_inner (Initializer, optional): Function for initializing the model's recurrent
                                            parameters.  If absent, will default to using same
                                            initializer provided to init.
        activation (Transform): Activation function for the input modulation
        batch_norm (bool, optional): defaults to False to not perform batch norm. If True,
                                     batch normalization is applied in each direction after
                                     multiplying the input by its W_input.
        reset_cells (bool): default to be True to make the layer stateless,
                            set to False to be stateful.
        return_sequence (bool): default to be True to return the whole sequence output.
        backward (bool): default to be False to process the sequence left to right
        name (str, optional): name to refer to this layer as.

    Attributes:
        W_input (Tensor): weights from inputs to output units
            (input_size, output_size)
        W_recur (Tensor): weights for recurrent connections
            (output_size, output_size)
        b (Tensor): Biases on output units (output_size, 1)
    """
    def __init__(self, nout, init, init_inner=None, activation=None, batch_norm=False,
                 reset_cells=True, return_sequence=True, backward=False, **kwargs):
        super(Recurrent, self).__init__(**kwargs)

        self.nout = nout
        self.activation = activation
        self.init = init
        self.init_inner = init_inner if init_inner is not None else init
        self.reset_cells = reset_cells
        self.return_sequence = return_sequence
        self.backward = backward
        self.batch_norm = BatchNorm() if batch_norm is True else None
        self.w_in_axes = None

    def interpret_axes(self, in_obj, init_state):

        if self.w_in_axes is None:
            self.in_axes = in_obj.axes

            self.in_feature_axes = self.in_axes.sample_axes() - self.recurrent_axis

            # if init state is given, use that as hidden axes
            if init_state:
                self.out_feature_axes = (init_state.axes.sample_axes() -
                                         init_state.axes.recurrent_axis())
                if sum(self.out_feature_axes.full_lengths) != self.nout:
                    raise ValueError("Length of init_state must be the same as nout: " +
                                     "{} != {}".format(sum(self.out_feature_axes.full_lengths),
                                                       self.nout))
            else:
                self.out_feature_axes = ng.make_axes([ng.make_axis(self.nout)])
                if len(self.in_feature_axes) == 1:
                    self.out_feature_axes[0].named(self.in_feature_axes[0].name)

            self.out_axes = self.out_feature_axes + self.in_axes.batch_axis()
            self.recurrent_axis_idx = len(self.out_feature_axes)

            # create temporary out axes which the dot ops will output.  These
            # temporary axes will be immediately cast to self.out_axes
            # afterwards.  We can't go directly to self.out_axes from the DotOp
            # because sometimes the self.out_axes intersect with the self.in_axes
            # and so the weight matrix would have a duplicate Axis which isn't
            # allowed.
            temp_out_axes = ng.make_axes(shadow_axes_map(self.out_feature_axes).keys())

            # determine the shape of the weight matrices
            self.w_in_axes = temp_out_axes + self.in_feature_axes
            self.w_re_axes = temp_out_axes + self.out_feature_axes

    def _step(self, h_ff, states):
        h_ff = ng.cast_role(h_ff, self.out_axes)
        h_rec = ng.cast_role(ng.dot(self.W_recur, states), self.out_axes)
        return self.activation(h_rec + h_ff + self.b)

    @SubGraph.scope_op_creation
    def __call__(self, in_obj, init_state=None, **kwargs):
        """
        Sets shape based parameters of this layer given an input tuple or int
        or input layer.

        Arguments:
            in_obj (int, tuple, Layer or Tensor): object that provides shape
                                                 information for layer
            init_state (Tensor): object that provides initial state

        Returns:
            rnn_out (Tensor): output

        """
        # for seq2seq, recurrent axis and init_state change
        # between training and inference
        self.recurrent_axis = in_obj.axes.recurrent_axis()
        if init_state is not None:
            self.h_init = init_state.named('h_init')

        # try to understand the axes from the input
        if not self.initialized:
            self.interpret_axes(in_obj, init_state)

            # initialize the hidden states if init_state was not given
            if init_state is None:
                if self.reset_cells:
                    self.h_init = ng.constant(
                        const=0, axes=self.out_axes).named('h_init')
                else:
                    self.h_init = ng.variable(
                        initial_value=0, axes=self.out_axes).named('h_init')

            self.W_input = ng.variable(axes=self.w_in_axes,
                                       initial_value=self.init,
                                       metadata={"label": LABELS["weight"]},
                                       ).named("W_in")
            self.W_recur = ng.variable(axes=self.w_re_axes,
                                       initial_value=self.init_inner,
                                       metadata={"label": LABELS["weight"]},
                                       ).named("W_re")
            self.b = ng.variable(axes=self.out_feature_axes, initial_value=0,
                                 metadata={"label": LABELS["bias"]},
                                 ).named("bias")

        h = self.h_init
        h_list = []

        h_ff = ng.dot(self.W_input, in_obj)
        # Batch norm is computed only on the weighted inputs
        # as in https://arxiv.org/abs/1510.01378
        if self.batch_norm is not None:
            h_ff = self.batch_norm(h_ff)

        # slice the weighted inputs into time slices
        in_s = get_steps(h_ff, self.recurrent_axis, self.backward)

        # unrolling computations
        for i in range(self.recurrent_axis.length):
            with ng.metadata(recurrent_step=str(i)):
                h = self._step(in_s[i], h)
                h_list.append(h)

        if self.return_sequence is True:
            # only when returning a sequence, need to reverse the output
            h_list = h_list[::-1] if self.backward else h_list
            rnn_out = ng.stack(h_list, self.recurrent_axis, pos=self.recurrent_axis_idx)
        else:
            rnn_out = h_list[-1]

        if self.reset_cells is True:
            return rnn_out
        else:
            return ng.sequential([
                ng.assign(self.h_init, h_list[-1]),
                rnn_out
            ])


class BiRNN(Layer):
    """
    Bi-directional recurrent layer.
    Arguments:
        nout (int): Number of hidden/output units
        init (Initializer): Function for initializing the model's input to hidden weights.  By
                            default, this initializer will also be used for recurrent parameters
                            unless init_inner is also specified.  Biases will always be
                            initialized to zero.
        init_inner (Initializer, optional): Function for initializing the model's recurrent
                                            parameters.  If absent, will default to using same
                                            initializer provided to init.
        activation (Transform): Activation function for the input modulation
        batch_norm (bool, optional): defaults to False to not perform batch norm. If True,
                                     batch normalization is applied in each direction after
                                     multiplying the input by its W_input.
        reset_cells (bool): default to be True to make the layer stateless,
                            set to False to be stateful.
        return_sequence (bool): default to be True to return the whole sequence output.
        sum_out (bool): default to be False. When True, sum the outputs from both directions
        concat_out (bool): default to False. When True, concatenate the outputs from both
                           directions. If concat_out and sum_out are both False, output will be a
                           list.
        name (str, optional): name to refer to this layer as.
    """
    def __init__(self, nout, init, init_inner=None, activation=None, batch_norm=False,
                 reset_cells=False, return_sequence=True, sum_out=False,
                 concat_out=False, **kwargs):
        if sum_out and concat_out:
            raise ValueError("sum_out and concat_out cannot both be True")

        super(BiRNN, self).__init__(**kwargs)
        self.sum_out = sum_out
        self.concat_out = concat_out
        self.nout = nout
        self.fwd_rnn = Recurrent(nout, init, init_inner, activation=activation,
                                 batch_norm=batch_norm, reset_cells=reset_cells,
                                 return_sequence=return_sequence)
        self.bwd_rnn = Recurrent(nout, init, init_inner, activation=activation,
                                 batch_norm=batch_norm, reset_cells=reset_cells,
                                 return_sequence=return_sequence, backward=True)

    @SubGraph.scope_op_creation
    def __call__(self, in_obj, init_state=None, **kwargs):
        """
        Sets shape based parameters of this layer given an input tuple or int
        or input layer.

        Arguments:
            in_obj (int, tuple, Layer or Tensor): object that provides shape
                                                 information for layer
            init_state (Tensor or list): object that provides initial state

        Returns:
            if sum_out or concat_out - rnn_out (Tensor): output
            otherwise - rnn_out (list of Tensors): list of length 2

        """
        if isinstance(in_obj, collections.Sequence):
            if len(in_obj) != 2:
                raise ValueError("If in_obj is a sequence, it must have length 2")
            if in_obj[0].axes != in_obj[1].axes:
                raise ValueError("If in_obj is a sequence, each element must have the same axes")
            fwd_in = in_obj[0]
            bwd_in = in_obj[1]
        else:
            fwd_in = in_obj
            bwd_in = in_obj

        if isinstance(init_state, collections.Sequence):
            if len(init_state) != 2:
                raise ValueError("If init_state is a sequence, it must have length 2")
            if init_state[0].axes != init_state[1].axes:
                raise ValueError("If init_state is a sequence, " +
                                 "each element must have the same axes")
            fwd_init = init_state[0]
            bwd_init = init_state[1]
        else:
            fwd_init = init_state
            bwd_init = init_state

        with ng.metadata(direction="fwd"):
            fwd_out = self.fwd_rnn(fwd_in, fwd_init)
        with ng.metadata(direction="bwd"):
            bwd_out = ng.cast_role(self.bwd_rnn(bwd_in, bwd_init), fwd_out.axes)

        if self.sum_out:
            return fwd_out + bwd_out
        elif self.concat_out:
            ax = fwd_out.axes.feature_axes()
            if len(ax) == 1:
                ax = ax[0]
            else:
                raise ValueError(("Multiple hidden axes: {}. "
                                  "Unable to concatenate automatically").format(ax))
            return ng.concat_along_axis([fwd_out, bwd_out], ax)
        else:
            return fwd_out, bwd_out


class LSTM(Recurrent):
    """
    Long Short-Term Memory (LSTM) layer based on
    Hochreiter and Schmidhuber, Neural Computation 9(8): 1735-80 (1997).

    Arguments:
        nout (int): Number of hidden/output units
        init (Initializer): Function for initializing the model's input to hidden weights.  By
                            default, this initializer will also be used for recurrent parameters
                            unless init_inner is also specified.  Biases will always be
                            initialized to zero.
        init_inner (Initializer, optional): Function for initializing the model's recurrent
                                            parameters.  If absent, will default to using same
                                            initializer provided to init.
        activation (Transform): Activation function for the input modulation
        batch_norm (bool, optional): defaults to False to not perform batch norm. If True,
                                     batch normalization is applied to each gate after
                                     multiplying the input by W_input.
        reset_cells (bool): default to be True to make the layer stateless,
                            set to False to be stateful.
        return_sequence (bool): default to be True to return the whole sequence output.
        backward (bool): default to be False to process the sequence left to right
        name (str, optional): name to refer to this layer as.
    Attributes:
        W_input (Tensor): weights from inputs to output units
            (output_size, input_size)
        W_recur (Tensor): weights for recurrent connections
            (output_size, output_size)
        b (Tensor): Biases on output units (output_size, 1)

    Gates: i - input gate, f - forget gate, o - output gate, g - input modulation
    """
    metadata = {'gates': ['i', 'f', 'o', 'g']}

    def __init__(self, nout, init, init_inner=None, activation=None, gate_activation=None,
                 batch_norm=False, reset_cells=True, return_sequence=True, backward=False,
                 **kwargs):
        super(LSTM, self).__init__(nout, init, init_inner=init_inner, activation=activation,
                                   reset_cells=reset_cells, return_sequence=return_sequence,
                                   backward=backward, **kwargs)

        if batch_norm is True:
            self.batch_norm = {k: BatchNorm() for k in self.metadata["gates"]}
        else:
            self.batch_norm = None
        self.gate_activation = gate_activation if gate_activation is not None else self.activation

    def _step(self, h_ff, states):
        h_state = states[0]
        c_state = states[1]
        ifog = {
            k: sum([ng.cast_role(h_ff[k], self.out_axes),
                    ng.cast_role(ng.dot(self.W_recur[k], h_state), self.out_axes),
                    self.b[k],
                    ]) for k in self.metadata['gates']
        }
        ifog_act = {k: self.activation(ifog[k]) if k is 'g'
                    else self.gate_activation(ifog[k]) for k in self.metadata['gates']}

        c = ifog_act['f'] * c_state + ifog_act['i'] * ifog_act['g']
        # c_prev is the state before applying activation
        h = ifog_act['o'] * self.activation(c)
        h = ng.cast_role(h, self.out_axes)
        return [h, c]

    @SubGraph.scope_op_creation
    def __call__(self, in_obj, init_state=None, return_cell_state=False, **kwargs):
        """
        Sets shape based parameters of this layer given an input tuple or int
        or input layer.

        Arguments:
            in_obj (int, tuple, Layer or Tensor): object that provides shape
                                                 information for layer
            init_state (tuple of Tensor): object that provides initial state, and in LSTM,
                                          it includes hidden state, and cell states

        Returns:
            rnn_out (Tensor): output

        """

        # for seq2seq, recurrent axis and init_state change
        # between training and inference
        self.recurrent_axis = in_obj.axes.recurrent_axis()
        if init_state is not None:
            assert len(init_state) == 2 and init_state[0].axes == init_state[1].axes
            self.h_init = init_state[0]
            self.c_init = init_state[1]

        if not self.initialized:
            # try to understand the axes from the input
            if init_state is not None:
                self.interpret_axes(in_obj, init_state[0])
            else:
                self.interpret_axes(in_obj, init_state)

            # initialize the hidden states
            if init_state is None:
                if self.reset_cells:
                    self.h_init = ng.constant(const=0,
                                              axes=self.out_axes).named('h_init')
                    self.c_init = ng.constant(const=0,
                                              axes=self.out_axes).named('c_init')
                else:
                    self.h_init = ng.variable(initial_value=0,
                                              axes=self.out_axes).named('h_init')
                    self.c_init = ng.variable(initial_value=0,
                                              axes=self.out_axes).named('c_init')

            # params are dictionary for i, f, o, g
            gates = self.metadata["gates"]
            self.W_input = {k: ng.variable(axes=self.w_in_axes,
                                           initial_value=self.init,
                                           metadata={"label": LABELS["weight"]},
                                           ).named("W_in_{}".format(k)) for k in gates}

            self.W_recur = {k: ng.variable(axes=self.w_re_axes,
                                           initial_value=self.init_inner,
                                           metadata={"label": LABELS["weight"]},
                                           ).named("W_re_{}".format(k)) for k in gates}

            self.b = {k: ng.variable(axes=self.out_feature_axes,
                                     initial_value=0,
                                     metadata={"label": LABELS["bias"]},
                                     ).named("bias_{}".format(k)) for k in gates}

        h = self.h_init
        c = self.c_init

        h_list = []
        c_list = []

        # Compute feed forward weighted inputs
        # Batch norm is computed only on the weighted inputs
        # as in https://arxiv.org/abs/1510.01378
        h_ff = dict()
        for k in self.metadata["gates"]:
            h_ff[k] = ng.dot(self.W_input[k], in_obj)
            if self.batch_norm is not None:
                h_ff[k] = self.batch_norm[k](h_ff[k])

            # slice the weighted inputs into time slices
        h_ff = get_steps(h_ff, self.recurrent_axis, self.backward)

        # recurrent computation
        for i in range(self.recurrent_axis.length):
            with ng.metadata(recurrent_step=str(i)):
                [h, c] = self._step(h_ff[i], [h, c])
                h_list.append(h)
                c_list.append(c)

        if self.return_sequence is True:
            if self.backward:
                h_list = h_list[::-1]
                c_list = c_list[::-1]
            h_stack = ng.stack(h_list, self.recurrent_axis, pos=self.recurrent_axis_idx)
            if return_cell_state:
                c_stack = ng.stack(c_list, self.recurrent_axis, pos=self.recurrent_axis_idx)
                lstm_out = (h_stack, c_stack)
            else:
                lstm_out = h_stack
        else:
            if return_cell_state:
                lstm_out = (h_list[-1], c_list[-1])
            else:
                lstm_out = h_list[-1]

        if self.reset_cells is True:
            return lstm_out
        else:
            return ng.sequential([
                ng.doall([
                    ng.assign(self.h_init, h_list[-1]),
                    ng.assign(self.c_init, c_list[-1])
                ]),
                lstm_out
            ])


def _cells_state_info(cells):
    """
    Given a list of cells, combine the individual state_info's
    of the cells into a single state_info for the collection of
    cells, i.e. do the equivalent of
    sum([c.state_info for c in cells], []),
    but using itertools instead because it's much faster

    Note: the goal here is to simply convert lists of dicts into
    a single list of dicts.

    Arguments:
    ----------
    cells: list containing cell objects
    """

    return list(itertools.chain(*[c.state_info for c in cells]))


def _cells_initialize_states(cells, batch_axis, **kwargs):
    """
    Given a list of cells, initialize the states of the individual
    cells together by doing the equivalent of
    sum([c.initialize_states(**kwargs) for c in cells], []),
    but using itertools instead because it's much faster

    Arguments:
    ----------
    cells: list containing cell objects
    """

    return list(itertools.chain(
        *[c.initialize_states(batch_axis, **kwargs) for c in cells]))


def unroll(cell, num_steps, inputs, init_states=None, reset_cells=True,
           return_sequence=True, reverse_mode=False):
    """
    Unroll the cell for num_steps steps.

    Arguments:
    ----------
    init_states: either None or a dictionary containing states
    """
    recurrent_axis = inputs.axes.recurrent_axis()
    recurrent_axis_idx = len(cell.feature_axes)
    batch_axis = inputs.axes.batch_axis()
    out_axes = cell.feature_axes + batch_axis
    if init_states is not None:
        states = {k: ng.cast_role(v, out_axes) for (k, v) in init_states.items()}
    else:
        states = init_states

    stepped_inputs = get_steps(inputs, recurrent_axis, backward=reverse_mode)
    stepped_outputs = []

    for t in range(num_steps):
        with ng.metadata(step=str(t)):
            output, states = cell(stepped_inputs[t], states)
            stepped_outputs.append(output)

    if reverse_mode:
        if return_sequence:
            stepped_outputs.reverse()

    if return_sequence:
        outputs = ng.stack(stepped_outputs, recurrent_axis, pos=recurrent_axis_idx)
    else:
        outputs = stepped_outputs[-1]

    if not reset_cells:
        update_inits = ng.doall([ng.assign(initial, states[name])
                                 for (name, initial) in init_states.items()])
        outputs = ng.sequential([update_inits, outputs])

    return outputs


class BaseRNNCell(Layer):
    """
    Abstract base class for RNN cells

    Arguments:
    ----------

    nout (int): Number of hidden/output units
    init (Initializer): Function to initialize the input-to-hidden weights.
        By default, this initializer will also be used to initialize recurrent
        weights unless init_inner is also specified. Biases are always
        initialized to zero.
    init_h2h (Initializer, optional): Function to initialize recurrent weights.
        If absent, will default to using the initializer passed as the init
        argument.
    activation (Transform): Activation function used to produce outputs.

    name (str, optional): Assigns given name to the cell.
    """

    def __init__(self, cell_type=None, **kwargs):
        super(BaseRNNCell, self).__init__(**kwargs)
        self.cell_type = cell_type

    def __call__(self, inputs, states, **kwargs):
        """
        Update the RNN cell for one time step. By definition,
        an RNN cell consumes a pair of inputs and states at a
        given time step to produce states at the next time step.

        Arguments:
        ----------
        inputs (Tensor): represents external input to the cell

        states (dict of Tensors): The states of a cell are collectively
            contained in a dictionary.

        Returns
        -------
        states (dict of Tensors): representing the new state of the cell
            after a single step.
        """
        raise NotImplementedError()

    @property
    def state_info(self):
        """shape and layout information of states"""
        raise NotImplementedError()

    @property
    def feature_axes(self):
        """shape and layout information of states"""
        raise NotImplementedError()

    @property
    def _gate_names(self):
        """name(s) of gates"""
        return ()

    @SubGraph.scope_op_creation
    def initialize_states(self, batch_axis, reset_cells=True):
        """
        Initialize the RNN cell's (external and internal) states.

        Arguments:
        ----------
        batch_axis: axis corresponding to the "batch" dimension
        reset_cells (bool): optional parameter used to determine
            the appropriate constructor for the states.

        Returns
        -------
        states (dict of Tensors): The initial states of the cell
            collectively contained in a dictionary.
        """

        state_axes = self.feature_axes + batch_axis
        states = {}
        for info in self.state_info:
            name = info['state_name']
            if reset_cells:
                states[name] = ng.constant(const=0,
                                           axes=state_axes).named(name)
            else:
                states[name] = ng.variable(initial_value=0,
                                           axes=state_axes).named(name)
        return states


class RNNCell(BaseRNNCell):
    """
    Vanilla RNN cell.

    Arguments:
    ----------
    nout (int): Number of hidden/output units
    init (Initializer): Function to initialize the input-to-hidden weights.
        By default, this initializer will also be used to initialize recurrent
        weights unless init_inner is also specified. Biases are always
        initialized to zero.
    init_h2h (Initializer, optional): Function to initialize recurrent weights.
        If absent, will default to using the initializer passed as the init
        argument.
    activation (Transform): Activation function used to produce outputs.
    batch_norm (bool, optional): Defaults to False. If True, batch normalization
        is applied to the weighted inputs.
    name (str, optional): Assigns given name to the cell.

    """
    def __init__(self, nout, init, init_h2h=None, bias_init=None, activation=None,
                 batch_norm=False, reset_cells=True, **kwargs):
        super(RNNCell, self).__init__(**kwargs)
        self.nout = nout
        self.init = init
        self.init_h2h = init_h2h if init_h2h is not None else init
        self.bias_init = bias_init
        self.activation = activation
        self.batch_norm = batch_norm
        self.reset_cells = reset_cells
        self.h2h = Linear(nout=self.nout,
                          init=self.init_h2h)
        self.i2h = Affine(axes=self.h2h.axes,
                          weight_init=self.init,
                          bias_init=self.bias_init,
                          batch_norm=self.batch_norm)

    @property
    def state_info(self):
        return [{'state_name': 'h'}]

    @property
    def feature_axes(self):
        return self.h2h.axes.feature_axes()

    @property
    def _gate_names(self):
        return ('',)

    @SubGraph.scope_op_creation
    def __call__(self, inputs, states, reset_cells=True, **kwargs):
        if states is None:
            batch_axis = inputs.axes.batch_axis()
            states = self.initialize_states(batch_axis,
                                            reset_cells=reset_cells)
        feed_fwd = ng.cast_role(self.i2h(inputs), states['h'].axes)
        states['h'] = self.activation(feed_fwd + self.h2h(states['h']))
        return states['h'], states

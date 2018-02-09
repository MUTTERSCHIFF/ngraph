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
import tensorflow as tf


def np_layout_shuffle(in_tensor, in_axes, out_axes):
    """
    Perform numpy array dim-shuffle and expand / shrink dims.

    Example usage (from tf -> ng):
        np_layout_shuffle(np_tf_image,  in_axes='NHWC', out_axes='CDHWN')
        np_layout_shuffle(np_tf_weight, in_axes='RSCK', out_axes='CTRSK')

    In the implementation:
        axis: string / char like "C"
        dim: length of a certain axis
        index: index of axis, e.g. in 'NHWC', idx of 'H' is 1

    Example dim-shuffle index:
        (N, H, W, C) -> (N, H, W, C, D) -> (C, D, H, W, N) => 3, 4, 1, 2, 0
                         0, 1, 2, 3, 4
        (C, D, H, W, N) -> (C, H, W, N) -> (N, H, W, C) => 3, 1, 2, 0
                            0, 1, 2, 3

    Arguments:
        in_tensor: input numpy array
        in_axes: input layout strings, for example, in conv2d,
                 tf's image layout : 'NHWC', with D=1 to expand dim
                 tf's weight layout: 'RSCK', with T=1 to expand dim
        out_axes: output layoutn strings, for example, in conv2d,
                  ng's image layout : 'CDHWN'
                  ng's weight layout: 'CTRSK'

    Returns:
        numpy array out_tensor
    """
    # in_tensor match in_axes
    if len(in_axes) != np.ndim(in_tensor):
        raise ValueError("in_tensor does not match in_axes.")

    # out_axes must be a (non-strict) superset of in_axes, except dim 1 in_axes
    in_axes_set = set(in_axes)
    out_axes_set = set(out_axes)
    for index, axis in enumerate(in_axes):
        if axis not in out_axes_set and in_tensor.shape[index] != 1:
            raise ValueError("out_axes not compatible with in_axes.")

    # dim expand / squeeze in_tensor to match output
    if len(in_axes) < len(out_axes):
        # expand
        extra_axes = "".join(list(out_axes_set - in_axes_set))
        extra_dims = (1,) * len(extra_axes)
        in_tensor = np.reshape(in_tensor, in_tensor.shape + extra_dims)
        in_axes = in_axes + extra_axes
    elif len(in_axes) > len(out_axes):
        # squeeze
        expanded_in_dims = [
            dim for axis, dim in zip(in_axes, in_tensor.shape)
            if axis in out_axes_set
        ]
        in_tensor = np.reshape(in_tensor, expanded_in_dims)
        in_axes = "".join(filter(lambda axis: axis in out_axes_set, in_axes))

    # sanity check
    assert np.ndim(in_tensor) == len(in_axes) == len(out_axes)
    assert set(in_axes) == set(out_axes)

    # create list mapping for dim-shuffle, find in_axes's index in out_axes
    in_axes_list = list(in_axes)
    try:
        in_out_index = [in_axes_list.index(axis) for axis in out_axes]
    except ValueError:
        raise ValueError("out_axes not compatible with in_axes.")

    # dim-shuffle
    out_tensor = np.transpose(in_tensor, in_out_index)

    return out_tensor


def remove_tf_name_prefix(name):
    """
    Strip ^ from TF's node name.

    Arguments:
        name: TF node name

    Returns:
        string: name with ^ stripped
    """
    return name[1:] if name[0] == "^" else name


def tf_obj_shape(input):
    """
    Convert tf objects to shape tuple.

    Arguments:
        input: tf.TensorShape, tf.Tensor, tf.AttrValue or tf.NodeDef
               the corresponding tensorflow object

    Returns:
        tuple: shape of the tensorflow object
    """
    if isinstance(input, tf.TensorShape):
        return tuple([int(i.value) for i in input])
    elif isinstance(input, tf.Tensor):
        return tf_obj_shape(input.get_shape())
    elif isinstance(input, tf.AttrValue):
        return tuple([int(d.size) for d in input.shape.dim])
    elif isinstance(input, tf.NodeDef):
        return tf_obj_shape(input.attr['shape'])
    else:
        raise TypeError("Input to `tf_obj_shape` has the wrong type.")


def to_int(input):
    """
    Convert np array, tuple, list or const value to int

    Arguments:
        input: tuple, list or const value
    Return:
        tuple, list or const of int(s)
    """
    if isinstance(input, np.ndarray):
        return input.astype(int)
    elif isinstance(input, tuple):
        return tuple([int(i) for i in input])
    elif isinstance(input, list):
        return [int(i) for i in input]
    else:
        return int(input)


def get_nested_attr(obj, name):
    """
    Similar to `getattr`, supports getting from nested attributes.
    E.g.
    tf.tanh <-> get_nested_attr(tf, 'tanh')
    tf.nn.relu <-> get_nested_attr(tf, 'nn.relu')
    """
    names = name.split('.')
    if len(names) != 1:
        return get_nested_attr(getattr(obj, names[0]), '.'.join(names[1:]))
    else:
        return getattr(obj, names[0])

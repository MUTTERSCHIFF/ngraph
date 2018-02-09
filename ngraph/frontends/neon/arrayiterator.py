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
import numpy as np
import ngraph as ng
from future.utils import viewitems
import six
from ngraph.frontends.neon import ax
import collections


class ArrayIterator(object):

    def __init__(self, data_arrays, batch_size,
                 total_iterations=None, tgt_key='label',
                 shuffle=False):
        """
        During initialization, the input data will be converted to backend tensor objects
        (e.g. CPUTensor or GPUTensor). If the backend uses the GPU, the data is copied over to the
        device.

        Args:
            data_arrays (ndarray, shape: [# examples, feature size]): Input features of the
                dataset.
            batch_size (int): number of examples in each minibatch
            total_iterations (int): number of minibatches to cycle through on this iterator.
                                    If not provided, it will cycle through all of the data once.
            tgt_key (str): name of the target (labels) key in data_arrays
            shuffle (bool): if true, shuffles the dataset at the beginning of every epoch.
        """
        # Treat singletons like list so that iteration follows same syntax
        self.batch_size = batch_size
        self.axis_names = None
        self.tgt_key = tgt_key
        if isinstance(data_arrays, dict):
            self.data_arrays = {k: v['data'] for k, v in data_arrays.items()}
            self.axis_names = {k: v['axes'] for k, v in data_arrays.items()}
        elif isinstance(data_arrays, collections.Sequence):
            self.data_arrays = {k: x for k, x in enumerate(data_arrays)}
        else:
            self.data_arrays = {0: data_arrays}

        self.keys = list(self.data_arrays.keys())

        if not self.axis_names:
            self.axis_names = {k: None for k in self.keys}

        # just get an arbitrary element for len
        self.ndata = len(self.data_arrays[self.keys[0]])

        if self.ndata < self.batch_size:
            raise ValueError('Number of examples is smaller than the batch size')

        self.index = 0
        self.pos = 0

        if shuffle:
            self.shuffle_data()
        self.shuffle = shuffle

        self.total_iterations = self.nbatches if total_iterations is None else total_iterations

    @property
    def nbatches(self):
        """
        Return the number of minibatches in this dataset.
        """
        return -((-self.ndata) // self.batch_size)

    def make_placeholders(self, include_iteration=False):
        placeholders = {}
        ax.N.length = self.batch_size
        for k, axnm in self.axis_names.items():
            p_axes = ng.make_axes([ax.N])
            for i, sz in enumerate(self.data_arrays[k].shape[1:], 1):
                name = axnm[i] if axnm else None
                if name == ax.REC.name:
                    ax.REC.length = sz
                    _axis = ax.REC
                else:
                    _axis = ng.make_axis(length=sz, name=name)
                p_axes += _axis
            placeholders[k] = ng.placeholder(p_axes)
        if include_iteration:
            placeholders['iteration'] = ng.placeholder(axes=())
        return placeholders

    def reset(self):
        """
        Resets the starting index of this dataset to zero. Useful for calling
        repeated evaluations on the dataset without having to wrap around
        the last uneven minibatch. Not necessary when data is divisible by batch size
        """
        self.start = 0
        self.index = 0
        self.pos = 0

    def shuffle_data(self):
        p = np.random.permutation(self.ndata)
        self.data_arrays = {k: src[p] for k, src in self.data_arrays.items()}

    def get_at_most(self, bsz):
        """
        Returns at most bsz elements from the buffers along with the number of elements
        actually retrieved, which may be fewer at the end of the dataset.
        """
        bsz = min(bsz, self.ndata - self.pos)
        oslice = slice(self.pos, self.pos + bsz)
        batch_bufs = {k: src[oslice] for k, src in self.data_arrays.items()}

        self.pos = (self.pos + bsz) % self.ndata
        if self.pos == 0 and self.shuffle:
            self.shuffle_data()

        return bsz, batch_bufs

    def __next__(self):
        """
        Returns a new minibatch of data with each call.

        Yields:
            tuple: The next minibatch which includes both features and labels.
        """
        if self.index >= self.total_iterations:
            raise StopIteration
        self.index += 1

        total, batch_bufs = self.get_at_most(self.batch_size)
        while total < self.batch_size:
            bsz, next_batch_bufs = self.get_at_most(self.batch_size - total)
            batch_bufs = {k: np.concatenate([batch_bufs[k], next_batch_bufs[k]])
                          for k in batch_bufs}
            total += bsz
        batch_bufs['iteration'] = self.index
        return batch_bufs

    def next(self):
        return self.__next__()

    def __iter__(self):
        return self


class SequentialArrayIterator(object):

    def __init__(self, data_arrays, time_steps, batch_size,
                 total_iterations=None, reverse_target=False, get_prev_target=False,
                 stride=None, include_iteration=False, tgt_key='tgt_txt',
                 shuffle=True):
        """
        Given an input sequence, generates overlapping windows of samples
        Input: dictionary of numpy arrays
            data_arrays[key] : Numpy array of shape (S, D).
                                S is length of sequence
                                D is input feature dimension
            Assumes each data_arrays[key] has the same length (S)
        Output of each iteration: Dictionary of input and output samples
            samples[key] has size (batch_size, time_steps, D)

        Arguments:
        data_arrays
        time_steps: Width of the rolling window (length of each input sequence)
        batch_size: how many samples to return for each iteration
        total_iterations: number of batches to retrieve from the sequence (roll over if necessary)
                         If set to None, will rotate through the whole sequence only once
        stride: Shift of steps between two consecutive samples
                If None, defaults to time_steps (no overlap of consecutive samples)
        reverse_target: reverses the direction of target key
        tgt_ket: key for the target sequence in data_arrays
        include_iteration: iWhen set to True, returned dictionary includes the iteration number
        shuffle: If set to True, batches in data_arrays are shuffled.
                 If False, they are taken sequentially
        get_prev_target: returns the target of the previous iteration as well as the current one

        Example:
            data_arrays['data1'] is a numpy array with shape (S, 1): [a1, a2, ..., aS]
            Each generated sample will be an input sequence / output sequence pairs such as:
                sample['data1'] is nparray of size (batch_size, S, 1):
                    sample['data1'][0] : [a1, a2, ..., a(time_steps)]
                    sample['data1'][1] : [a(stride +1), a(stride+2), ..., a(stride+time_steps)]
                        ...
            Each iteration will return batch_size number of samples
            If stride = 1, the window will shift by one
                sample['data1'][0] and sample['data1'][1] will have
                (time_steps - 1) elements that are the same
            If stride = time_steps, they will have no overlapping elements
        """
        self.data_array = data_arrays
        self.seq_len = time_steps
        self.get_prev_target = get_prev_target
        self.reverse_target = reverse_target
        self.batch_size = batch_size
        self.include_iteration = include_iteration
        self.tgt_key = tgt_key
        self.shuffle = shuffle
        self.current_iter = 0
        self.start = 0
        self.index = 0
        self.stride = time_steps if stride is None else stride

        if isinstance(data_arrays, dict):
            # Get the total length of the sequence
            # Assumes each value in data_arrays has the same length
            self.ndata = len(six.next(six.itervalues(data_arrays)))

            self.data_arrays = {k: v[:self.used_samples] for k, v in viewitems(data_arrays)}
            # Throw away samples in data arrays that cannot form a batch
            if self.get_prev_target:
                self.data_arrays['prev_tgt'] = np.copy(self.data_arrays[self.tgt_key])

            # Get the size of feature dimension for each array
            self.feature_dims = {k: v.shape[1] if (len(v.shape) > 1) else 1
                                 for k, v in viewitems(self.data_arrays)}

            # Preallocate iterator arrays for each batch
            self.samples = {k: np.squeeze(np.zeros((self.batch_size,
                                                    self.seq_len,
                                                    self.feature_dims[k]),
                                                   dtype=v.dtype))
                            for k, v in viewitems(self.data_arrays)}
        else:
            raise ValueError("Must provide dict as input")

        if self.nbatches < 1:
            raise ValueError('Number of examples is smaller than the batch size')

        self.total_iterations = self.nbatches if total_iterations is None else total_iterations

    @property
    def used_samples(self):
        """
        Return the number of minibatches in this dataset.
        """
        self.ndata = (self.ndata // (self.stride * self.batch_size)) * \
            self.stride * self.batch_size
        return self.ndata

    @property
    def nbatches(self):
        """
        Return the number of minibatches in this dataset.
        """
        return ((self.ndata - self.start) // self.stride // self.batch_size)

    def make_placeholders(self):
        ax.N.length = self.batch_size
        ax.REC.length = self.seq_len

        p_axes = ng.make_axes([ax.N, ax.REC])
        return {k: ng.placeholder(p_axes) for k in self.data_arrays.keys()}

    def reset(self):
        """
        Resets the starting index of this dataset to zero. Useful for calling
        repeated evaluations on the dataset without having to wrap around
        the last uneven minibatch. Not necessary when data is divisible by batch size
        """
        self.start = 0
        self.current_iter = 0

    def __iter__(self):
        """
        Returns a new minibatch of data with each call.
        Yields:
            dictionary: The next minibatch
                samples[key]: numpy array with shape (batch_size, seq_len, feature_dim)
        """

        while self.current_iter < self.total_iterations:
            for batch_idx in range(self.batch_size):
                if self.shuffle:
                    strt_idx = self.start + (self.current_iter * self.stride)
                    seq_start = strt_idx + (batch_idx * self.nbatches * self.seq_len)
                else:
                    strt_idx = self.start + (self.current_iter * self.batch_size * self.stride)
                    seq_start = strt_idx + (batch_idx * self.stride)

                idcs = np.arange(seq_start, seq_start + self.seq_len) % self.ndata
                for key in self.data_arrays.keys():
                    self.samples[key][batch_idx] = self.data_arrays[key][idcs]

            self.current_iter += 1

            if self.reverse_target:
                self.samples[self.tgt_key][:] = self.samples[self.tgt_key][:, ::-1]

            if self.get_prev_target:
                self.samples['prev_tgt'] = np.roll(self.samples[self.tgt_key], shift=1, axis=1)

            if self.include_iteration is True:
                self.samples['iteration'] = self.index
            yield self.samples

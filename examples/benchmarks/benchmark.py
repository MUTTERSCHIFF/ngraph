# ----------------------------------------------------------------------------
# Copyright 2017 Nervana Systems Inc.
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
from functools import wraps
from collections import OrderedDict
import ngraph.transformers as ngt
import numpy as np
import time
from contextlib import closing


class DefaultOrderedDict(OrderedDict):
    def __missing__(self, key):
        self[key] = type(self)()
        return self[key]


class Mark(object):
    def init_mark(self):
        return {'time': 0}

    def synchronize_mark(self):
        return

    def record_mark(self, marker):
        marker['time'] = time.time()

    def get_time(self, start_mark, end_mark):
        return (end_mark['time'] - start_mark['time']) * 1000.0


class Benchmark(object):

    marker = Mark()

    def __init__(self, computation, train_set, inputs, transformer, device):
        self.computation = computation
        self.train_set = train_set
        self.inputs = inputs
        self.transformer = transformer
        self.device = device

    @staticmethod
    def timing_wrapper(func, start, end, output):
        marker = Benchmark.marker

        @wraps(func)
        def wrapper(*args, **kwargs):
            marker.record_mark(start)
            res = func(*args, **kwargs)
            marker.record_mark(end)
            marker.synchronize_mark(end)
            output.append(marker.get_time(start, end))
            return res

        return wrapper

    def time(self, n_iterations, n_skip, computation_name, feed_dict):
        """
        This runs _any_ computation repeatedly with data from feed_dict, and times it

        (Nothing model-specific inside, can be reused)
        """
        times = DefaultOrderedDict()
        start = Benchmark.marker.init_mark()
        end = Benchmark.marker.init_mark()
        t_args = {}
        if self.transformer == 'hetr':
            t_args['device'] = self.device
        with closing(ngt.make_transformer_factory(self.transformer, **t_args)()) as transformer:
            model_out_computation = transformer.add_computation(self.computation)
            for i in range(n_skip):
                model_out_computation(feed_dict=feed_dict)
            for i in range(n_skip, n_iterations):
                Benchmark.marker.record_mark(start)
                model_out_computation(feed_dict=feed_dict)
                Benchmark.marker.record_mark(end)
                times[computation_name][i] = Benchmark.marker.get_time(start, end)
        return times

    @staticmethod
    def print_benchmark_results(benchmarks):
        for stat in benchmarks:
            times = np.array(list(benchmarks[stat].values()))
            header = ('Func', 'Mean', 'Min', 'Max', 'Median', 'Units')
            formatter = '| {:^20} ' * len(header) + '|'

            head_str = formatter.format(*header)
            sep = '-' * len(head_str)
            results = (stat, times.mean(),
                       times.min(), times.max(), np.median(times), 'msec')
            results_str = formatter.format(*results)
            print(sep)
            print(head_str)
            print(sep)
            print(results_str)
            print(sep)

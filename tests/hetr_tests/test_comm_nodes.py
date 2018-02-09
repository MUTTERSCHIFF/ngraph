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
from ngraph.op_graph.op_graph import TensorValueOp
from ngraph.factory.comm_node_factory import get_comm_pattern
from ngraph.op_graph.comm_nodes import set_parallel_axes, \
    CPUMlslBroadcastSendOp, CPUMlslBroadcastRecvOp
from multiprocessing import Process, Event, Manager
from ngraph.frontends.neon import UniformInit
from contextlib import closing
import ngraph as ng
import ngraph.transformers as ngt
import pytest
import time


ax_A = ng.make_axis(length=10, name='A')
ax_B = ng.make_axis(length=15, name='B')
ax_C = ng.make_axis(length=20, name='C')
axes = ng.make_axes([ax_A, ax_B, ax_C])


def test_calculate_new_axes_single_device():
    new_axes = set_parallel_axes(axes=axes, parallel_axis=ax_B)
    assert new_axes.full_lengths == axes.full_lengths


def test_calculate_new_axes_null_axes():
    with pytest.raises(TypeError):
        set_parallel_axes(axes=None, parallel_axis=ax_B)


def test_calculate_new_axes_null_parallel_axis():
    new_axes = set_parallel_axes(axes=axes, parallel_axis=None)
    # Checks null parallel axis. The axes calculated should have the same length as original
    assert new_axes.full_lengths == axes.full_lengths


@pytest.mark.parametrize("from_node, to_node, expected_type", [
    (None, None, None),
    (
        ng.Op(metadata=dict(device='cpu', device_id='0', transformer='cpu0')),
        ng.Op(metadata=dict(device='cpu', device_id='0', transformer='cpu0')),
        None
    ),
    (
        ng.Op(metadata=dict(device='cpu', device_id='0', transformer='cpu0')),
        ng.Op(metadata=dict(device='cpu', device_id='1', transformer='cpu1')),
        'direct'
    ),
    (
        ng.Op(metadata=dict(device='cpu', device_id='0', transformer='cpu0')),
        ng.Op(metadata=dict(device='gpu', device_id='0', transformer='gpu0')),
        'direct'
    ),
    (
        TensorValueOp(ng.constant(1),
                      metadata=dict(device='cpu', device_id='0', transformer='cpu0')),
        ng.Op(metadata=dict(device='cpu', device_id=('1', '2'), parallel=ax_B,
              transformer=['cpu1', 'cpu2'])),
        None
    ),
    (
        TensorValueOp(ng.placeholder([ax_A, ax_B]),
                      metadata=dict(device='cpu', device_id='0', transformer='cpu0')),
        ng.Op(metadata=dict(device='cpu', device_id=('1', '2'), parallel=ax_B,
                            transformer=['cpu1', 'cpu2'])),
        'scatter'
    ),
    (
        TensorValueOp(ng.placeholder([ax_A, ax_B]),
                      metadata=dict(device='cpu', device_id='0', transformer='cpu0')),
        ng.Op(metadata=dict(device='cpu', device_id=('1', '2'), parallel=ax_C,
                            transformer=['cpu1', 'cpu2'])),
        'broadcast'
    ),
    (
        ng.Op(metadata=dict(device='cpu', device_id=('1', '2'), parallel=ax_C,
                            transformer=['cpu1', 'cpu2'])),
        ng.Op(metadata=dict(device='cpu', device_id='0', transformer='cpu0')),
        'gather'
    ),
    (
        TensorValueOp(ng.placeholder([ax_A, ax_B]),
                      metadata=dict(device='cpu', device_id='0', transformer='cpu0')),
        ng.Op(metadata=dict(device='cpu', device_id=('1', '2'), parallel=None,
                            transformer=['cpu1', 'cpu2'])),
        'broadcast'
    ),
    (
        ng.Op(metadata=dict(device='cpu', device_id=('1', '2'), parallel=ax_C,
                            transformer=['cpu1', 'cpu2'], reduce_func='mean')),
        ng.Op(metadata=dict(device='cpu', device_id=('1', '2'), parallel=ax_C,
                            transformer=['cpu1', 'cpu2'])),
        'allreduce'
    ),
])
def test_get_node_type(from_node, to_node, expected_type):
    assert expected_type == get_comm_pattern(from_node, to_node)


@pytest.mark.parametrize('config', [
    {
        'sender_index': 0,
        'device_ids': ['0', '1', '2'],
        'x_input': [1., 2., 3., 4., 5., 6.],
        'shape_input': [1, 6],
        'expected_results': [[1., 2., 3., 4., 5., 6.], [1., 2., 3., 4., 5., 6.]],
    },
    {
        'sender_index': 0,
        'device_ids': ['0', '1', '2', '3', '4', '5'],
        'x_input': [5., 9.],
        'shape_input': [1, 2],
        'expected_results': [[5., 9.], [5., 9.], [5., 9.], [5., 9.], [5., 9.]],
    },
])
def test_broadcast_ops(config):
    class myProcess(Process):
        def __init__(self, y, comp_name):
            super(myProcess, self).__init__()
            self.y = y
            self.comp_name = comp_name
            self.manager = Manager()
            self.results_qs = self.manager.Queue()
            self.exit = Event()

        def run(self):
            with closing(ngt.make_transformer_factory('cpu')()) as t:
                comp = t.computation(self.y)
                self.results_qs.put(comp())

            while not self.exit.is_set():
                time.sleep(0.1)

        def get_result(self):
            while True:
                try:
                    result = self.results_qs.get(timeout=0.2)
                    return result
                except Exception:
                    raise

    pytest.xfail("bcast nodes should be created in context of hetr transformer \
                 to have mpi process manager launched")

    c = config
    y = [None] * len(c['device_ids'])
    active_processes = list()
    results = list()
    sender_id = c['device_ids'][c['sender_index']]
    receiver_ids = c['device_ids'][:c['sender_index']] + c['device_ids'][c['sender_index'] + 1:]

    ax_a = ng.make_axis(length=c['shape_input'][0], name='A')
    ax_b = ng.make_axis(length=c['shape_input'][1], name='B')
    axes = ng.make_axes([ax_a, ax_b])

    with ng.metadata(device='cpu', device_id=sender_id,
                     transformer='None', host_transformer='None', parallel=ax_a):
        from_node = ng.constant(axes=axes, const=c['x_input'])

    with ng.metadata(device='cpu', device_id=tuple(receiver_ids),
                     transformer='None', host_transformer='None', parallel=ax_a):
        to_node = ng.constant(axes=axes, const=0)

    with ng.metadata(parallel=ax_a):
        y[c['sender_index']] = CPUMlslBroadcastSendOp(from_node=from_node, to_node=to_node)
    for i in range(len(c['device_ids'])):
        if i != c['sender_index']:
            sc_op = CPUMlslBroadcastRecvOp(to_node=to_node, send_node=y[c['sender_index']])
            sc_op.idx = i if i < c['sender_index'] else i - 1
            y[i] = sc_op

    for i in range(len(c['device_ids'])):
        active_processes.append(myProcess(y[i], 'cpu' + str(i)))
        active_processes[i].start()

    for i in range(len(c['device_ids'])):
        if i != c['sender_index']:
            results.append(active_processes[i].get_result().tolist())
        active_processes[i].exit.set()
        active_processes[i].join()

    np.testing.assert_array_equal(results, c['expected_results'])


@pytest.mark.multi_device
@pytest.mark.hetr_only
@pytest.mark.parametrize('config', [
    {
        'input': 36,
        'device_id': (0, 1),
        'expected_result': -35,
    },
    {
        'input': 25,
        'device_id': (0, 1, 2, 3),
        'expected_result': -24,
    },
])
def test_allreduce_hint(hetr_device, config):
    if hetr_device == 'gpu':
        if 'gpu' not in ngt.transformer_choices():
            pytest.skip("GPUTransformer not available")

    input = config['input']
    device_id = config['device_id']
    axis_A = ng.make_axis(length=4, name='axis_A')
    parallel_axis = ng.make_axis(name='axis_parallel', length=16)

    with ng.metadata(device=hetr_device,
                     device_id=device_id,
                     parallel=parallel_axis):
        var_A = ng.variable(axes=[axis_A], initial_value=UniformInit(1, 1))
        var_B = ng.variable(axes=[axis_A], initial_value=UniformInit(input, input))
        var_B.metadata['reduce_func'] = 'sum'
        var_B_mean = var_B / len(device_id)
        var_minus = (var_A - var_B_mean)

    with closing(ngt.make_transformer_factory('hetr', device=hetr_device)()) as hetr:
        out_comp = hetr.computation(var_minus)
        result = out_comp()
        np_result = np.full((axis_A.length), config['expected_result'], np.float32)
        np.testing.assert_array_equal(result, np_result)


@pytest.mark.multi_device
@pytest.mark.hetr_only
def test_multiple_gather_ops(hetr_device):
    if hetr_device == 'gpu':
        if 'gpu' not in ngt.transformer_choices():
            pytest.skip("GPUTransformer not available")
        pytest.xfail("Failure due to gather recv tensor being returned in wrong shape, "
                     " possible mismatch between op layout and op.tensor layout")

    H = ng.make_axis(length=2, name='height')
    W = ng.make_axis(length=4, name='width')
    x = ng.placeholder(axes=[H, W])
    with ng.metadata(device_id=('0', '1'), parallel=W):
        x_plus_one = x + 1
        x_mul_two = x_plus_one * 2

    input = np.random.randint(100, size=x.axes.lengths)
    with closing(ngt.make_transformer_factory('hetr', device=hetr_device)()) as hetr:
        plus = hetr.computation([x_mul_two, x_plus_one], x)
        result_mul_two, result_plus_one = plus(input)

        np.testing.assert_array_equal(result_plus_one, input + 1)
        np.testing.assert_array_equal(result_mul_two, (input + 1) * 2)

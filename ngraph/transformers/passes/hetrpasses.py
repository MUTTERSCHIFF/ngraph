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
import socket

from orderedset import OrderedSet

from ngraph.factory.comm_node_factory import get_comm_pattern, CommNodePair
from ngraph.op_graph.op_graph import Op, TensorValueOp
from ngraph.op_graph.comm_nodes import RecvOp
from ngraph.transformers.passes.passes import GraphBuildingPass
from ngraph.op_graph.axes import make_axis
from ngraph.transformers.hetr.hetr_utils import update_parallel_axis


class DeviceAssignPass(GraphBuildingPass):

    def __init__(self, hetr, default_device, default_device_id, **kwargs):
        super(DeviceAssignPass, self).__init__(**kwargs)
        self.hetr = hetr
        self.default_device = default_device
        self.default_device_id = default_device_id

    def visit(self, op, *args):
        device = op.metadata.setdefault('device', self.default_device)
        if 'device_id' in op.metadata and \
           isinstance(op.metadata['device_id'], (list, tuple)) and \
           len(op.metadata['device_id']) == 1:
            op.metadata['device_id'] = op.metadata['device_id'][0]
        device_id = op.metadata.setdefault('device_id', self.default_device_id)
        transformer = "{}{}".format(device, device_id)
        op.metadata['host_transformer'] = socket.gethostname()
        if isinstance(op.metadata['device_id'], (list, tuple)):
            op.metadata['transformer'] = \
                [op.metadata['device'] + str(i) for i in op.metadata['device_id']]
            [self.hetr.register_transformer(tname) for tname in op.metadata['transformer']]
        else:
            op.metadata['transformer'] = transformer
            self.hetr.register_transformer(transformer)

        if isinstance(op, TensorValueOp):
            op.states_read[0].metadata.update(op.metadata)


class CommunicationPass(GraphBuildingPass):

    def __init__(self, send_nodes, **kwargs):
        super(CommunicationPass, self).__init__(**kwargs)
        self.send_nodes = send_nodes

    def visit(self, op, *op_args):
        args = list()
        if isinstance(op, RecvOp):
            self.send_nodes.add(op.send_node())
        for arg in op_args:
            comm_pattern = get_comm_pattern(from_node=arg, to_node=op)
            if comm_pattern:
                pair = CommNodePair(from_node=arg, to_node=op, node_type=comm_pattern)
                if pair.get_send_node():
                    self.send_nodes.add(pair.get_send_node())
                if pair.get_recv_node():
                    recv_node = pair.get_recv_node()
                    if isinstance(recv_node, (dict)):
                        start_node = recv_node['start_node']
                        wait_node = recv_node['wait_node']
                        args.append(start_node)
                        op.add_control_dep(wait_node)
                        start_node.invalidate_property_cache('all_deps')
                        wait_node.invalidate_property_cache('all_deps')
                    else:
                        args.append(pair.get_recv_node())
            else:
                args.append(arg)

        op._args = tuple(args)
        # invalidate deps cache as op._args is updated
        op.invalidate_property_cache('all_deps')

    def do_pass(self, ops, **kwargs):
        super(CommunicationPass, self).do_pass(ops=ops, **kwargs)
        ops.update(self.send_nodes)


class AxesUpdatePass(GraphBuildingPass):
    """
    Description:
        AxesUpdatePass updates the dimension of the parallel axis for ops in the
        subgraphs of which the root is a GatherSendOp
    """

    def __init__(self, **kwargs):
        super(AxesUpdatePass, self).__init__(**kwargs)
        self.parallel_axis = None

    def do_pass(self, ops, **kwargs):

        ops = OrderedSet(op.forwarded for op in ops)

        for op in reversed(Op.ordered_ops(ops)):
            if op.metadata.get('marker') == 'gather':
                # op is GatherRecvOp
                if self.parallel_axis is None:
                    a = op.metadata['parallel']
                    assert a.length % len(op.from_id) == 0, '{} can not be equally divided by {}'\
                        .format(a, len(op.from_id))
                    self.parallel_axis = make_axis(
                        name=a.name,
                        length=a.length // len(op.from_id),
                        docstring='HeTr parallel axis')
                gather_send_op = op.send_node()
                update_parallel_axis(gather_send_op, self.parallel_axis)

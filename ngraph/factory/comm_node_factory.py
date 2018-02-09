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
from ngraph.op_graph.comm_nodes import \
    CPUMlslSendOp, CPUMlslRecvOp, \
    CPUMlslGatherSendOp, CPUMlslGatherRecvOp, \
    CPUMlslScatterSendOp, CPUMlslScatterRecvOp, \
    CPUMlslAllReduceStartOp, CPUMlslAllReduceWaitOp, \
    CPUMlslBroadcastSendOp, CPUMlslBroadcastRecvOp, \
    GPUCudaSendOp, GPUCudaRecvOp, \
    GPUCudaGatherSendOp, GPUCudaGatherRecvOp, \
    GPUCudaScatterSendOp, GPUCudaScatterRecvOp, \
    GPUCudaAllReduceOp, GatherWrapperOp
from ngraph.op_graph.op_graph import BroadcastOp
from collections import defaultdict


class CommNodePair(object):
    """
    Represents a communication pair (sender, receiver).

    Arguments:
        from_node: The source node.
        to_node: The destination node.
        node_type: The type of node (direct/scatter/gather).
    """

    def __init__(self, from_node, to_node, node_type):

        def get_node_factory(node):
            if node.metadata['device'] == 'gpu':
                return GPUCommNodeFactory()
            elif node.metadata['device'] == 'cpu':
                return CPUCommNodeFactory()
            else:
                raise NotImplementedError("device must be either 'gpu' or 'cpu',"
                                          "currently it's {}".format(node.metadata['device']))

        def get_location(from_node, to_node):
            send_host = from_node.metadata['host_transformer']
            recv_host = to_node.metadata['host_transformer']

            if send_host == recv_host:
                return 'local'
            else:
                return 'remote'

        def get_comm_type(comm_options_send, comm_options_recv):
            for send_comm_type in comm_options_send:
                for recv_comm_type in comm_options_recv:
                    if send_comm_type == recv_comm_type:
                        return send_comm_type
            assert False, "Not compatible!!!"

        self.send_node = None
        self.recv_node = None

        send_node_factory = get_node_factory(from_node)
        recv_node_factory = get_node_factory(to_node)

        location = get_location(from_node, to_node)

        comm_options_send = send_node_factory.send_recv_types(location)
        comm_options_recv = recv_node_factory.send_recv_types(location)

        comm_type = get_comm_type(comm_options_send, comm_options_recv)

        if node_type == 'scatter':
            self.send_node = send_node_factory.build(
                node_type='scatter_send',
                comm_type=comm_type,
                from_node=from_node,
                to_node=to_node)
            self.recv_node = recv_node_factory.build(
                node_type='scatter_recv',
                comm_type=comm_type,
                from_node=from_node,
                to_node=to_node,
                send_node=self.send_node)
        elif node_type == 'gather':
            self.send_node = send_node_factory.build(
                node_type='gather_send',
                comm_type=comm_type,
                from_node=from_node,
                to_node=to_node)
            self.recv_node = recv_node_factory.build(
                node_type='gather_recv',
                comm_type=comm_type,
                from_node=from_node,
                to_node=to_node,
                send_node=self.send_node)
            self.send_node.source_id = self.recv_node.metadata['device_id']
        elif node_type == 'broadcast':
            self.send_node = send_node_factory.build(
                node_type='broadcast_send',
                comm_type=comm_type,
                from_node=from_node,
                to_node=to_node)
            self.recv_node = recv_node_factory.build(
                node_type='broadcast_recv',
                comm_type=comm_type,
                from_node=from_node,
                to_node=to_node,
                send_node=self.send_node)
        elif node_type == 'allreduce':
            self.send_node = None
            # send_node_factory is used here since for allreduce,
            # the hint is gotten from the from_node
            self.recv_node = send_node_factory.build(
                node_type=node_type,
                comm_type=comm_type,
                from_node=from_node)
        elif node_type == 'direct':
            self.send_node = send_node_factory.build(
                node_type='send',
                comm_type=comm_type,
                from_node=from_node,
                to_node=to_node)
            self.recv_node = recv_node_factory.build(
                node_type='recv',
                comm_type=comm_type,
                to_node=to_node,
                send_node=self.send_node)
            self.send_node.metadata['peer_id'] = int(self.recv_node.metadata['device_id'])
            self.recv_node.metadata['peer_id'] = int(self.send_node.metadata['device_id'])

    def get_send_node(self):
        return self.send_node

    def get_recv_node(self):
        return self.recv_node


class CommNodeFactory(object):
    """
    Represents a communication node factory.

    Arguments:
        None
    """

    def __init__(self):
        pass

    def send_recv_types(self):
        pass

    def build(self, node_type, comm_type, from_node=None, to_node=None, send_node=None):
        pass


class GPUCommNodeFactory(CommNodeFactory):
    """
    Represents a GPU communication node factory.

    Arguments:
        None
    """

    def send_recv_types(self, location):
        types = [
            ('remote', 'mpi'),
            ('local', 'cuda')
        ]

        send_recv_types = defaultdict(list)
        for loc, comm_type in types:
            send_recv_types[loc].append(comm_type)

        return send_recv_types[location]

    def build(self, node_type, comm_type, from_node=None, to_node=None, send_node=None):
        if node_type == 'send':
            if comm_type == 'cuda':
                return GPUCudaSendOp(
                    from_node=from_node,
                    to_node=to_node)
        elif node_type == 'recv':
            if comm_type == 'cuda':
                return GPUCudaRecvOp(
                    to_node=to_node,
                    send_node=send_node)
        elif node_type == 'scatter_send':
            if comm_type == 'cuda':
                return GPUCudaScatterSendOp(
                    from_node=from_node,
                    to_node=to_node)
        elif node_type == 'scatter_recv':
            if comm_type == 'cuda':
                return GPUCudaScatterRecvOp(
                    to_node=to_node,
                    send_node=send_node)
        elif node_type == 'gather_send':
            if comm_type == 'cuda':
                return GPUCudaGatherSendOp(
                    from_node=from_node)
        elif node_type == 'gather_recv':
            if comm_type == 'cuda':
                return GPUCudaGatherRecvOp(
                    from_node=from_node,
                    to_node=to_node,
                    send_node=send_node)
        elif node_type == 'allreduce':
            if comm_type == 'cuda':
                return GPUCudaAllReduceOp(
                    input_node=from_node,
                    func=from_node.metadata['reduce_func'])
        else:
            assert False, "Not supported!!! node_type: " + node_type


class CPUCommNodeFactory(CommNodeFactory):
    """
    Represents a CPU communication node factory.

    Arguments:
        None
    """

    def send_recv_types(self, location):
        types = [
            ('remote', 'mlsl'),
            ('local', 'mlsl')
        ]

        send_recv_types = defaultdict(list)
        for loc, comm_type in types:
            send_recv_types[loc].append(comm_type)

        return send_recv_types[location]

    def build(self, node_type, comm_type, from_node=None, to_node=None, send_node=None):
        if node_type == 'send':
            return CPUMlslSendOp(
                from_node=from_node)
        elif node_type == 'recv':
            return CPUMlslRecvOp(
                to_node=to_node,
                send_node=send_node)
        elif node_type == 'scatter_send':
            return CPUMlslScatterSendOp(
                from_node=from_node,
                to_node=to_node)
        elif node_type == 'scatter_recv':
            return CPUMlslScatterRecvOp(
                to_node=to_node,
                send_node=send_node)
        elif node_type == 'gather_send':
            return CPUMlslGatherSendOp(
                from_node=from_node)
        elif node_type == 'gather_recv':
            # GatherWrapperOp is created as a wrapper over the GatherRecvOp
            # when the parallel_axis is not the least contiguous axis.
            # The GatherWrapperOp is used by the HeTrTensorShaping pass
            # to add the necessary reorder ops to present the data back
            # in the original axis requested by the user
            recv_node = CPUMlslGatherRecvOp(
                from_node=from_node,
                to_node=to_node,
                send_node=send_node)
            if recv_node.axes == recv_node.native_axes:
                return recv_node
            else:
                return GatherWrapperOp(recv_node=recv_node, arg_op=recv_node)
        elif node_type == 'broadcast_send':
            return CPUMlslBroadcastSendOp(
                from_node=from_node,
                to_node=to_node)
        elif node_type == 'broadcast_recv':
            return CPUMlslBroadcastRecvOp(
                to_node=to_node,
                send_node=send_node)
        elif node_type == 'allreduce':
            start_node = CPUMlslAllReduceStartOp(
                input_node=from_node,
                func=from_node.metadata['reduce_func'])
            wait_node = CPUMlslAllReduceWaitOp(
                input_node=from_node,
                start_node=start_node,
                func=from_node.metadata['reduce_func'])
            return dict(start_node=start_node, wait_node=wait_node)
        else:
            assert False, "Not supported!!!"


def get_comm_pattern(from_node, to_node):
    """
    determine type of communication based on from_node and to_node
    """
    if not from_node or not to_node:
        return None

    if from_node.is_constant is True:
        return None

    if isinstance(from_node, BroadcastOp) and from_node.args[0].is_constant:
        return None

    # todo check 'host_transformer' or consolidate metadata #
    from_node_transformer = from_node.metadata['transformer']
    to_node_transformer = to_node.metadata['transformer']

    if from_node_transformer == to_node_transformer:
        if isinstance(from_node_transformer, (list, tuple)):
            if 'reduce_func' in from_node.metadata and 'reduce_func' not in to_node.metadata:
                return 'allreduce'
            else:
                return None
        else:
            return None

    if isinstance(to_node_transformer, (list, tuple)):
        if to_node.metadata['parallel']:
            # todo check if metadata['device_id'] and 'parallel' co-exists
            if to_node.metadata['parallel'] in from_node.axes:
                from_node.metadata['marker'] = 'scatter'
                return 'scatter'
            else:
                return 'broadcast'
        else:
            return 'broadcast'

    if isinstance(from_node_transformer, (list, tuple)):
        return 'gather'

    if from_node_transformer != to_node_transformer:
        return 'direct'

    return None

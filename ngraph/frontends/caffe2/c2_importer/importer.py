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
from __future__ import print_function
from ngraph.frontends.caffe2.c2_importer.ops_bridge import OpsBridge
from caffe2.python import workspace
import ngraph as ng
import copy


class C2Importer:
    """
    Importer for Caffe2 GraphDef
    """

    def __init__(self):
        self.reset()

    def reset(self):
        """
        Resets importer states.
        """
        self.name_op_map = dict()
        self.ops_bridge = OpsBridge()
        self.init_ops = []
        self.net_def = None

    def parse_net_def(self, net_def, init_net_def=None, c2_workspace=None, verbose=False):
        """
        Imports a net_def to ngraph.

        Arguments:
            net_def: GraphDef object
            verbose: Prints net_def at each node if True.
        """

        def _register_op(op, c2_op):
            # convert to list for convenience
            if isinstance(op, tuple):
                op = list(op)
            else:
                op = [op]

            # post-process output ops
            for idx in range(len(op)):
                op[idx] = self.post_process_op(op[idx])

            # convert back to tuple or op
            if len(op) > 1:
                op = tuple(op)
            else:
                op = op[0]

            # TODO: what if some c2_op have more than one output?
            key = c2_op.name if c2_op.name != '' else c2_op.output[0]
            self.name_op_map[key] = op

        self.init_net_def = init_net_def

        if init_net_def:
            self.net_def = copy.deepcopy(init_net_def)
            self.net_def.op.extend(net_def.op)
        else:
            self.net_def = net_def

        # process nodes
        for c2_op in self.net_def.op:
            # print node
            if verbose:
                print("------")
                print(c2_op)

            # resolve inputs
            input_ops = []
            for name in c2_op.input:
                try:
                    input_ops.append(self.get_op_handle_by_name(name))
                except KeyError as e:
                    if not c2_workspace.HasBlob(e.message):
                        raise e

                    c2_blob = c2_workspace.FetchBlob(e.message)
                    external_input = ng.persistent_tensor(
                        axes=ng.make_axes([ng.make_axis(i) for i in c2_blob.shape]),
                        dtype=c2_blob.dtype,
                        initial_value=c2_blob).named(e.message)
                    external_input.axes[0]._Axis__is_batch = True  # TODO: find nice way to do it
                    input_ops.append(external_input)

                    class mock_c2_op:
                        def __init__(self, name):
                            self.name = name

                    mock_obj = mock_c2_op(e.message)
                    _register_op(external_input, mock_obj)

            # get output op
            if None in input_ops:
                # ignored
                print("!!! IGNORED:{} !!!".format(c2_op.name))
                output_op = None
            else:
                # call bridge op
                output_op = self.ops_bridge(c2_op, input_ops)
                if output_op is None:
                    print("!!! Unknown Operation '{}' of type '{}' !!!"
                          .format(c2_op.name, c2_op.type))

            _register_op(output_op, c2_op)

    def post_process_op(self, op):
        """
        Replace op name for safety and cast op's axes if necessary.

        Args:
            op: A ngraph Op.

        Returns:
            Processed ngraph Op.
        """
        if op is None:
            return None
        # avoid illegal names in ngraph generated code
        op.name = op.name.replace("/", "_")

        # cast to new axes for safety: debugging purpose only
        # import ngraph as ng
        # if hasattr(op, 'axes'):
        #     new_axes = [ng.make_axis(a.length) for a in op.axes]
        #     op = ng.cast_axes(op, axes=new_axes)
        return op

    def get_op_handle_by_name(self, name):
        """
        Get ngraph op from Caffe2 Op's name
        TODO: how support for multiple output node should work?

        Arguments:
            name: Caffe-2 name.

        Returns:
            Op: the corresponding ngraph op
        """

        # TBD: remove prefix
        # name = remove_c2_name_prefix(name)

        # remove suffix of ":" for multiple output node
        name_splits = name.split(":")

        # get node
        if len(name_splits) > 1:
            # check
            assert len(name_splits) == 2
            # split
            idx = int(name_splits[1])
            name_truncated = name_splits[0]
            # get outputs
            outputs = self.name_op_map[name_truncated]
            # get by idx
            if not isinstance(outputs, tuple):
                assert idx == 0
                return self.name_op_map[name_truncated]
            else:
                return self.name_op_map[name_truncated][idx]
        else:
            return self.name_op_map[name]

    def get_op_handle(self, c2_op):
        """
        Get the matching caffe2 op to ngraph op

        Arguments:
            c2_op: caffe2 graph op name or a list of names.

        Returns:
            Op: the corresponding ngraph op or a list of ops.
        """
        if isinstance(c2_op, list):
            return [self.get_op_handle_by_name(op) for op in c2_op]
        else:
            return self.get_op_handle_by_name(c2_op)

    def _get_supported_ops(self):
        """
        Returns a list of supported ops' names.

        Arguments:

        Returns:
            List of supported ops' names.
        """
        ob = OpsBridge()
        supported_ops = set([
            name for name in dir(ob)
            if name[:1] != "_" and name not in ob.__dict__
        ])
        # common set
        supported_ops &= set(workspace.RegisteredOperators())
        return sorted(list(supported_ops))

    def _get_unimplemented_ops(self):
        """
        Returns a list of unimplemented ops' names.

        Arguments:

        Returns:
            List of unimplemented ops' names.
        """
        # get required op
        ops = workspace.RegisteredOperators()
        required_ops = set(ops)

        # get unimplemented ops
        unimplemented_ops = required_ops - set(self._get_supported_ops())
        return sorted(list(unimplemented_ops))


if __name__ == '__main__':
    # get unimplemented ops
    importer = C2Importer()
    supported_ops = importer._get_supported_ops()
    unimplemented_ops = importer._get_unimplemented_ops()

    for op in supported_ops:
        print("+ {}".format(op))

    for op in unimplemented_ops:
        print("- {}".format(op))

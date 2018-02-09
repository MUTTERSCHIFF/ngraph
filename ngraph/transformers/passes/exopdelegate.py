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
from ngraph.transformers.exop import ExOpBlock
from ngraph.transformers.passes.opdelegate import OpAccessor


class ExOpGraphOpAccessor(OpAccessor):
    """
    Provides access to exops so that many passes can be shared by exop-based transformers
    and opraph-based transformers. See OpAccessor for additional details.

    This class should be removed when opgraph-based transformers are no longer in use.
    """

    def exop_args(self, exop):
        return tuple(input_decl.source_output_decl.exop.op for input_decl in exop.input_decls)

    def op_arg(self, op, n):
        return self.computation_decl.get_exop(op).input_decls[n].source_output_decl.exop.op

    def op_args(self, op):
        return self.exop_args(self.computation_decl.get_exop(op))

    def get_device_op(self, op):
        """
        Helper function that traverses through any reshape ops or value ops
        to return the tensor op.

        Overridden by the exec graph to reflect modification made to the graph.

        Args:
            op: An op-graph Op.

        Returns:
            The op providing actual storage for op's value.

        """
        if op.is_device_op:
            return op

        for arg in self.op_args(op):
            dev_op = self.get_device_op(arg)
            if dev_op:
                return dev_op

        return None

    def run_pass(self, process_op, computation_decl, **kwargs):
        self.computation_decl = computation_decl
        self.execution_graph = self.computation_decl.execution_graph
        # TODO when more than one block, we would iterate over each block
        self.exop_block = computation_decl.exop_block

        # TODO Add other types when they are in use
        assert isinstance(self.exop_block, ExOpBlock)

        has_work = True
        while has_work:
            self.begin_batch()
            self.did_something = False
            for exop in self.exop_block:
                process_op(exop.op)
            has_work = self.end_batch()

    def perform_replace_op(self, op, replacement):
        self.exop_block.replace_op(op, replacement)

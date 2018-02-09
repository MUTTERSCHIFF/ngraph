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

from ngraph.transformers.passes.passes import PeepholeGraphPass
from ngraph.util.generics import generic_method
from ngraph.op_graph.op_graph import Op, Fill, AssignOp


class CPUAssignOp(AssignOp):
    """
    Executes tensor[...] = val on the CPU. For use when GPU cannot execute the assignment.
    """
    def __init__(self, tensor, val, **kwargs):
        super(CPUAssignOp, self).__init__(tensor, val, **kwargs)


class GPUSubstitution(PeepholeGraphPass):
    """TODO."""
    @generic_method(dispatch_base_type=Op)
    def visit(self, op, *args):
        """
        Base case.
        """
        pass

    @visit.on_type(Fill)
    def visit(self, op, tensor):
        # Fill op must operate on contiguous tensor
        if not tensor.tensor_description().c_contiguous:
            self.replace_op(op, AssignOp(tensor, op.scalar))

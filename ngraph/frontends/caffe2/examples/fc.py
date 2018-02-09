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
from ngraph.frontends.caffe2.c2_importer.importer import C2Importer
from caffe2.python import core, workspace
import ngraph.transformers as ngt
import numpy as np


def fc_example():
    # Caffe2 - network creation
    net = core.Net("net")

    X = net.GivenTensorFill([], "X", shape=[2, 2], values=[1.0, 2.0, 3.0, 4.0], name="X")
    W = net.GivenTensorFill([], "W", shape=[1, 2], values=[5.0, 6.0], name="W")
    b = net.ConstantFill([], ["b"], shape=[1, ], value=0.5, run_once=0, name="b")
    X.FC([W, b], ["Y"], name="Y")

    # Execute via Caffe2
    workspace.ResetWorkspace()
    workspace.RunNetOnce(net)

    # Import caffe2 network into ngraph
    importer = C2Importer()
    importer.parse_net_def(net.Proto(), verbose=False)

    # Get handle
    f_ng = importer.get_op_handle("Y")

    # Execute
    f_result = ngt.make_transformer().computation(f_ng)()

    # compare Caffe2 and ngraph results
    print("Caffe2 result: {}:\n{}".format("Y", workspace.FetchBlob("Y")))
    print("ngraph result: {}:\n{}".format("Y", f_result))
    assert(np.array_equal(f_result, workspace.FetchBlob("Y")))


if __name__ == '__main__':
    fc_example()

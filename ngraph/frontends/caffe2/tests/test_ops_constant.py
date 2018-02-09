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
from __future__ import division
from caffe2.python import core, workspace
from ngraph.frontends.caffe2.c2_importer.importer import C2Importer
from ngraph.testing import ExecutorFactory
import numpy as np
import random as random


def test_constant():
    workspace.ResetWorkspace()

    shape = [10, 10]
    val = random.random()
    net = core.Net("net")
    net.ConstantFill([], ["Y"], shape=shape, value=val, run_once=0, name="Y")

    # Execute via Caffe2
    workspace.RunNetOnce(net)

    # Import caffe2 network into ngraph
    importer = C2Importer()
    importer.parse_net_def(net.Proto(), verbose=False)

    # Get handle
    f_ng = importer.get_op_handle("Y")

    # Execute
    with ExecutorFactory() as ex:
        f_result = ex.executor(f_ng)()

        # compare Caffe2 and ngraph results
        assert(np.ma.allequal(f_result, workspace.FetchBlob("Y")))
        assert(np.isclose(f_result[0][0], val, atol=1e-6, rtol=0))


def test_gaussianfill():
    workspace.ResetWorkspace()

    # Size of test matrix
    N = 100
    shape = [N, N]

    net = core.Net("net")
    net.GaussianFill([], ["Y"], shape=shape, mean=0.0, std=1.0, name="Y")

    # Execute via Caffe2
    workspace.RunNetOnce(net)

    # Import caffe2 network into ngraph
    importer = C2Importer()
    importer.parse_net_def(net.Proto(), verbose=False)

    # Get handle
    f_ng = importer.get_op_handle("Y")

    # Execute
    with ExecutorFactory() as ex:
        f_result = ex.executor(f_ng)()

        # get caffe result
        caffe_res = workspace.FetchBlob("Y")

        # Elementwise difference of the two random matrixes
        difference_res = caffe_res - f_result

        # standard deviation of Difference Matrix
        diffe_res_std = difference_res.std()

        # testing can only be approximate (so in rare cases may fail!!)
        # if fails once try to re-run a couple of times to make sure there is a problem)
        # the difference must be still gaussian and P(|m'-m|)<3*std = 99.73%, and
        # std(m) = std/N, having N*N elements
        assert(np.isclose(difference_res.mean(), 0, atol=3 * diffe_res_std / N, rtol=0))


def test_uniformfill():
    workspace.ResetWorkspace()

    # Size of test matrix
    N = 100
    shape = [N, N]
    net = core.Net("net")
    net.UniformFill([], ["Y"], shape=shape, min=-2., max=2., name="Y")

    # Execute via Caffe2
    workspace.RunNetOnce(net)

    # Import caffe2 network into ngraph
    importer = C2Importer()
    importer.parse_net_def(net.Proto(), verbose=False)

    # Get handle
    f_ng = importer.get_op_handle("Y")

    # Execute
    with ExecutorFactory() as ex:
        f_result = ex.executor(f_ng)()

        # get caffe result
        caffe_res = workspace.FetchBlob("Y")

        # Elementwise difference of the two random matrixes
        difference_res = caffe_res - f_result

        # standard deviation of Difference Matrix
        diffe_res_std = difference_res.std()

        # testing can only be approximated, so sometimes can fail!!
        # approach mimicking gaussian test, and this time the multiplier is set to 5
        # to account for distorsion from gaussian
        # if fails once try to re-run a couple of times to make sure there is a problem)
        assert(np.isclose(difference_res.mean(), 0, atol=5 * diffe_res_std / N, rtol=0))


def test_uniformintfill():
    workspace.ResetWorkspace()

    N = 100
    shape = [N, N]
    net = core.Net("net")
    net.UniformIntFill([], ["Y"], shape=shape, min=-2, max=2, name="Y")

    # Execute via Caffe2
    workspace.RunNetOnce(net)

    # Import caffe2 network into ngraph
    importer = C2Importer()
    importer.parse_net_def(net.Proto(), verbose=False)

    # Get handle
    f_ng = importer.get_op_handle("Y")

    # Execute
    with ExecutorFactory() as ex:
        f_result = ex.executor(f_ng)()

        # get caffe result
        caffe_res = workspace.FetchBlob("Y")

        # Elementwise difference of the two random matrixes
        difference_res = caffe_res - f_result

        # standard deviation of Difference Matrix
        diffe_res_std = difference_res.std()

        # testing can only be approximated, so sometimes can fail!!
        # approach mimicking gaussian test, and this time the multiplier is set
        # to 8 to account for distorsion from gaussian
        # if fails once try to re-run a couple of times to make sure there is a problem)
        assert(np.isclose(difference_res.mean(), 0, atol=8 * diffe_res_std / N, rtol=0))


def test_xavierfill():
    workspace.ResetWorkspace()

    N = 100
    shape = [N, N]
    net = core.Net("net")
    net.XavierFill([], ["Y"], shape=shape, name="Y")

    # Execute via Caffe2
    workspace.RunNetOnce(net)

    # Import caffe2 network into ngraph
    importer = C2Importer()
    importer.parse_net_def(net.Proto(), verbose=False)

    # Get handle
    f_ng = importer.get_op_handle("Y")

    # Execute
    with ExecutorFactory() as ex:
        f_result = ex.executor(f_ng)()

        # get caffe result
        caffe_res = workspace.FetchBlob("Y")

        # Elementwise difference of the two random matrixes
        difference_res = caffe_res - f_result

        # standard deviation of Difference Matrix
        diffe_res_std = difference_res.std()

        # testing can only be approximated, so sometimes can fail!!
        # approach mimicking gaussian test
        # if fails once try to re-run a couple of times to make sure there is a problem)
        assert(np.isclose(difference_res.mean(), 0, atol=3 * diffe_res_std / N, rtol=0))


def test_giventensorfill():
    workspace.ResetWorkspace()

    shape = [10, 10]
    data1 = np.random.random(shape)

    net = core.Net("net")
    net.GivenTensorFill([], ["Y"], shape=shape, values=data1, name="Y")

    # Execute via Caffe2
    workspace.RunNetOnce(net)

    # Import caffe2 network into ngraph
    importer = C2Importer()
    importer.parse_net_def(net.Proto(), verbose=False)

    # Get handle
    f_ng = importer.get_op_handle("Y")

    # Execute
    with ExecutorFactory() as ex:
        f_result = ex.executor(f_ng)()

        # compare Caffe2 and ngraph results
        assert(np.ma.allequal(f_result, workspace.FetchBlob("Y")))
        assert(np.ma.allclose(f_result, data1, atol=1e-6, rtol=0))


def test_giventensorintfill():
    workspace.ResetWorkspace()

    shape = [10, 10]
    data1 = np.random.random_integers(-100, 100, shape)

    net = core.Net("net")
    net.GivenTensorIntFill([], ["Y"], shape=shape, values=data1, name="Y")

    # Execute via Caffe2
    workspace.RunNetOnce(net)

    # Import caffe2 network into ngraph
    importer = C2Importer()
    importer.parse_net_def(net.Proto(), verbose=False)

    # Get handle
    f_ng = importer.get_op_handle("Y")

    # Execute
    with ExecutorFactory() as ex:
        f_result = ex.executor(f_ng)()

        # compare Caffe2 and ngraph results
        assert(np.ma.allequal(f_result, workspace.FetchBlob("Y")))
        assert(np.ma.allequal(f_result, data1))

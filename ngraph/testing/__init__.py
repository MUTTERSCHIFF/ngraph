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

from ngraph.testing.decorators import with_error_settings, raise_all_numpy_errors
from ngraph.testing.error_check import assert_allclose
from ngraph.testing.random import RandomTensorGenerator
from ngraph.testing.execution import executor, ExecutorFactory, \
    numeric_derivative, check_derivative, is_flex_factory
from ngraph.testing.conv_utils import ConvParams, reference_conv, reference_deconv_bprop, \
    reference_deconv_fprop

__all__ = [
    'with_error_settings',
    'raise_all_numpy_errors',
    'assert_allclose',
    'RandomTensorGenerator',
    'executor',
    'ExecutorFactory',
    'numeric_derivative',
    'check_derivative',
    'ConvParams',
    'reference_conv',
    'reference_deconv_bprop',
    'reference_deconv_fprop',
    'is_flex_factory',
]

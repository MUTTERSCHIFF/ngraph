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

from ngraph.transformers.base import make_transformer, set_transformer_factory, \
    transformer_choices,  \
    allocate_transformer, make_transformer_factory, Transformer, \
    UnsupportedTransformerException

__all__ = [
    'allocate_transformer',
    'make_transformer',
    'make_transformer_factory',
    'set_transformer_factory',
    'transformer_choices',
    'Transformer'
]

PYCUDA_LOGIC_ERROR_CODE = 4

try:
    import ngraph.transformers.cputransform  # noqa
except UnsupportedTransformerException:
    pass

try:
    import ngraph.transformers.gputransform  # noqa
except UnsupportedTransformerException:
    pass

try:
    import ngraph.transformers.hetrtransform  # noqa
except UnsupportedTransformerException as e:
    pass

try:
    import artransformer.artransformer  # noqa
except ImportError:
    pass

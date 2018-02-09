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
import itertools as itt
import numpy as np

import ngraph as ng
from ngraph.op_graph.lookuptable import lookuptable_update
import ngraph.transformers as ngt
from ngraph.testing import RandomTensorGenerator, ExecutorFactory
from ngraph.frontends.neon import ax
import pytest

pytestmark = pytest.mark.transformer_dependent


rng = RandomTensorGenerator(0, np.float32)

delta = 1e-8
rtol = atol = 1e-2


def pytest_generate_tests(metafunc):
    bsz_rng = [1]

    if 'lut_args' in metafunc.fixturenames:
        fargs = []
        vocab_rng = [10, 50, 100]
        embed_rng = [20, 18, 31]
        bsz_rng = [4, 32]
        seq_rng = [3, 5]
        fargs = itt.product(vocab_rng, embed_rng, bsz_rng, seq_rng)
        metafunc.parametrize('lut_args', fargs)


def lut_fprop_ref(lut, idx):
    """
    Reference implementation of the lookuptable fprop
    """
    return lut.take(idx.flatten(), 0)


def lut_update_ref(error, lut, idx, pad_idx):
    """
    Reference implementation of the lookuptable update
    """
    unqidx, inv = np.unique(idx.flatten(), return_inverse=True)
    dw_ref = np.zeros(lut.shape)
    groups = [np.where(inv == i) for i in range(len(unqidx))]

    for (wrd_id, group) in zip(unqidx, groups):
        if wrd_id != pad_idx:
            dw_ref[wrd_id, :] = np.sum(error.take(group[0], axis=0), axis=0)
    return dw_ref


@pytest.config.flex_disabled(reason="Results slightly mismatch - #2040")
@pytest.config.argon_disabled(reason="Argon Transformer error")  # TODO triage
def test_lut(lut_args):
    """
    test lut fprop and bprop
    """
    pad_idx = 0
    with ExecutorFactory() as ex:

        vocab_size, embed_dim, bsz, seq_len = lut_args

        V = ng.make_axis(vocab_size)
        F = ng.make_axis(embed_dim)
        ax.N.length = bsz
        ax.REC.length = seq_len

        ax_idx = ng.make_axes([ax.REC, ax.N])
        ax_lut = ng.make_axes([V, F])

        lut = ng.placeholder(ax_lut)
        idx = ng.placeholder(ax_idx)
        idx_flat = ng.flatten(idx)
        ax_out = idx_flat.axes | ng.make_axes([F])

        # fprop
        lut_out_ng = ng.lookuptable(lut, idx_flat, ax_out, pad_idx=pad_idx)
        fprop_fun = ex.executor(lut_out_ng, lut, idx)

        # bprop
        update_error = ng.placeholder(ax_out)
        update_out_ng = lookuptable_update(update_error, lut, idx, lut_out_ng)
        update_fun = ex.executor(update_out_ng, update_error, lut, idx)

        # provide actual inputs and execute the graph
        lut_value = rng.uniform(-1, 1, lut.axes)
        idx_value = rng.random_integers(0, vocab_size - 1, idx.axes)
        fprop_lut = fprop_fun(lut_value, idx_value).copy()

        # compare fprop
        fprop_ref = lut_fprop_ref(lut_value, idx_value)
        ng.testing.assert_allclose(fprop_lut, fprop_ref, rtol=0.0, atol=1.0e-5)

        # provide actual delta and execute the update op
        update_value = rng.uniform(-1, 1, update_error.axes)
        update_lut = update_fun(update_value, lut_value, idx_value).copy()

        # compare bprop (udpate)
        update_ref = lut_update_ref(update_value, lut_value, idx_value, pad_idx=pad_idx)
        ng.testing.assert_allclose(update_lut, update_ref, rtol=0.0, atol=1.0e-5)


if __name__ == '__main__':
    factory = ngt.make_transformer_factory('cpu')
    ngt.set_transformer_factory(factory)
    (V, F, N, T) = (3, 6, 4, 5)
    lut_args = (V, F, N, T)
    test_lut(factory, lut_args)
